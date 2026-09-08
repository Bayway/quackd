# ADR-0030: a MuJoCo backend that runs the Microduck's own walking policy

**Status:** accepted · **Date:** 2026-09-07 · Amends [ADR-0007](0007-sim2d-cartoon.md) ·
Implemented in 0.8 (`--robot microduck:mujoco`, and `web/` in a browser)

## Context

[ADR-0007](0007-sim2d-cartoon.md) chose a cartoon. It was the right call and it says why:
the north-star demo had to run on any laptop in under a minute, what needed testing was the
agent loop rather than contact dynamics, and upstream's simulator "needs a GPU and CC
BY-NC-SA meshes we will not vendor". The cartoon has carried eight adapters since.

It also has a ceiling that the docs have always been honest about: *it will not tell you
whether a gait works*. Every quackd demo so far shows a sprite sliding at exactly the speed
it was asked for. A pilot that has only ever driven that has never met the thing that makes
a real robot hard, which is that it does not do what you asked.

Two of ADR-0007's premises turned out to be wrong by 2026-09, and one was always narrower
than it read.

- **The GPU is for training, not for running.** `microduck_rl` trains on mjlab and MuJoCo
  Warp and needs CUDA to do it, but its own evaluation path is `scripts/infer_policy.py`,
  which imports `mujoco`, `mujoco.viewer` and `onnxruntime` and nothing else. Upstream also
  ships `duck-body`, a plain CPU MuJoCo body served to the real `robotd`. Running a trained
  policy has never needed a GPU.
- **The policies are public and permissive.** The nine ONNX policies a Microduck ships with
  are on the Hugging Face Hub as `pollen-robotics/microduck-policies` under Apache-2.0. Only
  the 3D model files are CC BY-NC-SA.
- **"We will not vendor" is not "we cannot use".** `docs/licenses.md` has said since 0.1
  that a future MuJoCo backend "fetches them from upstream at runtime into a user cache,
  prints the license, and stays optional". That is a design, and it works.

`mjlab` was considered and rejected as the runtime. It is the factory that made the gait:
Isaac-Lab-style managers over MuJoCo Warp, built to step thousands of robots on an NVIDIA
GPU. Its README says an NVIDIA GPU is required for training and macOS is evaluation only;
its Windows support is "preliminary" and "not guaranteed to be stable"; MuJoCo Warp's own
documentation says a single step is *slower* than MuJoCo's because it optimises throughput
rather than latency; and `microduck_rl` pins Python 3.12 exactly with torch and warp behind
it. None of that suits one duck in a 50 Hz loop on a laptop. Plain MuJoCo is a wheel of 17
to 20 MB depending on the platform, with builds for Windows and Linux on x86-64 and macOS on
Apple Silicon, and no GPU. There is no Intel Mac wheel.

## Decision

- **A fifth Microduck backend, `microduck:mujoco`**, behind the same `DuckTransport`
  protocol as the other four. `quackd/sim3d/` is to `quackd/sim2d/` what physics is to a
  drawing: same arena, same seeded spawn order, same 0.3 s deadman, same kick cone, same
  unreliable scoop, and the same `extras` keys, so a `.duck` written for one runs on the
  other unchanged.
- **The robot is upstream's, all the way down.** `robot_walk.xml` and its 38 meshes come
  from `microduck_rl` at a pinned commit; `alpha_walking.onnx` and `alpha_stand.onnx` come
  from the Hub at a pinned revision; the 50 Hz loop around them is `infer_policy.py`'s,
  cited line by line in `quackd/sim3d/upstream_api.py`. quackd supplies a twist and a head
  pose, which is what a gamepad supplies on the real robot. It writes no gait.
- **Assets are fetched at run time, verified, and never shipped.** The first run downloads
  upstream's tarball into `~/.quackd/cache`, checks every file against the sha256 it was
  read at, and writes the licence notice beside it. `QUACKD_MICRODUCK_ASSETS` points at a
  checkout instead. Nothing CC BY-NC-SA enters the wheel, the repository or a CI fixture.
- **A stand-in body for the tests.** `body="puppet"` is a kinematic block that moves exactly
  as the cartoon does inside the same MuJoCo scene. It needs no download and no policy, so
  CI exercises every intent, the recorder and a seeded acceptance sweep offline, and the
  tests that need the real duck skip when the cache is empty.
- **The gait floor is handled in the open.** Under the model's own PD actuators the walking
  policy does not step below about 0.22 m/s or 1.0 rad/s, and it achieves about 0.42 of
  what it is asked. `move` defaults to 0.15 m/s, so passing a command through unchanged
  would give a duck that reports walking and stands still, which is the worst failure a
  simulator can have. A non-zero twist is scaled bodily up to the floor, keeping the ratio
  between its axes so an arc stays an arc; a twist below a third of the floor is dropped to
  zero rather than amplified into a lurch; and the floor, the commanded twist and the twist
  actually sent are all in the state, in the prompt and in `extras.assumptions`.
- **Four skills are named stand-ins.** `kick` and `grab` use the cartoon's contact rules,
  because upstream's episodic `ball_kick_*` and `ground_pick` policies did nothing from a
  standing pose when they were tried; `sit` is refused, because `alpha_sitstand` put the
  model on its back; and a fall is recovered by standing the model up again, because
  upstream ships no get-up policy. Each is listed in `state.extras.assumptions`, so a
  transcript never implies more than happened.
- **The same demo runs in a browser.** `web/` is a static page: MuJoCo compiled to
  WebAssembly, the same policy in onnxruntime-web, the same verbs and the same contract in
  six modules of plain JavaScript with no build step, and the model and the policy fetched from
  the same pinned upstreams. It exists so that trying quackd costs nobody an install, and it carries a
  switch that removes the quackd layer and hands the visitor the keyboard instead.
- **`sim2d` stays the default.** It starts in a second, needs no network, and is what eight
  adapters share. The physics backend is an extra, `quackd[mujoco]`, imported only inside
  `connect()`.

## Consequences

- The one thing the cartoon could never show is now on the table: `find-and-kick` succeeds
  on 10 of 10 seeds with the scripted pilot **and the duck walking on its own trained
  policy**, ground truth checked. That sweep is `test_find_and_kick_on_the_real_duck`; it runs
  only where upstream's model is already cached, and the sweep beside it runs the same ten
  seeds on the puppet. A pilot that works here has met a robot that undershoots.
- Rendering is the cost. On an Intel iGPU a head-camera frame is 4 ms with the shell hidden
  and the over-the-shoulder view about 110 ms with 431k triangles in it, so shadows are off,
  the recorder samples half as often as the cartoon's, and `--live` uses MuJoCo's own viewer.

  *Since:* the arena is upstream's own scene, from the `scene*.xml` wrappers in `microduck_rl`
  — the blue-grey checker with edge marks, the gradient skybox, the haze, the headlight, the
  directional light and the viewer's azimuth and elevation. Shadows stay off by default and
  `QUACKD_MUJOCO_SHADOWS=1` turns them on for a recording. What the scene cost is the head
  camera: that floor and that sky are the same blue as quackd's person marker, at hue 105 and
  114 with saturation and value overlapping too, so the detector read a person 0.12 m ahead in
  every frame of every heading. The head camera therefore renders a colourless copy of the
  same checker and no skybox, in a geom group MuJoCo hides everywhere else. It is a stand-in
  and it is in `extras.assumptions` with the rest. The defence of it is that upstream's blue
  tiles are a viewer texture and upstream's policies are blind: nothing in `microduck_rl` ever
  looks at its own floor, and a real Microduck's camera sees a room rather than a scene file.
- CI never fetches the model, so the `microduck:mujoco` row's ✅ rests on the puppet's sweep
  plus tests that skip where the cache is empty. The real duck's numbers in this ADR were
  measured on one machine, and `GAIT_THRESHOLD` is tagged UNVERIFIED for that reason.

  *Since:* both halves of that changed. A `physics` job installs the extra and runs the
  stand-in's sweep against OSMesa on every push, failing rather than skipping when it cannot
  make a context. A nightly job fetches the model into a runner it then destroys — no cache
  entry, because a keyed one is restorable by any run including a fork's, and `licenses.md`
  says no CI fixture carries a byte of these meshes — and runs the trained gait's sweep there.
  The 10 of 10 is a named test now rather than a memory, and it asserts the body really is the
  trained one, because a silent fall back to the puppet passing it is the point.
- Two upstreams now have to be tracked rather than one, both pinned, both in
  `quackd/sim3d/upstream_api.py`. A new export from either is a new pin and a new sha256.
- Flock mode stays `sim2d` only. `FlockClock` was generalised to any world with a `t` and a
  `step(dt)` so a MuJoCo arena could hold several ducks later, but nothing promises it.
- **Nothing in `web/` has been run in a browser.** `microduck.js` and `pilot.js` were exercised
  under Node against the real model and the real policy, and the rendering, the DOM and the
  recording were read rather than run. No CI job touches `web/`, and GitHub Pages was not enabled
  on the repository when this was written, so the page is not live. The first person to open it
  is the test.
- None of this makes a hardware claim. It is a better simulator, not a robot: the Microduck
  rows in `docs/adapter-status.md` that say "never run on a duck" still say it.
