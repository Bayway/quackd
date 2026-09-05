"""A ToddlerBot in the cartoon world.

The body is a walking biped with a head, which is close enough to what the simulator already
draws that this needs no new entity. It is `Sim2DTransport` with four differences.

It reports a humanoid's capabilities rather than a duck's, so the adapter narrows the manifest
the same way it would against a real daemon. It refuses the skills this robot does not have,
so a bug that somehow sent one fails loudly in sim rather than only on hardware. It answers
`stand` and the shipped motions, which are the only moves this body has offline. And it stops
reporting a battery, because nothing on a ToddlerBot reports one to Python.

The velocity limits are not enforced here. They live in the manifest, and `speed_limits()`
clamps every twist before it arrives.
"""

from __future__ import annotations

from typing import Any

from quackd.adapters.toddlerbot.verbs import MOTIONS
from quackd.transport.base import Ack, DuckState, Intent
from quackd.transport.sim2d import Sim2DTransport

STAND_S = 3.0
PERFORM_S = 6.0
NECK_YAW_LIMIT = 90.0
NECK_PITCH_LIMIT = 45.0

#: Telemetry the shared cartoon duck reports and this robot cannot.
_NOT_ON_THIS_ROBOT = ("kicks", "kicks_connected", "last_kick_ball_moved_m")

#: Skills that belong to other bodies. A ToddlerBot has no beak and no kick policy.
_CANNOT = ("kick_left", "kick_right", "ground_pick", "sit_toggle", "roulade")


class ToddlerBotSim2D(Sim2DTransport):
    name = "sim2d"
    mobility = "legged"
    camera_available = True
    neck_available = True
    gripper_available = False
    walk_available = True
    """The simulated robot is the one whose walk checkpoint is staged. A real one usually is
    not, because upstream publishes none."""
    deadman = True
    robot_name = "toddlerbot_2xc"
    motors = 30

    def __init__(self, seed: int = 0, **kwargs: object) -> None:
        super().__init__(seed, **kwargs)  # type: ignore[arg-type]
        self.neck_yaw = 0.0
        self.neck_pitch = 0.0
        self.motion: str | None = None
        self.stands = 0
        self.performed: list[str] = []
        self._busy_until = 0.0

    @property
    def moving(self) -> bool:
        return self.now() < self._busy_until

    async def get_state(self) -> DuckState:
        state = await super().get_state()
        extras = {k: v for k, v in state.extras.items() if k not in _NOT_ON_THIS_ROBOT}
        return state.model_copy(
            update={
                # nothing on a ToddlerBot reports a battery to Python
                "battery_percent": None,
                "extras": {
                    **extras,
                    "neck": {
                        "yaw_deg": round(self.neck_yaw, 1),
                        "pitch_deg": round(self.neck_pitch, 1),
                    },
                    "robot": self.robot_name,
                    "calibrated": True,
                    "moving": self.moving,
                    "loop_hz": 50.0,
                    "deadman_tripped": False,
                    "walk_policy": True,
                    "stale_ms": 0.0,
                    "stale_limit_ms": 1000.0,
                    "tilt_deg": 90.0 if state.fallen else 2.0,
                },
            }
        )

    def _do(self, skill: str) -> Ack:
        duck = self.world.ducks[self.duck_index]
        if duck.posture == "fallen":
            return Ack(accepted=False, reason="the robot has fallen")
        if skill == "stand":
            self.stands += 1
            self._busy_until = self.now() + STAND_S
            self.world.stop(duck_index=self.duck_index)
            return Ack()
        kind, _, name = skill.partition(":")
        if kind == "motion":
            if name not in MOTIONS:
                return Ack(accepted=False, reason=f"unknown motion {name!r}")
            self.performed.append(name)
            self.motion = name
            self._busy_until = self.now() + PERFORM_S
            self.world.stop(duck_index=self.duck_index)
            return Ack()
        if skill in _CANNOT:
            return Ack(accepted=False, reason=f"a ToddlerBot cannot {skill}")
        return super()._do(skill)

    async def send_intent(self, intent: Intent) -> Ack:
        p: dict[str, Any] = intent.params
        if intent.kind == "look":
            # the head is two joints, not an IK target: yaw and pitch arrive in degrees
            self.neck_yaw = max(-NECK_YAW_LIMIT, min(NECK_YAW_LIMIT, float(p.get("y", 0.0))))
            self.neck_pitch = max(-NECK_PITCH_LIMIT, min(NECK_PITCH_LIMIT, float(p.get("z", 0.0))))
            return Ack()
        if intent.kind == "sound":
            return Ack(accepted=False, reason="a ToddlerBot has no text to speech")
        if intent.kind == "gripper":
            return Ack(accepted=False, reason="this build has no grippers")
        if intent.kind == "stop":
            self._busy_until = self.now()
            self.motion = None
        return await super().send_intent(intent)
