# rosbridge (a wheeled base over ROS 2)

The first robot in quackd that is not a specific product: any wheeled base that takes a
`geometry_msgs/msg/Twist` and is reachable through `rosbridge_server`. quackd talks to it
with [roslibpy](https://github.com/gramaziokohler/roslibpy) over a WebSocket. The manifest
is small and honest: one intent (`twist`), odometry, optionally a compressed image topic,
and therefore `move`, `stop`, `report_state`, plus `observe`, `go_to`, `search_scan` and
`approach_and` only when a camera topic is given. No `say`, no `gaze`, no `kick`. The `ws`
backend has **never been run against a bridge by us**.

```bash
uvx quackd list-verbs --robot rosbridge:mock
uvx quackd run patrol-and-quack --robot rosbridge:mock --provider fake   # exit 1: requires quack, but base-01 (rosbridge-base) does not provide it
uv pip install "quackd[rosbridge]"
quackd doctor --robot rosbridge:ws --address "ws://robot.local:9090?cmd_vel=/cmd_vel&odom=/odom&image=/camera/image/compressed"
```

The address carries everything: host, port, `ws` or `wss`, and the three topics as query
parameters (`cmd_vel` and `odom` default to `/cmd_vel` and `/odom`; `image` is optional
and turns the camera verbs on).

## Backends

| `--robot` | Status | What it is |
|---|---|---|
| `rosbridge:mock` | ✅ | a planar kinematic integrator with the simulator's deadman semantics (a Twist holds for half a second, then the base coasts to zero), integrated odometry, a synthetic camera with an orange disc at a fixed spot |
| `rosbridge:ws` | 🧪 | roslibpy 2.x to a rosbridge server (extra `quackd[rosbridge]`); every roslibpy, rosbridge protocol and message name VERIFIED against pinned commits, never run against a bridge |

## The manifest

```json
{
  "manifest": 1, "id": "base-01", "vendor": "ros", "model": "rosbridge-base",
  "embodiment": "wheeled", "mobility": "wheeled",
  "intents": ["twist"], "sensors": ["odometry", "camera"],
  "verbs": ["observe", "report_state", "stop", "move", "go_to", "search_scan", "approach_and"],
  "preconditions": {},
  "safety_authority": {"native": "none", "deadman": false, "heartbeat_hz": 2.0},
  "frame": {"reference": "base", "note": "Twist in the base frame; odometry in its odom frame"},
  "limits": {"max_vx": 0.3, "max_vy": 0.0, "max_wz": 1.0},
  "extras": {"ros": "2", "cmd_vel": "/cmd_vel", "odom": "/odom", "image": null}
}
```

Every verb here is a core verb: the adapter adds no extension, it only says what it has.
The `limits` are what `move`, `go_to` and the turn used by `search_scan` clamp to; they are
quackd's caution, not the base's capability. A manifest can lower them, but not raise them past
`move`'s own schema bounds (±0.3 m/s, ±0.2 m/s, ±1.5 rad/s), which reject a larger request.

## Safety

There is no deadman anywhere in this stack that we verified: neither rosbridge nor a
base's driver. quackd re-sends the Twist at 10 Hz while a verb runs and publishes a zero
Twist on `stop`, on `close()`, and when the heartbeat fails, and that is the only stop
authority. The manifest says exactly that (`native: none`, `deadman: false`). A base
whose driver does implement a command timeout is safer than this page assumes.

## Upstream API

Three upstreams, each pinned and read on 2026-09-02: roslibpy at `f5793db` (2.1.0 on
PyPI), rosbridge_suite at `aa9a7a3` (the `ros2` branch), and ros2/common_interfaces at
`d54aa9b` (`rolling`).

### VERIFIED (read from source at the pins)

| Name | Note |
|---|---|
| `roslibpy` | 2.1.0 at the pin and on PyPI, Python 3.9 or newer |
| `roslibpy.Ros(host, port=None, is_secure=False, headers=None, transport=None)` | the constructor already calls `connect()` |
| `Ros.run(timeout)` | starts the non-blocking loop and waits until connected |
| `Ros.close(timeout)` | |
| `Ros.terminate()` | closes if connected, then stops the loop |
| `Ros.is_connected` | the heartbeat |
| `Ros.on_ready(callback, run_in_thread=True)` | |
| `Ros.get_topics(callback, errback)` | |
| `Ros.get_topic_type(topic, callback, errback)` | |
| `roslibpy.Topic(ros, name, message_type, compression=None, latch=False, throttle_rate=0, queue_size=100, queue_length=0, reconnect_on_close=True)` | |
| `Topic.publish(message)` | advertises on first use and sends `dict(message)`, so a plain dict works |
| `Topic.subscribe(callback)` | `callback(message: dict)` |
| `Topic.unsubscribe()` | |
| `Topic.advertise()` | |
| `Topic.unadvertise()` | |
| `compression: png or none` | quackd subscribes with `none` |
| `roslibpy.Message(values)` | a `UserDict` |
| `JSON text frames` | `json.loads` on every frame, keyed by `op` |
| `op=advertise {id, topic, type, latch, queue_size}` | |
| `op=publish {id, topic, msg, latch}` | |
| `op=subscribe {id, topic, type, compression, throttle_rate, queue_length}` | |
| `uint8[] fields arrive base64-encoded` | a `CompressedImage`'s `data` is one |
| `pkg/Type and pkg/msg/Type both resolve` | quackd sends the ROS 2 three-part form |
| `geometry_msgs/msg/Twist` | `{linear: Vector3, angular: Vector3}` |
| `geometry_msgs/msg/Vector3` | `{x, y, z}` |
| `sensor_msgs/msg/CompressedImage` | `{header, format, data: uint8[]}` |
| `nav_msgs/msg/Odometry` | `{header, child_frame_id, pose: PoseWithCovariance, twist: TwistWithCovariance}` |
| `geometry_msgs/msg/Pose` | `{position: Point, orientation: Quaternion}` |
| `geometry_msgs/msg/Quaternion` | `{x, y, z, w}` |

### UNVERIFIED (our assumptions, and what quackd does about each)

| Name | What quackd does |
|---|---|
| `NO_DEADMAN` | re-sends at 10 Hz, zeroes on stop; the manifest says `native: none` |
| `TOPIC_NAMES` | every topic is set in the address query; the defaults are conventions |
| `TWIST_UNITS` | m/s and rad/s in the base frame, angular z positive to the left |
| `IMAGE_FORMAT` | jpeg or png decoded with PIL, channels swapped when the format says `bgr8`, anything else refused |
| `ODOM_YAW` | yaw from the quaternion's z and w, a planar base assumed |
| `THREAD_SAFETY` | only the latest odometry and image are kept, under a lock; nothing calls back into the event loop from roslibpy's thread |
| `ROS1_BRIDGE` | a ROS 1 rosbridge should accept the three-part type strings; not tried |

## Status

`rosbridge:mock` drives, coasts on silence, turns, and reaches the ball through the
executor in the test suite. `rosbridge:ws` is exercised with an injected fake client and
fake topics (verified names, message shapes, base64 images, odometry). Nobody has run it
against a bridge, and this page will say so until someone has.
