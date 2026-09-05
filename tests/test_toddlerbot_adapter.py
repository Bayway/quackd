"""The ToddlerBot adapter: a humanoid, and the verbs it does not get to have.

quackd's first full humanoid, and the manifest is mostly absences. Three of them are the
point of this file: there is no text to speech, so `say` does not exist; there is no walk
checkpoint in the repository, so locomotion does not exist unless the daemon says one is
staged; and there is no get-up policy, so a fall is terminal and every moving verb has to say
so rather than letting a model thrash a fallen robot against the floor.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from quackd.adapters.base import RobotAdapter
from quackd.adapters.factory import make_adapter, parse_robot_spec
from quackd.adapters.toddlerbot import (
    MAX_VX,
    MAX_VY,
    MAX_WZ,
    ROBOTS,
    ToddlerBotAdapter,
    conditions,
    describe,
    implementations,
    toddlerbot_manifest,
)
from quackd.adapters.toddlerbot.mock import ToddlerBotMock
from quackd.adapters.toddlerbot.sim2d import ToddlerBotSim2D
from quackd.adapters.toddlerbot.verbs import MOTIONS, SHIPPED_MOTIONS, neck_limits
from quackd.agent.prompts import build_system_prompt
from quackd.cli import app
from quackd.duckfile.parser import load_duck
from quackd.duckfile.validate import validate_duck
from quackd.perception.color_blob import ColorBlobDetector
from quackd.safety import Executor, allow_all
from quackd.transport.base import Intent
from quackd.verbs.core import scan_mode
from quackd.verbs.registry import VerbNotFound, registry_from_manifest

runner = CliRunner()

#: Verbs other robots have and this body has not, at this pin.
ABSENT = {"say", "quack", "express", "play_sound", "wake_up", "sit", "kick", "grab", "stand_up"}

DUCK = load_duck("toddlerbot-lookout")


def _executor(adapter: ToddlerBotAdapter, manifest: object) -> Executor:
    return Executor(
        registry_from_manifest(manifest, adapter),  # type: ignore[arg-type]
        adapter,
        contract=None,
        detector=ColorBlobDetector(),
        confirm=allow_all,
    )


# ── the manifest ────────────────────────────────────────────────────────────────────────


def test_manifest_is_a_humanoid_with_no_voice() -> None:
    m = toddlerbot_manifest("mock", camera=True, walk=True)
    assert (m.embodiment, m.mobility) == ("humanoid", "legged")
    assert "sound" not in m.intents, "there is no text to speech anywhere at this pin"
    assert not (set(m.verb_names()) & ABSENT)
    assert "battery" not in m.sensors, "nothing reports a battery to Python"
    assert set(m.sensors) == {"imu", "joint_state", "camera"}


def test_without_a_walk_checkpoint_there_is_no_locomotion_at_all() -> None:
    """The walk policy is an ONNX artifact from a wandb run that upstream does not publish
    and does not check in. Nothing about that is quackd's to gate: the verbs do not exist."""
    walking = toddlerbot_manifest("bridge", camera=True, walk=True)
    grounded = toddlerbot_manifest("bridge", camera=True, walk=False)
    needs_legs = {"move", "go_to", "approach_and"}
    assert needs_legs <= set(walking.verb_names())
    assert not (needs_legs & set(grounded.verb_names()))
    assert grounded.mobility == "none" and "twist" not in grounded.intents
    assert walking.mobility == "legged" and "twist" in walking.intents
    # the verbs that do not need legs are unaffected
    assert {"stand", "perform", "look", "observe"} <= set(grounded.verb_names())


def test_a_build_with_no_neck_loses_the_head_verbs() -> None:
    m = toddlerbot_manifest("bridge", camera=True, neck=False)
    assert not m.provides("look")
    assert "gaze" not in m.intents
    # search_scan needs a camera and something to look around with
    assert not m.provides("search_scan")


def test_grippers_exist_only_on_the_builds_that_have_them() -> None:
    assert not toddlerbot_manifest("bridge").provides("grip")
    with_grip = toddlerbot_manifest("bridge", gripper=True, robot="toddlerbot_2xc_gripper")
    assert with_grip.provides("grip") and "gripper" in with_grip.intents


def test_the_deadman_is_only_claimed_when_quackd_owns_the_loop() -> None:
    """There is no watchdog, no timeout and no e-stop anywhere upstream, and silence on this
    body means hold forever. The only deadman that can exist is the daemon's own."""
    m = toddlerbot_manifest("bridge", deadman=True)
    assert m.safety_authority.native == "none"
    assert m.safety_authority.deadman is True
    assert toddlerbot_manifest("bridge", deadman=False).safety_authority.deadman is False
    assert "safe pose" in m.extras["deadman_scope"]


def test_extras_say_what_is_missing_and_what_is_assumed() -> None:
    m = toddlerbot_manifest("mock", camera=True, walk=True)
    assert "get-up" in m.extras["no_recovery"]
    assert "battery" in m.extras["no_battery"]
    assert m.extras["speech"] == "none"
    assumptions = " ".join(m.extras["assumptions"]).lower()
    for expected in ("tilt", "neck", "holding", "odometry"):
        assert expected in assumptions


def test_limits_stay_inside_the_schema() -> None:
    from quackd.verbs.core import MAX_VX as SCHEMA_VX
    from quackd.verbs.core import MAX_VY as SCHEMA_VY
    from quackd.verbs.core import MAX_WZ as SCHEMA_WZ

    m = toddlerbot_manifest("mock", camera=True, walk=True)
    assert m.limits["max_vx"] <= SCHEMA_VX
    assert m.limits["max_vy"] <= SCHEMA_VY
    assert m.limits["max_wz"] <= SCHEMA_WZ
    assert (MAX_VX, MAX_VY, MAX_WZ) == (0.2, 0.1, 1.0)


def test_digest_ignores_the_id_and_the_backend() -> None:
    a = toddlerbot_manifest("mock", "one", camera=True, walk=True)
    b = toddlerbot_manifest("sim2d", "two", camera=True, walk=True)
    assert a.digest() == b.digest()
    assert a.digest() != toddlerbot_manifest("mock", "one", camera=True, walk=False).digest()


def test_the_bridge_claims_nothing_until_the_daemon_has_spoken() -> None:
    static = describe(parse_robot_spec("toddlerbot:bridge").backend)
    assert static.mobility == "none"
    assert not static.provides("observe") and not static.provides("move")
    assert describe(parse_robot_spec("toddlerbot:mock").backend).provides("move")


# ── the motions quackd will and will not offer ─────────────────────────────────────────


def test_quackd_curates_the_motion_list_and_says_so() -> None:
    """Every shipped motion is something the robot can do, so this is a safety judgement
    rather than a capability claim, and the docs say which and why."""
    assert set(MOTIONS) < set(SHIPPED_MOTIONS)
    for excluded in ("cartwheel", "pull_up_grasp", "pull_up_pull", "walk_zmp"):
        assert excluded in SHIPPED_MOTIONS
        assert excluded not in MOTIONS


def test_the_neck_is_clamped_to_a_fraction_of_its_travel() -> None:
    limits = neck_limits({"neck_yaw": (-1.0, 1.0), "neck_pitch": (-0.5, 0.5), "knee": (-2, 2)})
    assert set(limits) == {"neck_yaw", "neck_pitch"}, "only the neck"
    assert limits["neck_yaw"] == pytest.approx((-0.8, 0.8))


# ── how this robot looks around ────────────────────────────────────────────────────────


def test_search_scan_sweeps_the_head_rather_than_turning_a_humanoid() -> None:
    """A body turn is available once a walk policy is staged, but turning a humanoid with no
    fall recovery to look around is not what quackd reaches for first."""
    grounded = toddlerbot_manifest("bridge", camera=True, walk=False)
    assert scan_mode(grounded) == "gaze"


# ── the registry, the prompt and .duck validation all agree ────────────────────────────


def test_an_absent_verb_is_absent_everywhere() -> None:
    m = toddlerbot_manifest("mock", camera=True, walk=True)
    registry = registry_from_manifest(m, implementations=implementations(), conditions=conditions())
    allow = DUCK.frontmatter.verbs.allow
    prompt = build_system_prompt(DUCK, [registry.view(n) for n in allow], "mock", manifest=m)
    offered = {line.split("`")[1] for line in prompt.splitlines() if line.startswith("- `")}
    for verb in ABSENT:
        with pytest.raises(VerbNotFound):
            registry.get(verb)
        assert verb not in offered
    assert offered == set(allow)


def test_the_shipped_lookout_task_validates_and_moves_no_legs() -> None:
    assert validate_duck(DUCK, [toddlerbot_manifest("mock", camera=True, walk=True)]) == []
    allowed = set(DUCK.frontmatter.verbs.allow)
    assert not (allowed & {"move", "go_to", "approach_and", "perform", "stand"}), (
        "the first task pointed at a real humanoid must not move it"
    )


def test_the_cli_refuses_a_task_this_robot_cannot_do() -> None:
    result = runner.invoke(
        app, ["validate", "ducks/find-and-kick.duck", "--robot", "toddlerbot:mock"]
    )
    assert result.exit_code != 0


# ── the mock backend, through a real executor ──────────────────────────────────────────


async def test_every_verb_runs_offline_through_the_executor() -> None:
    adapter = ToddlerBotAdapter(ToddlerBotMock())
    assert isinstance(adapter, RobotAdapter)
    manifest = await adapter.connect()
    ex = _executor(adapter, manifest)
    mock = adapter.transport
    assert isinstance(mock, ToddlerBotMock)

    assert (await ex.run_verb("report_state", {})).ok
    assert (await ex.run_verb("observe", {})).ok
    assert (await ex.run_verb("look", {"yaw_deg": 30.0, "pitch_deg": -10.0})).ok
    assert mock.neck_yaw == pytest.approx(30.0)

    stood = await ex.run_verb("stand", {})
    assert stood.ok and mock.stands == 1

    performed = await ex.run_verb("perform", {"motion": "kneel"})
    assert performed.ok and mock.performed == ["kneel"]

    assert (await ex.run_verb("move", {"vx": 0.1, "duration_s": 0.4})).ok
    assert (await ex.run_verb("stop", {})).ok
    assert (await adapter.get_state()).battery_percent is None
    health = await adapter.health()
    assert health.ok and health.battery_percent is None


async def test_the_mock_refuses_what_this_body_cannot_do() -> None:
    adapter = ToddlerBotAdapter(ToddlerBotMock())
    await adapter.connect()
    assert not (await adapter.send_intent(Intent.sound("chirp"))).accepted
    assert not (await adapter.send_intent(Intent.do("kick_left"))).accepted
    assert not (await adapter.send_intent(Intent.do("motion:cartwheel"))).accepted
    # quackd never limps a robot, and here there is no way back: torque-on is unreachable
    assert not (await adapter.send_intent(Intent.enable(False))).accepted


async def test_a_fallen_robot_is_told_to_wait_for_a_human() -> None:
    """There is no get-up policy for this body, so the refusal names no verb: `stand_up` does
    not exist and offering it would invite a model to thrash a fallen humanoid."""
    adapter = ToddlerBotAdapter(ToddlerBotMock(fallen=True))
    manifest = await adapter.connect()
    ex = _executor(adapter, manifest)
    for verb, params in (
        ("perform", {"motion": "kneel"}),
        ("look", {"yaw_deg": 10.0}),
        ("move", {"vx": 0.1, "duration_s": 0.2}),
    ):
        result = await ex.run_verb(verb, params)
        assert not result.ok
        assert "human" in result.summary and "stand_up" not in result.summary
    assert (await ex.run_verb("stop", {})).ok, "stop is never gated"
    assert not (await adapter.health()).ok


async def test_an_uncalibrated_robot_refuses_to_move() -> None:
    adapter = ToddlerBotAdapter(ToddlerBotMock(calibrated=False))
    manifest = await adapter.connect()
    ex = _executor(adapter, manifest)
    result = await ex.run_verb("stand", {})
    assert not result.ok and "calibration" in result.summary
    assert (await ex.run_verb("stop", {})).ok


async def test_a_silent_daemon_refuses_moving_verbs_but_never_stop() -> None:
    mock = ToddlerBotMock()
    adapter = ToddlerBotAdapter(mock)
    manifest = await adapter.connect()
    ex = _executor(adapter, manifest)
    mock.stale_ms = 5000.0
    result = await ex.run_verb("stand", {})
    assert not result.ok and "not answering" in result.summary
    assert "safe pose" in result.summary, "and it says the robot is standing, not falling"
    assert (await ex.run_verb("stop", {})).ok
    assert (await ex.run_verb("report_state", {})).ok


async def test_connect_narrows_to_what_the_transport_reported() -> None:
    grounded = ToddlerBotAdapter(ToddlerBotMock(walk=False, camera=False, neck=False))
    manifest = await grounded.connect()
    assert manifest.mobility == "none"
    for verb in ("move", "go_to", "approach_and", "observe", "search_scan", "look"):
        assert not manifest.provides(verb)
    assert manifest.provides("stand") and manifest.provides("perform")


# ── the simulator ──────────────────────────────────────────────────────────────────────


async def test_the_simulated_humanoid_walks_looks_and_performs() -> None:
    adapter = ToddlerBotAdapter(ToddlerBotSim2D(seed=3))
    manifest = await adapter.connect()
    ex = _executor(adapter, manifest)
    sim = adapter.transport
    assert isinstance(sim, ToddlerBotSim2D)

    assert (await ex.run_verb("observe", {})).ok
    assert (await ex.run_verb("move", {"vx": 0.15, "duration_s": 0.5})).ok
    assert (await ex.run_verb("look", {"yaw_deg": 25.0})).ok
    assert sim.neck_yaw == pytest.approx(25.0)
    assert (await ex.run_verb("stand", {})).ok and sim.stands == 1
    assert (await ex.run_verb("perform", {"motion": "hold"})).ok
    assert sim.performed == ["hold"]
    assert (await ex.run_verb("stop", {})).ok


async def test_the_simulator_refuses_the_skills_this_body_has_not_got() -> None:
    sim = ToddlerBotSim2D(seed=1)
    await sim.connect()
    for intent in (Intent.sound("chirp"), Intent.do("kick_left"), Intent.do("ground_pick")):
        assert not (await sim.send_intent(intent)).accepted


# ── the factory ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("backend", ["mock", "sim2d", "bridge"])
def test_the_factory_builds_every_backend(backend: str) -> None:
    adapter = make_adapter(f"toddlerbot:{backend}")
    assert adapter.name == "toddlerbot" and adapter.backend == backend


def test_an_unknown_backend_names_the_real_ones() -> None:
    from quackd.adapters.toddlerbot import make

    with pytest.raises(ValueError, match="unknown toddlerbot backend"):
        make("real")


def test_only_the_builds_quackd_will_drive_are_listed() -> None:
    """Upstream also ships teleop_leader, which is the arm a human holds, not a robot."""
    assert "teleop_leader" not in ROBOTS
    assert set(ROBOTS) == {
        "toddlerbot_2xc",
        "toddlerbot_2xc_gripper",
        "toddlerbot_2xm",
        "toddlerbot_2xm_gripper",
    }
