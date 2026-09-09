# Reachy Mini

A stationary expressive head from Pollen Robotics: a camera, a six-degree-of-freedom neck,
two antennas, a speaker and a microphone. No legs. quackd drives it through the same
loop, executor and `.duck` contract as the Microduck; what changes is the manifest, and
therefore the verbs. Reachy Mini hardware exists today; the `sdk` backend has **never been
run against one by us**.

```bash
uvx quackd run reachy-spotter --provider fake                       # the duck's default: reachy_mini:sim2d
uvx quackd run reachy-spotter --provider fake --robot reachy_mini:mock
uvx quackd validate ducks/find-and-kick.duck --robot reachy_mini:mock   # exit 1: requires kick, but reachy-01 (reachy-mini) does not provide it
uv pip install "quackd[reachy]" && quackd run reachy-spotter --provider anthropic --robot reachy_mini:sdk --address reachy-mini.local:8000
```

To exercise the `sdk` backend without a robot, run upstream's daemon in simulation
(`reachy-mini-daemon --sim`, or `--mockup-sim` for no physics) and point `--address` at
it. quackd never spawns the daemon itself.

## Backends

| `--robot` | Status | What it is |
|---|---|---|
| `reachy_mini:sim2d` | ✅ | a `StationaryHead` in the cartoon world: a fixed camera on a wall, a 180° neck, expressions and speech logged, `reachy-spotter` 10 of 10 seeds |
| `reachy_mini:mock` | ✅ | scripted, for tests: records intents, serves a synthetic frame whose ball moves with the gaze |
| `reachy_mini:sdk` | 🧪 | the real robot through `reachy-mini` (extra `quackd[reachy]`); every SDK name VERIFIED against a pinned commit and the 1.10.0 wheel, unverified end to end |

## The manifest

```json
{
  "manifest": 1, "id": "reachy-01", "vendor": "pollen-robotics", "model": "reachy-mini",
  "embodiment": "stationary_head", "mobility": "none",
  "intents": ["gaze", "sound", "skill"], "sensors": ["camera"],
  "verbs": ["observe", "report_state", "stop", "say", "search_scan", "gaze", "play_sound", "wake_up", "express"],
  "preconditions": {"gaze": ["motors_enabled"], "express": ["motors_enabled"]},
  "safety_authority": {"native": "none", "deadman": false, "heartbeat_hz": 2.0},
  "frame": {"reference": "head", "note": "bearings are camera-relative; body bearing = gaze_yaw_deg + bearing_deg"},
  "limits": {"gaze_yaw_deg": 180.0, "gaze_pitch_deg": 40.0},
  "extras": {"speech": "tones", "camera_calibrated": false}
}
```

`mobility: none` is why `move`, `go_to`, `approach_and`, `kick`, `grab`, `sit` and `stand`
do not exist on this robot: not in the registry, not in the MCP tool list, not in `.duck`
validation, not in the prompt. `search_scan` exists because the head can look around.

| Verb | Kind | What it does here |
|---|---|---|
| `observe` (alias `get_frame`) | core | a camera frame plus detections; bearings are camera-relative |
| `report_state` | core | head yaw and motor mode; battery is always `null` (the SDK has none) |
| `stop` | core | `cancel_move()`. Never limp (see Safety) |
| `say(text)` | core | no text to speech on this robot: the text is logged verbatim and voiced as the closest expressive sound (`?` is curious, a greeting is welcoming, joy is cheerful, sadness is sad, `!` is surprised, otherwise attentive). Chosen by the project owner over "no `say`" and "a local TTS extra" ([ADR-0023](../adr/0023-reachy-mini.md)) |
| `search_scan(target)` | core | a gaze sweep from the current yaw outward (`c, c+s, c-s, c+2s, ...`) within 180°, one frame per look; the head is left on the target and the result carries `gaze_yaw_deg` |
| `gaze` | extension | an exact yaw (±180°) and pitch (±40°), or a direction. The same name as the Microduck's `gaze`, so `requires: [gaze]` is satisfied by both |
| `express(name)` | extension | a recorded expression with its sound; `name` is an enum of what this robot can play (sim and mock: a fixed list; sdk: the local emotion library, see below) |
| `play_sound(name)` | extension | a bundled sound asset by file name (`wake_up.wav`); no paths |
| `wake_up` | extension, **confirm** | the official wake choreography. It moves every joint, so a human says yes first |

## Frames and the gaze sweep

`Detection.bearing_deg` is relative to the camera on every robot. On a head the body-frame
bearing is `gaze_yaw_deg + bearing_deg`, which `search_scan` reports. There is no shared
frame between a head and a duck on hardware; see the frame-of-reference note in
[flock.md](../flock.md). The simulated camera has a 90° field of view; the real camera's
intrinsics were not read (UNVERIFIED below), so distance estimates from the real camera
are uncalibrated and the manifest says so.

## Safety

- `stop` is `cancel_move()`, which stops a playing move and its sound. quackd never calls
  `disable_motors()` (torque off, the head falls limp), the same principle as never
  sending `robot.relax` to a Microduck.
- No client-disconnect deadman and no e-stop primitive were found in the SDK
  (UNVERIFIED as absences), so `safety_authority.native` is `none`: quackd's own 2 Hz
  heartbeat and short gaze moves (0.3 s) are the client-side authority. Upstream's motor
  watchdog protects the motors, not a dead client.
- There is no battery in the API: a `Battery below N%` abort cannot be enforced on this
  robot.
- `wake_up` is confirm-gated; `goto_sleep` and `disable_motors` are not exposed.

## The `sdk` backend

EXPERIMENTAL, like `microduck:jsonrpc`. `reachy_mini` is imported inside `connect()` only,
so a machine without the extra still validates, lists and simulates this robot. Every SDK
call runs in a worker thread, one at a time under a lock, with a deadline (thread safety
across concurrent client calls is UNVERIFIED). The emotion library is read from the
**local** Hugging Face cache at connect and never downloaded; when it is absent, `express`
is omitted from the manifest and a `.duck` that requires it fails validation against this
robot. `spawn_daemon=True` is never passed (it kills a mismatched daemon). Version
mismatches between the SDK and the daemon are warned about by the SDK, not fixed by us.

## VERIFIED and UNVERIFIED

Everything quackd asks of the SDK lives in `quackd/adapters/reachy_mini/upstream_api.py`,
read from `pollen-robotics/reachy_mini` at commit `da00973` (2026-09-01) and confirmed
against the installed `reachy-mini` 1.10.0 wheel (2026-09-02). A test keeps this table
complete and proves the UNVERIFIED names are only reachable from the `sdk` backend.

| Name | Status | Note |
|---|---|---|
| `reachy-mini` | VERIFIED | the PyPI name; the import name is `reachy_mini` |
| `>=3.11` | VERIFIED | requires-python |
| `ReachyMini` | VERIFIED | `ReachyMini(robot_name, host="reachy-mini.local", port=8000, connection_mode, spawn_daemon=False, use_sim=False, timeout=5.0, automatic_body_yaw=True, media_backend)`: a WebSocket client to a daemon |
| `/ws/sdk` | VERIFIED | `ws://{host}:{port}/ws/sdk` |
| `reachy-mini.local` | VERIFIED | the default host |
| `8000` | VERIFIED | the default port |
| `_reachy-mini._tcp.local.` | VERIFIED | the daemon's mDNS service type |
| `reachy_mini.utils.discovery.find_robots` | VERIFIED | `find_robots(timeout=5.0)` |
| `ReachyMini.__exit__` | VERIFIED | closes the media manager and disconnects; there is no `close()` |
| `client.disconnect` | VERIFIED | on the WebSocket client |
| `client.get_status` | VERIFIED | `mini.client.get_status(wait=True, timeout=5.0) -> DaemonStatus`; on the client, not on `ReachyMini` (the research draft had it wrong) |
| `DaemonStatus` | VERIFIED | robot_name, state, wireless_version, version, hardware_id, backend_status, ... |
| `DaemonState: not_initialized, starting, running, stopping, stopped, error` | VERIFIED | the daemon states; the heartbeat needs `running` |
| `StateSnapshot` | VERIFIED | head_pose, antennas, body_yaw, motor_mode, is_move_running, ... |
| `enabled` | VERIFIED | `MotorControlMode.Enabled`; quackd's `motors_enabled` precondition |
| `SDK/daemon version warning` | VERIFIED | the SDK warns on a mismatch |
| `spawn_daemon=True kills a mismatched daemon` | VERIFIED | never passed by quackd |
| `reachy-mini-daemon` | VERIFIED | `--sim` or `--mockup-sim` to test without hardware |
| `look_at_world` | VERIFIED | `look_at_world(x, y, z, duration)`, metres, x forward, y left, z up; quackd's gaze |
| `look_at_image` | VERIFIED | pixel coordinates; unused |
| `goto_target` | VERIFIED | interpolated head and antenna targets; unused |
| `set_target` | VERIFIED | immediate targets; unused |
| `get_current_head_pose` | VERIFIED | a 4x4 matrix |
| `get_current_joint_positions` | VERIFIED | head[7] with body yaw first, antennas [right, left] |
| `reachy_mini.utils.create_head_pose` | VERIFIED | a pose helper; unused |
| `head pitch/roll ±40°, head yaw ±180°, body yaw ±160°, head-body yaw delta ≤ 65°` | VERIFIED | clamped by the daemon |
| `body_rotation, stewart_1..stewart_6, right_antenna, left_antenna` | VERIFIED | the nine motors |
| `play_move` | VERIFIED | `async_to_sync(async_play_move)`: a client-side wall-clock loop |
| `async_play_move` | VERIFIED | |
| `cancel_move` | VERIFIED | quackd's `stop` |
| `RecordedMoves` | VERIFIED | `RecordedMoves(dataset).list_moves()` and `.get(name)` |
| `pollen-robotics/reachy-mini-emotions-library` | VERIFIED | the default emotion dataset |
| `wake_up` | VERIFIED | the wake choreography |
| `goto_sleep` | VERIFIED | never sent |
| `enable_motors` | VERIFIED | torque on |
| `disable_motors` | VERIFIED | torque off, limp. **Never sent** |
| `media` | VERIFIED | `mini.media`, a property |
| `media.get_frame` | VERIFIED | BGR uint8 or None |
| `media.get_frame_jpeg` | VERIFIED | unused |
| `media.play_sound` | VERIFIED | a path or a bundled asset name; there is no TTS anywhere in the SDK |
| `media.push_audio_sample` | VERIFIED | raw PCM; unused |
| `media.get_DoA` | VERIFIED | direction of arrival; unused |
| `no_media` | VERIFIED | `MediaBackend.NO_MEDIA` skips the GStreamer import chain |
| `no say / speak / tts method` | VERIFIED | the only TTS example calls an external service |
| `no battery field` | VERIFIED | `battery_percent` is always None |
| `motor liveness watchdog` | VERIFIED | more than 1 s of silent motors is an error; it protects the motors |
| `no client-disconnect deadman` | UNVERIFIED | nothing found; quackd keeps gaze moves short and runs its heartbeat |
| `no e-stop primitive` | UNVERIFIED | nothing found beyond limp; a human uses the daemon or the power switch |
| `camera heading = body_yaw + head-pose yaw` | UNVERIFIED | how `head_yaw_deg` is derived; listed in `extras.assumptions` |
| `camera field of view` | UNVERIFIED | intrinsics not read; fallback 90°, `camera_calibrated: false` |
| `concurrent SDK calls from several threads` | UNVERIFIED | quackd serialises every call |
| `look_at_world blocks for its duration` | UNVERIFIED | assumed, like `goto_target` |
| `emotion move names (cheerful1, curious1, ...)` | UNVERIFIED | a Hub dataset, not pinned; read from the local cache at connect |

## How to help

Run the `sdk` backend against a Reachy Mini (or `reachy-mini-daemon --mockup-sim`) and
open an issue with `quackd doctor --robot reachy_mini:sdk` and the run's
`transcript.jsonl`. That is what flips 🧪 to ✅.
