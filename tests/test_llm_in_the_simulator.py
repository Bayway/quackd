"""A real model, driving the physics simulator, over the network.

Everything else in this suite fakes the brain: `FakeProvider` scripts the verbs and proves the
loop, the executor and the world. Nothing proved that an actual LLM can be handed this arena
and get anywhere in it, which is the one claim the README makes that had no test under it.

Two of these tests cost money and need `OPENAI_API_KEY`, so they are opt-in twice over: the
`live_llm` marker and `QUACKD_LIVE_LLM=1`. CI sets neither. Run them with

    QUACKD_LIVE_LLM=1 uv run pytest tests/test_llm_in_the_simulator.py -m live_llm

and keep them cheap: the budgets here are four steps, which is a handful of calls, not a sweep.
The first test needs no key and no network and runs everywhere, because the thing most likely
to rot is the prompt text rather than the wire.

The arena has nobody in it (ADR-0030, *Since 0.8*). That is what the second live test is really
about: a model told to find a person should say so and stop, not spend its budget hunting.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("mujoco")

from quackd.adapters.factory import RobotSpec, registry_for
from quackd.adapters.microduck import MicroduckAdapter
from quackd.agent.loop import RunConfig, run_duck
from quackd.agent.prompts import build_system_prompt
from quackd.duckfile.parser import duck_from_goal, load_duck
from quackd.perception.color_blob import ColorBlobDetector
from quackd.sim3d.world import MujocoWorld
from quackd.transport.mujoco import MujocoTransport
from tests.gl import require_render

#: The stand-in body: no download, no ONNX, and the gait is not what is under test here.
BODY = "puppet"
SPEC = RobotSpec(adapter="microduck", backend="mujoco")
#: Small on purpose. Every step is a paid call with an image attached.
MAX_STEPS = 4


def _live_or_skip() -> None:
    if os.environ.get("QUACKD_LIVE_LLM") != "1":
        pytest.skip("live LLM tests are opt-in: set QUACKD_LIVE_LLM=1")
    # The CLI loads `.env` at startup (cli.py) and a developer's key usually lives there
    # rather than in the shell, so look there too before deciding there is no key.
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - dotenv ships with the CLI
        pass
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("no OPENAI_API_KEY in the environment or in .env")
    pytest.importorskip("openai")


def _provider(goal: str | None = None):
    """`QUACKD_LIVE_LLM_MODEL` points these at another model.

    Worth doing at least once per model family, because the wire is not the same for all of
    them: `gpt-6-astra` refuses function tools on Chat Completions and the provider moves the
    whole run to the Responses API, which is a different renderer, a different parser and a
    different shape of history. These tests are what proves that path carries a real run and
    not just a first call.
    """
    from quackd.agent.providers.factory import make_provider

    return make_provider("openai", model=os.environ.get("QUACKD_LIVE_LLM_MODEL"), goal=goal)


# ── the prompt, which needs no key ──────────────────────────────────────────────────────


def test_the_physics_prompt_tells_the_model_the_arena_is_empty() -> None:
    """The arena has no person in it, and a model cannot infer that from the verbs.

    `search_scan` still offers `person` as a target, because one shared registry serves the
    cartoon (which has a person), YOLO on a real camera, and this. The head camera's detector
    still carries the person hue band for the same reason. A model reading only the verb
    vocabulary would reasonably scan for somebody and never stop, so the backend's own note is
    the only place that can say otherwise, and this pins that it does.
    """
    duck = load_duck("find-and-kick")
    prompt = build_system_prompt(duck, [], "mujoco")
    assert "Nobody is in the arena with you" in prompt
    assert "no person here to find" in prompt
    # and the cartoon's note must not have picked it up: the cartoon still has a person
    cartoon = build_system_prompt(duck, [], "sim2d")
    assert "Nobody is in the arena" not in cartoon


# ── the wire, which does ────────────────────────────────────────────────────────────────


@pytest.mark.live_llm
async def test_a_real_model_drives_the_physics_simulator(tmp_path: Path) -> None:
    """`hello-world` end to end: a real model, real verbs, a real MuJoCo world.

    The assertion is deliberately about the machinery rather than the outcome. What must hold
    is that the model was reached, that what it chose became intents the executor accepted, and
    that the run ended by the model's own declaration rather than by falling over. Whether it
    declares success in four steps is the model's business and not a thing to pin in CI.
    """
    _live_or_skip()
    transport = MujocoTransport(seed=0, body=BODY)
    result = await run_duck(
        RunConfig(
            duck=load_duck("hello-world"),
            provider=_provider(),
            transport=MicroduckAdapter(transport),
            detector=ColorBlobDetector(),
            runs_dir=tmp_path,
            max_steps=MAX_STEPS,
        )
    )
    assert result.outcome in {"success", "failure"}, result.reason
    assert result.steps >= 1, "the model never chose a verb"
    assert (result.run_dir / "transcript.jsonl").exists()


@pytest.mark.live_llm
async def test_a_real_model_gives_up_on_a_person_who_is_not_there(tmp_path: Path) -> None:
    """Nobody is in this arena, and a model asked for somebody should say so and stop.

    This is the behaviour the emptiness note in `prompts.py` buys, and the reason it is worth
    the tokens: without it the honest reading of `search_scan(target="person")` is to keep
    scanning, and the run burns its whole budget on a lap of an empty room. Pinned loosely, at
    the shape of the answer rather than its words: it must not still be hunting when the budget
    runs out.
    """
    _live_or_skip()
    # The model steers on rendered frames here, so check for a context before paying for a
    # call. The transport builds its world inside connect(), so ask a throwaway one.
    probe = MujocoWorld(seed=0, body=BODY)
    try:
        require_render(probe)
    finally:
        probe.close()
    transport = MujocoTransport(seed=0, body=BODY)
    goal = "find the person in the arena and walk up to them"
    # As `quackd run --goal` does it (cli.py): the goal becomes the duck. Handing a real duck
    # a `goal=` does nothing, because only the FakeProvider reads that argument.
    safe = [v.name for v in registry_for(SPEC).verbs() if v.safety_class == "safe"]
    result = await run_duck(
        RunConfig(
            duck=duck_from_goal(goal, safe),
            provider=_provider(goal=goal),
            transport=MicroduckAdapter(transport),
            detector=ColorBlobDetector(),
            runs_dir=tmp_path,
            max_steps=MAX_STEPS,
        )
    )
    assert result.outcome == "failure", (
        f"the model reported {result.outcome} for a person who is not in the arena: {result.reason}"
    )
    assert result.steps < MAX_STEPS, (
        "the model spent its whole budget hunting for somebody who is not there, which is what "
        "the arena note in prompts.py exists to prevent"
    )
