# ToddlerBot

A small open source humanoid, about 56 cm and 3 kg, with two arms, two legs, a two joint neck
and thirty Dynamixel servos. It is quackd's first full humanoid, and the second body whose
robot side quackd ships, because upstream has no network API of any kind.

Upstream: [hshi74/toddlerbot](https://github.com/hshi74/toddlerbot), pinned at
[`84e02d1`](https://github.com/hshi74/toddlerbot/tree/84e02d14261292eec5d06f896e3145b35c54856c),
which is the commit the annotated tag `v2.0.0` points at (read 2026-09-05). Note the tag
object's own sha, `6fde5df5`, is **not** a commit and pinning it gets a 422. Code is MIT; **the
design, including everything under `descriptions/`, is CC BY-NC-SA 4.0 and therefore
non-commercial**, so quackd vendors none of it.

**Nothing here has ever run on a robot.**

```bash
# offline
uv run quackd run toddlerbot-lookout --robot toddlerbot:sim2d --provider fake

# a real robot, once quackd's daemon is running on it
uv run quackd run toddlerbot-lookout --robot toddlerbot:bridge \
  --address tcp://toddlerbot.local:9873
```

## Backends

| `--robot` | What it is | Status |
|---|---|---|
| `toddlerbot:mock` | the daemon's answers in memory | ✅ every verb runs offline in the test suite |
| `toddlerbot:sim2d` | the cartoon world with a humanoid profile | ✅ runs, no seeded sweep yet |
| `toddlerbot:bridge` | the real robot, through the daemon quackd ships | 🧪 names VERIFIED at the pin, the protocol and the daemon exercised against a fake body over loopback, **never run on a robot** |

## Why quackd ships a daemon

There is nothing to talk to. No socket, no daemon, no IPC: upstream is a Python library whose
control loop opens serial ports in-process. That is the Open Duck Mini situation rather than
the Microduck one, so [`bridge/toddlerbot/`](../../bridge/toddlerbot/) holds a daemon and this
adapter is its client.

But there is a second reason, and it is the one that matters. **A verb is episodic and this
robot is not.** `RealWorld.step()` is a no-op, so nothing times out and nothing re-arms: the
last commanded pose is held forever. A humanoid frozen mid-stride while a model thinks is a
humanoid on the floor. So the daemon runs the fifty hertz loop continuously and quackd's
intents only steer what it is already doing.

## What upstream does not protect, and what quackd added

Every row here was read at the pin. Upstream's CI is disabled and its repository has one test
file, so none of it was ever machine-verified by anyone.

| What is missing upstream | What the daemon does about it |
|---|---|
| `set_motor_target` clamps nothing and never reads the joint limits, which exist. The motors are in multi-turn mode, so the firmware limits are off too. | Clamps every target against the MJCF joint ranges. |
| No rate limit anywhere. A position command is a full-torque snap. | Caps how far any joint may move per tick. |
| A failed bulk read returns an all-zeros buffer, indistinguishable from every joint at zero. Believing it commands a full-scale move to zero. | Detects it, refuses it, and holds the last verified-good pose. |
| A controller fault surfaces as a bare `KeyError`, because the C++ swallows it and inserts an empty map. | Catches it and treats it as a hardware fault, not a transient. |
| No `reset` anywhere in the sim package: no home, no safe pose. | Builds one: upstream's default pose at upstream's own 0.3 rad/s, waist first. |
| No watchdog, no timeout, no e-stop. Silence means hold forever. | Its own deadman, which slews to the safe pose and holds. It never goes limp. |
| No Python signal handler, and the C `atexit` does not run on `SIGTERM`. | Installs handlers that settle before anything may exit. |
| `close()` is bound without releasing the GIL and retries torque-off forever on a dead bus, so a stuck shutdown freezes every thread. | Arms a hard-exit timer before calling it. |
| The constructor busy-waits forever on a silent IMU, with the motors already live. | Runs construction in a thread it is willing to abandon. |
| `set_motor_kps` raises `NotImplementedError` on hardware. | Never calls it, so no shutdown path depends on softening gains first. |
| Upstream tells hardware from sim with `"real" in sim.name`. | Dispatches on type. |

## What this robot cannot do

- **`say`.** `Speaker` imports `re`, `subprocess` and `sounddevice`: it plays audio, it does
  not synthesise it. There is no text to speech at this pin, so the `sound` intent is not
  declared.
- **Walk, usually.** The gait is an ONNX checkpoint fetched from a wandb artifact. Nothing is
  checked in and the README mentions no checkpoint, entity or download at all. Without one
  `move`, `go_to` and `approach_and` **do not exist**, and `mobility` is `none`. They appear
  only when the daemon reports one staged.
- **Get up.** There is no recovery policy for this body, so `stand_up` is not declared and a
  fall ends the run. Every moving verb refuses afterwards and asks for a human.
- **Report a battery.** Bus voltage is read in C++ and only printed, so a battery abort can
  never fire here.
- **Report a position.** The observation carries motor positions and an orientation. There is
  no odometry, so `go_to` closes the loop on the camera alone.

## The motions, and which ones quackd offers

Nine motions ship as keyframes, and they are the only motion that works with no downloads.
quackd offers five: **hold, kneel, cuddle, push_up, crawl**.

The other four are excluded on judgement rather than capability, and the distinction matters:
the robot can do all of them. `pull_up_grasp` and `pull_up_pull` assume the robot is hanging
from a bar, so asking for one on a robot standing on a table is a fall. `walk_zmp` is a gait
reference rather than a performance, and locomotion belongs to `move` where the deadman covers
it. `cartwheel` is excluded twice over. This body has no fall recovery, and a cartwheel is not
something to discover a language model can trigger, but it also *cannot* be replayed: its file
carries `action=None` because it is qpos-interpolated and meant to run as its own RL policy.
`walk_zmp` cannot be replayed either, for a different reason: despite sitting in the same
directory with the same extension it is not a keyframe file at all, it is a gait lookup table
used at training time.

Upstream ships no loader for any of this. Every call site there reads the file with
`joblib.load` inline, so the daemon does the same. Each motion is written twice, once per
variant, and the daemon picks `_2xc` or `_2xm` from the robot name it was started with. A
keyframe file that is missing, unreadable or carries no action array is **not offered**: the
handshake reports the motions that actually loaded, and quackd's manifest lists those. A
shorter list is better than a verb that refuses on a robot.

## Running the daemon

It needs upstream installed on the robot, in upstream's own environment. Note that `mujoco` is
not a declared dependency there and arrives transitively, unpinned, so pin it yourself.

```bash
git clone https://github.com/hshi74/toddlerbot && cd toddlerbot
git checkout 84e02d14261292eec5d06f896e3145b35c54856c
pip install -e . && pip install 'mujoco==3.3.4' 'scipy>=1.14'
python quackd_toddlerbot_bridge.py --robot toddlerbot_2xc --toddlerbot .
```

Three flags decide what this robot can do, and **each one is checked rather than believed**.
A capability the daemon reports is a verb quackd will offer, so the daemon only reports what
it actually loaded.

| Flag | What it needs | If it is not there |
|---|---|---|
| `--camera left` or `--camera right` | upstream's `Camera`, which needs `cv2`, the `v4l2-ctl` binary and a real device | logged, and the robot simply has no camera: `observe`, `go_to`, `search_scan` and `approach_and` never appear |
| `--walk-policy NAME` | `ckpts/NAME/model_best.onnx` **and** `env_config.json` beside it | the daemon refuses to start rather than reaching for a wandb artifact from a robot |
| `--gripper` | the gripper build | `grip` does not appear |

There is no `--walk` flag any more, and that is the point: walking needs a checkpoint upstream
neither publishes nor checks in, so it is a file you supply and the daemon loads. It reads that
checkpoint's own `command_range` at startup and reports the velocity envelope it was really
trained on, which is what quackd's `limits` then narrow to. Nothing is hardcoded from a gin
file.

`--fake` runs the whole daemon and protocol against a simulated body, with no robot and no
upstream, which is what CI does. The daemon **refuses to actuate without a zero calibration**
(`motors.yml`), because without it every commanded angle is offset by however that particular
robot was assembled.

## The contract job, and what a green one means

`.github/workflows/toddlerbot-contract.yml` runs nightly and on demand, and it is the only
thing in this repository that installs upstream. It takes a blobless sparse checkout of about
70 MB out of upstream's 1.2 GB, starts quackd's real daemon with `--sim mujoco`, and drives it
with quackd's real client over a real socket.

It is deliberately not part of `ci`. The main suite has to stay installable on Windows with
nothing but quackd's own dependencies, and this needs MuJoCo, jax, OpenCV and a 30-motor
model. It is also `continue-on-error`, because what it watches for is upstream drift rather
than a regression here.

Two things the plan for this adapter got wrong, corrected by reading the source. There is no
need for `MUJOCO_GL=osmesa` or `xvfb`: the headless path builds neither a viewer nor a
renderer, so no GL context is created at all, and upstream never reads `MUJOCO_GL`. What is
needed instead is that `import mujoco.viewer` succeeds, because `mujoco_sim` imports it at
module scope before it checks `vis_type`, and that pulls in glfw's shared library. The job
installs the X11 client libraries for that reason, and it never runs a display.

**A green run still means nothing about hardware.** It means the protocol, the fifty hertz
loop, the clamp and the deadman hold up against thirty simulated motors that push back, which
is strictly more than the fake body could prove and strictly less than a robot.

## VERIFIED (read from upstream source on 2026-09-05, at `84e02d1`)

| Thing | Value | Used for |
|---|---|---|
| The contract | `BaseSim` | six abstract methods and no more |
| The observation | `Obs` | twelve fields, and no image field of any kind |
| Always None on hardware | `pos, lin_vel, joint_pos, joint_vel` | and `motor_acc`; there is no pose |
| Stepping does nothing | `def step(self)` | the write already happened |
| Commanding | `RealWorld.set_motor_target` | radians, absolute, and it clamps nothing |
| Dict order is not motor order | `motor_angles.values()` | quackd only ever sends an array |
| Multi-turn | `extended_position` | firmware position limits are off |
| Gains cannot be set | `NotImplementedError` | so no shutdown may depend on softening them |
| Retries are ignored | `retries` | accepted and never read |
| A dropped read is zeros | `bulk_read` | indistinguishable from a valid reading |
| A fault is not an exception | `KeyError` | the C++ swallows it and leaves an empty map |
| A units error upstream | `motor currents in Amperes` | the hardware delivers milliamps |
| Quaternion order | `scalar_first` | w first, and it puts a real floor under scipy |
| The bindings | `PYBIND11_MODULE(dynamixel_cpp, m)` | eight names and no more |
| Torque cannot be re-enabled | `enable_motors` | exists in C++, not bound to Python |
| Closing goes limp | `set_torque_enabled` | with false; on a standing robot that is a fall |
| Any exit drops the robot | `atexit(dynamixel_cleanup_handler)` | registered from the client constructor |
| Except the exits that matter | `dynamixel_cleanup_handler` | C atexit does not run on SIGTERM |
| Shutdown holds the GIL | `close` | bound without a release guard, and it retries forever |
| And it is process-global | `close_motors` | closing one controller disconnects them all |
| And it is unguarded | `self.imu.close()` | an exception there skips the motor close |
| Construction energises | `initialize` | the robot is live the moment it returns |
| Construction needs an IMU | `get_latest_state` | dereferenced with no None guard |
| Construction can hang | `while not imu_data` | no sleep, no timeout, no cap |
| Construction hides failure | `Dynamixel controller not found` | printed, and it carries on |
| No safe pose exists | `reset` | nowhere in the sim package |
| The rate to move at | `reset_vel` | 0.3 rad/s, upstream's own |
| The waist goes first | `ResetPDPolicy` | upstream's own two-phase rule |
| The loop rate | `control_dt` | 0.02 s, and nothing overrides it |
| Walking needs a download | `load_wandb_policy` | nothing is checked in |
| And all three keys | `control_inputs` | a partial command raises mid-tick |
| The real envelope | `command_range` | comes from the checkpoint, not the gin file |
| The camera | `Camera` | exists, but not in the observation |
| The speaker cannot speak | `Speaker` | it plays audio and nothing synthesises it |
| No battery in Python | `read_vin` | read in C++ and only printed |
| The version disagrees | `0.2.0` | while the tag says v2.0.0 |
| CI is off | `Skipping tests` | nothing here was machine-verified upstream |
| MuJoCo is transitive | `brax` | undeclared and unpinned |
| The builds | `Robot` | five names, thirty to thirty-two motors |
| The only joint limits | `motor_limits` | parsed from the MJCF, never from YAML |
| Calibration is absent | `motors.yml` | gitignored, so a fresh clone has none |
| The only offline motion | `motion` | eighteen keyframes, nine motions |
| No loader exists | `joblib.load` | every reader upstream loads the file inline |
| Motions are per variant | `robot_suffix` | `_2xc` or `_2xm`, chosen from the robot name |
| The frames | `action` | (frames, 30) float32 radians, in `motor_ordering`, at 50 Hz |
| Not replayable | `cartwheel` | `action=None`: it is an RL policy, not a keyframe |
| Not a motion at all | `walk_zmp` | a gait lookup table that shares the extension |
| The camera takes a side | `Camera.__init__` | untyped, Linux only, and synchronous |
| Frames are BGR | `Camera.get_frame` | raises rather than returning None |
| Its JPEG is wrong | `Camera.get_jpeg` | hands RGB to `imencode`, which wants BGR |
| The walk loader | `load_wandb_policy` | returns a directory, not the dict it annotates |
| The walk step | `WalkPolicy.step` | takes the observation and the sim, returns a pair |
| The envelope | `command_range` | rows 5, 6 and 7 are the walk velocities |
| All three or none | `control_inputs` | a partial dict raises mid-tick |
| Never clipped upstream | `walk_x` | out-of-envelope goes straight to the network, so the daemon clamps |
| The simulated body | `MuJoCoSim` | takes the Robot, runs at the same fifty hertz |
| Headless by default | `vis_type` | only render or view build anything that needs GL |
| Do not use it | `controller_type` | the position controller's step takes the wrong arity |
| Paths are relative | `scene.xml` | so the daemon changes directory to the checkout root |

## UNVERIFIED, and what quackd does about it

| Name | The assumption | What quackd does |
|---|---|---|
| `DAEMON_PROTOCOL` | the wire is quackd's own at both ends | there is no upstream to verify it against, so citing one would be a false citation. What is cited instead is every assumption the daemon makes |
| `SAFE_POSE` | upstream's default pose is safe to slew to | true from standing; from a crawling or prone start it is untested and must be tried on a stand |
| `FALL_DETECTION` | a tilt past 50 degrees is a fall | there is no fall detection upstream at all; the threshold is a guess until somebody tips a real robot |
| `NECK_AXES` | which neck motor is yaw | inferred from the motor names rather than stated anywhere |
| `ZERO_LATCHING` | a calibrated zero survives `initialize` | reading did not settle whether the configured zero is re-latched at every startup; the daemon refuses to actuate without the file either way |
| `WALK_POLICY_IS_STATEFUL` | the gait policy can be driven only while `move` runs | it keeps a history and a buffer, expects a fixed fifty hertz, and ignores its commands for the first seven seconds. quackd steps it only while walking, so that window opens on the first command rather than at startup, and whether a gait driven that way behaves like one driven continuously is untested |
| `THREAD_SAFETY` | the C++ is not safe across threads | two of eight bindings release the GIL and six do not, so every call is serialised onto the control thread and the camera stays on another |

## How to help

If you have built a ToddlerBot, **put it on its safety stand first**. Then run quackd's daemon,
point `toddlerbot-lookout` at it, and say what happened: that task's allowlist moves no leg, no
arm and no waist. What most needs a real robot: whether the safe-pose slew is actually safe
from a crawl, what tilt angle really means fallen, whether the neck axes are what the motor
names imply, and whether a calibrated zero survives a restart.
