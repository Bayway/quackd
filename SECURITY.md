# Security Policy

## What "security" means for a robot brain

quackd sends *intents* to a robot. How much of the stopping the robot itself does depends
on the body, and each adapter declares it in its manifest's `safety_authority`
(see `docs/safety.md`). On a Microduck, `robotd` is the safety authority: it clamps
velocities, detects falls, and zeroes motion when commands stall. On an Open Duck Mini the
deadman is quackd's own daemon, running on the robot and zeroing the velocity inside the
50 Hz loop, so it is code we ship and therefore code we are answerable for. On the other
six bodies there is no deadman in the robot that we verified. A Reachy Mini and a rosbridge
base declare `native: none`, and a LeRobot arm has a torque limit but holds its last goal.
An XLeRobot's host watchdog zeroes its wheels and leaves the arms holding, and an
AlohaMini's covers the base and the lift and never the arms, so both are partial by
construction. A ToddlerBot has no watchdog, timeout or e-stop anywhere upstream at all, and
cannot get up if it falls, so its only deadman is the one quackd's own daemon runs. On all
six, quackd's own heartbeat and `stop` are most or all of what stops them. That makes the client-side
layer (verb allowlists, confirm gates, budgets, the heartbeat, the kill switch)
security-relevant, not just a convenience. A bug that lets an LLM or an MCP client bypass
it is a security issue.

Since 0.5 quackd also ships code that runs **on a robot**, which is a different kind of
surface from everything above. Everything under `bridge/` is in scope in its own right:
two daemons for an Open Duck Mini v2's Raspberry Pi, a host wrapper for an AlohaMini, and
since 0.7 a daemon that walks a ToddlerBot.

Also in scope:

- API keys leaking into transcripts, GIFs, logs, run directories, or a robot's memory file.
- **The memory file** (`~/.quackd/memory/<adapter>-<backend>.jsonl`, since 0.6). It holds
  sentences a model wrote about a place it has been, it persists between runs, and it is
  read back into the next system prompt. It never leaves the machine and the executor never
  reads it, so a note cannot widen an allowlist, lift a budget or open a confirm gate. What
  would be a security issue: memory reaching the executor, a note from one robot appearing
  in another robot's prompt, or the file escaping the directory `--memory-dir` names.
  `--no-memory` writes nothing at all, and `quackd memory clear` deletes the file.
- The MCP server executing verbs a loaded `.duck` contract does not allow.
- Anything that lets a `.duck` file (untrusted input — people will share them) execute
  code, read files, or reach the network.
- An adapter sending a body's "go limp" call (`robot.relax`, `disable_motors`,
  `disable_torque`, an XLeRobot `disconnect()`, a ToddlerBot torque-off) as if it were
  `stop`. Stop means stop, never collapse.
- The LAN surfaces behind `quackd[lan]`: zeroconf TXT records advertise a robot's identity
  to anything on the network, and the MQTT flock bus carries messages that command robots
  with no authentication of its own. Both are off by default and neither has a threat model
  yet, so treat them as trusted-network only.
- **The bridge daemon** (`bridge/open_duck/quackd_duck_bridge.py`), a TCP listener on port
  9871 that walks a 42 cm biped. It binds loopback by default and compares a token with
  `hmac.compare_digest`, but a token is only required if one is configured, and binding it
  wide only warns. Anything that lets an unauthenticated peer move the robot, defeat the
  300 ms deadman, exceed the clamps, or reach past the seven floats the protocol exposes is
  a security issue. Going limp is currently unreachable by construction, and it should stay
  that way: there is no method in the protocol that touches torque.
- **The camera daemon** (`bridge/open_duck/quackd_duck_camd.py`), an HTTP server on port
  9872 that serves a live view of wherever the robot is, with **no authentication at all**.
  It binds loopback by default and warns when told otherwise. Reach it through an ssh
  tunnel. If you bind it wide, everyone on that network can watch your home.
- **The ToddlerBot daemon** (`bridge/toddlerbot/quackd_toddlerbot_bridge.py`), a TCP
  listener on port 9873 that drives a 3 kg humanoid which cannot get up if it falls. It
  binds loopback by default, compares its token with `hmac.compare_digest`, and requires one
  only if one is configured. It is a larger surface than the Open Duck's because it owns the
  50 Hz loop rather than feeding one: anything that lets an unauthenticated peer move the
  robot, defeat the 500 ms deadman, exceed the joint clamps or the per-tick rate limit, or
  reach past the methods the protocol exposes is a security issue. As with the Open Duck,
  going limp is unreachable by construction and must stay that way, and here it matters
  more: torque off on this body means the robot falls over.
- The recommended deployment for all of them is an ssh tunnel
  (`ssh -L 9871:127.0.0.1:9871 -L 9872:127.0.0.1:9872 -L 9873:127.0.0.1:9873`) rather than
  exposing any of these ports.

## Reporting

Please **do not** open a public issue for vulnerabilities. Email
**ksjeno@gmail.com** with "quackd security" in the subject, or use GitHub's private
vulnerability reporting on the repository if enabled. You will get an acknowledgement
within 72 hours.

## Supported versions

Only the latest released minor version receives fixes.

The on-robot artifacts carry their own versions and live on someone else's computer, so
they can drift from the quackd that talks to them: `BRIDGE_VERSION` and `CAMD_VERSION`
on an Open Duck Mini's Raspberry Pi, `VERSION` in the ToddlerBot daemon on its Jetson,
and the AlohaMini host wrapper's `quackd_host_version` field. Each handshake carries a
protocol version and refuses a mismatch rather than guessing, but a daemon you installed
months ago is a daemon that has not had your fixes. `quackd doctor --robot
<adapter>:<backend> --address ...` prints what your robot is actually running.
