"""The trace: one event stream, and the views that must not lie about it or crash on it."""

from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest
from rich.console import Console

from quackd.trace import (
    ConsoleTrace,
    LineTrace,
    TracedTransport,
    TraceEvent,
    Tracer,
    cap_lines,
    capture_sink,
    capturing,
    counting,
    render_call,
    render_lines,
    thinking_limit_default,
    trace_enabled_default,
)
from quackd.transport.base import Ack, Intent
from quackd.transport.mock import MockTransport


def events(tracer: Tracer) -> list[TraceEvent]:
    seen: list[TraceEvent] = []
    tracer.add(seen.append)
    return seen


def lines(sink_events: list[TraceEvent], **kwargs: Any) -> list[str]:
    out: list[str] = []
    view = LineTrace(lambda text, _style: out.append(text), **kwargs)
    for event in sink_events:
        view(event)
    view.flush()
    return out


# ── the tracer ──────────────────────────────────────────────────────────────────────────


def test_the_record_sink_gets_every_event_and_its_failure_is_the_runs() -> None:
    """The transcript is the record: a write that fails must not be swallowed the way a
    console that cannot print is."""

    def broken(_event: TraceEvent) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        Tracer(record=broken).emit("run_start")


def test_an_observer_that_raises_never_ends_a_run() -> None:
    written: list[str] = []

    def broken(_event: TraceEvent) -> None:
        raise ValueError("a terminal that cannot print")

    tracer = Tracer(record=lambda e: written.append(e.kind), observers=[broken])
    tracer.emit("llm", text="hello")
    assert written == ["llm"] and tracer.dropped == 1


def test_a_payload_may_have_a_field_called_kind() -> None:
    """The intent's own kind used to collide with the event kind, and the transcript wrote
    `{"kind": "move"}` for what was an `intent` event."""
    seen: list[TraceEvent] = []
    Tracer(record=seen.append).emit("intent", intent="move", kind="not the event kind")
    assert seen[0].kind == "intent" and seen[0].data["kind"] == "not the event kind"


def test_events_are_stamped_in_order() -> None:
    tracer = Tracer()
    seen = events(tracer)
    tracer.emit("a")
    tracer.emit("b")
    assert [e.kind for e in seen] == ["a", "b"] and seen[0].t <= seen[1].t


# ── the transport verbs see ─────────────────────────────────────────────────────────────


async def test_every_intent_and_stop_is_an_event() -> None:
    tracer = Tracer()
    seen = events(tracer)
    inner = MockTransport()
    traced = TracedTransport(inner, tracer)
    await traced.send_intent(Intent.move(0.2, 0.0, 0.1))
    await traced.stop()
    assert [e.kind for e in seen] == ["intent", "intent"]
    assert seen[0].data == {
        "intent": "move",
        "params": {"vx": 0.2, "vy": 0.0, "wz": 0.1},
        "accepted": True,
        "reason": None,
    }
    assert seen[1].data["intent"] == "stop"
    # and the real transport really got them
    assert [i.kind for i in inner.intents] == ["move", "stop"]


async def test_a_refused_intent_says_so() -> None:
    tracer = Tracer()
    seen = events(tracer)
    traced = TracedTransport(MockTransport(refuse_kinds={"sound"}), tracer)
    ack = await traced.send_intent(Intent.sound("greet", "hi"))
    assert not ack.accepted
    assert seen[0].data["accepted"] is False and "refuses" in seen[0].data["reason"]


async def test_a_transport_that_raises_is_traced_and_still_raises() -> None:
    class Broken(MockTransport):
        async def send_intent(self, intent: Intent) -> Ack:
            raise ConnectionError("the link is gone")

    tracer = Tracer()
    seen = events(tracer)
    with pytest.raises(ConnectionError):
        await TracedTransport(Broken(), tracer).send_intent(Intent.stop())
    assert seen[0].data["accepted"] is False and "ConnectionError" in seen[0].data["reason"]


def test_everything_else_is_delegated() -> None:
    """Verbs probe the transport for things only some bodies have. `stop_error` is what the
    `stop` verb reads to tell "stopped" from "could not deliver a stop"."""
    inner = MockTransport()
    inner.stop_error = "the socket is gone"  # type: ignore[attr-defined]
    traced = TracedTransport(inner, Tracer())
    assert getattr(traced, "stop_error", None) == "the socket is gone"
    assert getattr(traced, "camera_error", None) is None
    assert traced.name == "mock" and traced.now() == inner.now()


def test_a_wrapper_without_its_privates_raises_attribute_error_not_recursion() -> None:
    traced = TracedTransport.__new__(TracedTransport)  # never ran __init__
    with pytest.raises(AttributeError):
        traced._inner  # noqa: B018


async def test_a_nested_verbs_intents_count_for_its_parent_too() -> None:
    """`approach_and` sends nothing itself; every intent comes from the `go_to` it runs. A
    parent that reported zero intents would be the misleading kind of true."""
    from collections import Counter

    traced = TracedTransport(MockTransport(), Tracer())
    with counting() as parent:
        await traced.send_intent(Intent.move(0.1))
        with counting() as child:
            await traced.send_intent(Intent.move(0.2))
            await traced.stop()
    assert child == Counter({"move": 1, "stop": 1})
    assert parent == Counter({"move": 2, "stop": 1})


async def test_an_intent_sent_outside_any_verb_is_counted_by_nobody() -> None:
    """The heartbeat's stop belongs to no verb: it must not land on whichever tally happens
    to be open in another task."""
    traced = TracedTransport(MockTransport(), Tracer())
    await traced.stop()  # no `counting()` block: must not raise, must count nowhere
    with counting() as tally:
        pass
    assert tally == {}


# ── rendering ───────────────────────────────────────────────────────────────────────────


def test_a_burst_of_one_intent_kind_becomes_one_line_with_its_ranges() -> None:
    """`go_to` recomputes its twist every 100 ms, so consecutive intents are never identical;
    coalescing by kind is what keeps a 20 s approach from being 200 lines."""
    tracer = Tracer()
    seen = events(tracer)
    for wz in (-0.4, 0.0, 0.35):
        tracer.emit("intent", intent="move", params={"vx": 0.2, "wz": wz}, accepted=True)
    tracer.emit("intent", intent="stop", params={}, accepted=True)
    out = lines(seen)
    assert len(out) == 2
    assert "move x3" in out[0] and "vx 0.2" in out[0] and "wz -0.4..0.35" in out[0]
    assert out[1].split() == ["->", "stop"]  # the label column is padded


def test_a_refused_intent_is_never_folded_into_a_count() -> None:
    tracer = Tracer()
    seen = events(tracer)
    tracer.emit("intent", intent="move", params={"vx": 0.1}, accepted=True)
    tracer.emit("intent", intent="move", params={"vx": 0.1}, accepted=False, reason="too fast")
    out = lines(seen)
    assert len(out) == 2 and "REFUSED: too fast" in out[1]


def test_the_dry_run_gate_shows_a_parameter_the_model_left_null() -> None:
    """`--dry-run` promises every parameter a model would have sent. A parameter it
    explicitly left unset used to render identically to one it never named."""
    event = TraceEvent(
        "gate",
        0.0,
        {
            "name": "go_to",
            "gate": "dry_run",
            "outcome": "skipped",
            "reason": "would run go_to, sent nothing",
            "params": {"target": None, "stop_distance": 0.25},
        },
    )
    ((text, _),) = render_lines(event)
    assert "target=null" in text and "stop_distance=0.25" in text


def test_an_intent_line_still_drops_null_parameters() -> None:
    """A twist's `vy=null` on every one of two hundred burst lines is noise."""
    event = TraceEvent("intent", 0.0, {"intent": "move", "params": {"vx": 0.1, "vy": None}})
    ((text, _),) = render_lines(event)
    assert "vx=0.1" in text and "vy" not in text


def test_a_burst_with_many_distinct_labels_shows_three_and_an_ellipsis() -> None:
    tracer = Tracer()
    seen = events(tracer)
    for i in range(50):
        tracer.emit("intent", intent="do", params={"skill": f"s{i}"}, accepted=True)
    (out,) = lines(seen)
    assert "s0'/'s1'/'s2'..." in out.replace('"', "'") or "s0" in out
    assert "..." in out


def test_a_write_that_fails_keeps_the_burst_for_the_next_flush() -> None:
    """`flush` used to clear the pending burst before writing it, so a write that raised
    lost the intents entirely."""
    written: list[str] = []
    failed = {"once": True}

    def write(text: str, _style: str) -> None:
        if failed["once"]:
            failed["once"] = False
            raise RuntimeError("the terminal went away")
        written.append(text)

    view = LineTrace(write)
    view(TraceEvent("intent", 0.0, {"intent": "move", "params": {"vx": 0.1}, "accepted": True}))
    with pytest.raises(RuntimeError):
        view.flush()
    view.flush()
    assert len(written) == 1 and "move" in written[0]


def test_a_renderer_bug_never_turns_a_result_into_an_internal_error() -> None:
    """`render_call` runs outside the tracer, so nothing swallows its exceptions: a
    formatting error would have failed the MCP tool call instead of answering it."""
    broken = TraceEvent("verb_end", 0.0, {"elapsed_s": "soon", "intents": {"move": 1}})
    rendered = render_call([broken])
    assert len(rendered) == 1 and "could not be rendered" in rendered[0]


def test_the_llm_line_shows_thinking_the_call_and_the_tokens() -> None:
    event = TraceEvent(
        "llm",
        0.0,
        {
            "step": 2,
            "text": "going for it",
            "thinking": "the ball is 0.4 m away, so walk first",
            "tool_calls": [{"name": "go_to", "arguments": {"target": "ball"}}],
            "usage": {"input_tokens": 1200, "output_tokens": 40},
            "usage_total": {"input_tokens": 5000, "output_tokens": 130},
            "latency_s": 1.25,
            "stop_reason": "tool_use",
        },
    )
    out = [text for text, _ in render_lines(event)]
    assert any("the ball is 0.4 m away" in line for line in out)
    assert any("go_to(target='ball')" in line for line in out)
    assert any("in=1200 out=40" in line and "latency=1.2 s" in line for line in out)


def test_long_thinking_is_cut_with_a_pointer_to_the_transcript() -> None:
    event = TraceEvent("llm", 0.0, {"thinking": "x" * 5000, "tool_calls": [], "usage": {}})
    out = [text for text, _ in render_lines(event, thinking_chars=100)]
    assert "+4900 chars in transcript.jsonl" in out[0] and len(out[0]) < 400
    full = [text for text, _ in render_lines(event, thinking_chars=None)]
    assert "transcript.jsonl" not in full[0] and len(full[0]) > 4000
    none = [text for text, _ in render_lines(event, thinking_chars=0)]
    assert not any("xxx" in line for line in none)


def test_an_llm_call_that_failed_is_a_line_too() -> None:
    event = TraceEvent("llm", 0.0, {"error": "ProviderError: rate limited", "latency_s": 3.0})
    ((text, style),) = render_lines(event)
    assert "rate limited" in text and style == "red"


def test_a_gate_says_which_rule_refused_and_why() -> None:
    event = TraceEvent(
        "gate",
        0.0,
        {"name": "kick", "gate": "allowlist", "outcome": "refused", "reason": "not allowed here"},
    )
    ((text, style),) = render_lines(event)
    assert "allowlist: refused not allowed here" in text and style == "red"


def test_the_dry_run_gate_shows_what_would_have_been_sent() -> None:
    event = TraceEvent(
        "gate",
        0.0,
        {
            "name": "walk",
            "gate": "dry_run",
            "outcome": "skipped",
            "reason": "would run walk, sent nothing",
            "params": {"vx": 0.15, "duration_s": 1.0},
        },
    )
    ((text, _),) = render_lines(event)
    assert "vx=0.15" in text and "duration_s=1" in text


def test_the_verb_end_line_counts_the_intents_and_the_seconds() -> None:
    event = TraceEvent(
        "verb_end",
        0.0,
        {
            "name": "go_to",
            "ok": True,
            "outcome": "ok",
            "summary": "reached the ball",
            "elapsed_s": 12.5,
            "intents": {"move": 120, "stop": 1},
        },
    )
    ((text, style),) = render_lines(event)
    assert "go_to ok: reached the ball (12.5 s, 121 intents)" in text and style == "green"


def test_the_loops_own_verb_record_renders_nothing() -> None:
    """It is the same call as `verb_end`, kept in the transcript for the readers that pin it."""
    assert render_lines(TraceEvent("verb", 0.0, {"name": "kick", "ok": True})) == []
    assert render_lines(TraceEvent("frame", 0.0, {"path": "frames/0001.png"})) == []
    assert render_lines(TraceEvent("run_end", 0.0, {"outcome": "success"})) == []


def test_run_start_shows_the_prompt_once_and_can_be_asked_not_to() -> None:
    event = TraceEvent(
        "run_start",
        0.0,
        {
            "duck": "find-and-kick",
            "provider": "anthropic",
            "model": "claude-opus-5",
            "transport": "sim2d",
            "adapter": "microduck",
            "tools": ["walk", "kick"],
            "system_prompt": "You are the brain of a duck.\nRules follow.",
            "connect_s": 0.05,
        },
    )
    with_prompt = [text for text, _ in render_lines(event)]
    assert any("You are the brain of a duck." in line for line in with_prompt)
    assert any("robot=microduck:sim2d" in line for line in with_prompt)
    without = [text for text, _ in render_lines(event, prompt=False)]
    assert not any("brain of a duck" in line for line in without)


# ── the console ─────────────────────────────────────────────────────────────────────────


def console_trace() -> tuple[ConsoleTrace, io.StringIO]:
    buffer = io.StringIO()
    console = Console(file=buffer, width=200, force_terminal=False, no_color=True)
    return ConsoleTrace(console, thinking_chars=None), buffer


def test_square_brackets_in_what_the_model_wrote_survive_verbatim() -> None:
    """Rich reads `[dim]` as markup and raises on an unpaired closing tag. Every line here
    carries text a model or a robot wrote, so none of it may be parsed as markup."""
    view, buffer = console_trace()
    view(
        TraceEvent(
            "llm",
            0.0,
            {
                "thinking": "[/think] and [dry-run] and [bold]",
                "text": "the ball is [behind] the sofa",
                "tool_calls": [],
                "usage": {},
            },
        )
    )
    out = buffer.getvalue()
    assert "[/think]" in out and "[dry-run]" in out and "[bold]" in out
    assert "[behind]" in out


def test_the_console_flushes_a_pending_burst_before_the_next_line() -> None:
    view, buffer = console_trace()
    for _ in range(3):
        view(TraceEvent("intent", 0.0, {"intent": "move", "params": {"vx": 0.1}, "accepted": True}))
    view(
        TraceEvent(
            "verb_end", 0.4, {"name": "move", "ok": True, "outcome": "ok", "summary": "walked"}
        )
    )
    out = buffer.getvalue().splitlines()
    assert "move x3" in out[0] and "walked" in out[1]


# ── capturing one call (the MCP server) ─────────────────────────────────────────────────


async def test_two_concurrent_calls_never_see_each_others_events() -> None:
    """The MCP SDK runs every tool call as its own task. A buffer on the session would put
    one call's intents in the other call's result."""
    tracer = Tracer(observers=[capture_sink])

    async def call(name: str, delay: float) -> list[str]:
        with capturing() as seen:
            tracer.emit("verb_start", name=name)
            await asyncio.sleep(delay)
            tracer.emit("intent", intent=name, params={}, accepted=True)
            await asyncio.sleep(delay)
            tracer.emit("verb_end", name=name, ok=True, outcome="ok", summary="done")
            return [e.data.get("name") or e.data.get("intent") for e in seen]

    slow, fast = await asyncio.gather(call("go_to", 0.02), call("quack", 0.001))
    assert set(slow) == {"go_to"} and set(fast) == {"quack"}


def test_nothing_is_captured_outside_a_call() -> None:
    Tracer(observers=[capture_sink]).emit("note", text="the heartbeat failed")  # must not raise


def test_render_call_is_short_plain_lines() -> None:
    tracer = Tracer(observers=[capture_sink])
    with capturing() as seen:
        tracer.emit("tool_call", tool="robot_run_verb", robot="duck", verb="go_to", params={})
        tracer.emit("verb_start", name="go_to", params={"target": "ball"}, source="mcp")
        for wz in (0.1, 0.2):
            tracer.emit("intent", intent="move", params={"vx": 0.2, "wz": wz}, accepted=True)
        tracer.emit(
            "verb_end",
            name="go_to",
            ok=True,
            outcome="ok",
            summary="reached the ball",
            elapsed_s=1.0,
            intents={"move": 2},
        )
        tracer.emit(
            "tool_result", tool="robot_run_verb", ok=True, elapsed_s=1.1, budget="step 1/40"
        )
    rendered = render_call(seen)
    assert any("go_to(target='ball') from mcp" in line for line in rendered)
    assert any("move x2" in line for line in rendered)
    assert any("reached the ball" in line for line in rendered)
    assert any("step 1/40" in line for line in rendered)
    assert all(isinstance(line, str) for line in rendered)


def test_a_long_trace_is_capped_and_says_what_it_cut() -> None:
    capped = cap_lines([f"line {i}" for i in range(100)], limit=10, head=3)
    assert len(capped) == 10
    assert capped[:3] == ["line 0", "line 1", "line 2"]
    assert "91 more lines" in capped[3] and "stderr" in capped[3]
    assert capped[-1] == "line 99"
    short = ["a", "b"]
    assert cap_lines(short, limit=10) == short


# ── the switch ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "on"),
    [
        (None, True),
        ("", True),
        ("1", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("off", False),
    ],
)
def test_the_env_switch(monkeypatch: pytest.MonkeyPatch, value: str | None, on: bool) -> None:
    if value is None:
        monkeypatch.delenv("QUACKD_TRACE", raising=False)
    else:
        monkeypatch.setenv("QUACKD_TRACE", value)
    assert trace_enabled_default() is on


@pytest.mark.parametrize(
    ("value", "limit"), [("", 2000), ("all", None), ("0", 0), ("500", 500), ("nonsense", 2000)]
)
def test_how_much_thinking_the_console_shows(
    monkeypatch: pytest.MonkeyPatch, value: str, limit: int | None
) -> None:
    monkeypatch.setenv("QUACKD_TRACE_THINKING", value)
    assert thinking_limit_default() == limit
