"""The physics world keeps the cartoon's rules, and the transport over it speaks the protocol.

Skipped wholesale without `quackd[mujoco]`. The rendering tests are skipped separately when
no OpenGL context can be made, which is what a bare CI runner without EGL or OSMesa looks
like; everything else runs headless.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

mujoco = pytest.importorskip("mujoco")

from quackd.perception.color_blob import ColorBlobDetector  # noqa: E402
from quackd.sim2d.recorder import FrameRecorder  # noqa: E402
from quackd.sim2d.world import World  # noqa: E402
from quackd.sim3d.render import render_headcam, render_overview  # noqa: E402
from quackd.sim3d.scene import BALL_PARK  # noqa: E402
from quackd.sim3d.world import CONTROL_DT, DEADMAN_S, MujocoWorld, Puppet  # noqa: E402
from quackd.transport.base import Intent, TransportError  # noqa: E402
from quackd.transport.mujoco import MujocoTransport  # noqa: E402


def _run(world: MujocoWorld, seconds: float) -> None:
    for _ in range(round(seconds / CONTROL_DT)):
        world.step()


def _place_ball(world: MujocoWorld, dist: float, bearing_deg: float) -> None:
    """Put the ball `dist` metres from the front of the duck at `bearing_deg`."""
    hx, hy, _z, _yaw, _pitch = world.head_pose()
    ang = world.theta + math.radians(bearing_deg)
    adr = world._ball_qpos
    world.data.qpos[adr : adr + 3] = (hx + dist * math.cos(ang), hy + dist * math.sin(ang), 0.05)
    world.data.qvel[world._ball_dof : world._ball_dof + 6] = 0.0
    mujoco.mj_forward(world.model, world.data)
    world.ball_start = (world.ball_x, world.ball_y)


def _can_render(world: MujocoWorld) -> bool:
    try:
        world.renderer(64)
    except Exception:
        return False
    return True


# ── the world ───────────────────────────────────────────────────────────────────────────


def test_a_seed_lays_the_arena_out_as_it_does_in_sim2d() -> None:
    for seed in range(10):
        cartoon, physics = World(seed=seed), MujocoWorld(seed=seed)
        assert (cartoon.duck.x, cartoon.duck.y, cartoon.duck.theta) == pytest.approx(
            (physics.x, physics.y, physics.theta)
        )
        assert (cartoon.ball.x, cartoon.ball.y) == pytest.approx(
            (physics.ball_x, physics.ball_y), abs=1e-3
        )
        assert (cartoon.people[0].x, cartoon.people[0].y) == pytest.approx(physics.people[0])
        physics.close()


def test_deadman_zeroes_velocity() -> None:
    w = MujocoWorld(seed=0)
    w.set_velocity(0.2, 0.0, 0.0)
    _run(w, DEADMAN_S / 2)
    assert w.moving
    _run(w, DEADMAN_S)
    assert not w.moving
    w.close()


def test_walking_moves_the_body_and_the_walls_hold_it() -> None:
    w = MujocoWorld(seed=0)
    w.body.reset(0.0, 0.0, 0.0)
    for _ in range(5):
        w.set_velocity(0.2, 0.0, 0.0)
        _run(w, 0.2)
    assert 0.15 < w.x < 0.25 and abs(w.y) < 0.02
    for _ in range(60):
        w.set_velocity(0.3, 0.0, 0.0)
        _run(w, 0.2)
    assert w.x <= 1.0 - 0.08 + 1e-9
    w.close()


def test_kick_connects_only_when_close_and_ahead_and_the_ball_rolls() -> None:
    w = MujocoWorld(seed=3)
    w.body.reset(0.0, 0.0, 0.0)
    _place_ball(w, 0.6, 0.0)
    assert not w.kick()
    _place_ball(w, 0.2, 60.0)
    assert not w.kick()
    assert w.last_kick_ball_moved_m == pytest.approx(0.0, abs=1e-6)
    _place_ball(w, 0.2, 0.0)
    assert w.kick()
    assert w.kicks == 3 and w.kicks_connected == 1
    _run(w, 1.5)  # what the kick verb waits before it reads the telemetry
    moved = w.last_kick_ball_moved_m
    assert moved is not None and 0.3 <= moved <= 1.2, moved
    _run(w, 3.0)
    assert w.last_kick_ball_moved_m == pytest.approx(moved, abs=0.2)  # it stopped
    assert w.snapshot()["ball"]["present"]
    w.close()


def test_a_kick_while_sitting_or_fallen_does_nothing() -> None:
    w = MujocoWorld(seed=1)
    w.body.reset(0.0, 0.0, 0.0)
    _place_ball(w, 0.2, 0.0)
    assert w.sit_toggle() == "sitting"
    assert not w.kick()
    w.set_velocity(0.2, 0.0, 0.0)
    _run(w, 0.2)
    assert (w.x, w.y) == (0.0, 0.0), "moved while sitting"
    assert w.sit_toggle() == "standing"
    assert isinstance(w.body, Puppet)
    w.body.fall()
    assert w.posture == "fallen" and not w.kick()
    w.enable()
    assert w.posture == "standing" and w.kick()
    w.close()


def test_ground_pick_is_unreliable_and_parks_a_held_ball() -> None:
    outcomes = []
    for seed in range(12):
        w = MujocoWorld(seed=seed)
        w.body.reset(0.0, 0.0, 0.0)
        _place_ball(w, 0.1, 0.0)
        got = w.ground_pick()
        outcomes.append(got)
        if got:
            assert w.holding and not w.ball_present
            assert (w.ball_x, w.ball_y) == pytest.approx(BALL_PARK[:2])
            _run(w, 1.0)
            assert (w.ball_x, w.ball_y) == pytest.approx(BALL_PARK[:2])
            assert w.snapshot()["ball"] == {"present": False}
            assert w.ball_displacement_m == 0.0
            assert not w.ground_pick()  # the beak is full
        w.close()
    assert any(outcomes) and not all(outcomes), outcomes
    # out of reach: never
    w = MujocoWorld(seed=0)
    w.body.reset(0.0, 0.0, 0.0)
    _place_ball(w, 0.4, 0.0)
    assert not w.ground_pick()
    w.close()


def test_look_pans_the_camera_and_clamps() -> None:
    w = MujocoWorld(seed=0)
    assert not w.look(1.0, 0.5)
    assert w.head_yaw == pytest.approx(math.atan2(0.5, 1.0))
    assert w.look(0.0, 1.0)
    assert w.head_yaw == pytest.approx(math.radians(60))
    assert w.head_pose()[3] == pytest.approx(w.theta + math.radians(60))
    w.close()


def test_determinism_under_seed() -> None:
    def run(seed: int) -> tuple[float, ...]:
        w = MujocoWorld(seed=seed)
        for i in range(100):
            if i % 10 == 0:
                w.set_velocity(0.2, 0.05, 0.5)
            w.step()
        w.kick()
        _run(w, 1.0)
        out = (w.x, w.y, w.theta, w.ball_x, w.ball_y)
        w.close()
        return out

    assert run(7) == run(7)
    assert run(7) != run(8)


# ── the transport ───────────────────────────────────────────────────────────────────────


def test_construction_imports_nothing_and_refuses_an_unknown_body() -> None:
    t = MujocoTransport(seed=1, body="puppet")
    assert t.world is None and t.clock is None and t.now() == 0.0
    with pytest.raises(TransportError, match="unknown mujoco body"):
        MujocoTransport(body="reachy")
    # the real duck is the default, because a physics backend that simulates a stand-in
    # would be a cartoon with extra steps; the tests ask for the stand-in explicitly
    assert MujocoTransport().body == "microduck"


async def test_intents_reach_the_world_and_state_reads_back() -> None:
    t = MujocoTransport(seed=2, body="puppet")
    hooks: list[float] = []
    t.add_tick_hook(lambda w: hooks.append(w.t))  # before connect: buffered
    await t.connect()
    state = await t.get_state()
    assert state.posture == "standing" and state.policy == "stand" and state.battery_percent == 100
    assert (state.x, state.y, state.theta) == (t.world.x, t.world.y, t.world.theta)
    assert state.extras["physics"] == "puppet" and state.extras["ball"]["present"]

    assert (await t.send_intent(Intent.move(0.2, 0.0, 0.0))).accepted
    await t.sleep(0.1)
    assert t.world.moving and (await t.get_state()).policy == "walk"
    assert t.now() == pytest.approx(0.1) and len(hooks) == 5
    await t.stop()
    assert not t.world.moving

    ack = await t.send_intent(Intent(kind="look", params={"x": 0.0, "y": 1.0, "z": 0.0}))
    assert ack.accepted and ack.reason == "clamped to head limits"
    assert (await t.send_intent(Intent(kind="sound", params={"tag": "greet"}))).accepted
    assert t.world.quacks[0][1] == "greet"
    assert (await t.send_intent(Intent.do("sit_toggle"))).accepted
    assert (await t.get_state()).posture == "sitting"
    ack = await t.send_intent(Intent.do("kick_left"))
    assert not ack.accepted and "sitting" in (ack.reason or "")
    assert (await t.send_intent(Intent.do("sit_toggle"))).accepted
    assert (await t.send_intent(Intent.do("kick_right"))).accepted
    assert (await t.send_intent(Intent.do("roulade"))).accepted
    assert not (await t.send_intent(Intent.do("moonwalk"))).accepted
    assert not (await t.send_intent(Intent(kind="joint", params={}))).accepted
    assert (await t.send_intent(Intent.enable(True))).accepted

    got = []
    async for row in t.subscribe("state"):
        got.append(row)
        if len(got) == 2:
            break
    assert got[1]["t"] > got[0]["t"] and got[0]["topic"] == "state"
    await t.heartbeat()
    await t.close()
    with pytest.raises(Exception, match="closed"):
        await t.heartbeat()


async def test_a_fallen_duck_refuses_skills_until_enabled() -> None:
    t = MujocoTransport(seed=0, body="puppet")
    await t.connect()
    t.world.body.fall()
    assert (await t.get_state()).fallen
    ack = await t.send_intent(Intent.do("kick_right"))
    assert not ack.accepted and "fallen" in (ack.reason or "")
    await t.send_intent(Intent.enable(True))
    assert not (await t.get_state()).fallen
    await t.close()


# ── rendering ───────────────────────────────────────────────────────────────────────────


def test_the_head_camera_shows_the_detector_what_the_cartoon_would() -> None:
    w = MujocoWorld(seed=3)
    if not _can_render(w):
        pytest.skip("no OpenGL context for offscreen rendering")
    w.body.reset(0.0, 0.0, 0.3)
    _place_ball(w, 0.5, 20.0)
    w.step()
    dets = {d.label: d for d in ColorBlobDetector().detect(render_headcam(w, 256))}
    assert "ball" in dets, dets
    assert dets["ball"].bearing_deg == pytest.approx(20.0, abs=6.0)
    assert dets["ball"].est_distance_m == pytest.approx(0.5, abs=0.2)
    # the head pans the view, so the ball moves the other way
    w.look(math.cos(math.radians(45)), math.sin(math.radians(45)))
    dets = {d.label: d for d in ColorBlobDetector().detect(render_headcam(w, 256))}
    assert dets["ball"].bearing_deg == pytest.approx(-25.0, abs=6.0)
    # a held ball is out of every frame
    w.look(1.0, 0.0)
    w.ground_pick()
    while w.ball_present:
        _place_ball(w, 0.1, 0.0)
        w.ground_pick()
    assert "ball" not in {d.label for d in ColorBlobDetector().detect(render_headcam(w, 256))}
    assert render_overview(w, 64).size == (64, 64)
    w.close()


def test_the_person_is_blue_enough_to_be_seen() -> None:
    w = MujocoWorld(seed=0)
    if not _can_render(w):
        pytest.skip("no OpenGL context for offscreen rendering")
    px, py = w.people[0]
    w.body.reset(px - 0.8, py, 0.0)  # 0.8 m west of the person, facing it
    w.step()
    labels = {d.label for d in ColorBlobDetector().detect(render_headcam(w, 256))}
    assert "person" in labels, labels
    w.close()


async def test_the_recorder_draws_the_physics_panes(tmp_path: Path) -> None:
    t = MujocoTransport(seed=0, body="puppet")
    rec = FrameRecorder(t, size=64)  # before connect, as the CLI does
    await t.connect()
    if not _can_render(t.world):
        pytest.skip("no OpenGL context for offscreen rendering")
    await t.send_intent(Intent.move(0.2, 0.0, 0.3))
    await t.sleep(0.6)
    rec.capture(await t.get_frame(), "observe")
    gif = rec.save_gif(tmp_path / "run.gif")
    assert gif.exists() and gif.stat().st_size > 500
    assert len(rec.frames) >= 3 and rec.frames[0].size == (64 * 2 + 4, 64 + 22)
    await t.close()


# ── the real duck ───────────────────────────────────────────────────────────────────────


#: The Microduck body needs upstream's model and policies, which are fetched at run time and
#: never shipped. Tests must not reach the network, so these run only when a previous run
#: (or a developer) has already filled the cache, and are skipped everywhere else. Every
#: caller carries `@pytest.mark.real_duck`, which is what exempts it from the conftest's
#: throwaway cache; without the marker this would look in an empty directory and always skip.
def _cached_microduck() -> Any:
    from quackd.sim3d.assets import AssetError, ensure_microduck

    try:
        return ensure_microduck(offline=True)
    except AssetError as e:
        pytest.skip(f"upstream's Microduck model is not cached: {e}")


@pytest.mark.real_duck
def test_the_real_duck_walks_turns_and_stays_upright() -> None:
    assets = _cached_microduck()
    from quackd.sim3d.microduck import MicroduckBody

    w = MujocoWorld(seed=6, body=MicroduckBody(assets))
    assert w.posture == "standing"
    assert w.snapshot()["physics"] == "microduck"
    assert any("ONNX" in a for a in w.snapshot()["assumptions"])

    def drive(vx: float, wz: float, seconds: float) -> tuple[float, float]:
        """Metres travelled and NET heading change. Net, not the sum of the steps: a real
        gait wags the trunk every stride, so the absolute total is large walking straight."""
        x0, y0, turned, previous = w.x, w.y, 0.0, w.theta
        for i in range(round(seconds / CONTROL_DT)):
            if i % 5 == 0:  # re-sent at 10 Hz, as the move verb does, or the deadman fires
                w.set_velocity(vx, 0.0, wz)
            w.step()
            turned += math.atan2(math.sin(w.theta - previous), math.cos(w.theta - previous))
            previous = w.theta
        return math.hypot(w.x - x0, w.y - y0), turned

    walked, turned = drive(0.3, 0.0, 6.0)
    assert walked > 0.3, f"asked for 0.3 m/s and moved {walked:.2f} m in 6 s"
    assert abs(turned) < 1.0, f"walking straight turned it {turned:.2f} rad"
    assert w.posture == "standing"
    _walked, turned = drive(0.0, 1.2, 6.0)
    assert turned > 1.5, f"asked for 1.2 rad/s and turned {turned:.2f} rad in 6 s"
    assert w.posture == "standing", "the duck fell over walking on its own policy"
    w.close()


@pytest.mark.real_duck
def test_the_real_duck_refuses_to_sit_and_stands_itself_up() -> None:
    from quackd.sim3d.microduck import MicroduckBody
    from quackd.sim3d.world import NotSupported

    w = MujocoWorld(seed=0, body=MicroduckBody(_cached_microduck()))
    with pytest.raises(NotSupported, match="sit"):
        w.sit_toggle()
    # tip it over: a policy that cannot get up must at least report that it is down
    w.data.qpos[w.body.free_q + 3 : w.body.free_q + 7] = (0.7, 0.7, 0.0, 0.0)
    for _ in range(30):
        w.step()
    assert w.posture == "fallen"
    assert w.snapshot()["tilt_deg"] > 45
    w.enable()
    for _ in range(50):
        w.step()
    assert w.posture == "standing"
    w.close()
