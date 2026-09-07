"""The loop narrates itself: one stream of events, and three views of it.

Everything quackd does on the model's behalf used to happen behind a terminal that printed a
header and an outcome, with the transcript on disk as the only record. This module is the
event stream that record was written from, opened up: the loop, the executor and a wrapper
around the transport emit `TraceEvent`s, and sinks render them. The transcript is the record
and always gets every event. The CLI's console and the MCP server's tool results are views of
the same stream, on by default and off with `--no-trace` or `QUACKD_TRACE=0`. Over MCP the
model is the client, so its reasoning never reaches quackd; there the trace shows what quackd
can see: the verb, the gates that fired, every intent sent, what came back, and how long it
took.

Lines are ASCII first. A redirected stderr on Windows turns an arrow glyph into a `?`, and this
is exactly the output people redirect. Colour, not glyphs, carries meaning, and every line is
printed as plain text: a model that thinks `[/think]` must not crash the renderer.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from quackd.transport.base import Ack, Intent


@dataclass(frozen=True)
class TraceEvent:
    kind: str
    t: float
    """Seconds since the tracer was made. The transcript stamps its own clock and ignores it."""
    data: dict[str, Any]
    """The payload, verbatim: what the transcript writes after `t` and `kind`."""


Sink = Callable[[TraceEvent], None]

_OFF = ("0", "false", "no", "off")


def trace_enabled_default() -> bool:
    """On unless `QUACKD_TRACE` says otherwise. An empty value is on, so `QUACKD_TRACE=` in a
    shell or a `.env` file switches nothing off by accident."""
    return os.environ.get("QUACKD_TRACE", "1").strip().lower() not in _OFF


def thinking_limit_default() -> int | None:
    """How much of the model's thinking the console shows per turn: `QUACKD_TRACE_THINKING` in
    characters, `all` for everything, `0` for none. The transcript always has all of it."""
    raw = os.environ.get("QUACKD_TRACE_THINKING", "").strip().lower()
    if raw == "all":
        return None
    try:
        return int(raw) if raw else 2000
    except ValueError:
        return 2000


class Tracer:
    """Fan-out. One `record` sink whose failure is the run's failure (the transcript), and any
    number of observers whose failure is their own: a console that cannot print must not end
    a run, so an observer's exception is swallowed and counted."""

    def __init__(self, record: Sink | None = None, observers: Iterable[Sink] = ()) -> None:
        self.record = record
        self.observers: list[Sink] = list(observers)
        self._t0 = time.monotonic()
        self.dropped = 0
        """Events an observer raised on and therefore never showed."""

    def add(self, sink: Sink) -> None:
        self.observers.append(sink)

    def remove(self, sink: Sink) -> None:
        if sink in self.observers:
            self.observers.remove(sink)

    def emit(self, kind: str, /, **data: Any) -> None:
        # positional-only: a payload is free to have a field of its own called `kind`
        event = TraceEvent(kind, round(time.monotonic() - self._t0, 3), data)
        if self.record is not None:
            self.record(event)
        for sink in self.observers:
            try:
                sink(event)
            except Exception:
                self.dropped += 1


# ── capturing one call's events (the MCP server) ────────────────────────────────────────

_capture: contextvars.ContextVar[list[TraceEvent] | None] = contextvars.ContextVar(
    "quackd_trace_capture", default=None
)


def capture_sink(event: TraceEvent) -> None:
    """An observer that appends to whatever `capturing()` is open in this context. The MCP
    server runs every tool call as its own task, and asyncio copies the context into a task
    at creation, so two calls on one robot never see each other's events."""
    buffer = _capture.get()
    if buffer is not None:
        buffer.append(event)


@contextlib.contextmanager
def capturing() -> Iterator[list[TraceEvent]]:
    events: list[TraceEvent] = []
    token = _capture.set(events)
    try:
        yield events
    finally:
        _capture.reset(token)


# ── counting one verb's intents ─────────────────────────────────────────────────────────

_tallies: contextvars.ContextVar[tuple[Counter[str], ...]] = contextvars.ContextVar(
    "quackd_intent_tallies", default=()
)


@contextlib.contextmanager
def counting() -> Iterator[Counter[str]]:
    """One tally for the verb in flight in this context, chained onto its parents' so a nested
    verb's intents count for the composite too.

    A context variable rather than a list on the executor: asyncio copies the context into
    each task at creation, so two MCP calls running at once on one executor never see each
    other's frame, and a verb that is cancelled unwinds its own frame instead of popping
    somebody else's. With a shared stack, a `quack` that overlapped a `move` reported the
    move's intents as its own and the move reported neither its resends nor its stop."""
    tally: Counter[str] = Counter()
    token = _tallies.set((*_tallies.get(), tally))
    try:
        yield tally
    finally:
        _tallies.reset(token)


# ── the transport as verbs see it ───────────────────────────────────────────────────────


class TracedTransport:
    """A transport for verbs: every intent they send becomes an `intent` event.

    Everything else is delegated to the real transport, so a verb's
    `getattr(ctx.transport, "stop_error", None)` still reaches the adapter. The tallies are
    read from the context at send time, not captured here, so an intent counts for whichever
    verb is in flight in the sending task and for each of its parents: that is how
    `approach_and` reports the intents its `go_to` sent."""

    def __init__(self, inner: Any, tracer: Tracer) -> None:
        self._inner = inner
        self._tracer = tracer

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):  # never delegate our own privates (copy, pickle, half-init)
            raise AttributeError(name)
        return getattr(self._inner, name)

    def _count(self, kind: str) -> None:
        for tally in _tallies.get():
            tally[kind] += 1

    async def send_intent(self, intent: Intent) -> Ack:
        try:
            ack = await self._inner.send_intent(intent)
        except Exception as e:
            self._count(intent.kind)
            self._tracer.emit(
                "intent",
                intent=intent.kind,
                params=intent.params,
                accepted=False,
                reason=f"{type(e).__name__}: {e}",
            )
            raise
        self._count(intent.kind)
        self._tracer.emit(
            "intent",
            intent=intent.kind,
            params=intent.params,
            accepted=ack.accepted,
            reason=ack.reason,
        )
        return ack

    async def stop(self) -> None:
        try:
            await self._inner.stop()
        except Exception as e:
            self._count("stop")
            self._tracer.emit(
                "intent",
                intent="stop",
                params={},
                accepted=False,
                reason=f"{type(e).__name__}: {e}",
            )
            raise
        self._count("stop")
        self._tracer.emit("intent", intent="stop", params={}, accepted=True, reason=None)


# ── rendering ───────────────────────────────────────────────────────────────────────────

Line = tuple[str, str]
"""(text, style). Styles are Rich style names the console maps; other writers ignore them."""

_LABEL = 8
_PAD = " " * _LABEL


def _label(name: str) -> str:
    return f"{name:<{_LABEL}}"


def _indent(text: str) -> str:
    return ("\n" + _PAD).join(text.splitlines()) if text else ""


def fmt_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3g}"
    if isinstance(value, str):
        return repr(value) if len(value) <= 60 else repr(value[:57] + "...")
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


def fmt_params(params: Mapping[str, Any] | None, *, drop_none: bool = False) -> str:
    """`drop_none` is for intent bursts, where a twist's `vy=null` on every one of two
    hundred lines is noise. Everywhere else a parameter the model left unset is part of what
    it chose, and `--dry-run` promises to show every one of them."""
    if not params:
        return ""
    return ", ".join(
        f"{k}={fmt_value(v)}" for k, v in params.items() if not (drop_none and v is None)
    )


def _ok(outcome: str) -> bool:
    return outcome == "ok"


def render_lines(
    event: TraceEvent, *, thinking_chars: int | None = 2000, prompt: bool = True
) -> list[Line]:
    """One event as zero or more (text, style) lines. The loop's own `verb` record, the
    `frame` record and `run_end` render nothing: the first duplicates `verb_end`, the second
    is a file on disk, and the CLI prints the outcome itself."""
    d = event.data
    k = event.kind
    if k == "run_start":
        adapter = d.get("adapter")
        robot = f"{adapter}:{d.get('transport')}" if adapter else str(d.get("transport"))
        head = (
            f"{_label('run')}{d.get('duck')} provider={d.get('provider')} "
            f"model={d.get('model')} robot={robot}"
        )
        if d.get("dry_run"):
            head += " DRY RUN"
        if "connect_s" in d:
            head += f" connected in {d['connect_s']:.2f} s"
        lines: list[Line] = [(head, "bold")]
        lines.append((f"{_label('tools')}{', '.join(d.get('tools') or [])}", "dim"))
        memory = d.get("memory")
        if memory:
            lines.append(
                (
                    f"{_label('memory')}{memory.get('notes')} notes, "
                    f"{memory.get('episodes')} earlier runs",
                    "dim",
                )
            )
        system = d.get("system_prompt")
        if prompt and system:
            n_lines = system.count("\n") + 1
            lines.append(
                (
                    f"{_label('prompt')}system prompt, {len(system)} chars, {n_lines} lines "
                    "(also in transcript.jsonl as run_start):",
                    "dim",
                )
            )
            lines.append((_PAD + _indent(system), "dim"))
        return lines
    if k == "observation":
        if "error" in d:
            return [(f"{_label('obs')}ERROR {d['error']}", "red")]
        return [(_label("obs") + _indent(str(d.get("text", ""))), "")]
    if k == "llm_request":
        text = (
            f"{_label('llm>')}step {d.get('step')}: {d.get('messages')} messages "
            f"({d.get('images', 0)} with image) to {d.get('provider')} {d.get('model')}"
        )
        if d.get("reprompt"):
            text += " (re-prompt: it made no tool call)"
        return [(text, "dim")]
    if k == "llm":
        if "error" in d:
            return [
                (f"{_label('llm<')}ERROR {d['error']} after {d.get('latency_s', 0):.1f} s", "red")
            ]
        out: list[Line] = []
        thinking = d.get("thinking")
        if thinking and thinking_chars != 0:
            text = str(thinking)
            if thinking_chars is not None and len(text) > thinking_chars:
                text = text[:thinking_chars] + (
                    f"... (+{len(text) - thinking_chars} chars in transcript.jsonl)"
                )
            out.append((_label("think") + _indent(text), "dim italic"))
        if d.get("text"):
            out.append((_label("llm<") + _indent(str(d["text"])), ""))
        calls = d.get("tool_calls") or []
        if not calls:
            out.append((f"{_label('tool')}(no tool call)", "yellow"))
        for call in calls:
            out.append(
                (f"{_label('tool')}{call.get('name')}({fmt_params(call.get('arguments'))})", "bold")
            )
        usage = d.get("usage") or {}
        total = d.get("usage_total") or {}
        tokens = (
            f"{_label('tokens')}in={usage.get('input_tokens', 0)} "
            f"out={usage.get('output_tokens', 0)}"
        )
        if usage.get("reasoning_tokens"):
            tokens += f" reasoning={usage['reasoning_tokens']}"
        if total:
            tokens += (
                f" (run total in={total.get('input_tokens', 0)} "
                f"out={total.get('output_tokens', 0)})"
            )
        if "latency_s" in d:
            tokens += f" latency={d['latency_s']:.1f} s"
        if d.get("stop_reason"):
            tokens += f" stop={d['stop_reason']}"
        out.append((tokens, "dim"))
        return out
    if k == "enforce":
        return [(f"{_label('enforce')}{d.get('issue')}: {d.get('action')}", "yellow")]
    if k == "verb_start":
        text = f"{_label('verb')}{d.get('name')}({fmt_params(d.get('params'))})"
        if d.get("nested"):
            text = f"{_label('verb')}  {d.get('name')}({fmt_params(d.get('params'))}) [nested]"
        if d.get("source") and d.get("source") != "agent":
            text += f" from {d['source']}"
        return [(text, "bold")]
    if k == "gate":
        text = f"{_label('gate')}{d.get('gate')}: {d.get('outcome')}"
        if d.get("reason"):
            text += f" {d['reason']}"
        if d.get("params"):
            text += f" ({fmt_params(d['params'])})"
        if d.get("state"):
            text += f" [state: {d['state']}]"
        if d.get("last"):
            text += f" [last: {d['last']}]"
        refused = d.get("outcome") in ("refused", "denied", "exceeded", "fired")
        return [(text, "red" if refused else "yellow")]
    if k == "intent":
        return [intent_line([event])]
    if k == "verb_end":
        outcome = str(d.get("outcome", "ok" if d.get("ok") else "fail"))
        verdict = "ok" if _ok(outcome) else ("FAIL" if outcome == "fail" else outcome.upper())
        n = sum((d.get("intents") or {}).values())
        tail = f" ({d.get('elapsed_s', 0):.1f} s, {n} intent{'s' if n != 1 else ''})"
        text = f"{_label('<-')}{d.get('name')} {verdict}: {d.get('summary')}{tail}"
        if d.get("nested"):
            text = f"{_label('<-')}  {d.get('name')} {verdict}: {d.get('summary')}{tail}"
        return [(text, "green" if _ok(outcome) else "red")]
    if k == "declare":
        return [
            (
                f"{_label('declare')}{d.get('outcome')}: {d.get('reason')}",
                "bold green" if d.get("outcome") == "success" else "bold red",
            )
        ]
    if k == "memory":
        return [(f"{_label('memory')}{d.get('summary')}", "cyan")]
    if k == "note":
        return [(_label("note") + _indent(str(d.get("text", ""))), "dim")]
    if k == "tool_call":
        args = {key: value for key, value in d.items() if key not in ("tool", "robot")}
        return [(f"{_label('tool')}{d.get('tool')} {fmt_params(args)} on {d.get('robot')}", "bold")]
    if k == "tool_result":
        text = f"{_label('done')}{'ok' if d.get('ok') else 'FAIL'} in {d.get('elapsed_s', 0):.1f} s"
        if d.get("budget"):
            text += f" budget: {d['budget']}"
        return [(text, "dim")]
    return []


def _ranges(events: list[TraceEvent]) -> str:
    """`vx 0.05..0.2, vy 0, wz -1..0.4` for numbers; the distinct values for anything else."""
    seen: dict[str, list[Any]] = {}
    for event in events:
        for key, value in (event.data.get("params") or {}).items():
            if value is not None:
                seen.setdefault(key, []).append(value)
    parts: list[str] = []
    for key, values in seen.items():
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in values):
            lo, hi = min(values), max(values)
            parts.append(
                f"{key} {fmt_value(lo)}" if lo == hi else f"{key} {fmt_value(lo)}..{fmt_value(hi)}"
            )
        else:
            # only ever three are shown, so stop at four: this runs inside the console
            # observer, on the event loop, between two deadman resends
            distinct: list[str] = []
            for v in values:
                shown = fmt_value(v)
                if shown not in distinct:
                    distinct.append(shown)
                if len(distinct) > 3:
                    break
            parts.append(f"{key} {'/'.join(distinct[:3])}{'...' if len(distinct) > 3 else ''}")
    return ", ".join(parts)


def intent_line(events: list[TraceEvent]) -> Line:
    """One line for a burst of intents of one kind: the intent itself when there is one, a
    count with the parameter ranges when a steering loop sent dozens."""
    first = events[0]
    kind = first.data.get("intent")
    if len(events) == 1:
        params = fmt_params(first.data.get("params"), drop_none=True)
        text = f"{_label('->')}{kind}({params})" if params else f"{_label('->')}{kind}"
        if not first.data.get("accepted", True):
            return (f"{text} REFUSED: {first.data.get('reason') or 'no reason given'}", "red")
        return (text, "dim")
    span = events[-1].t - first.t
    ranges = _ranges(events)
    text = f"{_label('->')}{kind} x{len(events)} over {span:.1f} s"
    if ranges:
        text += f" ({ranges})"
    return (text, "dim")


class LineTrace:
    """A sink that renders events as lines through `write(text, style)`, coalescing a burst of
    one intent kind into one line. A `go_to` sends a different twist every 100 ms, so the
    burst is collapsed by kind, not by identical parameters, and flushed when anything else
    arrives. Refused intents are never coalesced: each one is worth a line."""

    def __init__(
        self,
        write: Callable[[str, str], None],
        *,
        thinking_chars: int | None = 2000,
        prompt: bool = True,
    ) -> None:
        self._write = write
        self.thinking_chars = thinking_chars
        self.prompt = prompt
        self._pending: list[TraceEvent] = []

    def __call__(self, event: TraceEvent) -> None:
        if event.kind == "intent" and event.data.get("accepted", True):
            if self._pending and self._pending[0].data.get("intent") != event.data.get("intent"):
                self.flush()
            self._pending.append(event)
            return
        self.flush()
        for text, style in render_lines(
            event, thinking_chars=self.thinking_chars, prompt=self.prompt
        ):
            self._write(text, style)

    def flush(self) -> None:
        if not self._pending:
            return
        # write first, clear after: a write that fails (the Tracer swallows and counts it)
        # should leave the burst for the next flush rather than losing it
        self._write(*intent_line(self._pending))
        self._pending = []


class ConsoleTrace(LineTrace):
    """The CLI view: every line to a Rich console, as plain text with a style, never markup."""

    def __init__(
        self, console: Any, *, thinking_chars: int | None = None, prompt: bool = True
    ) -> None:
        super().__init__(
            self._print,
            thinking_chars=thinking_limit_default() if thinking_chars is None else thinking_chars,
            prompt=prompt,
        )
        self.console = console

    def _print(self, text: str, style: str) -> None:
        self.console.print(text, style=style or None, markup=False, highlight=False, soft_wrap=True)


MCP_TRACE_MAX_LINES = 30
_MCP_HEAD = 10


def cap_lines(
    lines: list[str], limit: int = MCP_TRACE_MAX_LINES, head: int = _MCP_HEAD
) -> list[str]:
    """The first few and the last many, with one line saying what was cut. A tool result is
    read by the model on every call; the uncapped trace is on the server's stderr."""
    if len(lines) <= limit:
        return lines
    tail = limit - head - 1
    cut = len(lines) - head - tail
    return [
        *lines[:head],
        f"... {cut} more lines (the full trace is on the server's stderr)",
        *lines[-tail:],
    ]


def call_lines(events: list[TraceEvent]) -> list[str]:
    """One call's events as plain lines, uncapped.

    Guarded, unlike the `Tracer`'s observers: this runs outside the tracer, so a formatting
    error here would turn a robot's refusal into an MCP internal error rather than a result.
    """
    lines: list[str] = []
    view = LineTrace(lambda text, _style: lines.append(text), prompt=False)
    try:
        for event in events:
            view(event)
        view.flush()
    except Exception as e:
        lines.append(f"(the trace could not be rendered: {type(e).__name__}: {e})")
    return lines


def render_call(events: list[TraceEvent]) -> list[str]:
    """One MCP tool call's events as short plain lines for the `trace` field of its result."""
    return cap_lines(call_lines(events))


__all__ = [
    "MCP_TRACE_MAX_LINES",
    "ConsoleTrace",
    "LineTrace",
    "Sink",
    "TraceEvent",
    "TracedTransport",
    "Tracer",
    "call_lines",
    "cap_lines",
    "capture_sink",
    "capturing",
    "counting",
    "fmt_params",
    "intent_line",
    "render_call",
    "render_lines",
    "thinking_limit_default",
    "trace_enabled_default",
]
