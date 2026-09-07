"""Provider request/response mapping against stubbed SDK clients. No network, no SDKs."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS
from typing import Any

import pytest

from quackd.agent.providers.anthropic import AnthropicProvider
from quackd.agent.providers.anthropic import render_messages as a_messages
from quackd.agent.providers.base import Decision, Exchange, Observation, ProviderError, ToolCall
from quackd.agent.providers.factory import make_provider
from quackd.agent.providers.gemini import GeminiProvider, clean_schema, render_contents
from quackd.agent.providers.grok import GrokProvider
from quackd.agent.providers.openai import OpenAIProvider
from quackd.agent.providers.openai import render_messages as o_messages

PNG = b"\x89PNG\r\n\x1a\nfake"
TOOLS = [
    {
        "name": "walk",
        "description": "Walk.",
        "input_schema": {
            "type": "object",
            "properties": {"vx": {"type": "number", "default": 0.1, "title": "Vx"}},
            "additionalProperties": False,
        },
    }
]


def history() -> list[Exchange]:
    first = Exchange(
        observation=Observation(text="obs 1", image_png=PNG),
        decision=Decision(
            tool_call=ToolCall(id="call-1", name="walk", arguments={"vx": 0.1}), text="going"
        ),
    )
    second = Exchange(
        observation=Observation(text="obs 2 (result)", image_png=PNG, tool_call_id="call-1")
    )
    return [first, second]


# ── anthropic ───────────────────────────────────────────────────────────────────────────


class FakeAnthropic:
    def __init__(self, response: Any, *, beta_ok: bool = True) -> None:
        self.kwargs: dict[str, Any] = {}
        self.beta_used = False
        self._response = response

        async def plain(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            return self._response

        async def beta(**kwargs: Any) -> Any:
            if not beta_ok:
                raise TypeError("unexpected keyword argument 'fallbacks'")
            self.beta_used = True
            self.kwargs = kwargs
            return self._response

        self.messages = NS(create=plain)
        self.beta = NS(messages=NS(create=beta))


def anthropic_response(*blocks: Any, stop_reason: str = "tool_use") -> Any:
    return NS(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=NS(input_tokens=120, output_tokens=30),
        stop_details=None,
    )


async def test_anthropic_request_and_response_mapping() -> None:
    client = FakeAnthropic(
        anthropic_response(
            NS(
                type="thinking",
                thinking="",
                model_dump=lambda: {"type": "thinking", "thinking": "", "signature": "sig"},
            ),
            NS(
                type="tool_use",
                id="toolu_1",
                name="walk",
                input={"vx": 0.2},
                model_dump=lambda: {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "walk",
                    "input": {"vx": 0.2},
                },
            ),
        )
    )
    p = AnthropicProvider(model="claude-opus-5", client=client, effort="medium")
    turn = await p.step("SYS", history(), TOOLS)
    assert client.beta_used
    kw = client.kwargs
    assert kw["model"] == "claude-opus-5" and kw["system"] == "SYS"
    assert kw["tool_choice"] == {"type": "any", "disable_parallel_tool_use": True}
    assert kw["output_config"] == {"effort": "medium"}
    # adaptive is the model's default; `display` is what makes the blocks carry text at all,
    # and without it the trace's "what it thought" would be blank on every turn
    assert kw["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["tools"][0]["input_schema"]["additionalProperties"] is False
    msgs = kw["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"][0]["type"] == "image" and msgs[0]["content"][1]["text"] == "obs 1"
    assert msgs[1]["content"][-1] == {
        "type": "tool_use",
        "id": "call-1",
        "name": "walk",
        "input": {"vx": 0.1},
    }
    result = msgs[2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "call-1"
    assert [c["type"] for c in result["content"]] == ["text", "image"]
    assert turn.tool_calls == [ToolCall(id="toolu_1", name="walk", arguments={"vx": 0.2})]
    assert turn.usage.input_tokens == 120 and turn.stop_reason == "tool_use"
    assert turn.raw[0]["type"] == "thinking"  # replayed verbatim next turn


def test_anthropic_replays_raw_blocks() -> None:
    ex = Exchange(
        observation=Observation(text="o"),
        decision=Decision(
            tool_call=ToolCall(id="t", name="walk"),
            raw=[
                {"type": "thinking", "thinking": "", "signature": "s"},
                {"type": "tool_use", "id": "t", "name": "walk", "input": {}},
            ],
        ),
    )
    msgs = a_messages([ex])
    assert msgs[1]["content"][0]["type"] == "thinking"


async def test_anthropic_falls_back_to_plain_endpoint_on_old_sdk() -> None:
    client = FakeAnthropic(
        anthropic_response(NS(type="tool_use", id="1", name="walk", input={})), beta_ok=False
    )
    p = AnthropicProvider(client=client)
    await p.step("S", history()[:1], TOOLS)
    assert not client.beta_used and p.fallbacks is False
    assert "fallbacks" not in client.kwargs


async def test_anthropic_refusal_yields_no_tool_call() -> None:
    resp = anthropic_response(
        NS(type="text", text="no", model_dump=lambda: {"type": "text", "text": "no"}),
        stop_reason="refusal",
    )
    resp.stop_details = NS(category="x", explanation="policy")
    p = AnthropicProvider(client=FakeAnthropic(resp))
    turn = await p.step("S", history()[:1], TOOLS)
    assert turn.tool_calls == [] and turn.stop_reason == "refusal" and "policy" in (turn.text or "")


async def test_anthropic_errors_are_classified() -> None:
    class RateLimitError(Exception):
        response = NS(headers={"retry-after": "7"})

    async def boom(**_: Any) -> Any:
        raise RateLimitError("429")

    client = NS(messages=NS(create=boom), beta=NS(messages=NS(create=boom)))
    with pytest.raises(ProviderError, match=r"rate limited \(retry-after 7s\)"):
        await AnthropicProvider(client=client).step("S", history()[:1], TOOLS)


# ── openai / grok ───────────────────────────────────────────────────────────────────────


class FakeOpenAI:
    def __init__(self, response: Any) -> None:
        self.kwargs: dict[str, Any] = {}

        async def create(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            return response

        self.chat = NS(completions=NS(create=create))


def openai_response(name: str, args: str, content: str | None = None) -> Any:
    tc = NS(id="call_9", function=NS(name=name, arguments=args))
    return NS(
        choices=[NS(message=NS(content=content, tool_calls=[tc]), finish_reason="tool_calls")],
        usage=NS(prompt_tokens=50, completion_tokens=9),
    )


async def test_openai_request_and_response_mapping() -> None:
    client = FakeOpenAI(openai_response("walk", json.dumps({"vx": 0.3})))
    p = OpenAIProvider(model="gpt-5", client=client)
    turn = await p.step("SYS", history(), TOOLS)
    kw = client.kwargs
    assert kw["tool_choice"] == "required" and kw["parallel_tool_calls"] is False
    assert kw["tools"][0]["type"] == "function" and kw["tools"][0]["function"]["name"] == "walk"
    roles = [m["role"] for m in kw["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "user"]  # image after tool result
    assert kw["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"vx": 0.1}'
    assert kw["messages"][3]["tool_call_id"] == "call-1"
    assert kw["messages"][4]["content"][1]["type"] == "image_url"
    assert turn.tool_calls == [ToolCall(id="call_9", name="walk", arguments={"vx": 0.3})]
    assert turn.usage.input_tokens == 50 and turn.stop_reason == "tool_calls"


async def test_openai_bad_json_arguments_do_not_crash() -> None:
    p = OpenAIProvider(client=FakeOpenAI(openai_response("walk", "{not json")))
    turn = await p.step("S", history()[:1], TOOLS)
    assert "_unparsed" in turn.tool_calls[0].arguments


def test_openai_history_without_images_has_no_extra_user_turn() -> None:
    ex = Exchange(
        observation=Observation(text="o"),
        decision=Decision(tool_call=ToolCall(id="c", name="stop")),
    )
    msgs = o_messages("S", [ex, Exchange(observation=Observation(text="r", tool_call_id="c"))])
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool"]


def test_grok_is_openai_with_xai_endpoint() -> None:
    p = GrokProvider(client=FakeOpenAI(None))
    assert p.name == "grok" and p.base_url == "https://api.x.ai/v1" and p.model == "grok-4"


def test_missing_keys_are_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        OpenAIProvider()
    with pytest.raises(ProviderError, match="XAI_API_KEY"):
        GrokProvider()
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        GeminiProvider()


# ── gemini ──────────────────────────────────────────────────────────────────────────────


class FakeGemini:
    def __init__(self, response: Any) -> None:
        self.kwargs: dict[str, Any] = {}

        async def generate_content(**kwargs: Any) -> Any:
            self.kwargs = kwargs
            return response

        self.aio = NS(models=NS(generate_content=generate_content))


async def test_gemini_request_and_response_mapping() -> None:
    part = NS(function_call=NS(name="walk", args={"vx": 0.25}), text=None)
    response = NS(
        candidates=[NS(content=NS(parts=[part]), finish_reason="STOP")],
        usage_metadata=NS(prompt_token_count=70, candidates_token_count=12),
    )
    client = FakeGemini(response)
    turn = await GeminiProvider(client=client).step("SYS", history(), TOOLS)
    kw = client.kwargs
    assert kw["model"] == "gemini-2.5-pro"
    assert kw["config"]["system_instruction"] == "SYS"
    assert kw["config"]["tool_config"] == {"function_calling_config": {"mode": "ANY"}}
    decl = kw["config"]["tools"][0]["function_declarations"][0]
    assert decl["name"] == "walk"
    assert "additionalProperties" not in decl["parameters"]
    assert "title" not in decl["parameters"]["properties"]["vx"]
    contents = kw["contents"]
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][-1]["function_call"] == {"name": "walk", "args": {"vx": 0.1}}
    assert contents[2]["parts"][0]["function_response"]["name"] == "walk"
    assert contents[2]["parts"][1]["inline_data"]["mime_type"] == "image/png"
    assert turn.tool_calls == [ToolCall(id="gemini-0", name="walk", arguments={"vx": 0.25})]
    assert turn.usage.input_tokens == 70


def test_gemini_clean_schema_is_recursive() -> None:
    schema = {
        "type": "object",
        "title": "T",
        "properties": {"a": {"type": "array", "items": {"default": 1, "type": "integer"}}},
    }
    cleaned = clean_schema(schema)
    assert "title" not in cleaned and "default" not in cleaned["properties"]["a"]["items"]


def test_gemini_first_turn_has_no_function_response() -> None:
    contents = render_contents([Exchange(observation=Observation(text="hi", tool_call_id="x"))])
    assert contents[0]["parts"][0] == {"text": "hi"}


# ── factory ─────────────────────────────────────────────────────────────────────────────


def test_factory_fake_and_unknown() -> None:
    assert make_provider("fake", duck_name="hello-world").name == "fake"
    with pytest.raises(ProviderError, match="unknown provider"):
        make_provider("hal")


def test_factory_reports_missing_extra_or_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        make_provider("openai")


# ── what the model thought: the `thinking` field the trace shows ────────────────────────


class BadRequestError(Exception):
    """Named as the SDK names it, because `_classify` and the thinking retry match on that."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def thinking_block(text: str) -> Any:
    dump = {"type": "thinking", "thinking": text, "signature": "sig"}
    return NS(type="thinking", thinking=text, model_dump=lambda: dump)


def tool_use_block(name: str = "walk") -> Any:
    dump = {"type": "tool_use", "id": "t1", "name": name, "input": {}}
    return NS(type="tool_use", id="t1", name=name, input={}, model_dump=lambda: dump)


async def test_anthropic_thinking_skips_empty_blocks_and_names_redacted_ones() -> None:
    """A response carries zero or more thinking blocks and any of them can be empty (a
    progress block, or a display that returns none). An empty one renders nothing."""
    redacted = NS(
        type="redacted_thinking", data="xx", model_dump=lambda: {"type": "redacted_thinking"}
    )
    client = FakeAnthropic(
        anthropic_response(
            thinking_block(""),
            thinking_block("the ball is left, so turn first"),
            redacted,
            thinking_block("   "),
            tool_use_block(),
        )
    )
    turn = await AnthropicProvider(client=client).step("S", history()[:1], TOOLS)
    assert turn.thinking == "the ball is left, so turn first\n\n[redacted thinking]"


async def test_anthropic_all_empty_thinking_is_none_not_a_blank_line() -> None:
    client = FakeAnthropic(anthropic_response(thinking_block(""), tool_use_block()))
    turn = await AnthropicProvider(client=client).step("S", history()[:1], TOOLS)
    assert turn.thinking is None


async def test_anthropic_retries_once_without_thinking_on_an_older_model() -> None:
    """A model older than Claude 4.6 rejects the parameter. Losing the thinking text is
    acceptable; losing the run because the trace asked for it is not."""
    calls: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if "thinking" in kwargs:
            raise BadRequestError("thinking: unsupported parameter for this model")
        return anthropic_response(tool_use_block())

    client = NS(messages=NS(create=create), beta=NS(messages=NS(create=create)))
    p = AnthropicProvider(client=client, fallbacks=False)
    turn = await p.step("S", history()[:1], TOOLS)
    assert [tc.name for tc in turn.tool_calls] == ["walk"]
    assert len(calls) == 2 and "thinking" in calls[0] and "thinking" not in calls[1]
    assert p.thinking_display is None
    await p.step("S", history()[:1], TOOLS)  # and no later turn asks again
    assert len(calls) == 3 and "thinking" not in calls[2]


async def test_anthropic_other_bad_requests_still_raise() -> None:
    async def boom(**_: Any) -> Any:
        raise BadRequestError("max_tokens is too large")

    client = NS(messages=NS(create=boom), beta=NS(messages=NS(create=boom)))
    with pytest.raises(ProviderError, match="bad request"):
        await AnthropicProvider(client=client, fallbacks=False).step("S", history()[:1], TOOLS)


def test_anthropic_thinking_display_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUACKD_THINKING_DISPLAY", "")
    assert AnthropicProvider(client=FakeAnthropic(None)).thinking_display is None
    monkeypatch.setenv("QUACKD_THINKING_DISPLAY", "omitted")
    assert AnthropicProvider(client=FakeAnthropic(None)).thinking_display == "omitted"


@pytest.mark.parametrize("field", ["reasoning_content", "reasoning"])
async def test_openai_reads_reasoning_from_either_field(field: str) -> None:
    """DeepSeek, vLLM, llama.cpp, LM Studio and xAI answer with `reasoning_content`; Ollama's
    OpenAI-compatible endpoint and OpenRouter with `reasoning`."""
    response = openai_response("walk", "{}")
    setattr(response.choices[0].message, field, "  I should walk  ")
    response.usage.completion_tokens_details = NS(reasoning_tokens=44)
    turn = await OpenAIProvider(client=FakeOpenAI(response)).step("S", history()[:1], TOOLS)
    assert turn.thinking == "I should walk" and turn.usage.reasoning_tokens == 44


async def test_openai_without_reasoning_reports_none() -> None:
    client = FakeOpenAI(openai_response("walk", "{}"))
    turn = await OpenAIProvider(client=client).step("S", history()[:1], TOOLS)
    assert turn.thinking is None and turn.usage.reasoning_tokens == 0


async def test_openai_ignores_a_non_string_reasoning_field() -> None:
    response = openai_response("walk", "{}")
    response.choices[0].message.reasoning = {"summary": "an object, not text"}
    turn = await OpenAIProvider(client=FakeOpenAI(response)).step("S", history()[:1], TOOLS)
    assert turn.thinking is None


async def test_local_splits_inline_think_tags_out_of_the_answer() -> None:
    """A server with no reasoning separation leaves `<think>` in `content`, where it would be
    shown as the answer and replayed to the model next turn as something it said."""
    from quackd.agent.providers.local import LocalProvider

    response = openai_response("walk", "{}", content="<think>ball is left</think>turning left")
    p = LocalProvider("m", preset="ollama", client=FakeOpenAI(response))
    turn = await p.step("S", history()[:1], TOOLS)
    assert turn.thinking == "ball is left" and turn.text == "turning left"


async def test_gemini_asks_for_thoughts_and_keeps_them_out_of_the_text() -> None:
    thought = NS(function_call=None, text="I will walk", thought=True)
    answer = NS(function_call=None, text="walking now", thought=False)
    call = NS(function_call=NS(name="walk", args={}), text=None)
    response = NS(
        candidates=[NS(content=NS(parts=[thought, answer, call]), finish_reason="STOP")],
        usage_metadata=NS(prompt_token_count=1, candidates_token_count=2, thoughts_token_count=9),
    )
    client = FakeGemini(response)
    turn = await GeminiProvider(client=client).step("SYS", history()[:1], TOOLS)
    assert client.kwargs["config"]["thinking_config"] == {"include_thoughts": True}
    assert turn.thinking == "I will walk"
    assert turn.text == "walking now"  # a thought is not something the model said
    assert turn.usage.reasoning_tokens == 9


async def test_gemini_retries_once_without_thoughts_on_a_model_without_them() -> None:
    seen: list[dict[str, Any]] = []
    answered = NS(
        candidates=[
            NS(
                content=NS(parts=[NS(function_call=NS(name="walk", args={}), text=None)]),
                finish_reason="STOP",
            )
        ],
        usage_metadata=NS(prompt_token_count=1, candidates_token_count=1),
    )

    async def generate_content(**kwargs: Any) -> Any:
        seen.append(kwargs)
        if "thinking_config" in kwargs["config"]:
            raise ValueError("INVALID_ARGUMENT: thinking_config is not supported by this model")
        return answered

    client = NS(aio=NS(models=NS(generate_content=generate_content)))
    p = GeminiProvider(model="gemini-2.0-flash", client=client)
    turn = await p.step("S", history()[:1], TOOLS)
    assert [tc.name for tc in turn.tool_calls] == ["walk"]
    assert len(seen) == 2 and not p.include_thoughts


async def test_gemini_other_errors_still_raise() -> None:
    async def boom(**_: Any) -> Any:
        raise ValueError("quota exhausted")

    client = NS(aio=NS(models=NS(generate_content=boom)))
    with pytest.raises(ProviderError, match="quota exhausted"):
        await GeminiProvider(client=client).step("S", history()[:1], TOOLS)


def test_gemini_thoughts_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUACKD_GEMINI_THOUGHTS", "0")
    p = GeminiProvider(client=NS())
    assert not p.include_thoughts and "thinking_config" not in p._config("S", TOOLS)


def test_usage_adds_reasoning_tokens_too() -> None:
    from quackd.agent.providers.base import Usage

    total = Usage(input_tokens=1, output_tokens=2, reasoning_tokens=3) + Usage(
        input_tokens=10, output_tokens=20, reasoning_tokens=30
    )
    assert total.model_dump() == {"input_tokens": 11, "output_tokens": 22, "reasoning_tokens": 33}
