"""The deliberation loop, end to end on the mock transport with the scripted provider."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from quackd.agent.loop import RunConfig, run_duck
from quackd.agent.providers.base import Exchange, ProviderError, ProviderTurn, ToolCall, Usage
from quackd.agent.providers.fake import FakeProvider
from quackd.agent.transcript import Transcript
from quackd.duckfile.schema import Budgets, DuckFile
from quackd.transport.mock import MockTransport

GOLDEN_HELLO = ["quack", "walk", "quack", "declare_success"]


async def test_hello_world_golden(hello_duck: DuckFile, tmp_path: Path) -> None:
    transport = MockTransport()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=transport,
            runs_dir=tmp_path,
        )
    )
    assert result.outcome == "success", result.reason
    assert result.steps == 3 and result.llm_calls == 4
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run_start" and kinds[-1] == "run_end"
    assert {"observation", "llm", "verb", "declare"} <= set(kinds)
    calls = [tc["name"] for e in events if e["kind"] == "llm" for tc in e["tool_calls"]]
    assert calls == GOLDEN_HELLO
    assert (result.run_dir / "summary.json").exists()
    assert [i.kind for i in transport.intents if i.kind != "stop"] == ["sound"] + ["move"] * 10 + [
        "sound"
    ]
    assert transport.intents[-1].kind == "stop"  # the loop always stops the duck on exit
    assert not transport.connected  # and closes the transport
    assert (result.run_dir / "frames").is_dir()


class NoToolProvider:
    name = "no-tool"
    model = "x"
    supports_vision = False

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        return ProviderTurn(tool_calls=[], text="I would rather talk.")


class ClockAdvancingProvider:
    name = "clock-advancing"
    model = "test"
    supports_vision = False

    def __init__(
        self, transport: MockTransport, seconds: float, declaration: str = "declare_success"
    ) -> None:
        self.transport = transport
        self.seconds = seconds
        self.declaration = declaration

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        await self.transport.sleep(self.seconds)
        return ProviderTurn(
            tool_calls=[ToolCall(name=self.declaration, arguments={"reason": "provider response"})]
        )


async def test_no_tool_call_is_reprompted_once_then_failure(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    result = await run_duck(
        RunConfig(
            duck=hello_duck, provider=NoToolProvider(), transport=MockTransport(), runs_dir=tmp_path
        )
    )
    assert result.outcome == "failure" and "no tool call" in result.reason
    assert result.llm_calls == 2


@pytest.mark.parametrize("declaration", ["declare_success", "declare_failure"])
async def test_time_budget_wins_over_late_declaration(
    hello_duck: DuckFile, tmp_path: Path, declaration: str
) -> None:
    hello_duck.frontmatter.budgets = Budgets(max_minutes=0.1)
    transport = MockTransport()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=ClockAdvancingProvider(transport, 7, declaration),
            transport=transport,
            runs_dir=tmp_path,
        )
    )

    assert result.outcome == "budget"
    assert result.reason == "max_minutes (0.1) exceeded"
    assert transport.now() == 7
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    kinds = [event["kind"] for event in events]
    assert "llm" in kinds and "declare" not in kinds


async def test_provider_response_before_time_budget_is_processed(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    hello_duck.frontmatter.budgets = Budgets(max_minutes=0.1, max_llm_calls=1)
    transport = MockTransport()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=ClockAdvancingProvider(transport, 5),
            transport=transport,
            runs_dir=tmp_path,
        )
    )

    assert result.outcome == "success"
    assert result.reason == "provider response"
    assert result.llm_calls == 1
    assert transport.now() == 5
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    assert "declare" in [event["kind"] for event in events]


async def test_budget_ends_the_run(hello_duck: DuckFile, tmp_path: Path) -> None:
    forever = FakeProvider(script=[ToolCall(name="quack", arguments={})])
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=forever,
            transport=MockTransport(),
            runs_dir=tmp_path,
            max_steps=2,
        )
    )
    assert result.outcome == "budget" and "max_steps" in result.reason
    assert result.steps == 2


async def test_disallowed_verb_is_feedback(hello_duck: DuckFile, tmp_path: Path) -> None:
    naughty = FakeProvider(
        script=[
            ToolCall(name="kick", arguments={}),
            ToolCall(name="declare_failure", arguments={"reason": "refused"}),
        ]
    )
    transport = MockTransport()
    result = await run_duck(
        RunConfig(duck=hello_duck, provider=naughty, transport=transport, runs_dir=tmp_path)
    )
    assert result.outcome == "failure"
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    verb_events = [e for e in events if e["kind"] == "verb"]
    assert verb_events[0]["name"] == "kick" and not verb_events[0]["ok"]
    assert "allowlist" in verb_events[0]["summary"]
    assert transport.intents_of("do") == []


async def test_heartbeat_failure_aborts_the_run(hello_duck: DuckFile, tmp_path: Path) -> None:
    transport = MockTransport(fail_heartbeat_after=0)
    forever = FakeProvider(script=[ToolCall(name="walk", arguments={"duration_s": 2.0})])
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=forever,
            transport=transport,
            runs_dir=tmp_path,
            heartbeat_period_s=0.001,
        )
    )
    assert result.outcome == "aborted"
    assert "heartbeat" in result.reason
    assert transport.stops >= 1


async def test_dry_run_touches_nothing(hello_duck: DuckFile, tmp_path: Path) -> None:
    transport = MockTransport()
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=transport,
            runs_dir=tmp_path,
            dry_run=True,
        )
    )
    assert result.outcome == "success"
    assert [i.kind for i in transport.intents] == ["stop"]  # only the final safety stop


# ── the trace: the run narrates itself ──────────────────────────────────────────────────


class ThinkingProvider:
    """A model that reasons out loud, which no scripted strategy does."""

    name = "thinker"
    model = "test"
    supports_vision = False

    def __init__(self, *calls: ToolCall) -> None:
        self.script = list(calls)
        self.calls = 0

    async def step(
        self, system: str, history: list[Exchange], tools: list[dict[str, Any]]
    ) -> ProviderTurn:
        call = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return ProviderTurn(
            tool_calls=[call],
            text="on it",
            thinking=f"turn {self.calls}: I will {call.name}",
            usage=Usage(input_tokens=100, output_tokens=10),
            stop_reason="tool_use",
        )


async def test_the_transcript_carries_the_whole_conversation(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    """Every step the run takes on the model's behalf is a line: what was asked, what it
    thought, what it answered, what the executor decided, what went to the robot."""
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=ThinkingProvider(
                ToolCall(name="quack", arguments={"text": "hi"}),
                ToolCall(name="declare_success", arguments={"reason": "quacked"}),
            ),
            transport=MockTransport(),
            runs_dir=tmp_path,
        )
    )
    assert result.outcome == "success"
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    kinds = {e["kind"] for e in events}
    assert {"llm_request", "verb_start", "intent", "verb_end"} <= kinds

    llm = next(e for e in events if e["kind"] == "llm")
    assert llm["thinking"] == "turn 1: I will quack"
    assert llm["latency_s"] >= 0 and llm["usage_total"]["input_tokens"] == 100

    request = next(e for e in events if e["kind"] == "llm_request")
    assert request["messages"] == 1 and request["reprompt"] is False

    start = next(e for e in events if e["kind"] == "verb_start")
    assert start["name"] == "quack" and start["source"] == "agent" and start["nested"] is False

    intent = next(e for e in events if e["kind"] == "intent")
    assert intent["intent"] == "sound" and intent["accepted"] is True

    end = next(e for e in events if e["kind"] == "verb_end")
    assert end["outcome"] == "ok" and end["intents"] == {"sound": 1} and end["elapsed_s"] >= 0
    # the loop's own `verb` record is unchanged, so everything that reads it still can
    verb = next(e for e in events if e["kind"] == "verb")
    assert verb["name"] == "quack" and verb["ok"] is True


async def test_the_final_safety_stop_is_in_the_trace_too(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    """The intents that matter most are the ones sent because something went wrong."""
    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path,
        )
    )
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    stops = [e for e in events if e["kind"] == "intent" and e["intent"] == "stop"]
    assert stops, "the run always stops the robot on the way out, and must say so"


async def test_a_provider_that_fails_says_so_instead_of_exiting_unexpectedly(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    """A bad key, a 429 or a dropped connection is what a first real run hits. The run used
    to end with `loop exited unexpectedly` and no record of the call that failed."""

    class Failing:
        name, model, supports_vision = "failing", "test", False

        async def step(self, system: str, history: Any, tools: Any) -> ProviderTurn:
            raise ProviderError("anthropic: rate limited (retry-after 7s)")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(ProviderError):
        await run_duck(
            RunConfig(
                duck=hello_duck,
                provider=Failing(),
                transport=MockTransport(),
                run_dir=run_dir,
                runs_dir=tmp_path,
            )
        )
    events = Transcript.read(run_dir / "transcript.jsonl")
    failed = next(e for e in events if e["kind"] == "llm")
    assert "rate limited" in failed["error"] and failed["latency_s"] >= 0
    end = next(e for e in events if e["kind"] == "run_end")
    assert end["outcome"] == "error" and "rate limited" in end["reason"]


async def test_a_cancelled_run_ends_as_an_abort_that_still_stops_and_records(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    """`KeyboardInterrupt` and `CancelledError` are not `Exception`, so neither reached the
    error branch and `run_end` kept its default, `loop exited unexpectedly` — the very string
    the trace work claimed to have removed. The CLI's second Ctrl-C is this path."""

    class Stalling:
        name, model, supports_vision = "stalling", "test", False

        async def step(self, system: str, history: Any, tools: Any) -> ProviderTurn:
            await asyncio.sleep(10)
            raise AssertionError("never reached")

    run_dir = tmp_path / "cancelled"
    run_dir.mkdir()
    transport = MockTransport()
    task = asyncio.create_task(
        run_duck(
            RunConfig(
                duck=hello_duck,
                provider=Stalling(),
                transport=transport,
                run_dir=run_dir,
                runs_dir=tmp_path,
            )
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    events = Transcript.read(run_dir / "transcript.jsonl")
    end = next(e for e in events if e["kind"] == "run_end")
    assert end["outcome"] == "aborted" and "CancelledError" in end["reason"]
    assert any(e["kind"] == "note" and "interrupted" in e["text"] for e in events)
    assert transport.intents[-1].kind == "stop" and not transport.connected
    assert (run_dir / "summary.json").exists()


async def test_a_record_that_fails_at_run_end_still_gets_its_summary_and_is_closed(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    """A disk that fills at the last line used to skip summary.json, leak the handle and
    replace the run's own outcome with an OSError."""
    from quackd.agent.loop import AgentLoop

    run_dir = tmp_path / "full"
    run_dir.mkdir()
    loop = AgentLoop(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            run_dir=run_dir,
            runs_dir=tmp_path,
        )
    )
    good = loop.transcript.sink

    def record(event: Any) -> None:
        if event.kind == "run_end":
            raise OSError("disk full")
        good(event)

    loop.tracer.record = record
    with pytest.raises(OSError, match="disk full"):
        await loop.run()
    assert (run_dir / "summary.json").exists()
    assert loop.transcript._fh.closed


def test_writing_to_a_closed_transcript_is_a_no_op(tmp_path: Path) -> None:
    """A verb task cancelled during teardown narrates its last intent after the record has
    closed; that must not raise inside a task nobody awaits."""
    from quackd.trace import TraceEvent

    t = Transcript(tmp_path)
    t.close()
    t.write("intent", intent="stop")
    t.sink(TraceEvent("intent", 0.0, {"intent": "stop"}))
    assert t.events == 0


async def test_a_console_sees_the_run_as_it_happens(hello_duck: DuckFile, tmp_path: Path) -> None:
    seen: list[str] = []
    await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path,
            trace=lambda event: seen.append(event.kind),
        )
    )
    assert seen[0] == "run_start" and seen[-1] == "run_end"
    assert {"observation", "llm", "verb_start", "intent", "verb_end", "declare"} <= set(seen)


async def test_a_broken_console_never_ends_a_run(hello_duck: DuckFile, tmp_path: Path) -> None:
    """A terminal that cannot print is not a reason to stop a robot mid-task."""

    def broken(_event: Any) -> None:
        raise RuntimeError("the terminal went away")

    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path,
            trace=broken,
        )
    )
    assert result.outcome == "success"
    assert Transcript.read(result.run_dir / "transcript.jsonl")  # the record is unaffected


async def test_the_summary_counts_the_events_a_broken_console_dropped(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    """A console that raises on every event produced a silent trace, an unchanged exit code
    and no line anywhere saying events had been dropped."""

    def broken(_event: Any) -> None:
        raise RuntimeError("the terminal went away")

    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path,
            trace=broken,
        )
    )
    assert result.trace_dropped > 0
    summary = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
    end = next(
        e for e in Transcript.read(result.run_dir / "transcript.jsonl") if e["kind"] == "run_end"
    )
    # the record's own count is one short of the run's, and can only ever be: it is taken
    # while the summary is built, and emitting `run_end` with it is one more event to drop.
    # The CLI prints the result's, which is complete.
    assert summary["trace_dropped"] == end["trace_dropped"] == result.trace_dropped - 1


async def test_thinking_on_the_reprompt_turn_is_recorded(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    """The re-prompt is a second call to the model in the same step, and nothing asserted
    that the request was marked as one or that its answer's reasoning was kept."""

    class Dithering:
        name, model, supports_vision = "dithering", "test", False

        def __init__(self) -> None:
            self.calls = 0

        async def step(self, system: str, history: Any, tools: Any) -> ProviderTurn:
            self.calls += 1
            if self.calls == 1:
                return ProviderTurn(tool_calls=[], text="hmm", thinking="turn 1: still deciding")
            return ProviderTurn(
                tool_calls=[ToolCall(name="declare_success", arguments={"reason": "done"})],
                thinking="turn 2: it wants exactly one tool",
            )

    result = await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=Dithering(),
            transport=MockTransport(),
            runs_dir=tmp_path,
        )
    )
    assert result.outcome == "success"
    events = Transcript.read(result.run_dir / "transcript.jsonl")
    requests = [e for e in events if e["kind"] == "llm_request"]
    assert [r["reprompt"] for r in requests] == [False, True]
    assert [e["thinking"] for e in events if e["kind"] == "llm"][1] == (
        "turn 2: it wants exactly one tool"
    )
    enforce = next(e for e in events if e["kind"] == "enforce")
    assert enforce["text"] == "You must call exactly one tool. Choose now."


async def test_the_log_callback_still_gets_the_lines_that_only_it_had(
    hello_duck: DuckFile, tmp_path: Path
) -> None:
    """`log` is a contract other callers rely on: the flock's member records, the MCP
    logger, and tests that assert on what a run said. The trace observes it, never replaces
    it."""
    # a v1 task may allow more than it needs; a verb this body lacks is dropped with a line
    hello_duck.frontmatter.duck = 1
    hello_duck.frontmatter.requires = ["quack"]
    hello_duck.frontmatter.verbs.allow = ["quack", "walk", "stop", "fly"]
    lines: list[str] = []
    seen: list[Any] = []
    await run_duck(
        RunConfig(
            duck=hello_duck,
            provider=FakeProvider.for_duck("hello-world"),
            transport=MockTransport(),
            runs_dir=tmp_path,
            log=lines.append,
            trace=seen.append,
        )
    )
    assert any("does not have fly" in line for line in lines)
    notes = [e.data["text"] for e in seen if e.kind == "note"]
    assert any("does not have fly" in note for note in notes)
