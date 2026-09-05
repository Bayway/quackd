#!/usr/bin/env python3
"""quackd's ToddlerBot daemon: the fifty hertz loop, and everything upstream does not do.

ToddlerBot has no network API of any kind. No socket, no daemon, no IPC: it is a Python
library whose control loop opens serial ports in-process. So quackd ships this, the way it
ships one for the Open Duck Mini, and it runs on the robot in upstream's own environment.

It exists for two reasons, and the second is the important one.

**A verb is episodic and this robot is not.** `RealWorld.step()` is a no-op, so nothing times
out and nothing re-arms: the last commanded pose is held forever. A humanoid frozen mid-stride
while a language model thinks is a humanoid on the floor, so the loop has to run continuously
and quackd's intents only nudge what it is doing.

**Upstream protects nothing, and its shutdown drops the robot.** Verified at the pinned commit:
`set_motor_target` clamps nothing and never reads the joint limits that exist; the motors are
in multi-turn mode so the firmware limits are off too; there is no watchdog, no timeout, no
e-stop and no reset anywhere; a dropped packet returns an all-zeros observation that looks
exactly like every joint at zero; a controller fault surfaces as a bare `KeyError`; and a C
level `atexit` handler disconnects every client on any normal interpreter exit, which disables
torque and drops a standing robot. There is no Python signal handler anywhere upstream, so
`SIGTERM` does not even reach that.

So this daemon carries seven things upstream has not got:

1. signal handlers that reach a safe pose before anything is allowed to exit;
2. a hard-exit timer around `close()`, which is bound without releasing the GIL and can block
   forever on an unresponsive bus, freezing every thread that might have supervised it;
3. a safe-pose slew, since no reset exists: upstream's own default pose at upstream's own
   0.3 rad/s, waist first, because a position command here is a full-torque snap;
4. a last-known-good observation cache with an all-zeros detector, so a dropped packet cannot
   be mistaken for a reading;
5. its own clamp against the joint limits, plus a per-tick rate limit;
6. a construction watchdog, because the constructor busy-waits forever on a silent IMU with
   the motors already live;
7. capability dispatch by type rather than by testing whether a name contains "real".

Rules this file lives by, the same three as `bridge/open_duck/`:

- **It never imports quackd.** quackd's dependencies do not belong on a robot.
- **It ships in the sdist and never in the wheel**, so `packages` stays `["quackd"]`.
- **It is testable with no hardware.** Everything above the `Robot` boundary is pure and takes
  plain arrays, and `--fake` runs the whole daemon and protocol against a simulated body.

    python quackd_toddlerbot_bridge.py --robot toddlerbot_2xc --fake
    python quackd_toddlerbot_bridge.py --robot toddlerbot_2xc --toddlerbot ~/toddlerbot
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import socket
import socketserver
import sys
import threading
import time
from typing import Any

try:  # numpy is upstream's own dependency and is always present beside it
    import numpy as np
except ImportError:  # pragma: no cover - the daemon cannot run without it
    np = None  # type: ignore[assignment]

VERSION = "1"
PROTOCOL = "quackd-toddlerbot-bridge"
PROTOCOL_VERSION = 1
JSONRPC_VERSION = "2.0"
DEFAULT_PORT = 9872
TOKEN_ENV = "QUACKD_TODDLERBOT_TOKEN"

CONTROL_HZ = 50.0
CONTROL_DT = 1.0 / CONTROL_HZ
DEADMAN_S = 0.5
"""How long quackd may go quiet before the loop stops taking its word for anything. It does
not stop the robot, because stopping is not a thing this body can do: it slews to a safe pose
and holds it."""
RESET_VEL = 0.3
"""Radians per second, upstream's own rate for moving to a rest pose."""
WAIST_THRESHOLD = 0.5
"""Untwist the waist first if it is further than this from zero, as upstream's reset does."""
MAX_STEP_RAD = RESET_VEL * CONTROL_DT * 4.0
"""The most any joint may move in one tick, whatever asked for it."""
CLOSE_TIMEOUT_S = 5.0
"""`close()` holds the GIL and retries torque-off forever on a dead bus. If it has not
returned by now, leave hard: a torqued robot beats a frozen supervisor that cannot be killed."""
CONSTRUCT_TIMEOUT_S = 30.0
FALL_TILT_DEG = 50.0
"""Untested against a real robot, and named as an assumption in the adapter's docs."""

ERR_BAD_TOKEN = 2
ERR_REFUSED = 3
ERR_UNKNOWN = 4

log = logging.getLogger("quackd-toddlerbot")


# ── the pure core: no hardware, no upstream, no quackd ──────────────────────────────────


def clamp_to_limits(target: Any, lo: Any, hi: Any) -> Any:
    """The only thing standing between a commanded radian and a joint winding itself round.

    Upstream's `set_motor_target` does not clip and never reads the joint limits, and the
    motors are in multi-turn mode so the firmware limits are off as well."""
    return np.clip(target, lo, hi)


def rate_limit(target: Any, current: Any, max_step: float = MAX_STEP_RAD) -> Any:
    """No more than `max_step` of movement per joint per tick, whatever was asked for.

    A position command on this body is a full-torque snap, so the difference between a slew
    and a jump is the difference between a move and a bang."""
    delta = np.clip(target - current, -max_step, max_step)
    return current + delta


def looks_like_a_dropped_read(pos: Any, vel: Any) -> bool:
    """True when an observation is the all-zeros buffer a failed bulk read returns.

    With zero retries a comm failure hands back the pre-zeroed buffer, which is
    indistinguishable from every joint genuinely at zero. Feeding that to a position
    controller commands a full-scale move to zero, so it is refused instead."""
    if pos is None or len(pos) == 0:
        return True
    return bool(np.all(pos == 0.0) and np.all(vel == 0.0))


def tilt_degrees(gravity_z: float) -> float:
    """How far off upright, from the body-frame gravity vector's vertical component."""
    return math.degrees(math.acos(max(-1.0, min(1.0, gravity_z))))


def slew(current: Any, goal: Any, dt: float, vel: float = RESET_VEL) -> Any:
    """One step of a bounded-rate move towards a goal."""
    return rate_limit(goal, current, max_step=vel * dt)


def waist_first(goal: Any, current: Any, waist: Any) -> Any:
    """Upstream's own two-phase rule: untwist the waist before anything else moves.

    If any waist joint is more than half a radian from zero, drive only the waist to zero and
    hold everything where it is; the rest of the pose follows once it is straight."""
    if waist is None or len(waist) == 0:
        return goal
    if float(np.max(np.abs(current[waist]))) <= WAIST_THRESHOLD:
        return goal
    staged = current.copy()
    staged[waist] = 0.0
    return staged


class SafeState:
    """The last observation quackd is willing to believe, and the pose derived from it.

    Kept because a stop on this body means *hold the last verified-good measured pose*, and a
    fresh read at that moment may be the all-zeros buffer."""

    def __init__(self, initial: Any) -> None:
        self.pose = np.array(initial, dtype=np.float32)
        self.stamp = 0.0
        self.rejected = 0

    def offer(self, pos: Any, vel: Any, now: float) -> bool:
        if looks_like_a_dropped_read(pos, vel):
            self.rejected += 1
            return False
        self.pose = np.array(pos, dtype=np.float32)
        self.stamp = now
        return True


# ── the command source: what the loop is trying to do this tick ─────────────────────────


class Command:
    """A tiny state machine, because the loop must always be doing exactly one thing."""

    HOLD = "hold"
    STAND = "stand"
    MOTION = "motion"
    WALK = "walk"
    DEADMAN = "deadman"

    def __init__(self, default_pose: Any) -> None:
        self.default_pose = np.array(default_pose, dtype=np.float32)
        self.mode = self.HOLD
        self.goal = np.array(default_pose, dtype=np.float32)
        self.motion: str | None = None
        self.frames: list[Any] = []
        self.frame_index = 0
        self.walk: dict[str, float] = {"walk_x": 0.0, "walk_y": 0.0, "walk_turn": 0.0}
        self.last_client = 0.0

    def hold(self, pose: Any) -> None:
        self.mode = self.HOLD
        self.goal = np.array(pose, dtype=np.float32)
        self.motion = None
        self.frames = []

    def stand(self) -> None:
        self.mode = self.STAND
        self.goal = self.default_pose.copy()
        self.motion = None
        self.frames = []

    def play(self, name: str, frames: list[Any]) -> None:
        self.mode = self.MOTION
        self.motion = name
        self.frames = frames
        self.frame_index = 0

    def drive(self, walk_x: float, walk_y: float, walk_turn: float) -> None:
        self.mode = self.WALK
        # all three keys or none: the walk policy indexes them unconditionally
        self.walk = {"walk_x": walk_x, "walk_y": walk_y, "walk_turn": walk_turn}

    def trip(self, pose: Any) -> None:
        """The deadman. It is a trajectory, not a message: silence on this body means hold
        forever, and neither holding a bad target nor going limp is safe."""
        self.mode = self.DEADMAN
        self.goal = np.array(pose, dtype=np.float32)
        self.motion = None
        self.frames = []

    @property
    def busy(self) -> bool:
        return self.mode in (self.STAND, self.MOTION)


# ── the loop ────────────────────────────────────────────────────────────────────────────


class Daemon:
    """Owns the robot, the loop and the safe pose. Everything else asks it politely."""

    def __init__(self, robot: Any, sim: Any, *, fake: bool = False) -> None:
        self.robot = robot
        self.sim = sim
        self.fake = fake
        self.lock = threading.Lock()
        self.running = False
        self.loop_hz = 0.0
        self.fallen = False
        self.tilt_deg = 0.0
        self.deadman_tripped = False
        self.calibrated = bool(getattr(robot, "quackd_calibrated", False))
        self.motion_library: dict[str, list[Any]] = {}
        n = int(getattr(robot, "nu", 30))
        order = list(getattr(robot, "motor_ordering", [f"m{i}" for i in range(n)]))
        self.order = order
        limits = dict(getattr(robot, "motor_limits", {}) or {})
        self.lo = np.array([limits.get(k, (-math.pi, math.pi))[0] for k in order], np.float32)
        self.hi = np.array([limits.get(k, (-math.pi, math.pi))[1] for k in order], np.float32)
        self.waist = np.array([i for i, k in enumerate(order) if "waist" in k], dtype=int)
        self.neck = [i for i, k in enumerate(order) if "neck" in k]
        default = np.array(getattr(robot, "default_motor_pos", np.zeros(n)), np.float32)
        self.safe = SafeState(default)
        self.command = Command(default)
        self.command.last_client = time.monotonic()
        self.target = default.copy()

    # -- one tick ------------------------------------------------------------------

    def observe(self) -> Any:
        """Read, and refuse to believe a reading that looks like a dropped packet.

        A controller fault arrives as a bare `KeyError` rather than an exception the C++
        raised, so it is caught here and treated as a hardware fault, not a transient."""
        try:
            obs = self.sim.get_observation()
        except KeyError as e:
            log.error("controller fault while reading (%s); holding the last good pose", e)
            return None
        pos = np.asarray(obs.motor_pos, dtype=np.float32)
        vel = np.asarray(obs.motor_vel, dtype=np.float32)
        if len(pos) != len(self.order):
            log.error("partial motor read: %d of %d; holding", len(pos), len(self.order))
            return None
        if not self.safe.offer(pos, vel, time.monotonic()):
            return None
        if getattr(obs, "rot", None) is not None:
            try:
                gravity = obs.rot.apply([0.0, 0.0, 1.0], inverse=True)
                self.tilt_deg = tilt_degrees(float(gravity[2]))
                self.fallen = self.tilt_deg > FALL_TILT_DEG
            except Exception:  # orientation is advisory, never fatal
                pass
        return obs

    def plan(self, dt: float) -> Any:
        """What this tick's target is, before any clamping."""
        cmd = self.command
        current = self.safe.pose
        if cmd.mode in (Command.STAND, Command.DEADMAN):
            goal = waist_first(cmd.goal, current, self.waist)
            nxt = slew(current, goal, dt)
            if float(np.max(np.abs(goal - nxt))) < 1e-3 and cmd.mode == Command.STAND:
                cmd.hold(goal)
            return nxt
        if cmd.mode == Command.MOTION:
            if cmd.frame_index >= len(cmd.frames):
                cmd.hold(current)
                return current
            frame = np.asarray(cmd.frames[cmd.frame_index], dtype=np.float32)
            cmd.frame_index += 1
            return frame
        if cmd.mode == Command.WALK:
            # the policy owns the gait; the daemon only feeds it and clamps what comes back
            policy = getattr(self, "walk_policy", None)
            if policy is None:
                cmd.hold(current)
                return current
            policy.control_inputs = dict(cmd.walk)
            return np.asarray(policy.step_target(current), dtype=np.float32)
        return cmd.goal

    def tick(self, dt: float = CONTROL_DT) -> Any:
        """One control step: read, decide, clamp, write. Never raises for a bad reading."""
        with self.lock:
            self.observe()
            if time.monotonic() - self.command.last_client > DEADMAN_S:
                if not self.deadman_tripped:
                    log.warning("quackd went quiet; slewing to the safe pose and holding")
                    self.deadman_tripped = True
                    self.command.trip(self.command.default_pose)
            else:
                self.deadman_tripped = False
            wanted = self.plan(dt)
            wanted = clamp_to_limits(wanted, self.lo, self.hi)
            self.target = rate_limit(wanted, self.target)
            self.sim.set_motor_target(self.target)
            self.sim.step()
            return self.target

    def run(self) -> None:
        """The absolute schedule upstream uses, so a slow tick does not accumulate error."""
        self.running = True
        start = time.monotonic()
        step = 0
        while self.running:
            self.tick()
            step += 1
            self.loop_hz = step / max(1e-6, time.monotonic() - start)
            slack = start + CONTROL_DT * step - time.monotonic()
            if slack > 0:
                time.sleep(slack)

    # -- shutdown, which is the dangerous part --------------------------------------

    def settle(self, timeout_s: float = 8.0) -> bool:
        """Reach the safe pose before anything is allowed to exit.

        Nothing upstream does this: its own shutdown disables torque with no lowering and no
        ramp, which on a standing humanoid is a fall."""
        log.info("settling to the safe pose before shutdown")
        with self.lock:
            self.command.trip(self.command.default_pose)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.tick()
            with self.lock:
                if float(np.max(np.abs(self.command.default_pose - self.target))) < 1e-2:
                    log.info("settled")
                    return True
            time.sleep(CONTROL_DT)
        log.warning("did not settle within %.0fs; leaving it where it is", timeout_s)
        return False

    def shutdown(self) -> None:
        """Settle, then close under a hard deadline.

        `close()` is bound without releasing the GIL and retries torque-off forever on an
        unresponsive bus, so a stuck shutdown freezes every thread including this one. A
        torqued robot and a dead process beats a frozen process nobody can signal."""
        self.running = False
        try:
            self.settle()
        except Exception:  # never let settling stop the close
            log.exception("settling failed; closing anyway")

        def bail() -> None:
            log.error("close() did not return in %.0fs; exiting hard", CLOSE_TIMEOUT_S)
            os._exit(1)

        timer = threading.Timer(CLOSE_TIMEOUT_S, bail)
        timer.daemon = True
        timer.start()
        try:
            self.sim.close()
        finally:
            timer.cancel()

    # -- what the socket asks it ----------------------------------------------------

    def state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "t": round(time.monotonic(), 3),
                "policy": self.command.motion or self.command.mode,
                "posture": "fallen" if self.fallen else "standing",
                "fallen": self.fallen,
                "tilt_deg": round(self.tilt_deg, 1),
                "joints": {
                    k: round(float(v), 3) for k, v in zip(self.order, self.target, strict=True)
                },
                "neck": {
                    "yaw_deg": round(math.degrees(float(self.target[self.neck[0]])), 1)
                    if self.neck
                    else 0.0,
                    "pitch_deg": round(math.degrees(float(self.target[self.neck[1]])), 1)
                    if len(self.neck) > 1
                    else 0.0,
                },
                "holding": {},
                "calibrated": self.calibrated,
                "moving": self.command.busy,
                "loop_hz": round(self.loop_hz, 1),
                "deadman_tripped": self.deadman_tripped,
                "age_ms": round((time.monotonic() - self.safe.stamp) * 1000.0, 1),
                "rejected_reads": self.safe.rejected,
            }

    def touch(self) -> None:
        self.command.last_client = time.monotonic()


# ── the socket ──────────────────────────────────────────────────────────────────────────


class Handler(socketserver.StreamRequestHandler):
    daemon_ref: Daemon
    token: str | None
    capabilities: dict[str, bool]
    robot_name: str
    motors: int

    def handle(self) -> None:
        authed = self.token is None
        for raw in self.rfile:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            method, params = msg.get("method"), msg.get("params") or {}
            req_id = msg.get("id")
            try:
                result, authed = self._dispatch(method, params, authed)
            except _Refused as e:
                self._error(req_id, e.code, str(e))
                continue
            if req_id is not None:
                self._reply(req_id, result)

    def _dispatch(
        self, method: str | None, params: dict[str, Any], authed: bool
    ) -> tuple[Any, bool]:
        d = self.daemon_ref
        if method == "bot.hello":
            if self.token is not None and params.get("token") != self.token:
                raise _Refused(ERR_BAD_TOKEN, "bad or missing token")
            return {
                "protocol": PROTOCOL,
                "protocol_version": PROTOCOL_VERSION,
                "daemon_version": VERSION,
                "robot": self.robot_name,
                "motors": self.motors,
                "capabilities": dict(self.capabilities),
            }, True
        if not authed:
            raise _Refused(ERR_BAD_TOKEN, "say bot.hello with a token first")
        d.touch()
        if method == "bot.state":
            return d.state(), authed
        if method == "bot.health":
            return {
                "ok": not d.fallen,
                "reason": "the robot has fallen" if d.fallen else None,
                "loop_hz": round(d.loop_hz, 1),
            }, authed
        if method == "bot.stop":
            with d.lock:
                d.command.hold(d.safe.pose)
            return {"accepted": True}, authed
        if method == "bot.stand":
            if d.fallen:
                return {"accepted": False, "reason": "the robot has fallen"}, authed
            with d.lock:
                d.command.stand()
            return {"accepted": True}, authed
        if method == "bot.perform":
            name = str(params.get("motion", ""))
            frames = d.motion_library.get(name)
            if not frames:
                return {"accepted": False, "reason": f"no motion named {name!r}"}, authed
            if d.fallen:
                return {"accepted": False, "reason": "the robot has fallen"}, authed
            with d.lock:
                d.command.play(name, frames)
            return {"accepted": True}, authed
        if method == "bot.look":
            if not self.capabilities.get("neck"):
                return {"accepted": False, "reason": "this build has no neck"}, authed
            with d.lock:
                _aim_neck(d, float(params.get("yaw_deg", 0.0)), float(params.get("pitch_deg", 0.0)))
            return {"accepted": True}, authed
        if method == "bot.command":
            if not self.capabilities.get("walk"):
                return {"accepted": False, "reason": "no walk policy is staged"}, authed
            with d.lock:
                d.command.drive(
                    float(params.get("walk_x", 0.0)),
                    float(params.get("walk_y", 0.0)),
                    float(params.get("walk_turn", 0.0)),
                )
            return {"accepted": True}, authed
        if method == "bot.grip":
            if not self.capabilities.get("gripper"):
                return {"accepted": False, "reason": "this build has no grippers"}, authed
            return {"accepted": True}, authed
        if method == "bot.frame":
            frame = getattr(d, "camera_jpeg", None)
            return {"jpeg": frame() if callable(frame) else None}, authed
        raise _Refused(ERR_UNKNOWN, f"unknown method {method!r}")

    def _reply(self, req_id: Any, result: Any) -> None:
        self.wfile.write(
            (
                json.dumps({"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}) + "\n"
            ).encode()
        )

    def _error(self, req_id: Any, code: int, message: str) -> None:
        if req_id is None:
            return
        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "error": {"code": code, "message": message},
        }
        self.wfile.write((json.dumps(payload) + "\n").encode())


class _Refused(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    address_family = socket.AF_INET


def _aim_neck(d: Daemon, yaw_deg: float, pitch_deg: float) -> None:
    """Point the head by writing the two neck joints of the held pose.

    Which neck motor is yaw and which is pitch is inferred from the motor names rather than
    stated anywhere upstream, and the result is clamped like every other joint."""
    goal = d.safe.pose.copy()
    if d.neck:
        goal[d.neck[0]] = math.radians(yaw_deg)
    if len(d.neck) > 1:
        goal[d.neck[1]] = math.radians(pitch_deg)
    d.command.hold(goal)


# ── the fake body, so the whole daemon runs with nothing installed ──────────────────────


class FakeRobot:
    def __init__(self, name: str = "toddlerbot_2xc", nu: int = 30) -> None:
        self.nu = nu
        self.name = name
        self.motor_ordering = ["neck_yaw", "neck_pitch", "waist_roll", "waist_yaw"] + [
            f"joint_{i}" for i in range(nu - 4)
        ]
        self.motor_limits = {k: (-2.0, 2.0) for k in self.motor_ordering}
        self.default_motor_pos = [0.0] * nu
        self.quackd_calibrated = True


class FakeSim:
    """A body that holds what it was told, so the loop and the protocol are exercised whole."""

    def __init__(self, robot: FakeRobot) -> None:
        self.robot = robot
        self.pos = np.zeros(robot.nu, dtype=np.float32)
        self.writes = 0
        self.closed = False
        self.drop_next = False

    def get_observation(self) -> Any:
        pos = np.zeros(self.robot.nu, np.float32) if self.drop_next else self.pos.copy()
        self.drop_next = False
        return type("Obs", (), {"motor_pos": pos, "motor_vel": np.zeros_like(pos), "rot": None})()

    def set_motor_target(self, target: Any) -> None:
        self.pos = np.asarray(target, dtype=np.float32).copy()
        self.writes += 1

    def step(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


# ── wiring it up ────────────────────────────────────────────────────────────────────────


def build_real(robot_name: str, root: str) -> tuple[Any, Any]:
    """Construct upstream's Robot and RealWorld, under a watchdog.

    The constructor busy-waits forever on a silent IMU with the motors already live and
    torqued, and nothing inside the class can recover from that, so it runs in a thread this
    one is willing to abandon."""
    os.chdir(root)  # every description path upstream builds is relative
    sys.path.insert(0, root)
    from toddlerbot.sim.robot import Robot  # late: importable only after the chdir above

    robot = Robot(robot_name)
    motors_yml = os.path.join(root, "toddlerbot", "descriptions", robot_name, "motors.yml")
    robot.quackd_calibrated = os.path.exists(motors_yml)
    if not robot.quackd_calibrated:
        raise SystemExit(
            f"{robot_name} has no zero calibration at {motors_yml}, so every commanded angle "
            "would be offset by however this robot was assembled. Run upstream's "
            "calibrate_zero first. quackd refuses to actuate without it."
        )

    box: dict[str, Any] = {}

    def construct() -> None:
        from toddlerbot.sim.real_world import (
            RealWorld,
        )  # late: this is the import that needs abandoning

        box["sim"] = RealWorld(robot)

    thread = threading.Thread(target=construct, daemon=True, name="quackd-construct")
    thread.start()
    thread.join(CONSTRUCT_TIMEOUT_S)
    if "sim" not in box:
        raise SystemExit(
            f"the robot did not finish connecting in {CONSTRUCT_TIMEOUT_S:.0f}s. Its "
            "constructor busy-waits forever on a silent IMU, with the motors already "
            "powered, so check the IMU before anything else."
        )
    sim = box["sim"]
    if not getattr(sim, "controllers", None):
        raise SystemExit("no Dynamixel controllers were found; the robot is not on its bus")
    return robot, sim


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--robot", default="toddlerbot_2xc")
    parser.add_argument("--toddlerbot", default=os.environ.get("TODDLERBOT_ROOT", "."))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--token", default=os.environ.get(TOKEN_ENV))
    parser.add_argument("--fake", action="store_true", help="Run with a simulated body.")
    parser.add_argument("--camera", action="store_true", help="Offer a camera.")
    parser.add_argument("--walk", action="store_true", help="A walk checkpoint is staged.")
    parser.add_argument("--gripper", action="store_true", help="This build has grippers.")
    parser.add_argument("--once", action="store_true", help="Set up, report, and exit.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if np is None:
        sys.stderr.write("quackd's ToddlerBot daemon needs numpy\n")
        return 2

    if args.fake:
        robot: Any = FakeRobot(args.robot)
        sim: Any = FakeSim(robot)
    else:
        try:
            robot, sim = build_real(args.robot, os.path.abspath(args.toddlerbot))
        except ImportError as e:
            sys.stderr.write(
                "quackd's ToddlerBot daemon needs upstream installed on this robot:\n"
                "  git clone https://github.com/hshi74/toddlerbot\n"
                "  cd toddlerbot && pip install -e .\n"
                f"Point --toddlerbot at that checkout. ({e})\n"
            )
            return 2

    daemon = Daemon(robot, sim, fake=args.fake)
    capabilities = {
        "camera": bool(args.camera),
        "neck": bool(daemon.neck),
        "gripper": bool(args.gripper),
        "walk": bool(args.walk),
        "deadman": True,
    }
    if args.once:
        log.info("robot=%s motors=%d capabilities=%s", args.robot, robot.nu, capabilities)
        return 0

    # Nothing upstream installs a signal handler, and its C level atexit does not run on
    # SIGTERM at all, so a systemd stop would leave a torqued robot holding its last target.
    def on_signal(signum: int, _frame: Any) -> None:
        log.warning("signal %s: settling before exit", signum)
        daemon.shutdown()
        raise SystemExit(0)

    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", signal.SIGINT)):
        signal.signal(sig, on_signal)

    loop = threading.Thread(target=daemon.run, daemon=True, name="quackd-control")
    loop.start()

    Handler.daemon_ref = daemon
    Handler.token = args.token
    Handler.capabilities = capabilities
    Handler.robot_name = args.robot
    Handler.motors = int(robot.nu)
    with Server((args.host, args.port), Handler) as server:
        log.info("listening on tcp://%s:%d for %s", args.host, args.port, args.robot)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            daemon.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
