# Licenses

| What | License | Our relationship |
|---|---|---|
| quackd (this repository) | [Apache-2.0](../LICENSE) | Ours. `NOTICE` credits upstream. |
| [microduck](https://github.com/pollen-robotics/microduck) — the onboard daemon stack, `duck-ipc-proto` | Apache-2.0 | We interoperate with its JSON-RPC contract. We copy method names and enum values (facts), not code. |
| [microduck_rl](https://github.com/pollen-robotics/microduck_rl) — training stack, ONNX policies | code Apache-2.0 | We cite the policy contract (`obs[61] → act[14]`, 50 Hz). Nothing vendored. |
| microduck_rl **3D model files** (meshes) | **CC BY-NC-SA** | **Never vendored.** If a future MuJoCo backend needs them, it fetches them from upstream at runtime into a user cache, prints the license, and stays optional. Non-commercial + share-alike terms apply to *that* asset use, not to quackd's code. |
| Pollen Robotics / Microduck / Hugging Face names and logos | trademarks | Nominative use only. No logos, videos or brand assets in this repo. quackd is unofficial and says so in README and NOTICE. |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | MIT | dependency |
| typer, rich, pydantic, numpy, Pillow, opencv-python-headless, python-dotenv | MIT / BSD / Apache | dependencies (see `uv.lock`) |
| ultralytics (optional `[yolo]`) | AGPL-3.0 | optional extra, lazily imported, never required; if you ship a product on it, read its license |
| pygame (optional `[live]`) | LGPL | optional extra |
| [reachy_mini](https://github.com/pollen-robotics/reachy_mini) (optional `[reachy]`) | Apache-2.0 | optional extra, imported only inside `connect()`. We cite method names read at a pinned commit (facts), not code. See [adapters/reachy_mini.md](adapters/reachy_mini.md) |
| [LeRobot](https://github.com/huggingface/lerobot) (optional `[lerobot]`) | Apache-2.0 | optional extra, Python 3.12 or newer, pulls torch. Imported only inside `connect()`. See [adapters/lerobot.md](adapters/lerobot.md) |
| [roslibpy](https://github.com/gramaziokohler/roslibpy) (optional `[rosbridge]`) | MIT | optional extra. The protocol it speaks is [rosbridge_suite](https://github.com/RobotWebTools/rosbridge_suite) (BSD-3-Clause) and the message shapes are [common_interfaces](https://github.com/ros2/common_interfaces) (Apache-2.0). Names only, nothing vendored |
| [XLeRobot](https://github.com/Vector-Wangel/XLeRobot) | Apache-2.0 | **Nothing vendored, and it is not a dependency.** It is not an installable package at all, so quackd cannot import it even in principle: it speaks the ZeroMQ host protocol that repository already ships, and cites port numbers, key names and units as facts read at a pinned commit. The wheel mixing stays on the robot. See [adapters/xlerobot.md](adapters/xlerobot.md) |
| [AlohaMini](https://github.com/liyiteng/lerobot_alohamini) and [its hardware repo](https://github.com/liyiteng/AlohaMini) | Apache-2.0 | **Nothing vendored, and it cannot be a dependency:** the software repository is a fork of LeRobot that calls itself `lerobot`, is not published to PyPI, and would collide with HuggingFace's own package. quackd speaks its ZeroMQ host protocol and cites ports, key names and units as facts read at a pinned commit. Its driver files carry HuggingFace copyright headers, so [LeRobot](https://github.com/huggingface/lerobot)'s Apache-2.0 notice covers them too. See [adapters/alohamini.md](adapters/alohamini.md) |
| pyzmq (optional `[xlerobot]`, `[alohamini]`, and in `dev`) | BSD-3-Clause | optional extra for the XLeRobot host protocol, imported only inside `connect()`. `dev` carries it too, because the fake-host loopback test is what that backend's status claim rests on |
| python-zeroconf (optional `[lan]`) | **LGPL-2.1** | optional extra for `quackd discover` / `announce`, imported lazily and never on the default path. Dynamic linking as a library; if you redistribute, read its terms |
| paho-mqtt (optional `[lan]`) | EPL-2.0 / EDL-1.0 | optional extra for the MQTT flock bus, imported lazily |
| [Open_Duck_Mini](https://github.com/apirrone/Open_Duck_Mini) — the robot design and the walk policy `BEST_WALK_ONNX_2.onnx` | Apache-2.0 | **Nothing vendored.** The policy, the CAD, the meshes and the sounds stay upstream: you fetch them onto your own robot. We cite the command contract as a fact, the way we cite `microduck_rl`'s. See [adapters/open_duck.md](adapters/open_duck.md) |
| picamzero and opencv, on **your robot** | their own | quackd's camera daemon imports them lazily on the Pi, where you installed them. Neither is a quackd dependency and neither is in `uv.lock` |
| [Open_Duck_Mini_Runtime](https://github.com/apirrone/Open_Duck_Mini_Runtime) — the on-robot runtime (`mini_bdx_runtime`) | **no license file: all rights reserved** | **Never vendored, never a dependency, never in `uv.lock`, never in the wheel.** There is no `quackd[open_duck]` extra and CI never installs it. quackd's bridge daemon imports it lazily on **your** robot, where **you** installed it from upstream. Method and constant names are cited as facts at a pinned commit. If upstream adds a license, this row and `NOTICE` change in the same commit |

Contributions are accepted under Apache-2.0 (see `LICENSE` §5). Do not submit code or
assets you do not have the right to license that way — including upstream meshes.
