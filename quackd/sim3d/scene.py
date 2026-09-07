"""The arena as MJCF text: floor, walls, a ball, a person, and a body dropped in.

The arena is the cartoon's, 2 m across with the same orange ball and the same blue person,
so the colour detector that reads `sim2d`'s frames reads these unchanged. The floor is a
grey checker rather than MuJoCo's usual blue one for the same reason: a blue floor is a
person-sized blue blob in every frame.

Shadows are off on purpose. They are the single biggest render cost once a real robot is in
the scene (366 ms per frame against 112 ms with `shadowsize="0"`, measured at 256 px on an
Intel iGPU with the Microduck's 431k triangles), and a GIF of a run needs tens of frames.

Bodies are strings the caller supplies, not files this module knows: the stand-in puppet
below is ours (a kinematic block, for tests and for anyone without the upstream meshes),
and the real Microduck arrives as an `<include>` plus an asset dict from the run-time cache,
with its own licence printed. Everything this module names is prefixed `quackd_`, because
an included robot brings its own names into the same document.
"""

from __future__ import annotations

ARENA_HALF = 1.0  # metres; the arena is [-1, 1]², as in sim2d
BALL_R = 0.05
PERSON_R = 0.12
PERSON_H = 0.5  # half-height of the cylinder: a metre-tall marker, as tall as a duck sees
WALL_H = 0.08
HEADCAM_FOV_DEG = 90.0  # the cartoon's, and the detector's default
OFFSCREEN_PX = 1024  # the largest --gif-size the offscreen buffer allows

BALL_RGBA = "1 0.55 0 1"  # (255, 140, 0): H≈16 in OpenCV, inside the detector's ball range
PERSON_RGBA = "0.24 0.35 0.86 1"  # (60, 90, 220): H≈112, the detector's person range
DUCK_RGBA = "0.98 0.82 0.16 1"  # the cream colorway

#: Where a held ball is parked: outside the walls, beyond what a 256 px frame can resolve.
BALL_PARK = (6.0, 6.0, BALL_R)

# Rolling friction slows the ball, as it does a real one: the coefficient is a lever arm
# in metres, so a rolling sphere decelerates at 2.5·coef·g/r, and 0.002 gives the cartoon's
# 1 m/s² (a 1.2 m/s kick travels about 0.8 m). Joint damping would brake the spin too,
# which stops a rolling ball dead in a few centimetres.
BALL_ROLLING = 0.002
BALL_MASS = 0.05

#: The kinematic stand-in. A mocap body is placed, not simulated: it collides with the ball
#: and nothing collides back, which is exactly what a test double for the plumbing wants.
#: Its trunk reaches the floor so a ball it walks into is shoved ahead, the way the
#: cartoon's contact push shoves it, rather than slipping underneath and being pinned.
PUPPET_BODY_Z = 0.125
PUPPET_SIT_Z = 0.07
PUPPET_HEAD_Z = 0.20  # the camera's height above the floor, the cartoon's figure
PUPPET_HEAD_AHEAD = 0.09  # the camera sits this far ahead of the centre: clear of the head
PUPPET_XML = f"""
    <body name="duck" mocap="true" pos="0 0 {PUPPET_BODY_Z}">
      <geom name="duck_body" type="box" size="0.05 0.04 0.062" pos="0 0 -0.063"
            group="2" rgba="{DUCK_RGBA}"/>
      <geom name="duck_head" type="box" size="0.03 0.03 0.03" pos="0.05 0 0.09"
            group="2" rgba="{DUCK_RGBA}"/>
      <geom name="duck_beak" type="box" size="0.02 0.012 0.008" pos="0.09 0 0.06"
            group="2" rgba="0.25 0.25 0.25 1"/>
    </body>
"""


def arena_xml(
    body_xml: str,
    *,
    ball: tuple[float, float],
    person: tuple[float, float] | None,
    timestep: float = 0.005,
    include: str = "",
) -> str:
    """The whole scene. `include` goes first (a robot's own MJCF, merged by MuJoCo's
    `<include>`); `body_xml` is dropped into `<worldbody>` as given."""
    lim = ARENA_HALF + 0.02
    walls = "\n".join(
        f'    <geom name="quackd_wall_{name}" type="box" pos="{px} {py} {WALL_H}" '
        f'size="{sx} {sy} {WALL_H}" rgba="0.55 0.55 0.58 1"/>'
        for name, px, py, sx, sy in (
            ("east", lim, 0.0, 0.02, lim),
            ("west", -lim, 0.0, 0.02, lim),
            ("north", 0.0, lim, lim, 0.02),
            ("south", 0.0, -lim, lim, 0.02),
        )
    )
    person_xml = (
        f'    <body name="person" pos="{person[0]} {person[1]} {PERSON_H}">\n'
        f'      <geom name="person_body" type="cylinder" size="{PERSON_R} {PERSON_H}" '
        f'rgba="{PERSON_RGBA}"/>\n'
        "    </body>"
        if person is not None
        else ""
    )
    return f"""
<mujoco model="quackd arena">
{include}
  <option timestep="{timestep}" gravity="0 0 -9.81"/>
  <visual>
    <global fovy="{HEADCAM_FOV_DEG:g}" offwidth="{OFFSCREEN_PX}" offheight="{OFFSCREEN_PX}"/>
    <headlight ambient="0.5 0.5 0.5" diffuse="0.6 0.6 0.6" specular="0 0 0"/>
    <quality shadowsize="0" offsamples="0"/>
    <!-- No antialiasing: a blended edge pixel on the orange ball lands in the
         detector's cream band and reads as a second duck. The cartoon draws flat
         fills for the same reason. -->
  </visual>
  <asset>
    <texture name="quackd_floor" type="2d" builtin="checker" width="256" height="256"
             rgb1="0.86 0.86 0.84" rgb2="0.74 0.74 0.72"/>
    <material name="quackd_floor" texture="quackd_floor" texrepeat="8 8" reflectance="0.05"/>
    <texture name="quackd_sky" type="skybox" builtin="gradient" width="256" height="256"
             rgb1="0.80 0.86 0.95" rgb2="0.60 0.70 0.85"/>
  </asset>
  <worldbody>
    <light name="quackd_sun" pos="0.5 -0.5 3" dir="-0.15 0.15 -1" diffuse="0.7 0.7 0.7"
           specular="0 0 0" castshadow="false"/>
    <geom name="quackd_floor" type="plane" size="{ARENA_HALF + 0.5:g} {ARENA_HALF + 0.5:g} 0.1"
          material="quackd_floor" friction="0.8 0.005 0.0001"/>
{walls}
    <body name="ball" pos="{ball[0]} {ball[1]} {BALL_R}">
      <joint name="ball_free" type="free"/>
      <geom name="ball_geom" type="sphere" size="{BALL_R}" rgba="{BALL_RGBA}" condim="6"
            mass="{BALL_MASS}" friction="0.8 0.005 {BALL_ROLLING}"/>
    </body>
{person_xml}
{body_xml}
  </worldbody>
</mujoco>
"""
