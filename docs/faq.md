# FAQ

**Why is the simulator a cartoon?** Because the demo tests the *agent loop* — search,
approach, act, verify — not contact dynamics. Upstream's real simulator needs a GPU and
CC BY-NC-SA meshes we will not vendor. `sim2d` runs anywhere in seconds and the same
detector works on its duck-cam and on a real camera. ([ADR-0007](adr/0007-sim2d-cartoon.md))

**Does `uvx quackd run … --provider anthropic` work with no extras?** The default install
is light on purpose (no vendor SDKs). Use `uvx --from "quackd[anthropic]" quackd run …`, or
`uv pip install "quackd[anthropic]"`. Without the extra, quackd prints exactly that command.
`--provider fake` needs nothing.

**Which models are the defaults?** `anthropic` → `claude-opus-5`; `openai` → `gpt-5`;
`gemini` → `gemini-2.5-pro`; `grok` → `grok-4`. The non-Anthropic IDs were not verified
against vendor docs at release (no keys in CI) — override with `--model` or `QUACKD_MODEL`
if yours differs. Anthropic extras: `QUACKD_EFFORT` (default `medium`) and
`QUACKD_ANTHROPIC_FALLBACKS=0` to disable server-side refusal fallbacks.

**Are local LLMs supported (llama.cpp, vLLM, Ollama, LM Studio)?** Yes. They all speak
OpenAI's Chat Completions API, so `--provider ollama`, `vllm`, `llamacpp`, `lmstudio`, or
`local --base-url http://host:port/v1` works with no API key. Tool calling must be enabled
on the server (`llama-server --jinja`, `vllm serve --enable-auto-tool-choice
--tool-call-parser …`), vision is off unless you pass `--vision`, and a small model that
writes its tool call as plain JSON is still understood. Details: [local-llms.md](local-llms.md).

**How does the LLM "see"?** Providers with vision get the duck-cam PNG for the last two
turns; every provider gets a text line like `ball at bearing 12° left, ~0.80 m` from the
detector. Composite verbs steer on detections at 10 Hz and never wait for the model.

**Does the robot need a powerful onboard computer?** No. quackd's own process, the part
that calls the LLM and runs the detector, never runs on the robot itself — you run
`quackd run` on a laptop or a server, a network hop away, and it talks to the robot (or the
simulator) from there. The Open Duck Mini's official target, a Raspberry Pi Zero 2 W, only
ever runs its existing 50 Hz walk policy plus two small daemons that do run on the Pi, a
bridge and a camera server, and neither does any perception or inference of its own: just
enough to swap the gamepad for a socket and to serve a JPEG ([`bridge/open_duck/`](../bridge/open_duck/README.md)). The Microduck's onboard
computer works the same way, through `robotd`. Nothing here needs an NPU or a bigger board
to keep up, because nothing model-shaped runs on the robot's own board in the first place.

**Does quackd use TOF or another depth sensor for obstacle avoidance?** Not yet. The only
sensing input today is a single colour camera: an HSV threshold (or optionally YOLO) gives
a bearing and an apparent-size distance to one named target, and `go_to` steers toward it —
there's no depth data, no occupancy grid and no general obstacle avoidance. The manifest
schema has a generic `tof` sensor slot for future adapters
([manifest-spec.md](manifest-spec.md)), and the Microduck's own `tofd` depth stream isn't
read yet either ([adapter-status.md](adapter-status.md)); the Open Duck Mini's official
build has no depth sensor at all.

**How do I tune the detector for a real orange ball?** `ColorBlobDetector` takes
`targets=(Target("ball", HSVRange(h_lo, h_hi, s_lo, v_lo), size_m=radius, round=True), …)`
in OpenCV HSV (H 0–180). Photograph the ball under your light, sample its hue, give ±8, and
pass `--fov-deg 62` to `quackd run` for the IMX219. Distance comes from apparent size:
measure the pixel radius at 1 m once and adjust `size_m` until it reads 1.00. Or install
`quackd[yolo]` and use `YoloDetector`.

**Does it remember anything between runs?** Since 0.6, a little, per robot. Each
`adapter:backend` has a JSONL file under `~/.quackd/memory/` holding two kinds of line: the
notes the pilot chose to keep with the `remember` tool, and one line per earlier run that
quackd writes itself (outcome, reason, the last few verb results). The newest twenty notes
and five episodes go into the next run's system prompt. It is deliberately not a memory
*system*: no embeddings, no search, newest wins, nothing shared between bodies, and the
executor never reads it, so a note can never widen an allowlist or lift a budget. The
scripted pilot has no `remember` in its script, so `--provider fake` accumulates run
outcomes and never a note. [memory.md](memory.md), [ADR-0025](adr/0025-memory-between-runs.md)

**Who decides the run succeeded?** The LLM, via `declare_success(reason)` — that is the
honest state of the art. In `sim2d` the run summary also records ground truth
(`ball_displacement_m`) and the tests check the claim against it.

**Why can't the duck say words?** Upstream has seven duck sounds and no TTS. `quack(text)`
maps your text to the closest tone (`greet`, `inquire`, `alarm`, `wheee`, …) and logs the
text.

**What does it cost?** A `find-and-kick` run is 3–8 model turns, each a few thousand input
tokens (mostly the system prompt and one image) and a short tool call. `transcript.jsonl`
records usage per turn.

**Windows?** Fully supported for sim, MCP and development. The real-robot `unix://` socket
is POSIX-only; forward it with `ssh -L 9870:/run/robotd.sock <robot>` and use
`--address tcp://127.0.0.1:9870`.

**Can I run it on my Microduck today?** `--robot microduck:jsonrpc` speaks the verified
`duck-ipc-proto` v23 vocabulary but has never touched hardware. Start with `--dry-run`,
read [adapter-status.md](adapter-status.md), and tell us what happened.

**Can I drive it from the Claude mobile app?** Not yet. `quackd serve-mcp` speaks `stdio`
only, so Claude Code and Claude Desktop spawn it as a local subprocess on the same machine
and talk to it over pipes. The mobile app reaches tools as remote connectors instead:
servers that run persistently at a network address with their own auth. quackd would need
an HTTP or SSE transport, a long-lived process, a reachable address and authentication
before a phone could talk to it. Roadmap, not shipped. The details are in
[mcp.md](mcp.md#why-not-from-my-phone-yet).

**Is control text-only?** Yes, from you — a `--goal` string, a `.duck` file, or a chat
message over MCP; there's no voice or GUI input. The loop isn't text-only end to end,
though: cloud providers also read the camera frame as an image each turn, and whatever
the model decides is always one of a fixed set of verbs (`walk_to`, `kick`, `quack`, …),
never a freeform command sent to the motors.

**Do I need to be near the robot to control it?** No — proximity isn't the constraint,
network reachability is. `robotd`'s socket only ever accepts connections from processes
on the robot's own computer, so reaching it from anywhere else always goes through a
network hop first (the same Wi-Fi, a VPN, or an SSH forward, as in the `Windows?` answer
above), and that works the same from across the room or across the world. Latency is what
actually matters: the deadman expects `robot.move` roughly every 100 ms, so a slow or
flaky link can stop the robot outright, regardless of physical distance.

**Is quackd production-ready?** No — it's a research prototype built around one trusted
local operator, not a hardened multi-user product. There's almost no authentication anywhere;
`.duck` files with a `flock:` block are refused over MCP for exactly that reason ("one
pilot, a flock needs a coordinator"), and nothing arbitrates two sessions driving the same
robot at once. Every real-hardware transport is experimental and unverified end to end
([adapter-status.md](adapter-status.md)); the CLI and MCP server are both thin callers of
the same executor and verb registry, so a real client like a phone app would mean adding a
network-reachable server and auth on top, not rewriting the core.

**Can I control who's allowed to pilot my robot?** Barely, and only on one body. quackd
adds no login or accounts, so access is mostly whatever your OS and network enforce.
`robotd`'s socket can't be reached off the robot's own computer unless something bridges
it, so the real gate there is SSH's authentication (and your Wi-Fi's), not quackd's;
`quackd announce`/`discover` do broadcast a robot's identity, unauthenticated, to anyone on
the LAN ([lan.md](lan.md)), though that's identity only, not a way to drive it. The one
exception is the Open Duck bridge, which quackd itself ships: it binds loopback, and if a
token file is configured it checks one with `hmac.compare_digest` before accepting a
handshake (`--token`, or `QUACKD_DUCK_TOKEN`). Its camera server has no authentication at
all, so tunnel it. On a Microduck the physical gamepad preempts remote commands; on an Open
Duck it does not, because quackd's daemon *replaces* the gamepad the walk loop reads, which
makes the power switch the only thing that always wins ([safety.md](safety.md)).

**What stops the model itself from doing something dangerous?** The executor, not the
model's judgment: every verb call is checked against the loaded `.duck`'s allowlist,
budgets and confirm gates before anything is sent, and machine-enforced `abort_when` rules
and preconditions (not fallen, not sitting) run right after — a refusal is enforced code,
not a request the model can talk its way around. That's still only the software layer, and
what the body adds under it varies: the Microduck's `robotd` has fall detection, thermal
clamps and a deadman, while an Open Duck Mini v2 declares `none` and the watching human is
its fall detector — see [safety.md](safety.md).

**Does my data ever leave my machine?** Only if you choose a cloud provider. Claude,
OpenAI, Gemini and Grok each send the camera frame and prompt to that provider's API over
the network, under its own terms; the `fake` pilot and any local model (`ollama`, `vllm`,
`llamacpp`, `lmstudio`) never do and need no API key, though a local model is still served
over its own local HTTP endpoint, not literally air-gapped. Since 0.6 one thing also stays
behind on your machine: `~/.quackd/memory/<robot>.jsonl`, a plain text file of sentences
about where things are, which is then part of the prompt on the next run and so part of what
a cloud provider sees. `quackd memory show` prints it, `quackd memory clear` deletes it, and
`--no-memory` never writes it. See [memory.md](memory.md) and
[local-llms.md](local-llms.md).

**Can quackd drive something that is not a duck?** Since 0.4, yes: a robot is an adapter
that returns a manifest, and the verbs come from the manifest. `quackd list-adapters`
shows the five that ship (Microduck, Reachy Mini, a LeRobot arm, any base over
rosbridge, and an Open Duck Mini v2), `quackd list-verbs --robot reachy_mini:sim2d` shows what one of them can do,
and `quackd validate your.duck --robot lerobot:mock` tells you, field by field, whether
your task fits that body. The rule never bends: a verb that is not in the manifest does
not exist on that robot. Writing one: [adapters.md](adapters.md).

**Why does `validate` say "requires kick, but reachy-01 (reachy-mini) does not provide
it"?** Because it is true. A `.duck` lists what it needs (`requires`, or for a `duck: 0`
file its whole allowlist) and a head has no legs. Either pick a body that has the verb,
or write a task for the body you have; `reachy-spotter` is the head's own starter.

**Can two different robots share a task?** In the simulator, yes: `reachy-spots-duck-kicks`
puts a Reachy Mini head and a Microduck under one contract, the head spots and judges,
the duck kicks ([flock.md](flock.md)). On hardware, not yet: a flock across machines
needs a clock across machines, and nothing multi-robot has run on hardware.

**Why "quackd"?** Upstream names its daemons `robotd`, `mediad`, `padd`, `tofd`… the brain
daemon was missing. ([ADR-0002](adr/0002-name.md))
