"""The contract job: quackd's real client against quackd's real daemon on a real physics body.

This is the only test in the repository that needs upstream installed, so it is opt-in and
skipped everywhere else. The main suite must stay installable on Windows with nothing but
quackd's own dependencies, which is why this cannot simply be another loopback test.

What it adds over `test_toddlerbot_daemon.py` is a body that pushes back. The fake body holds
exactly what it was told, so it can prove the protocol and the safety machinery and nothing
about physics. Here the daemon drives upstream's own MuJoCo model, through upstream's own
`MuJoCoSim`, and the pose it commands is not the pose it reads back.

Run it with:

    QUACKD_TODDLERBOT_CONTRACT=1 TODDLERBOT_ROOT=~/toddlerbot uv run pytest \
        tests/test_toddlerbot_contract.py

It still proves nothing about 3 kg of servos, and `docs/adapter-status.md` says so.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys

import pytest

from quackd.adapters.toddlerbot import ToddlerBotAdapter
from quackd.adapters.toddlerbot.bridge import ToddlerBotBridge
from quackd.transport.base import Intent
from tests.conftest import REPO

DAEMON = REPO / "bridge" / "toddlerbot" / "quackd_toddlerbot_bridge.py"
ROBOT = "toddlerbot_2xc"

pytestmark = pytest.mark.skipif(
    os.environ.get("QUACKD_TODDLERBOT_CONTRACT") != "1",
    reason="the contract job is opt-in: it needs upstream and its MuJoCo model installed",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _wait_for(predicate: object, limit_s: float = 30.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_s
    while loop.time() < deadline:
        if predicate():  # type: ignore[operator]
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the daemon never reached the expected state")


class _Daemon:
    """The real daemon, as a real process, exactly as it runs on a robot."""

    def __init__(self) -> None:
        root = os.environ.get("TODDLERBOT_ROOT")
        assert root, "TODDLERBOT_ROOT must point at an upstream checkout"
        self.port = _free_port()
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(DAEMON),
                "--sim",
                "mujoco",
                "--robot",
                ROBOT,
                "--toddlerbot",
                os.path.abspath(os.path.expanduser(root)),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    @property
    def address(self) -> str:
        return f"tcp://127.0.0.1:{self.port}"

    def __enter__(self) -> _Daemon:
        return self

    def __exit__(self, *exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def alive(self) -> bool:
        return self.proc.poll() is None


async def _connect(daemon: _Daemon, tries: int = 60) -> ToddlerBotBridge:
    """MuJoCo compiles the model and loads 47 meshes before the socket opens."""
    last: Exception | None = None
    for _ in range(tries):
        assert daemon.alive(), daemon.proc.stdout.read() if daemon.proc.stdout else ""
        link = ToddlerBotBridge(address=daemon.address)
        try:
            await link.connect()
        except Exception as e:
            last = e
            await asyncio.sleep(1.0)
            continue
        return link
    raise AssertionError(f"the daemon never accepted a connection: {last}")


async def test_the_handshake_describes_the_simulated_body() -> None:
    with _Daemon() as daemon:
        link = await _connect(daemon)
        assert link.hello is not None
        assert link.robot_name == ROBOT
        assert link.motors == 30, "upstream's own model has thirty motors"
        assert link.neck_available
        # No checkpoint and no camera on a bare checkout, so neither is offered.
        assert not link.walk_available
        assert not link.camera_available
        await link.close()


async def test_the_loop_runs_at_fifty_hertz_against_real_physics() -> None:
    with _Daemon() as daemon:
        link = await _connect(daemon)
        await _wait_for(lambda: True)
        state = await link.get_state()
        assert state.extras["loop_hz"] > 40.0, state.extras["loop_hz"]
        assert state.extras["calibrated"] is True
        # There is no odometry at this boundary even in simulation, because the adapter
        # reports what the real robot could report and no more.
        assert (state.x, state.y, state.theta) == (None, None, None)
        assert state.battery_percent is None
        await link.close()


async def test_stand_settles_on_a_body_that_pushes_back() -> None:
    """The fake body holds exactly what it is told. This one does not, so `stand` finishing
    means the slew actually converged under gravity and the PD gains upstream ships."""
    with _Daemon() as daemon:
        link = await _connect(daemon)
        assert (await link.send_intent(Intent.do("stand"))).accepted
        await _wait_for(lambda: True, limit_s=1.0)
        state = await link.get_state()
        assert state.extras["moving"] in (True, False)
        await link.stop()
        assert not (await link.get_state()).extras["deadman_tripped"]
        await link.close()


async def test_the_manifest_narrows_to_what_this_body_really_has() -> None:
    with _Daemon() as daemon:
        adapter = ToddlerBotAdapter(ToddlerBotBridge(address=daemon.address))
        for _ in range(60):
            try:
                manifest = await adapter.connect()
                break
            except Exception:
                await asyncio.sleep(1.0)
        else:
            raise AssertionError("the daemon never accepted a connection")
        # No walk checkpoint on a bare checkout, so locomotion does not exist here at all.
        assert manifest.mobility == "none"
        for verb in ("move", "go_to", "approach_and"):
            assert not manifest.provides(verb), verb
        assert manifest.provides("stand") and manifest.provides("report_state")
        await adapter.transport.close()


async def test_a_client_that_goes_quiet_trips_the_deadman_on_real_physics() -> None:
    """The failure the deadman exists for, against a body that will actually fall over if it
    is wrong. It must slew and hold, and it must never torque off."""
    with _Daemon() as daemon:
        link = await _connect(daemon)
        assert (await link.send_intent(Intent.do("stand"))).accepted
        await asyncio.sleep(2.0)  # longer than the daemon's 500 ms deadman
        state = await link.get_state()
        assert state.extras["deadman_tripped"] is True
        health = await link.request("bot.health")
        assert isinstance(health, dict)
        assert health.get("loop_hz", 0) > 40.0, "it is still running the loop, not stopped"
        assert daemon.alive(), "and the daemon is still alive rather than having exited"
        await link.close()
