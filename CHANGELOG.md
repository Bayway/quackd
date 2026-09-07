# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.0] — 2026-09-07

A sixth, a seventh and an eighth robot, two hardware paths audited against upstream rather
than against themselves, and an abort that finally reaches the verb it is aborting. Two of the
new robots quackd drives without importing anything from them, because neither is an
installable package, and the third has no network API at all, so quackd ships the loop it runs
on. The Open Duck Mini's daemon and installer were read against a duck set up exactly the way
the docs instruct, and it could not start the bridge; if it could, it would have had no camera
verbs; and the operator's Ctrl-C would not have stopped it. The Microduck's transport was read
against an API that had moved on while nobody was looking. Still nothing has run on a robot;
what changed is that several things which could not have worked now can, and several claims
that were not true no longer are.

### Added

- **The XLeRobot: a dual-arm mobile manipulator on an IKEA cart, about $660 to build**
  (`--robot xlerobot:mock` or `xlerobot:zmq`). Two five-joint arms with grippers on a
  three-omniwheel base that really can drive sideways, so `move` here carries a `vy` that
  means something for the first time. It is also the first body quackd talks to **without
  importing anything from it**: XLeRobot is not a package — no PyPI entry, no `pyproject.toml`,
  and its documented install is copying files into an existing lerobot tree — but it already
  ships a ZeroMQ host, so quackd speaks that wire and its extra is `pyzmq` and nothing else.
  That keeps the 3.11 floor and works on Windows, unlike `quackd[lerobot]`. Design:
  `docs/adr/0026-xlerobot.md`, with the page at
  [docs/adapters/xlerobot.md](docs/adapters/xlerobot.md).
- **The whole wire format is exercised against a fake host over loopback**, on every CI
  platform. Upstream ships no test, no CI and no simulator that runs — its ManiSkill host
  imports `xlerobot_single`, which is defined nowhere in the repository — so the other end of
  the protocol is written from upstream's source at a pinned commit and quackd's real client is
  driven against it. That caught a bug no reading would have: `stop` rebuilt its hold from the
  latest observation, which is several cycles behind and carries no timestamp, so stopping
  would have commanded an arm back towards zero. A stop that moves an arm is the failure this
  project exists to prevent. `stop` now zeroes the wheels and leaves every arm goal exactly
  where it already was.
- **`xlerobot-lookout`**, the task to point at a real cart first: nothing in its allowlist
  moves a wheel or an arm. It is the thinnest starter quackd ships, and honestly so — without
  a head to turn and without a voice, a task that moves nothing can only look and report.
- **The AlohaMini: two arms on a motorised lift, on a wheeled base** (`--robot alohamini:mock`,
  `sim2d` or `zmq`). quackd's second bimanual body and its first with a vertical axis. Like the
  XLeRobot it is reached by speaking its ZeroMQ host protocol rather than importing it, and for
  a stronger reason: upstream is a fork of LeRobot that *calls itself* `lerobot`, is not on
  PyPI, and installs only from a large git clone on Python 3.12 with torch. Speaking the wire is
  also more correct than importing would have been, because upstream's own client throws away
  the camera list the host sends and its robot-model default disagrees with the host's, with
  nothing cross-checking either. quackd reads both off the wire, so neither can be silently
  wrong. Design: `docs/adr/0027-alohamini.md`, with the page at
  [docs/adapters/alohamini.md](docs/adapters/alohamini.md).
- **A host wrapper for the robot, because upstream's own host leaves the arms limp.**
  `configure()` disables arm torque and both of its `enable_torque()` calls are commented out;
  nothing else in the driver turns it on. So `bridge/alohamini/` holds a wrapper that runs
  upstream's loop with torque enabled and the lift stopped, and adds three fields so quackd can
  tell it from a stock host. Without it, `move_joints`, `gripper` and `home_arms` refuse and say
  why, rather than commanding joints that would not move.
- **A stop that actually stops this robot.** Three upstream behaviours conspire against one.
  All three velocity keys are mandatory in every payload, because `send_action` indexes them
  with no default and would otherwise discard the whole action, arms included, without
  refreshing its own watchdog. The lift latches, so a payload that says nothing about it leaves
  it travelling. And the lift's two keys are not symmetric, so a payload carrying both freezes
  it instead. One function builds every payload and holds all three invariants, and the fake
  host reproduces the bugs so the tests mean something: `test_stop_zeroes_the_lift` fails
  against the naive three-key stop that the shape of the driver invites.
- **`alohamini-lookout`**, the task to point at a real AlohaMini first: nothing in its
  allowlist moves a wheel, an arm or the lift. It is the same shape as `xlerobot-lookout` and
  for the same reason, since this body has no head and no voice either: `observe`,
  `report_state` and `stop` are the whole allowlist, a human aims the camera, and the answer
  goes in the reason the pilot declares success with. The budget is twelve steps and three
  minutes. The scripted pilot takes one frame and answers, and on `alohamini:sim2d` it succeeds
  on ten of ten seeds with the world's ground truth checked that the base never moved. The
  AlohaMini checklist runs it at step 5, on upstream's stock host with the arms still limp.
- **The ToddlerBot: a small open source humanoid, and the first body here that can hurt
  itself** (`--robot toddlerbot:mock`, `sim2d` or `bridge`). Two arms, two legs, a two joint
  neck and thirty servos, on a machine with no network API of any kind, so quackd ships the
  daemon that runs on it. That is the Open Duck Mini's shape, but for a second reason that
  matters more: a verb is episodic and this body is not. Its `step()` is a no-op, so nothing
  times out and nothing re-arms, and a humanoid frozen mid-stride while a model thinks is a
  humanoid on the floor. The daemon runs the fifty hertz loop and quackd's intents steer what
  it is already doing. Design: `docs/adr/0028-toddlerbot.md`, with the page at
  [docs/adapters/toddlerbot.md](docs/adapters/toddlerbot.md).
- **Seven things upstream does not do, because reading it at the pin said so.** It clamps
  nothing and never reads the joint limits that exist, on motors in multi-turn mode where the
  firmware limits are off too. A dropped packet returns an all-zeros reading indistinguishable
  from every joint at zero, which fed to a position controller commands a full-scale move to
  zero. A controller fault arrives as a bare `KeyError`. There is no reset anywhere, no
  watchdog, no timeout and no e-stop. So the daemon carries a clamp, a rate limit, an
  all-zeros detector, a fault guard, a safe-pose slew, signal handlers and a construction
  watchdog, and every one of them is exercised in CI against a fake body over a real socket.
- **A shutdown that does not drop the robot.** Upstream's does: a C level `atexit` handler
  disconnects every client and disconnecting disables torque, so any unhandled exception or
  plain Ctrl-C de-torques a standing humanoid with no lowering and no ramp. `SIGTERM` does not
  even reach that handler, and upstream installs no Python one, so systemd stopping it leaves
  the robot fully torqued holding its last target instead. quackd's daemon settles to a safe
  pose first, then closes under a hard deadline, because `close()` holds the GIL and retries
  forever on a dead bus.
- **A deadman that is a trajectory rather than a message.** On a duck, silence is safe and
  zero velocity is a stop. Here the command is an absolute pose, so holding the last target,
  jumping to a new one and going limp are the only three options and none of them is safe. The
  daemon slews to upstream's own default pose at upstream's own rate, waist first as its own
  reset does, and holds.
- **`toddlerbot-lookout`**, the task to point at a real humanoid first, on its safety stand:
  nothing in its allowlist moves a leg, an arm or the waist.
- **[docs/toddlerbot-hardware-checklist.md](docs/toddlerbot-hardware-checklist.md), the order
  to try a real ToddlerBot in.** Fourteen steps on the safety stand upstream ships, feet off
  the ground until step 13. Step 2 is `calibrate_zero`, because the daemon refuses to actuate
  without a `motors.yml`. It runs the daemon with `--fake --once` and `quackd doctor` against
  port 9873 before a motor is powered, points `toddlerbot-lookout` at the robot at step 8, and
  holds steps 11 and 12 (pull the network cable mid-move, then send `SIGTERM`) as the two that
  matter, because on this body silence means hold forever and the daemon is the only thing that
  makes it mean anything else. It ends with the four things only a real robot can answer, the
  safe-pose slew from a crawl or a prone start first. There is no issue template for it, so
  open a plain issue with the transcript.
- **`QUACKD_TODDLERBOT_TOKEN` and `TODDLERBOT_ROOT`**, the two environment variables the
  ToddlerBot's adapter and daemon read. The token is the ToddlerBot's own and not
  `QUACKD_DUCK_TOKEN`, and `--token`'s help says so now: `quackd/adapters/toddlerbot/bridge.py`
  reads it when `--token` is absent and sends it in `bot.hello`, and
  `bridge/toddlerbot/quackd_toddlerbot_bridge.py` reads the same name as the default for its
  own `--token`, compares it with `hmac.compare_digest`, and refuses every other method until a
  hello carries it. A daemon started with no token accepts everyone, and nothing writes one for
  you, because this daemon has no installer. `TODDLERBOT_ROOT` is the daemon's alone: it is the
  default for `--toddlerbot` (otherwise `.`), the upstream checkout the daemon changes
  directory into and imports from, because every path upstream's `Robot` builds is relative,
  and `--fake` never opens it. The nightly contract job sets it to its own sparse checkout of
  upstream.
- **Video off a real Microduck** (`--camera-url webrtc://host:8443`, `quackd[microduck-camera]`).
  There is no camera method in `duck-ipc-proto`, no snapshot route in `mediad` and no camera
  subcommand in `robotctl`, so a picture means being a WebRTC peer. It runs on your machine and
  writes nothing to the robot — the alternative needs `mediad` stopped, because its `v4l2src`
  holds `/dev/video0`. Signalling is read off `mediad`'s own web client at the pin and tested
  through a fake socket; the H.264 and the ICE are not tested and have never met a duck.
- [docs/microduck-hardware-checklist.md](docs/microduck-hardware-checklist.md), an issue
  template, and `microduck-lookout` — a bring-up task whose allowlist moves no legs, which
  copes with having no camera and stops to say so when posture reads `unknown`. The checklist
  assumes the duck is borrowed: nothing in it installs anything or needs `sudo`.
- CI runs on Windows. `robotd` speaks over a unix socket, Windows cannot open one, and the test
  covering quackd's `ssh -L` answer only runs there — so it had never run anywhere.
- **Bring-up checklists for the XLeRobot and the AlohaMini**
  ([docs/xlerobot-hardware-checklist.md](docs/xlerobot-hardware-checklist.md),
  [docs/alohamini-hardware-checklist.md](docs/alohamini-hardware-checklist.md)). The two
  bodies here you can buy today were the two without one. They are not copies of each other:
  the cart's hazard is that its watchdog stops the wheels and leaves fourteen arm servos
  holding, so it stays on blocks until step 9; the AlohaMini's is the opposite, that its arms
  are limp until quackd's own host turns torque on, which makes upstream's stock host the
  safest place to learn the base and the lift first.
- **[docs/reading-robots.md](docs/reading-robots.md), the traps by pattern rather than by
  robot.** quackd drives eight bodies and has run on none, so everything it does came from
  reading upstream closely enough to be safe without executing it, and the same shapes kept
  recurring: a number that looks like a different number, a default pose that is not neutral,
  a stop that is not a stop, a partial message that means something else, a capability that is
  only a claim, a name that exists on the wrong class, a line somebody commented out. The next
  robot will not have the AlohaMini's bug; it will have one of the AlohaMini's shape.

### Changed

- **The ToddlerBot's manifest is mostly absences, and every one of them is upstream's.** There
  is no text to speech at this pin, so `say` does not exist. There is no get-up policy, so
  `stand_up` is not declared and a fall ends the run with a message that names no verb and
  asks for a human. Nothing reports a battery to Python, so a battery abort cannot fire. And
  the walk policy is an ONNX checkpoint from a wandb artifact that upstream neither publishes
  nor checks in, so on a bare install **there is no locomotion at all**: `move`, `go_to` and
  `approach_and` are not gated off, they do not exist, and `mobility` reads `none` until the
  daemon reports a checkpoint staged.
- **No raw joint verb on the humanoid.** Thirty unclamped radians from a language model, on a
  machine in multi-turn mode with no current limit and no position limit, is the exact failure
  this project exists to prevent. quackd offers named moves and the daemon owns every
  trajectory.
- **The XLeRobot's manifest says no to more than it says yes to, and each no is upstream's.**
  There is no speaker and no microphone in the bill of materials, so the `sound` intent is not
  declared and `say` does not exist here. Which head motor is yaw is stated nowhere upstream,
  so quackd never commands the head and `search_scan` turns the whole cart. The power station
  has no data link, so `battery_percent` is permanently `None`. There is no odometry, so
  `go_to` closes the loop on the camera alone. And a stock cart ships with every camera
  commented out of its config, so `observe`, `go_to`, `search_scan` and `approach_and` exist
  only once a camera has actually been seen on the wire.
- Arm positions on **both** new robots are **normalised −100..100, not degrees**, because their
  `use_degrees` defaults to False. That is a different contract from the SO-101 arm next door,
  which sets degrees: the same number means a different angle, so `move_joints` validates
  against `joint_norm` and never against `lerobot`'s `joint_deg`. Turn rate is converted on both
  too, because each wire is deg/s while quackd is rad/s, and a pass-through would be a 57× error
  on a robot heavy enough to hurt someone.
- `pyzmq` joins the `dev` extra, and is the extra for both new robots. CI installs only
  `dev`, and the fake-host tests are what the two `zmq` backends' 🧪 rest on, so a status claim
  CI could not check would not have been honest.
- **`quackd run` asks "Are you watching the robot right now?" once before a fall-blind robot
  walks.** The question comes at the start of the run, before any verb, when the task allows
  `move`, `go_to`, `search_scan` or `approach_and` on a robot that reports `fall_detection`
  false and has no `stand_up`, which today is `open_duck:bridge` alone, because the Microduck
  can get up and no other body reports the flag. The default answer is no, and no aborts the
  run with exit 1 before a leg moves, so a script that started the bridge walking without
  `--yes` in 0.6.0 now stops at the question until you add `--yes`. Over MCP nothing asks: the
  pilot sees `fall-blind=nothing-detects-falls` in `report_state` and every observation,
  `quackd doctor` prints the warning, and that is all it gets. This is the guard that stands in
  for the ones "It claimed guards it did not have" above says were never there
  ([docs/open-duck-hardware-checklist.md](docs/open-duck-hardware-checklist.md)).
- **`quackd serve-mcp` with no `.duck` loaded now runs on a default budget of 40 verb steps and
  five minutes, counted from when the server started.** In 0.6.0 that session had no `Budget`
  at all, so `quackd serve-mcp --robot open_duck:bridge` would have handed an MCP client
  unlimited and uncounted control of a physical biped. The numbers are the frontmatter
  defaults, `max_steps: 40` and `max_minutes: 5`, and every `robot_run_verb` and
  `robot_observe` counts, `stop` included, so from the 41st call or once five minutes have
  passed every verb answers `budget exhausted` until `robot_load_duckfile` starts the
  contract's own budget. The clock is wall time on `open_duck:bridge` and `microduck:jsonrpc`
  and the simulator's own clock on `sim2d`, and there is no flag to turn the budget off
  ([docs/mcp.md](docs/mcp.md)).
- **One Ctrl-C stops the robot, and a second one quits.** The first Ctrl-C, or `q`, cancels the
  verb that is running and sends `stop`, the fix described under "The operator's stop did not
  stop the duck" above. New here is the second: the kill switch hands `SIGINT` back before it
  fires, so another Ctrl-C is a plain `KeyboardInterrupt`, where 0.6.0 swallowed every Ctrl-C
  after the first for the rest of the run and left you holding a key on a robot you could not
  be sure had heard. The `kill switch: Ctrl-C` line now prints to stderr on every `quackd run`
  rather than only with `--verbose`, and the banner says `Ctrl-C or q stops the duck. Press it
  twice to quit at once.` A flock run keeps its old banner, and its kill-switch line is still
  `--verbose` only.
- **The bridge refuses to start when `--max-vx`, `--max-vy` or `--max-vyaw` is above upstream's
  own clamp, or `--head-safety` is outside (0, 1].** The three velocity flags, documented in
  [bridge/open_duck/README.md](bridge/open_duck/README.md), were never checked, so the number
  in the unit went straight into the clamp the bridge applies and into the limits it advertises
  in the hello, and a unit asking for more than the 0.15, 0.2 and 1.0 that upstream's own
  gamepad allows would have been honoured. Narrowing them is the obvious first power-on
  precaution, and widening them past the pad is not something quackd should do quietly on your
  behalf, so the bridge exits with the bound in the message rather than silently clamping.
  `--head-safety` is the fraction of upstream's head range quackd will use, not a multiplier on
  it, so 0 and anything above 1 are refused the same way.
- **The bridge's systemd unit has no start rate limit any more (`StartLimitIntervalSec=0`).**
  It was 3 starts in 120 s, and with `Restart=no` the only thing a burst limit could throttle
  is you editing a path and running `systemctl start` again, which is exactly what bring-up is.
  The fourth attempt failed with an error about none of the problems being debugged and needed
  `systemctl reset-failed`, which appeared nowhere in the docs.
- **camd captures at 5 fps and 256 px by default, from 1 fps and 512.** `go_to` and
  `search_scan` close a visual loop at 10 Hz, and holding one steering correction for a whole
  second gives a per-frame loop gain above 1, a weave that swings the target back out of frame.
  The smaller frame pays for the faster rate on a Pi Zero 2 W, and `quackd-duck-camd.service`
  now passes `--fps 5 --size 256` explicitly. A 0.6.0 unit left in place still passes `--fps 1`
  and nothing for `--size`, so it keeps the slow loop at the new size until you re-run
  `install.sh`.
- **mypy type-checks `bridge/` now, the code that actually runs on the robot.** `[tool.mypy]`
  had `packages = ["quackd"]`, so the daemons on the robot's side were the only Python in the
  repository nothing type-checked. It is `files = ["quackd", "bridge"]` now, because mypy takes
  packages or files and not both, and CI's bare `uv run mypy` enforces it. The two Open Duck
  files were clean when the scope widened, and the gate earned its keep at the merge that
  brought the three new robots in: the ToddlerBot daemon's `int(getattr(robot, "nu", ...))` was
  typed `Any | None` because `robot` is optional there, and it now falls back to the frame's
  own width instead of crashing on a body nobody passed.
- **Nine of ten upstream unknowns were closed by reading, not guessing** — the import form the
  shim depends on, that `get_last_command` runs at 50 Hz and before the pause check, that `B`
  is the sound button, that the antennas are trigger-driven and unclamped, that the head slots
  are written unconditionally with no mode button, that the walk loop opens no camera, and that
  the IMU in use is `raw_imu.Imu` (a dict of gyro and accelero) rather than `imu.Imu` (a
  quaternion). The four head floats turn out to be **offsets** added to the walk policy's own
  head targets, not absolute joint angles. Fall detection was deliberately left unimplemented:
  which axis reads gravity depends on an axis remap, a config flag and a tare offset, and a
  fall detector that is wrong fails as a confident "not fallen".

### Fixed

- **The ToddlerBot's `search_scan` sweeps its head rather than turning its body.** `scan_mode`
  turns any robot with mobility and the twist intent, which is right for a duck and wrong for
  a humanoid with no get-up policy: with a walk checkpoint staged the shared verb would have
  pirouetted 3 kg of fall-prone robot to look for a ball. quackd supplies its own for this
  body, and it waits for the neck to arrive before taking the frame, because the daemon rate
  limits every joint and the shared sweep looks after a tenth of a second.
- **The transport keeps the link alive, so a long verb is not cancelled by its own deadman.**
  The daemon's deadman fires after half a second of silence and `stand` takes three, and the
  executor sends one command and then only polls while it waits. quackd's own `Heartbeat`
  cannot be that signal, because its period is a run setting rather than the manifest's and
  defaults to the same half second. The ToddlerBot transport now sends `bot.keepalive` on its
  own timer, and reading state or a frame deliberately does not count as being alive.
- **Every ToddlerBot disconnect used to stall for the full request timeout.** `close()`
  cancelled the read loop and then asked for a final stop, which waits on a future only that
  read loop could resolve.
- **A walk checkpoint that cannot move the robot is no longer offered as locomotion.** An
  envelope of zero on every axis clamps every velocity to nothing, so `move`, `go_to` and
  `approach_and` would have accepted every command and moved nothing.
- **The mocks and the simulators stopped reporting a pose their robots do not have.** Neither
  ZeroMQ wire carries a position, so the real backends report None and the offline doubles
  were dead-reckoning one. A double that is easier than the robot is a task that passes here
  and fails there.
- **The ToddlerBot daemon stopped claiming four things it could not do.** An audit of the
  three new adapters against their own plan found the same shape of bug three times, and it
  is the shape this project exists to prevent: a capability flag the operator sets, a
  manifest that promises verbs because of it, and a daemon with no implementation behind it.
  `--camera` declared `observe`, `search_scan`, `go_to` and `approach_and` while the frame
  handler read an attribute that was never defined, so every frame came back empty and
  `toddlerbot-lookout`, the one task shipped for the first hardware day, could not have run.
  `--walk` declared locomotion and returned `accepted: True` for every command while the
  policy attribute it consulted was never assigned, so the robot would have stood still and
  reported success. And `perform` refused every motion because the keyframe library was
  initialised empty and never filled. A later pass found a fourth of the same shape: `grip`
  answered accepted and commanded nothing at all, on a capability read from the command line
  rather than from the body. All four are now real, and **the handshake reports what actually
  loaded rather than what was asked for**: a camera that will not open means the camera verbs
  never appear, a walk checkpoint is a file you supply rather than a claim you make, and the
  gripper capability follows the motors.
- **`policy.step_target()` never existed upstream.** It was quackd's invention, which is the
  exact failure ADR-0022 is written to prevent. The real interface takes the whole
  observation and the sim and answers with a pair, and it is now cited at a pinned line
  along with sixteen other names the daemon needed and did not have: that motions carry a
  per-variant suffix, that upstream ships no loader at all, that `cartwheel` cannot be
  replayed because its file holds no action array, that `walk_zmp` is a lookup table rather
  than a motion, and that `Camera.get_jpeg` hands RGB to an encoder that wants BGR and so
  returns a picture with red and blue swapped.
- **The walk envelope comes from the checkpoint now.** `command_range` is read at connect off
  the policy that is actually loaded, rather than hardcoded from a gin file, so a robot whose
  gait was trained tighter than quackd's caps gets the tighter number. It can only ever
  narrow: a checkpoint trained wider does not get to widen `limits`.
- **A daemon fault no longer looks like a healthy robot.** A raising tick used to kill the
  control thread while the socket went on answering `ok`. It is now caught: the deadman is
  forced, `bot.health` reports the fault so quackd's heartbeat trips, and a bus that never
  comes back settles and stops rather than failing fifty times a second forever. The
  `sys.excepthook` and `threading.excepthook` that Part C of the plan asked for are installed
  too, because upstream's C level `atexit` disables torque on any interpreter exit and would
  otherwise drop a standing robot before Python got a say.
- **The ToddlerBot daemon moved off port 9872 to 9873.** The Open Duck Mini already had it:
  9871 for its bridge and 9872 for its camera daemon, and `SECURITY.md` tells people to
  tunnel that pair. The comment justifying the old choice named only the bridge. Its token is
  also compared with `hmac.compare_digest` now, as the Open Duck's always was, rather than a
  plain `!=` that returns as soon as two bytes differ.
- **Two simulator rows earned the tick they were claiming.** `alohamini:sim2d` and
  `toddlerbot:sim2d` were marked ✅ while their own text admitted no seeded sweep, on a page
  where ✅ means exactly that. Both now run their lookout task on ten of ten seeds in CI, with
  the ground truth checked: the AlohaMini never moves a wheel, an arm or the lift, and the
  ToddlerBot never takes a step or turns its body. The `alohamini:zmq` row was also sitting
  under the ToddlerBot's heading rather than its own robot's.
- **`quackd[alohamini]` was never locked.** The extra shipped in `pyproject.toml` and never
  reached `uv.lock`, so `uv sync --locked` refused it. `NOTICE` also credited every other
  upstream and none of the three new ones, including the fact that ToddlerBot's design files
  are non-commercially licensed and quackd therefore distributes none of them.
- **The five-to-eight sweep reached the places the tests do not police.** `test_docs.py`
  checks three exact phrases, so everything phrased differently had gone stale: `SECURITY.md`
  counted five bodies and scoped on-robot code to the Open Duck's two daemons, `docs/safety.md`
  had five rows in the table that answers "what stops this body when quackd goes quiet",
  `docs/faq.md` listed five adapters, and the README said five in four more places while
  saying eight in a fifth. The architecture pages also still said quackd hosts a control loop
  on one body when it now does on two, and in very different ways.
- **The duck could not be started at all.** The shipped `ExecStart` exits 2 before binding a
  socket, because `--script-arg --onnx_model_path` makes argparse refuse a value beginning with
  a dash — and it was the only `serve --script` invocation shipped anywhere, so it was the one
  an owner would copy. `WorkingDirectory` was one level above the data: upstream opens
  `./polynomial_coefficients.pkl` and `../mini_bdx_runtime/assets/` relative to the working
  directory, and the first is read inside `RLWalk.__init__` *after* the servo bus is powered,
  so the wrong directory is a traceback over fourteen energised joints. A pre-flight now
  refuses before the socket and before the servos. And no configuration produced both frames
  and the verbs that use them: the camera capability came from `expression_features.camera`,
  but that flag says who owns the *device*, and camd refused to start while it was true — so a
  correctly configured duck reported no camera and dropped `observe`, `go_to`, `search_scan`
  and `approach_and`, making both starter tasks and three checklist steps unreachable.
- **The operator's stop did not stop the duck.** An abort never reached the verb that was
  moving: `asyncio.wait_for` watches only the clock, so a kill switch, a Ctrl-C or a failed
  heartbeat set a flag nothing read until the verb returned on its own, while the verb's own 10
  Hz resend kept feeding the daemon's deadman. `stop` was then refused by the very gate that
  made it necessary, in both the executor and the MCP session. `duck.stop` lasted one tick and
  was undone by the next command. Nothing settled the duck on shutdown — the `finally` that
  looked like it did runs after the loop has exited, so its zeros had no reader — and
  `systemctl stop` killed the interpreter between two 20 ms ticks with the servos holding their
  last goal. Any client's disconnect zeroed a walking duck, including the `doctor` the
  checklist tells you to run from a second terminal. And `stop` reported a success it could not
  know, because the guard reads `stop_error` off the adapter and no adapter forwarded it.
- **It claimed guards it did not have.** The task file told the pilot every moving verb would
  refuse if it fell; nothing detects a fall on this backend, so none ever did, and an accepted
  `move` read to the model as evidence it was upright. A duck with `start_paused` could never
  walk and was misdiagnosed as a starved Pi. A wedged control loop reported itself healthy at
  50 Hz forever. A failed state read was dressed up as a healthy duck, with a fabricated pose
  for a robot that has no odometry. And the token was unreadable by the service user, so the
  bridge ran with authentication silently off while four places in the docs promised otherwise.
- **The camera was not safe to steer on.** camd served a frozen frame forever once capture
  stopped; its 1 fps default gives a divergent per-frame loop gain against a 10 Hz visual loop;
  `doctor` could not probe it at all; `go_to`'s command cadence was frame-fetch-bound against a
  300 ms deadman; and every distance was wrong, because the detector assumes the simulator's
  90° field of view where a Pi Camera Module 2 is about 62 — 0.23 m against 0.38 m for the same
  ball, enough for `go_to` to announce arrival outside the task's own success criterion.
  `--no-swap-rb`, offered in the README as the cure for wrong colours, inverts a correct image
  and relabels an orange ball as a person.
- **`express` on an Open Duck was a guaranteed no-op, and `droop` moved nothing even when it
  played.** `duck.antennas` does not refresh the command timestamp and every verb is its own
  tool call with an LLM turn between, so the command was always stale by the time a gesture
  arrived and the deadman rested the antennas before it played, while `express` reported
  success. Two 9 g servos on a GPIO pin are not motion, so a gesture now plays through a stale
  command for `GESTURE_S` (1.0 s) and then rests on its own, and `duck.stop` still rests it at
  once. `droop` sent 0.0, which upstream maps to the antennas' exact resting position, so it
  now sends `DROOP_POSITION`, -0.6 on upstream's -1..1 scale, a value no gamepad trigger can
  produce and a place nobody has watched these two servos go on a real duck, which is why it
  stops short of -1.
- **A second connection could drive the duck with no handshake at all.** The bridge kept its
  `greeted` flag on the core rather than on the connection, so on a bridge with no token, which
  the token bug above made every duck 0.6.0's `install.sh` set up, once any client had said
  `duck.hello` another socket could send `duck.command` straight away and skip the protocol and
  version checks on a socket that walks a robot. `authed` is per connection now, and anything
  but `duck.hello` on a fresh connection is refused with `say duck.hello first` whether or not
  a token is set.
- **camd served its last frame forever once capture stopped.** The handler read the capture
  timestamp and threw it away, so after one good frame the only 503 was unreachable: a ribbon
  working loose on a walking duck left `/snapshot.jpg` answering 200 with the same JPEG,
  `observe` reporting a confident detection and `go_to` steering on a photograph. Every
  snapshot now carries an `X-Frame-Age` header, and one older than four capture periods, never
  less than 1.5 s, answers 503 with the reason in the body (`/healthz` reports the threshold as
  `stale_after_s`). On the laptop `get_frame` reads the header, returns no frame instead of
  raising and keeps the reason where `doctor` can see it, treats a stamped frame over 2 s old
  as stale whatever the server's own threshold was (a server that does not stamp its frames is
  not checked), and gives up on a fetch after 1 s rather than 3, because `go_to` sends its next
  command only when the fetch returns and the deadman is 300 ms.
- **camd refused to start when `duck_config.json` had `expression_features.camera` true.** That
  flag says who owns the device, and camd exited 2 to avoid fighting the runtime for it, while
  the 0.6.0 bridge took its camera capability from the same flag, so the one setting under
  which the bridge advertised a camera was the one under which nothing served frames. Reading
  upstream at the pin, the walk loop the bridge runs opens no camera at all, so the collision
  could not happen in that process. camd now logs a warning and starts, and if you do run one
  of upstream's own camera scripts alongside it the contention shows up as failing captures on
  `/healthz` and expiring snapshots rather than a frozen frame, though setting the flag false
  is still the tidier setup.
- **Every distance on a real camera was wrong, and nothing let you correct it.** The detector
  assumed the simulator's 90 degree field of view where a Pi Camera Module 2 is about 62, so on
  hardware distances came out about 40 percent short, and [docs/faq.md](docs/faq.md) told you
  to set `fov_deg=62` in code. `quackd run` now takes `--fov-deg`, a manifest can carry
  `camera_fov_deg` under `limits` ([docs/manifest-spec.md](docs/manifest-spec.md)), and the
  flag wins over the key. Until one of them is set, every detection on a real backend ends in
  `(uncalibrated: distance is a rough guess)` and a warning names the flag, while `sim2d` and
  `mock` stay calibrated because their camera is the one the geometry assumes.
- **The API version quackd was written against had moved on.** `upstream_api.py` was the one
  adapter ADR-0022 let cite `main` instead of a commit hash, and in the week after it was
  read upstream went from `API_VERSION` 16 to 23. The handshake refuses on mismatch rather
  than guessing — correct behaviour, and it meant the first real Microduck anyone connected
  to would have closed the socket before a single intent was sent. The file now carries `PIN`
  and `READ_ON` like the other four, every ref links to a line at that hash, and a test keeps
  `/blob/main/` out. Re-reading all of them found the rest of the drift is small and additive:
  `Skill` is a free string now (a robot's real list arrives in `robot.subscribe`'s answer),
  and `RobotState.theremin`, `RobotState.chorale` and `HealthResult.cpu_temp_c` are new.
- **`robot.subscribe` was never sent, so nothing was ever known about the robot.** It lived
  in the `subscribe()` generator, which nothing in the CLI, the agent loop, the MCP server or
  the executor iterates, and upstream does not push state until asked. Every fact derived from
  the state frame was therefore empty for the life of a session — and empty read as safe:
  `fallen` was `False` because nobody was looking, so the precondition layer `docs/safety.md`
  advertises was inert on the one backend where a fall is a real robot on a real floor.
  `connect()` now subscribes, frames carry an arrival time and stop being believed when they
  stop arriving, and a duck nobody is watching reads as `unknown` rather than as standing.
- **`sit` and `stand` could do the opposite of what they said.** Both send upstream's single
  `sit_toggle`, and posture was the only thing telling them apart, so with posture permanently
  unknown `stand` would sit a standing duck down and report success. They refuse rather than
  fire a toggle nobody can aim. `stand_up` no longer reports "upright" when nothing reports
  falls.
- **One dropped camera frame ended the run.** `get_frame` raised beneath a comment promising
  it would not, and `AgentLoop._observe` calls it every step and catches nothing. Frames are
  now pulled on a timer and served from memory, `get_frame` never raises, and `camera_health()`
  carries the failure.
- **`doctor` accepted `--camera-url` and never fetched a frame**, so a wrong snapshot URL
  passed preflight and failed at the first `observe`. It now fetches one and prints its size.
- **The manifest claimed a camera on every backend.** Upstream serves no frames over
  `robotd`'s socket, so on a real duck `--camera-url` is the whole camera; `observe`, `go_to`,
  `search_scan` and `approach_and` were advertised while only able to answer "this transport
  has no camera". They are absent unless something is serving frames.
- **The heartbeat logged a stop it had not delivered.** `stop()` swallowed every error. It
  still never raises — it is called from the paths that run because the socket died — but it
  records why it failed and says so, and the heartbeat no longer asserts the outcome.
- An unknown sound tag became a chirp silently; JSON-RPC errors lost their code, so `BUSY` and
  `PERMISSION_DENIED` were the same thing to a caller.
- **Loading a second `.duck` over MCP refunded the budget.** `robot_load_duckfile` is a tool
  the model itself holds, and adopting a contract built a fresh `Budget` and cleared the
  consecutive-failure tallies, so a pilot that had spent its steps or been refused a verb
  could load a wider duck and start counting from zero. The limits still become the new
  contract's; the steps, the llm calls, the clock and the failure counts now stay the
  session's, and the tool's reply says what carried over.
- **`quackd doctor` and `quackd validate` crashed on a Windows pipe.** Python uses the ANSI
  codepage when stdout is not a console there, and quackd prints ✓, 🦆 and the status emoji in
  `doctor`, so on cp1252 the first two commands
  [docs/microduck-hardware-checklist.md](docs/microduck-hardware-checklist.md) puts in front of
  a Windows user died with `UnicodeEncodeError`, and so did the last step of CI's own Windows
  job. Both streams now replace what the codepage cannot carry, because a lost glyph costs a
  character and the raise cost the command.

### Known limitations

- **Nothing has run on hardware, on any of the eight adapters.** `microduck:jsonrpc`,
  `open_duck:bridge`, `reachy_mini:sdk`, `lerobot:real`, `rosbridge:ws`, `xlerobot:zmq`,
  `alohamini:zmq` and `toddlerbot:bridge` spell every upstream name from upstream source at a
  pinned commit and have only ever talked to fakes, the daemons quackd ships have only ever run
  with `--fake` over loopback or, for the ToddlerBot's, against upstream's MuJoCo body in a
  nightly job, and `microduck:websocket` is still a stub. If you have a body, the first thing
  to point at it is the task that moves nothing: `open-duck-lookout` with the feet off the
  ground until step 10 of
  [docs/open-duck-hardware-checklist.md](docs/open-duck-hardware-checklist.md),
  `microduck-lookout` on a duck you are probably borrowing with someone holding the gamepad
  ([docs/microduck-hardware-checklist.md](docs/microduck-hardware-checklist.md), feet off until
  step 9), `xlerobot-lookout` with the wheels on blocks until step 9, `alohamini-lookout` on
  upstream's stock host with the arms limp, before quackd's wrapper ever turns torque on, and
  `toddlerbot-lookout` on the safety stand with the feet off until step 13. The Reachy Mini,
  the LeRobot arm and the rosbridge base have no lookout task and no checklist, and the base
  has no verified deadman, so it goes on blocks first.
- **An Open Duck set up by 0.6.0 needs `bridge/open_duck/install.sh` run again on the robot
  before the new bridge will start.** 0.6.0's installer wrote the token `0600 root:root` inside
  a `0700` directory while the unit ran as `pi`, and the new daemon refuses to start on a token
  file it cannot read rather than run with authentication silently off, which is what the old
  one did. Nothing is lost by re-running it: the 0.6.0 unit could never start the bridge
  anyway, because argparse exits 2 on `--script-arg --onnx_model_path` before a socket is
  bound. The new `install.sh` keeps an existing token, makes it group readable by the service
  user and checks that it is, so the `--token` or `QUACKD_DUCK_TOKEN` your laptop already has
  stays valid.
- **Update the laptop and the robot together, because the handshake cannot tell 0.6.0 from
  0.7.0.** `PROTOCOL_VERSION` is still 1 on both ends, so a 0.6.0 laptop pairs with an updated
  bridge without a word and then sends every `duck.command` without the `epoch` the bridge now
  uses to tell a deliberate command from one that was already in flight when a stop landed. A
  client that sends none is held to the blunt window instead: for `--deadman-ms` (300 by
  default) after every stop its commands are silently dropped, and since `_turn` ends every
  `search_scan` step with a stop, the opening commands of the next step (up to three at 10 Hz)
  are swallowed and the duck under-rotates the scan. The other way round is quieter and no
  better: a 0.7.0 laptop drives a 0.6.0 bridge, which ignores `epoch`, but that bridge has none
  of the fixes above.
- **`--fov-deg` is a `run` option only, and no shipped manifest sets `camera_fov_deg`.**
  `record` and `doctor` do not take the flag and `serve-mcp` reads only the manifest key, so an
  MCP session on hardware carries the uncalibrated label with no way to clear it short of
  editing the adapter's manifest in source. The label is text the pilot reads, not a gate:
  nothing in the verbs checks `calibrated`, so an uncalibrated `go_to` still drives on the
  number.
- **`quackd[microduck-camera]` is a heavy extra, and the default install is unchanged.** It is
  `aiortc`, `av` and `websockets`, and `aiortc` brings `aioice`, `pylibsrtp`, `pyee`,
  `google-crc32c`, `cryptography` and `pyopenssl` with it, while `av` carries FFmpeg in a wheel
  of 18 to 39 MB depending on the platform. Nothing imports any of it unless `--camera-url`
  starts with `webrtc://`, and a missing extra is one error naming the `pip install` and the
  HTTP snapshot alternative that needs none. Nobody who is not pointing quackd at a real
  Microduck needs it, and the H.264 and the ICE inside it have never met a duck.

## [0.6.0] — 2026-09-04

A run stops starting from nothing. Every release so far built a pilot with no past: the
transcript recorded each prompt, tool call and frame, and the next run never read a line of
it, so a duck that had found the ball behind the sofa three times searched the whole room a
fourth time. Now each robot keeps a small file of notes the pilot chose to save and one
line per earlier run, and the newest of both are in the prompt before the first observation.
This is also the first release built on other people's pull requests: memory (#5) and the
`max_minutes` fix (#3) are both theirs. Design: `docs/adr/0025-memory-between-runs.md`,
with the release's own notes in [docs/design/memory.md](docs/design/memory.md).

Still nothing has run on a robot of any kind. What memory adds is tested end to end offline,
and no cloud model has ever written a note.

### Added

- **Memory between runs** (`quackd/memory.py`, [docs/memory.md](docs/memory.md)). Every
  run used to start from nothing. Now each robot, keyed `adapter:backend`, has a JSONL
  file under `~/.quackd/memory/` that holds the notes the pilot saved with the new
  `remember` tool and an episode line quackd writes at the end of every non-dry run
  (outcome, reason, the last few verb results). The newest of both are rendered into the
  system prompt at the next run. `remember` costs an LLM call but no step, and a repeated
  sentence refreshes the old note. `quackd run --no-memory` / `--memory-dir`,
  `quackd memory show|add|clear`, and over MCP `robot_recall` / `robot_remember` (eight
  tools now). A simulated body never inherits a real one's notes. Thanks to
  [@Bayway](https://github.com/Bayway) (#5), whose design and implementation this is.
- **The solo starter ducks ask for a note.** `find-and-kick`, `fetch`, `follow-me`,
  `patrol-and-quack`, `open-duck-scout`, `open-duck-lookout` and `reachy-spotter` carry
  `remember` in their last strategy step and a *Memory* section saying what is worth
  keeping, and `--goal` runs get the same line. A prompt-level hint alone was ignored by a
  14B local model; the strategy step is followed. The v0 duck goldens were regenerated
  for this. `hello-world` and the flock ducks are unchanged.
- **A test that the PyPI project page's links resolve** (`tests/test_pypi_readme.py`),
  because the rewrite below is invisible when it breaks: nothing in a normal run reads the
  built metadata, and the only symptom is dead links on a page the maintainer rarely opens.

### Changed

- CI runs on `actions/checkout@v7` and `astral-sh/setup-uv@v7`. `checkout@v4` targets
  Node 20, which GitHub deprecated and now force-runs on Node 24. Thanks to Dependabot
  (#1, #2).

### Fixed

- **`max_minutes` could be beaten by a slow provider.** The time budget was checked in
  `note_llm_call()`, *before* `provider.step()`, and nothing looked at the clock again
  before the answer was processed, so a provider that replied after the deadline still had
  its `declare_success` honoured and the run recorded a success it had no right to. The
  loop now re-checks the clock the moment a turn comes back, and a late declaration ends
  the run as `budget`. Thanks to [@r0jin](https://github.com/r0jin) (#3).
- **Every relative link in the README 404'd on the PyPI project page.** `README.md` is the
  long description, and its 60 relative links are correct on GitHub, where a relative link
  follows the branch you are reading, and meaningless anywhere else. A hatchling metadata
  hook (`hatch_build.py`) absolutises them at build time, in both syntaxes this README
  uses: 56 Markdown links and four raw `<a href>` in the centred HTML blocks. The first cut
  of the hook handled only Markdown, so the test now checks both and would have caught it.
  The repository's own README is unchanged, images were already absolute, and in-page
  anchors are left alone.
- **A hand-edited memory file could take the whole command down.** The file is documented
  as one you may edit, and a line that is not JSON is skipped. A line that *was* JSON but
  not an object (`"a note"`, `17`, `[]`) raised `AttributeError` out of every reader,
  because only `JSONDecodeError` was caught. Now every such line is skipped, as promised.
- **`--dry-run` wrote permanent notes.** The episode at the end of a run was guarded and
  the `remember` tool was not, so a run that sent nothing to the robot could still leave a
  permanent conclusion drawn from verb results the dry run itself invented. It now refuses
  and says so, like every other intent a dry run declines to send.
- **A refreshed note sorted as the oldest.** Repeating a sentence refreshes its timestamp
  and used to leave it where it was in the file, and both the prompt's "newest notes" window
  and the 400-entry cap read file order. So the note a model had just repeated was the first
  one dropped. A refresh now moves the note to the newest position.
- **`quackd memory show --raw` did not print the file as is.** It went through Rich, which
  ate anything in square brackets: a note reading `the ball is [bold]behind[/bold] the sofa`
  printed as `the ball is behind the sofa`. A note is text a model wrote, so it can contain
  anything.
- Tests set `QUACKD_MEMORY_DIR` to a temporary directory, so a test run no longer writes
  the developer's own `~/.quackd/memory`.
- `quackd memory show|add|clear --robot <bad spec>` printed a Python traceback. Every other
  command taking `--robot` answers in one line, and now these do too.
- With `--no-memory` the MCP server still told the pilot to call `robot_recall` early, a
  tool that would answer "memory is off". Those two sentences are now omitted.
- The prompt told the model `remember` "is free". It costs an LLM call, which is a budget it
  shares with every other turn, and the ADR and docs both said so.
- **Claims that had gone stale before this release, found while auditing it.**
  `docs/architecture.md` still described the `duck_*` MCP aliases 0.5 deleted, and had not
  been updated for memory at all (no `memory` command, no `remember` tool, no `memory`
  transcript event). The README's architecture diagram listed four adapters and omitted
  `open_duck` and its `bridge` backend, which the adapter-count guard could not see because
  it reads the phrase "N adapters" and not a list. The README, `docs/architecture.md` and
  the FAQ each said one quackd daemon runs on a robot, while `bridge/open_duck/` has shipped
  two since 0.5, and `docs/architecture.md` contradicted itself about it. `docs/duck-spec.md`
  called `max_minutes` a cap without saying a verb already running is not interrupted.
  `_deprecated()` in `quackd/cli.py` was dead from the 0.5 `--transport` removal. `quackd
  --help` still introduced the tool as a way to "pilot a Microduck", five adapters later.
  `_pick_default` justified its rule with the `duck_*` aliases. `tests/test_goldens.py`
  dated its goldens to 0.3.0 after four of the six duck hashes were regenerated here, and
  ADR-0025 filed learned verbs under ADR-0019, which is the `.duck` spec v1.
- **The README said no live local server had been run.** One now has, by this release's
  contributor, which is the first local-model evidence this project has had. The sentence
  says whose machine it was and that no transcript from it is in the repository.
- `test_cap_drops_old_episodes_before_notes` wrote 405 entries one at a time, each one
  re-reading and rewriting the whole file. It took 14.6 s here, on a matrix that runs it
  four times, to prove a property a cap of 12 proves in 0.16 s. It now also asserts *which*
  entries survive, which is what the test was named for.
- Guards for the class of mistake this release's own review kept finding. A living document
  *or a Python string a user reads* may not claim a number of `robot_*` tools the server
  disagrees with, nor still describe the `duck_*` aliases 0.5 deleted: 0.5's guard proved
  nothing still *offers* a removed thing and could not see one still being *described*, and
  the stale count turned out to be in a `--robots` help text and two docstrings as well as
  two README sentences. The key the CLI computes for a robot's memory file must equal the
  key the MCP server computes, for all five adapters and all fourteen backends, because
  "a note saved from Claude Desktop is read by the next `quackd run`" is otherwise an
  intention. And the built wheel's long description must contain no relative links.
- The `quackd memory` command group, and the memory flags on `run`, now have tests. They
  shipped with none, which is how two of the three subcommands were wrong.
- One assertion in the new memory tests was `A or B` where `A` was never true (the sound in
  the highlight is the robot's own tone, not the text), so it checked almost nothing. It is
  one assertion now.

### Known limitations

- **The scripted pilot never calls `remember`**, so `--provider fake` accumulates run
  outcomes and never writes a note. Notes have been exercised by one local model
  (Qwen 2.5 Coder 14B through LM Studio, `find-and-kick`, seeds 5 and 6) on one machine,
  and by no cloud model at all.
- **`--no-memory` does not silence the ducks.** The seven starter tasks above ask for a
  `remember` inside their strategy, and that text is in the prompt whether or not memory is
  on. A pilot that follows it gets a clear refusal that costs an LLM call and no step.
- Memory is a file, not a memory system: newest wins, there is no embedding and no search,
  nothing is shared between bodies, and the executor never reads it. A note is text a model
  wrote.

## [0.5.0] — 2026-09-03

The first robot you can actually build. Every hardware backend before this one targeted a
robot you could not buy or had not assembled: the Microduck ships around Christmas 2026, and
the Reachy, LeRobot and rosbridge backends have only ever talked to fakes. The Open Duck
Mini v2 is open hardware people are printing at home today, so for the first time a stranger
can follow these instructions all the way to a walking robot. That also makes this the first
release where quackd ships code that runs **on** a robot. Design: `docs/adr/0024-open-duck-mini.md`.

Still nothing has run on a duck. What is new is that everything except the duck is tested.

### Added

- **The Open Duck Mini v2 adapter** (`--robot open_duck:sim2d`, `open_duck:mock`,
  `open_duck:bridge`): the
  first robot quackd supports that anyone can build today. It is an open hardware 3D
  printed biped that walks on its own 50 Hz ONNX policy on a Raspberry Pi Zero 2 W. Its
  manifest is a strict subset and says so: this robot has no beak, no gripper, no kick
  policy, no sit policy and no get-up-after-fall policy, so `kick`, `grab`, `sit`, `stand`
  and `stand_up` are never declared and therefore do not exist for it anywhere. A duck
  built without a camera or a speaker loses exactly the verbs that need them. Velocities
  are clamped to the ranges read from the robot's own runtime (0.15 m/s forward, 0.2 m/s
  sideways, 1.0 rad/s turning), and a fallen duck refuses to move with a message saying a
  human must stand it up, because nothing quackd can call will.
- **A bridge daemon that runs on the robot** (`bridge/open_duck/`), which is a first for
  quackd: every other adapter talks to someone else's daemon, and this robot has none. It
  does not reimplement the 50 Hz control loop, it *is* that loop, with the class upstream
  imports to read a gamepad rebound to read a socket instead. One process, so the servo bus
  keeps one owner, and nothing of upstream's is copied. Going limp is unreachable rather
  than forbidden: the only channel from the network to the body is seven floats and a few
  buttons. The deadman is quackd's own, it runs on the robot, and it is evaluated by the
  control loop rather than a timer, so a server thread that is starved, wedged or dead still
  stops the duck. Standard library plus numpy, so it installs on a 512 MB Pi, and
  `--fake` runs the whole protocol on a laptop with no robot at all.
- **A camera server for the duck's Pi** (`bridge/open_duck/quackd_duck_camd.py`), in its
  own process because encoding a JPEG inside a 20 ms control tick is not affordable on a Pi
  Zero 2 W. It captures on a timer so a slow client cannot stall it, serves the newest frame
  over HTTP, and has no control path at all: it reads a camera and answers GET. Without it
  the bridge advertises no camera and the verbs that need one do not exist rather than exist
  and fail. `--fake` paints a duck's eye view, so the whole chain runs with no hardware.
- **Two starter tasks**, `open-duck-scout` (find the ball, walk up, report, 10 of 10 seeds)
  and `open-duck-lookout`, whose allowlist moves no legs at all and which exists to be the
  first thing anyone points at a physical duck.
- ADR-0024, `docs/adapters/open_duck.md`, and a hardware checklist and issue template for
  the first person to run this on a duck they built.
- **`--camera-url`** on `run`, `serve-mcp` and `doctor`, for a robot whose camera is an HTTP
  snapshot rather than something the control socket can serve.
- **`--token` and `QUACKD_DUCK_TOKEN`** for a robot that wants authentication. The Open Duck
  bridge's own installer writes one, so until now a duck set up by the book refused every
  client and no document explained why.
- **`quackd doctor --robot X --address Y` connects.** Everything else in `doctor` is offline
  and reads the static manifest, which describes a fully built robot. This prints what your
  robot actually reported: its capabilities, which verbs it does and does not have, and
  whether its control loop is healthy. It is the only way to see that difference before a
  run does.

### Removed

- **`--transport X`**, the 0.4 alias of `--robot microduck:X`, along with `resolve_robot`'s
  transport branch and the warn-once machinery that existed only to support it. 0.4 said in
  ten places that it would go in 0.5.
- **The eight `duck_*` MCP tools**, 0.3 aliases pinned to the default robot. Omitting the
  `robot` argument to a `robot_*` tool does the same thing. `duck_get_frame` has no exact
  replacement by design: `robot_observe` does the same job but goes through the executor, so
  frames are now budgeted and logged like every other verb.
- Removing them broke the MCP system prompt, which named three of the removed tools and
  hardcoded "a small biped duck robot (25 cm, 800 g)" for every body. It now names the robot
  and takes its description from the manifest's own `blurb`, so a lone Open Duck introduces
  itself as the duck that cannot pick anything up and cannot get back up if it falls.

### Fixed

- **Perception was attached only for the simulator.** Every hardware backend with a camera
  ran blind: it fetched frames, detected nothing because nothing was detecting, and reported
  that it could not see. The detector now follows the camera rather than the backend, which
  also fixes `microduck:jsonrpc` and `rosbridge:ws`. Both entry points ask one function,
  `perception.detector_for`, and both ask it at *connect*: the first cut of this fix keyed
  `quackd run` on the camera and left `serve-mcp` keyed on the backend, so every hardware
  body over MCP still ran blind, and deciding from the static description would still have
  missed a `rosbridge:ws` base, which only reports its camera once it has connected.
- **A robot that reports fewer capabilities at connect than its description claims** used to
  crash the run. `validate` checks the static manifest, which describes a fully built robot,
  so a duck with no camera got past it and then raised a bare `VerbNotFound` when the agent
  loop built its tools. A verb the task *requires* now refuses in the validator's words, and
  one it merely *allows* is dropped with a line in the log, which is what a v1 task allowing
  more than it needs is for.
- `quackd run` now checks a `.duck` against its robot before connecting, the way
  `serve-mcp` always has. Pointing a task at a robot that lacks one of its verbs used to
  reach the agent loop and raise a bare `VerbNotFound` with the robot already connected and
  an empty run directory already written. It now refuses up front with the validator's own
  sentence and writes nothing.
- **Two commands still told users to pass `--transport`**, the flag this release removes: a
  `doctor` table title and the `TransportError` the WebSocket stub raises. The guard that
  swept the documentation for it could not see a Python string, and now reads
  `quackd/**/*.py` too. Six other user-visible strings were still dated "in 0.4", and
  `doctor` printed the extra as `quackd` because rich ate the `[lan]` as markup.
- **The PyPI summary and keywords never mentioned the Open Duck Mini**, the robot this
  release is named for, and no test had ever read `pyproject.toml`. One now does. The
  `Framework :: Robot Framework` classifier is also gone: that is the test-automation tool
  of the same name, not robotics, and it filed quackd under the wrong ecosystem.
- `quackd doctor` reported `?` for opencv and Pillow, which are not optional and were plainly
  installed. An import name is not a distribution name, so it now asks the installer which
  distribution provides the module before giving up.
- The Open Duck bring-up checklist keeps the feet off the ground through step 9 and puts
  them down at step 10. Three documents said step 8.
- `mypy` failed on Python 3.12 (the opencv stubs that resolve there type only the array
  overload of `cv2.inRange`, so the tuple bounds in `perception/color_blob.py` matched no
  variant). Bounds are now `uint8` arrays. OpenCV accepts both, so nothing about detection
  changes: the seeded goldens are byte-identical and all five sweeps still pass 10 of 10.
  This landed just after the v0.4.0 tag, so the tagged commit and the 0.4.0 files on PyPI
  still carry it. It is a type-check-only issue and does not affect the released package at
  runtime.

## [0.4.0] — 2026-09-02

From "a brain for the Microduck" to "a brain for any small robot". The thesis does not
change: the LLM picks verbs, the robot's own controllers move, quackd enforces the
contract. Four adapters (Microduck, Reachy Mini, a LeRobot arm, any base over rosbridge),
one `.duck` contract across bodies, a head and a duck completing one task together in the
simulator, and nothing claimed on hardware. Design: `docs/design/multi-robot.md`.

### Added

- **Robot adapters and manifests** (`quackd/adapters/`): every robot is an adapter that
  returns a `RobotManifest` from `connect()`, and the verb registry is built from that
  manifest rather than hardcoded. A verb that is not in the manifest does not exist. The
  Microduck is the first adapter and wraps the four existing transports with zero
  behaviour change; `manifest.schema.json` is generated and drift-tested. (ADR-0017)
- **Core verbs and aliases**: `observe`, `report_state`, `stop`, `say`, `move`, `go_to`,
  `search_scan` and `approach_and` exist on any robot that meets their requirements;
  `get_frame`, `walk_to` and `walk` are permanent aliases, listed once in
  `quackd/verbs/aliases.py`. `search_scan` sweeps the head on a robot that can only look.
  Preconditions are named in the manifest and supplied by the adapter; the executor spells
  none. (ADR-0018)
- **`.duck` v1**: `requires`, `robots`, `flock.roles` and `flock.frame_hints`; v0 files
  parse unchanged. `quackd validate --robot <adapter>:<backend>` checks a task against a
  robot's manifest with field-level errors such as `requires kick, but reachy-01
  (reachy-mini) does not provide it`. (ADR-0019)
- **`--robot <adapter>:<backend>`** on `run`, `validate`, `serve-mcp`, `doctor` and
  `list-verbs`; `--robots name=spec,...` on `run` and `validate`; `quackd list-adapters`;
  `doctor --robot` shows one manifest; a `.duck` may declare its default robot.
- Transcripts: `verb` events carry `canonical`; `run_start` and `summary.json` carry the
  robot's manifest and id. `duck_list_verbs` entries gain `canonical`, `aliases` and
  `core`; `duck_get_state` gains `robot`.
- Goldens recorded from 0.3.0 (`tests/golden/`) prove seeded worlds, the starter ducks and
  a `flock-kick` conversation are unchanged; CI runs both seeded sweeps at 10 of 10
  (`QUACKD_STRICT_SEEDS=1`).
- **Reachy Mini adapter** (`--robot reachy_mini:sim2d | mock | sdk`, extra `quackd[reachy]`
  for the SDK): a stationary head with a camera, a 180° neck, expressions and a speaker.
  Its manifest carries `observe`, `report_state`, `stop`, `say`, `search_scan` (a gaze
  sweep), `gaze`, `express`, `play_sound` and a confirm-gated `wake_up`; no locomotion
  verbs exist on it. `say(text)` is voiced as the closest expressive sound because the SDK
  has no text-to-speech; `stop` is `cancel_move` and `disable_motors` is never sent. Every
  SDK name is VERIFIED in `quackd/adapters/reachy_mini/upstream_api.py` against a pinned
  commit and the 1.10.0 wheel; the `sdk` backend has never been run on a robot.
  (ADR-0022, ADR-0023)
- **`StationaryHead`** in `sim2d`: a fixed camera on a wall with zero RNG draws, so every
  world without a head is byte-identical to 0.3; the recorder and the live window can
  focus a head camera.
- **`reachy-spotter` starter duck** (`duck: 1`, `robots: reachy_mini:sim2d`): find the
  ball with your gaze and say where it is; 10 of 10 seeds with the scripted pilot, judged
  by ground truth.
- **Heterogeneous flocks** (ADR-0020): members are adapters sharing one arena and one
  lockstep clock; bids carry a capability term so a robot bids only for a role its
  manifest can fill; one auction fills every role (most constrained first, lowest own
  distance, member-name tie-break, per-role hysteresis; the spotter is held for the run).
  With roles the kicker reports `kick_done` and the spotter judges from its own fresh
  frames (`VERDICT`); only `moved` is a success and the ground-truth veto stays on top.
  Frame hints (`HINT`, arena frame, sim only) choose the kicker's pre-turn; the
  frame-of-reference limitation is documented in `docs/flock.md`. `run --robots
  name=<adapter>:<backend>,...`.
- **`reachy-spots-duck-kicks` starter duck**: a Reachy Mini head spots the ball, a
  Microduck kicks it, the head judges the kick. 10 of 10 seeds with scripted pilots,
  every message in `flock.jsonl`, zero planner calls with the fake provider.
- **Multi-robot MCP**: `quackd serve-mcp --robots duck=microduck:sim2d,reachy=reachy_mini:mock`
  fronts a fleet with `robot_list`, `robot_list_verbs`, `robot_run_verb`, `robot_observe`,
  `robot_say` and `robot_load_duckfile`; every robot has its own executor, budget,
  heartbeat and contract, and `robot_load_duckfile` checks the contract's `requires`
  against that robot's manifest before adopting it. The eight `duck_*` tools stay as
  aliases of the default robot (deprecated, removed in 0.5). Simulated robots over MCP
  each get their own world; a shared arena over MCP is future work.
- **LAN discovery** (`quackd discover`, `quackd announce`, ADR-0021): zeroconf service
  `_quackd._tcp.local.` with an identity-only TXT record (manifest id, digest, adapter,
  body, verb count), every pair validated under 200 bytes before zeroconf sees it. Behind
  `quackd[lan]`, imported lazily, tested on fakes; exercised once for real between two
  processes on one machine, never between two machines.
- **MQTT flock bus** (`quackd.flock.mqtt_bus.MqttBus`, `run_flock(bus_factory=)`): the
  same two-method `Bus` protocol over a broker, `quackd/<flock_id>/ctl` at QoS 1 and
  `/hb` at QoS 0, never retained, the `FlockMessage` JSON as payload. Broker echo is
  dropped, the tap fires exactly once per message per node, remote messages are
  marshalled onto the event loop, and duplicates are tolerated by the coordinator's
  idempotent handlers. Library only: a flock across machines also needs a clock across
  machines, so there is no `--bus` flag. Tested on a fake broker; exercised once for real
  against a local `amqtt` broker with paho 2.1 (all eight kinds, one machine).
  `Subscription.drain()` is now an atomic `popleft` loop. `doctor` lists both LAN
  libraries.
- **LeRobot adapter** (`--robot lerobot:mock|real`, ADR-0022): an SO-101 class desktop arm
  with `move_joints`, `gripper`, `place` and, when a policy is available, `pick` as one
  skill intent that the arm's own learned policy executes. No locomotion, no voice, no
  gaze in its manifest. `real` sits behind `quackd[lerobot]` (Python 3.12 or newer, torch
  never imported on the default path), passes `calibrate=False`, refuses an uncalibrated
  arm, holds position on stop and never disables torque; every LeRobot name is pinned
  and line-linked in `quackd/adapters/lerobot/upstream_api.py`; never run on an arm.
- **rosbridge adapter** (`--robot rosbridge:mock|ws`): any wheeled base that takes a
  `geometry_msgs/msg/Twist` over `rosbridge_server`. The address carries the topics
  (`ws://host:9090?cmd_vel=/cmd_vel&odom=/odom&image=/camera/compressed`); with an image
  topic the base also gets `observe`, `go_to`, `search_scan` and `approach_and`. There is
  no deadman: quackd re-sends the Twist at 10 Hz and zeroes it on stop, and the manifest
  says so. `ws` sits behind `quackd[rosbridge]` (roslibpy 2.x); every roslibpy, rosbridge
  protocol and message name is pinned and line-linked; never run against a bridge.
- **Speed limits come from the manifest**: `move`, `go_to` and the turn used by
  `search_scan` clamp to `limits.max_vx/max_vy/max_wz` when a manifest names them; the
  Microduck's limits equal the old schema bounds, so its runs are unchanged.
- **Docs**: `docs/adapters.md` (write an adapter in a day), `docs/manifest-spec.md`,
  `docs/adapter-status.md` (every adapter's honesty table, the Microduck's rows moved
  there unchanged), `docs/lan.md`, one page per adapter under `docs/adapters/`, and
  ADRs 0017 to 0023. `docs/safety.md` says what stops each body; `docs/faq.md` answers
  "can it drive something that is not a duck".

### Changed

- `default_registry()` is the Microduck manifest's registry; its names are canonical
  (`move`, `go_to`, `observe`) and every entry point accepts the old spellings. The
  bundled starter ducks keep their 0.3 spellings and stay at `duck: 0`.
- The agent loop connects before writing `run_start`, because the vocabulary comes from
  the connected robot.
- `docs/transport-status.md` is a redirect to `docs/adapter-status.md`; the docs test
  that keeps the Microduck's upstream table in sync now reads the new page.
- **The README was rewritten for four bodies**: the tagline and intro name the other
  robots, a new "Any small robot" section puts all four side by side with what each gets
  and what has actually run, the verb table gains a row per body, both architecture
  diagrams show the adapter layer, and the status table states per feature what was
  exercised against its real target and what was not.
- Test suite: 360 tests collected, no network and no keys, with four seeded sweeps CI holds
  at 10 of 10 (`find-and-kick`, `flock-kick`, `reachy-spotter`, `reachy-spots-duck-kicks`).
- Eight starter `.duck` files ship, up from six.

### Deprecated

- `--transport X` is an alias of `--robot microduck:X` that prints one warning per
  process; it is removed in 0.5. The `quackd.transport` package is not deprecated: it is
  the Microduck backend layer.
- The eight `duck_*` MCP tools (`duck_list_verbs`, `duck_run_verb`, `duck_get_frame`,
  `duck_get_state`, `duck_set_velocity`, `duck_stop`, `duck_quack`, `duck_load_duckfile`)
  are aliases of the six `robot_*` tools on the default robot. Each carries a deprecation
  note in its description and all eight are removed in 0.5.

### Fixed

- A role auction is complete only when every role can be filled by a *different* member,
  so a single robot that satisfies both roles can no longer deadlock a heterogeneous
  flock.
- `Subscription.drain()` is an atomic `popleft` loop rather than copy-then-clear, so a
  producer on another thread (the MQTT bus, before a message reaches the event loop)
  cannot have its message cleared unseen.

### Known limitations

- **Nothing has run on hardware, on any of the four adapters.** `microduck:jsonrpc`,
  `reachy_mini:sdk`, `lerobot:real` and `rosbridge:ws` spell every upstream name from
  upstream source (the three new ones at pinned commits) and have only ever talked to
  fakes. `microduck:websocket` is a stub waiting on upstream.
- LAN discovery and the MQTT bus were each exercised once, on one machine: zeroconf
  between two processes, MQTT against a local `amqtt` broker. Neither has crossed to a
  second machine, and a flock across machines also needs a clock across machines, which
  does not exist.
- Flock mode stays simulator only, with two choreographies and exactly two roles.
- A manifest can be smaller than the robot: `lerobot:real` claims no camera and no `pick`
  until it connects, and `rosbridge:ws` has no camera verbs unless the address names an
  image topic.
- The MCP server speaks `stdio` only, so it is a local subprocess of Claude Code or
  Claude Desktop and cannot be reached from a phone. A network transport is roadmap, not
  shipped.

## [0.3.0] — 2026-08-31

Multiple simulated Microducks cooperate: split the search, hold an auction, the closest
one kicks. Everything is on the record.

### Added

- **Flock mode** (`flock:` block in the `.duck`, or `--flock N` on `run`/`record`): 2 to 4
  ducks share one arena and an in-process message bus. A deterministic Contract Net
  auction picks the kicker (bid = each duck's own camera distance estimate, 20 %
  hysteresis, 6 s claim lease, duck-id tie-break, one-claimant lock), heading sectors
  split the search, misses trigger a full-circle re-search and re-auction, and a sim-time
  watchdog drops silent ducks. Every message, bid, claim and role change lands in
  `flock.jsonl`; the outcome is judged from sim ground truth, not a model claim.
  Guide: `docs/flock.md`. (ADR-0015)
- **Multi-duck simulator**: `World(n_ducks=…)` with per-duck deadman, noise streams, kick
  counters, duck-duck collisions and the four Microduck colorways (Cream, Sky, Lavender,
  Graphite); per-duck cameras render teammates, and the detector gained four `duck`
  targets. Sim time is governed by a lockstep clock, so the world freezes while any pilot
  thinks and single-duck runs stay bit-identical per seed. (ADR-0016)
- The planner makes **at most one** LLM call per flock run (parameters validated and
  clamped, deterministic fallback); `--provider fake` computes the plan as a pure
  function. Per-duck LLM pilots are deliberately out of scope.
- Duck to duck separation is watched from world ground truth while a claim is live: the
  coordinator orders an intruding non-kicker to retreat, and the retreat still runs
  through that duck's own executor.
- Starter `ducks/flock-kick.duck`; `runs/<ts>-flock-…/` layout with per-duck transcripts;
  flock demo GIF in the README. Scripted 3-duck acceptance: 10 of 10 seeds.
- The flock shipped through an adversarial review (69 agents, 24 confirmed findings, all
  fixed before release): deadlock guards around the shared clock's tick hooks and around
  member connect failures, per-duck `max_minutes` enforcement, a heartbeat watchdog floor
  above the longest verb sleep, cooldown gating at bid time, per-field planner clamping,
  `--max-steps` honoured on flock runs, `flock.search.restart_s` honoured, and
  `one_claimant: false` rejected instead of silently ignored.

### Changed

- `.duck` spec v0 gains the optional `flock:` block (`docs/duck-spec.md`, `schema.json`
  regenerated). Files using it need quackd 0.3.0 or newer; older versions refuse them
  loudly. `quackd validate` reports flock size and rejects flock + `verbs.confirm`.
- `quackd doctor` notes flock status; `serve-mcp` refuses flock ducks with a clear
  message.

## [0.2.0] — 2026-08-29

Local and open-source LLMs can pilot the duck. No API key needed.

### Added

- **Local providers** `ollama`, `vllm`, `llamacpp`, `lmstudio` and `local --base-url …`
  for any OpenAI-compatible server: no key, model discovery from `/v1/models`,
  `tool_choice=auto` and no `parallel_tool_calls` field for picky servers
  (`QUACKD_TOOL_CHOICE` overrides), vision opt-in with `--vision`, and a JSON text
  fallback for models that cannot call tools natively (marked `text_fallback` in the
  transcript). `quackd doctor` probes the four default local addresses.
  Guide: `docs/local-llms.md`. (ADR-0014)
- `quackd run --goal "…"`: a plain-language goal instead of a `.duck` file (ad-hoc contract:
  every `safe` verb, default budgets, standard abort rules). The scripted `fake` pilot picks
  a strategy from the goal's keywords.
- `--base-url`, `--api-key`, `--vision/--no-vision`, and `--gif-size` on `run`/`record`.
- Logo (`docs/assets/logo.svg`, a Microduck-like biped in the Lavender colourway) and a
  social-preview card.

### Changed

- README rewritten for people who know nothing about robots or LLMs first, developers
  second: what it does today vs. where it is going, Mermaid architecture diagrams, usage,
  configuration, performance and limitations sections. Images use absolute URLs so the
  PyPI page renders them. Providers are named by company ("OpenAI"), not model family.
- The hero GIF is recorded at 320 px panes.

### Fixed

- Rich markup ate `quackd[extra]` in CLI error hints.
- mypy on Python 3.12 (numpy's PEP 695 stubs) in CI.

## [0.1.0] — 2026-08-28

First release: sim-first, honest about hardware.

### Added

- **`.duck` spec v0**: strict pydantic frontmatter, generated `schema.json`,
  `quackd validate` with fail-fast field-level errors; five starter ducks
  (`hello-world`, `find-and-kick`, `patrol-and-quack`, `follow-me`, `fetch`) bundled in the
  wheel and resolvable by name.
- **Verb registry**: built-ins mapping 1:1 to shipped robot behaviours (`walk`, `sit`,
  `stand`, `kick`, `grab`, `stand_up`, `stop`, `quack`, `gaze`, `get_frame`), composites
  (`search_scan`, `walk_to`, `approach_and`), and the reserved learned-verb interface.
- **Safety executor**: allowlist, confirm gates, budgets, dry-run, machine-enforced
  `abort_when` (battery, consecutive failures), heartbeat, kill switch (Windows-safe).
- **Agent loop** with one tool call per turn, `runs/<ts>/transcript.jsonl`, frames,
  `summary.json`, and `run.gif` on the simulator.
- **`sim2d`**: built-in 2D simulator (deterministic under `--seed`, deadman, kick cone,
  unreliable open-loop scoop), top-down + first-person duck-cam renders, GIF recorder,
  optional `--live` window.
- **Perception**: `ColorBlobDetector` (HSV, bearing + distance from apparent size) and a
  lazy `YoloDetector` extra.
- **Providers**: `anthropic` (adaptive thinking, refusal handling, thinking-block replay),
  `openai`, `grok` (xAI endpoint), `gemini`, and the scripted `fake`; all vendor SDKs are
  optional extras.
- **`quackd serve-mcp`**: the duck as MCP tools for Claude Code / Claude Desktop through
  the same executor; `docs/mcp.md` with verified client config; project `.mcp.json`.
- **Transports**: `sim2d` (default), `mock`, experimental `jsonrpc` for the real robot
  (verified `duck-ipc-proto` v16 vocabulary, fake-robotd tests), `websocket` stub.
- **`quackd doctor`**, `quackd list-verbs`, `quackd record`.
- Docs: architecture, duck spec, transport status, safety, learned verbs (v2), licenses,
  FAQ, MCP; 13 ADRs; LAUNCH.md; CONTRIBUTING.md; hero GIF (scripted pilot, labelled).

### Known limitations

- The hardware transport has never run on a Microduck (hardware ships Christmas 2026).
- The README hero is a scripted-pilot recording; a real-model recording needs an API key.
- Non-Anthropic default model IDs are unverified; override with `QUACKD_MODEL`.

[Unreleased]: https://github.com/rokbenko/quackd/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/rokbenko/quackd/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/rokbenko/quackd/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/rokbenko/quackd/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/rokbenko/quackd/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rokbenko/quackd/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rokbenko/quackd/releases/tag/v0.1.0
