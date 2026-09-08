"""The physics simulator: a MuJoCo arena the same shape as the cartoon's.

`sim2d` exists to test the agent loop, and says so; it will never tell you whether a gait
works, because it has no joints. This package is where a robot's own controllers run for
real: a rigid body world, a camera that renders what the head would see, and, once a body
brings one, the walking policy the robot ships with. The arena, the ball, the person, the
kick cone, the deadman and the seeded spawn order are the cartoon's, deliberately, so a
`.duck` written against one runs unchanged against the other and a seed means the same
layout in both.

Nearly everything here imports `mujoco`, which is an optional extra (`quackd[mujoco]`):
nothing on the default path imports this package, and the transport that uses it imports it
inside `connect()` so `--robot microduck:mujoco` fails with the extra's name rather than a
stack. The exception is `gait.py`, which is deliberately pure arithmetic over floats, so the
rule that decides whether a duck moves or only reports moving is tested on every runner
rather than only where the extra and a filled asset cache happen to meet.
"""
