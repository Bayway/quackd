"""What the scripted pilot puts on the trace's `think` line.

Every runnable example in the README uses `--provider fake`, so this line is the only
thinking most readers ever see. It has to be honest about being a rule, and it has to be
inert: the transcript is grepped elsewhere for quoted verb names.
"""

from __future__ import annotations

from typing import Any

import pytest

from quackd.agent.providers.base import Decision, Exchange, Observation, ToolCall
from quackd.agent.providers.fake import FakeProvider

SYSTEM = "You are the brain of a small duck robot."
ALLOWED = ["search_scan", "walk_to", "kick", "quack", "declare_success", "declare_failure"]


def _observation(
    *,
    detections: list[dict[str, Any]] | None = None,
    last_result: dict[str, Any] | None = None,
) -> Observation:
    return Observation(
        text="[step 0/12] state: posture=stand policy=walk",
        features={
            "state": {"posture": "stand", "policy": "walk"},
            "detections": detections or [],
            "last_result": last_result,
            "allowed": ALLOWED,
        },
    )


def _ball(distance: float = 0.58, bearing: float = 18.0) -> dict[str, Any]:
    return {
        "label": "ball",
        "cx": 0.4,
        "cy": 0.6,
        "area": 0.02,
        "bearing_deg": bearing,
        "est_distance_m": distance,
    }


def _scanned(verb: str = "search_scan") -> list[Exchange]:
    """Two turns already spent on `verb`, so the observation under test is really step 2."""
    return [
        Exchange(
            observation=_observation(),
            decision=Decision(tool_call=ToolCall(id=f"fake-{i}", name=verb, arguments={})),
        )
        for i in (1, 2)
    ]


async def test_the_scripted_pilot_says_what_it_saw_and_what_it_picked() -> None:
    """The line names the two inputs the rule branched on — the camera and the last verb —
    and the verb that fell out, which is the whole point of showing it."""
    history = [
        *_scanned(),
        Exchange(
            observation=_observation(
                detections=[_ball()],
                last_result={"verb": "search_scan", "ok": True, "summary": "found 1", "data": {}},
            )
        ),
    ]
    turn = await FakeProvider.for_duck("find-and-kick").step(SYSTEM, history, [])

    assert turn.thinking == (
        "[scripted] step 2: sees 1 ball (nearest 0.58 m, 18 deg left) after search_scan ok, "
        "so the rule picks walk_to"
    )
    assert turn.thinking.endswith(f"so the rule picks {turn.tool_calls[0].name}")


async def test_the_scripted_pilot_says_when_it_sees_nothing() -> None:
    """An empty camera and no verb behind it still produce a whole sentence: a blank think
    line would be indistinguishable from the bug this feature fixes."""
    history = [Exchange(observation=_observation())]
    turn = await FakeProvider.for_duck("find-and-kick").step(SYSTEM, history, [])

    assert (
        turn.thinking == "[scripted] step 0: sees nothing it knows, so the rule picks search_scan"
    )
    assert turn.tool_calls[0].name == "search_scan"


HOSTILE_LABEL = 'ball" ' + "with an implausibly long detector label " * 5


@pytest.mark.parametrize(
    ("provider", "observation"),
    [
        (FakeProvider.for_duck("hello-world"), _observation()),
        (
            FakeProvider.for_duck("find-and-kick"),
            _observation(
                detections=[_ball(0.22, 0.0)],
                last_result={"verb": 'walk_to "ball"', "ok": False, "summary": "", "data": {}},
            ),
        ),
        (FakeProvider(script=[ToolCall(name="kick")]), _observation(detections=[_ball()])),
        (
            FakeProvider.for_duck("find-and-kick"),
            _observation(
                detections=[
                    {"label": HOSTILE_LABEL, "cx": 0.5, "cy": 0.5, "area": 0.1, "bearing_deg": None}
                ]
            ),
        ),
    ],
    ids=["hello-world", "find-and-kick", "a fixed script", "a hostile label"],
)
async def test_scripted_thinking_never_contains_a_double_quote_or_stands_alone(
    provider: FakeProvider, observation: Observation
) -> None:
    """Three invariants the rest of the suite leans on. The quote matters most:
    `tests/test_cli.py` greps the raw transcript for `"kick"` and `"name": "kick"` to prove
    the duck kicked, and a quoted verb name in the thinking would make that pass vacuously.
    The prefix keeps the line from ever reading as a model's own words, and the trace prints
    one `think` row per turn, so it stays a single line."""
    turn = await provider.step(SYSTEM, [Exchange(observation=observation)], [])

    assert turn.thinking is not None
    assert '"' not in turn.thinking
    assert turn.thinking.startswith("[scripted] step ")
    assert "\n" not in turn.thinking
    assert turn.thinking.endswith(f"so the rule picks {turn.tool_calls[0].name}")


async def test_the_scripted_pilot_has_no_text_and_no_reasoning_tokens() -> None:
    """A rule says nothing to the human and spends nothing thinking. Inventing either would
    make the trace's token line lie about what a keyless run costs."""
    history = [Exchange(observation=_observation(detections=[_ball()]))]
    turn = await FakeProvider.for_duck("find-and-kick").step(SYSTEM, history, [])

    assert turn.text is None
    assert turn.usage.reasoning_tokens == 0
    assert turn.thinking  # but it does explain itself
