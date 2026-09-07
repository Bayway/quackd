"""OpenAI as the duck's brain, via the `openai` SDK (optional extra). Also the base for Grok.

Chat Completions with function tools, `tool_choice="required"` and
`parallel_tool_calls=False` for one call per turn. Tool results go back as `tool` messages;
because a `tool` message cannot carry an image, the frame follows in a `user` message.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from quackd.agent.providers.base import (
    Exchange,
    ProviderError,
    ProviderMissingKey,
    ProviderNotInstalled,
    ProviderTurn,
    ToolCall,
    Usage,
)

DEFAULT_MODEL = "gpt-5"


def _image_part(png: bytes) -> dict[str, Any]:
    data = base64.standard_b64encode(png).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}


def render_messages(system: str, history: list[Exchange]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for ex in history:
        obs = ex.observation
        if obs.tool_call_id:
            messages.append({"role": "tool", "tool_call_id": obs.tool_call_id, "content": obs.text})
            if obs.image_png:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Current camera frame:"},
                            _image_part(obs.image_png),
                        ],
                    }
                )
        else:
            parts: list[dict[str, Any]] = [{"type": "text", "text": obs.text}]
            if obs.image_png:
                parts.append(_image_part(obs.image_png))
            messages.append({"role": "user", "content": parts})
        if ex.decision is not None:
            tc = ex.decision.tool_call
            messages.append(
                {
                    "role": "assistant",
                    "content": ex.decision.text,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                    ],
                }
            )
    return messages


def render_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def parse_response(response: Any) -> ProviderTurn:
    choice = response.choices[0]
    message = choice.message
    tool_calls: list[ToolCall] = []
    for tc in getattr(message, "tool_calls", None) or []:
        fn = tc.function
        raw_args = fn.arguments
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
        except json.JSONDecodeError:
            args = {"_unparsed": raw_args}
        tool_calls.append(ToolCall(id=str(tc.id), name=str(fn.name), arguments=args))
    usage = getattr(response, "usage", None)
    # OpenAI's own Chat Completions returns no reasoning text, only a count of the tokens it
    # spent on it. DeepSeek, vLLM's reasoning parsers, llama.cpp, LM Studio and xAI put the
    # text in `reasoning_content`; Ollama's /v1 and OpenRouter in `reasoning`. The SDK's
    # message model keeps unknown wire fields as attributes, so both reads work on the real
    # object and on a stub alike.
    reasoning = next(
        (
            v
            for v in (
                getattr(message, "reasoning_content", None),
                getattr(message, "reasoning", None),
            )
            if isinstance(v, str) and v.strip()
        ),
        None,
    )
    details = getattr(usage, "completion_tokens_details", None)
    return ProviderTurn(
        tool_calls=tool_calls,
        text=getattr(message, "content", None) or None,
        usage=Usage(
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            reasoning_tokens=int(getattr(details, "reasoning_tokens", 0) or 0),
        ),
        stop_reason=getattr(choice, "finish_reason", None),
        raw=None,
        thinking=reasoning.strip() if reasoning else None,
    )


class OpenAIProvider:
    """OpenAI's own API. Subclasses (Grok, the local servers) only change the class knobs."""

    name = "openai"
    supports_vision = True
    key_env = "OPENAI_API_KEY"
    base_url: str | None = None
    default_tool_choice: str | None = "required"
    """`required` forces a call on OpenAI. `auto` for servers that reject `required`,
    `none` to omit the field entirely."""
    send_parallel_flag = True
    """OpenAI accepts `parallel_tool_calls=False`. Some local servers 400 on unknown fields."""
    prompt_hint = ""
    """Extra system-prompt text a provider wants (the local one explains the JSON fallback)."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        client: Any = None,
        api_key: str | None = None,
        base_url: str | None = None,
        tool_choice: str | None = None,
        vision: bool | None = None,
    ) -> None:
        self.model = model
        self.calls = 0
        if base_url is not None:
            self.base_url = base_url
        if vision is not None:
            self.supports_vision = vision
        self.tool_choice = tool_choice if tool_choice is not None else self.default_tool_choice
        if client is None:
            import os

            key = api_key or os.environ.get(self.key_env) or self._fallback_key()
            if not key:
                raise ProviderMissingKey(self.name, self.key_env)
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                extra = "grok" if self.name == "grok" else "openai"
                raise ProviderNotInstalled(self.name, extra) from e
            client = AsyncOpenAI(api_key=key, base_url=self.base_url)
        self.client = client

    def _fallback_key(self) -> str | None:
        """What to use when no key is configured. Cloud: nothing (error). Local: a dummy."""
        return None

    def _params(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": render_messages(system, history),
            "tools": render_tools(tools),
        }
        if self.tool_choice and self.tool_choice != "none":
            params["tool_choice"] = self.tool_choice
        if self.send_parallel_flag:
            params["parallel_tool_calls"] = False
        return params

    def _fallback(self, turn: ProviderTurn, tools: list[dict[str, Any]]) -> ProviderTurn:
        """Hook for providers that can rescue a tool call from plain text. Base: nothing."""
        return turn

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        self.calls += 1
        try:
            response = await self.client.chat.completions.create(
                **self._params(system, history, tools)
            )
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"{self.name}: {type(e).__name__}: {e}") from e
        turn = parse_response(response)
        if not turn.tool_calls:
            turn = self._fallback(turn, tools)
        return turn
