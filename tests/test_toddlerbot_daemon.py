"""quackd's ToddlerBot daemon: the seven things upstream does not do.

This is the file that earns the `bridge` backend's 🧪. Upstream protects nothing on this
robot: no clamp, no rate limit, no watchdog, no reset, no e-stop, and a shutdown that
disables torque and drops a standing humanoid. Every test here is about one of the
mechanisms quackd added because of that, and the protocol is driven end to end against the
real daemon over a real loopback socket, exactly as `test_open_duck_daemon.py` does.

What it cannot prove: that any of it is right on 3 kg of servos. Nothing here has run on a
robot, and `docs/adapter-status.md` says so.
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
import threading
from types import ModuleType

import numpy as np
import pytest

from quackd.adapters.toddlerbot import ToddlerBotAdapter
from quackd.adapters.toddlerbot.bridge import PROTOCOL, PROTOCOL_VERSION, ToddlerBotBridge
from quackd.transport.base import Intent, TransportError
from tests.conftest import REPO

DAEMON = REPO / "bridge" / "toddlerbot" / "quackd_toddlerbot_bridge.py"


def load_daemon() -> ModuleType:
    """It lives outside the package on purpose: quackd's core must never import it."""
    spec = importlib.util.spec_from_file_location("quackd_toddlerbot_bridge", DAEMON)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


D = load_daemon()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _daemon(**kwargs: object) -> object:
    robot = D.FakeRobot()
    return D.Daemon(robot, D.FakeSim(robot), fake=True, **kwargs)  # type: ignore[arg-type]


# ── 1. the clamp, because set_motor_target has none ────────────────────────────────────


def test_a_command_past_the_joint_limits_is_clamped() -> None:
    """Upstream never reads motor_limits and the motors are in multi-turn mode, so the
    firmware limits are off too. This clamp is the only thing there is."""
    lo, hi = np.array([-2.0, -2.0], np.float32), np.array([2.0, 2.0], np.float32)
    assert list(D.clamp_to_limits(np.array([9.0, -9.0], np.float32), lo, hi)) == [2.0, -2.0]


def test_no_joint_may_move_far_in_one_tick() -> None:
    """A position command on this body is a full-torque snap, so the difference between a
    slew and a jump is the difference between a move and a bang."""
    current = np.zeros(3, np.float32)
    stepped = D.rate_limit(np.ones(3, np.float32) * 5.0, current)
    assert float(np.max(stepped)) == pytest.approx(D.MAX_STEP_RAD)
    # and it is symmetric
    stepped = D.rate_limit(np.ones(3, np.float32) * -5.0, current)
    assert float(np.min(stepped)) == pytest.approx(-D.MAX_STEP_RAD)


def test_the_daemon_clamps_and_rate_limits_every_tick() -> None:
    d = _daemon()
    d.command.hold(np.ones(d.robot.nu, np.float32) * 50.0)
    d.tick()
    assert float(np.max(d.target)) == pytest.approx(D.MAX_STEP_RAD)
    for _ in range(500):
        d.tick()
    assert float(np.max(d.target)) <= 2.0, "the joint limit holds however long it is pushed"


# ── 2. the all-zeros detector, because a dropped read looks like a valid one ────────────


def test_an_all_zeros_reading_is_refused_rather_than_believed() -> None:
    """With zero retries a comm failure returns the pre-zeroed buffer, indistinguishable
    from every joint genuinely at zero. Believing it commands a full-scale move to zero."""
    assert D.looks_like_a_dropped_read(np.zeros(4), np.zeros(4))
    assert not D.looks_like_a_dropped_read(np.array([0.0, 0.1, 0.0, 0.0]), np.zeros(4))


def test_the_last_good_pose_survives_a_dropped_read() -> None:
    d = _daemon()
    d.command.hold(np.ones(d.robot.nu, np.float32) * 0.5)
    for _ in range(200):
        d.tick()
    settled = d.safe.pose.copy()
    assert float(np.max(settled)) > 0.1, "the fake body moved"

    # a body genuinely at all zeros is indistinguishable from a dropped packet, so the very
    # first reading of one is refused too. That is the honest side of this trade.
    before = d.safe.rejected
    d.sim.drop_next = True
    d.tick()
    assert d.safe.rejected == before + 1
    assert np.allclose(d.safe.pose, settled), "a dropped read never becomes the held pose"


def test_a_controller_fault_is_survived_rather_than_raised() -> None:
    """A per-controller fault arrives as a bare KeyError because the C++ swallows it and
    inserts an empty map. It is a hardware fault, not a transient."""
    d = _daemon()

    def explode() -> None:
        raise KeyError("pos")

    d.sim.get_observation = explode  # type: ignore[method-assign]
    d.tick()  # must not raise
    assert d.sim.writes >= 1, "the loop kept commanding the last good pose"


# ── 3. the safe pose, because no reset exists anywhere upstream ────────────────────────


def test_the_waist_untwists_before_anything_else_moves() -> None:
    """Upstream's own reset rule: a twisted waist is straightened first, on its own."""
    order_len = 6
    waist = np.array([0, 1])
    current = np.zeros(order_len, np.float32)
    current[0] = 1.2  # well past the half radian threshold
    current[3] = 0.9
    goal = np.ones(order_len, np.float32)
    staged = D.waist_first(goal, current, waist)
    assert staged[0] == 0.0 and staged[1] == 0.0, "the waist is driven to zero"
    assert staged[3] == pytest.approx(0.9), "everything else holds where it is"


def test_a_straight_waist_goes_straight_to_the_goal() -> None:
    current = np.zeros(4, np.float32)
    goal = np.ones(4, np.float32)
    assert np.allclose(D.waist_first(goal, current, np.array([0, 1])), goal)


def test_settling_reaches_the_safe_pose_before_shutdown() -> None:
    d = _daemon()
    d.command.hold(np.ones(d.robot.nu, np.float32) * 1.5)
    for _ in range(300):
        d.tick()
    assert float(np.max(d.target)) > 0.5
    assert d.settle(timeout_s=30.0) is True
    assert float(np.max(np.abs(d.target))) < 0.05, "it ended at the default pose"


def test_shutdown_settles_and_then_closes() -> None:
    d = _daemon()
    d.command.hold(np.ones(d.robot.nu, np.float32) * 0.4)
    for _ in range(100):
        d.tick()
    d.shutdown()
    assert d.sim.closed, "the bus was closed"
    assert float(np.max(np.abs(d.target))) < 0.05, "and only after reaching the safe pose"


# ── 4. the deadman, which is a trajectory rather than a message ────────────────────────


def test_silence_slews_to_the_safe_pose_and_never_goes_limp() -> None:
    """On this body silence means hold forever, and torque off means fall. Neither is safe,
    so the deadman manufactures a third option."""
    d = _daemon()
    d.command.hold(np.ones(d.robot.nu, np.float32) * 1.0)
    for _ in range(200):
        d.tick()
    assert float(np.max(d.target)) > 0.3

    d.command.last_client -= D.DEADMAN_S * 4  # quackd went quiet
    d.tick()
    assert d.deadman_tripped
    assert d.command.mode == D.Command.DEADMAN
    for _ in range(500):
        d.tick()
    assert float(np.max(np.abs(d.target))) < 0.05, "it settled rather than collapsing"
    assert not d.sim.closed, "and never disabled torque"


def test_a_command_clears_the_deadman() -> None:
    d = _daemon()
    d.command.last_client -= D.DEADMAN_S * 4
    d.tick()
    assert d.deadman_tripped
    d.touch()
    d.tick()
    assert not d.deadman_tripped


# ── 5. the protocol, end to end over a real socket ─────────────────────────────────────


class _Serving:
    """The real daemon, its real loop and its real socket, on loopback."""

    def __init__(self, **caps: bool) -> None:
        self.port = _free_port()
        robot = D.FakeRobot()
        self.daemon = D.Daemon(robot, D.FakeSim(robot), fake=True)
        D.Handler.daemon_ref = self.daemon
        D.Handler.token = caps.pop("token", None)  # type: ignore[assignment]
        D.Handler.capabilities = {
            "camera": caps.get("camera", False),
            "neck": True,
            "gripper": caps.get("gripper", False),
            "walk": caps.get("walk", False),
            "deadman": True,
        }
        D.Handler.robot_name = "toddlerbot_2xc"
        D.Handler.motors = robot.nu
        self.server = D.Server(("127.0.0.1", self.port), D.Handler)
        self._loop = threading.Thread(target=self.daemon.run, daemon=True)
        self._serve = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> _Serving:
        self._loop.start()
        self._serve.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.daemon.running = False
        self.server.shutdown()
        self.server.server_close()

    @property
    def address(self) -> str:
        return f"tcp://127.0.0.1:{self.port}"


async def test_the_handshake_reports_what_the_robot_actually_has() -> None:
    with _Serving(camera=True, walk=True) as s:
        link = ToddlerBotBridge(address=s.address)
        await link.connect()
        assert link.hello is not None
        assert link.hello["protocol"] == PROTOCOL
        assert link.hello["protocol_version"] == PROTOCOL_VERSION
        assert link.camera_available and link.walk_available and link.neck_available
        assert not link.gripper_available
        assert link.motors == 30
        await link.close()


async def test_a_robot_with_no_walk_checkpoint_has_no_locomotion_at_all() -> None:
    """The walk policy is an ONNX artifact upstream does not publish. Without one the verbs
    that need the twist intent do not exist, rather than being gated off."""
    with _Serving(camera=True, walk=False) as s:
        adapter = ToddlerBotAdapter(ToddlerBotBridge(address=s.address))
        manifest = await adapter.connect()
        link = adapter.transport
        assert not link.walk_available
        assert manifest.mobility == "none"
        assert "twist" not in manifest.intents
        for verb in ("move", "go_to", "approach_and"):
            assert not manifest.provides(verb)
        assert manifest.provides("stand") and manifest.provides("perform")
        ack = await link.send_intent(Intent.move(vx=0.1))
        assert not ack.accepted and "walk" in str(ack.reason)
        await link.close()


async def test_a_staged_checkpoint_brings_locomotion_into_the_manifest() -> None:
    with _Serving(camera=True, walk=True) as s:
        adapter = ToddlerBotAdapter(ToddlerBotBridge(address=s.address))
        manifest = await adapter.connect()
        link = adapter.transport
        assert manifest.mobility == "legged"
        assert "twist" in manifest.intents
        for verb in ("move", "go_to", "approach_and", "search_scan"):
            assert manifest.provides(verb)
        await link.close()


async def test_stop_holds_the_last_good_pose_and_never_limps() -> None:
    with _Serving() as s:
        link = ToddlerBotBridge(address=s.address)
        await link.connect()
        assert (await link.send_intent(Intent.do("stand"))).accepted
        await asyncio.sleep(0.2)
        await link.stop()
        state = await link.get_state()
        assert state.extras["moving"] is False
        assert not s.daemon.sim.closed, "stopping never disables torque"
        await link.close()


async def test_state_never_claims_a_pose_or_a_battery() -> None:
    with _Serving() as s:
        link = ToddlerBotBridge(address=s.address)
        await link.connect()
        state = await link.get_state()
        assert (state.x, state.y, state.theta) == (None, None, None)
        assert state.battery_percent is None
        assert state.extras["loop_hz"] > 0
        await link.close()


async def test_a_wrong_token_is_refused_and_says_so() -> None:
    with _Serving(token="hunter2") as s:
        link = ToddlerBotBridge(address=s.address, token=None)
        with pytest.raises(TransportError, match="token"):
            await link.connect()
        good = ToddlerBotBridge(address=s.address, token="hunter2")
        await good.connect()
        assert good.hello is not None
        await good.close()


async def test_a_version_mismatch_is_refused_rather_than_guessed() -> None:
    with _Serving() as s:
        link = ToddlerBotBridge(address=s.address)
        original = D.PROTOCOL_VERSION
        D.PROTOCOL_VERSION = original + 1
        try:
            with pytest.raises(TransportError, match="refusing rather than guessing"):
                await link.connect()
        finally:
            D.PROTOCOL_VERSION = original
        await link.close()


async def test_no_daemon_says_what_to_start() -> None:
    link = ToddlerBotBridge(address=f"tcp://127.0.0.1:{_free_port()}")
    with pytest.raises(TransportError, match="quackd-toddlerbot-bridge"):
        await link.connect()
    await link.close()


# ── 6. the rules this file lives by ────────────────────────────────────────────────────


def test_the_daemon_never_imports_quackd() -> None:
    """quackd's dependencies do not belong on a robot, and this file is the proof."""
    for line in DAEMON.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "quackd" not in stripped, f"the daemon imports quackd: {stripped}"


def test_the_daemon_runs_with_upstream_absent() -> None:
    """It is the only quackd code that runs on the robot, and it must start before upstream
    is proven good, so nothing at import time may need it."""
    import subprocess

    script = (
        "import sys\n"
        "for name in ('toddlerbot', 'torch', 'mujoco', 'jax', 'quackd'):\n"
        "    sys.modules[name] = None\n"
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('d', r'{DAEMON}')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "raise SystemExit(m.main(['--fake', '--once']))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_it_ships_in_the_sdist_and_never_in_the_wheel() -> None:
    import tomllib

    build = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["hatch"][
        "build"
    ]["targets"]
    assert build["wheel"]["packages"] == ["quackd"]
    assert "bridge" in build["sdist"]["include"]
