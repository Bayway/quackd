# Pilot the robot from Claude (MCP)

`quackd serve-mcp` exposes a robot, or a fleet of them, as
[Model Context Protocol](https://modelcontextprotocol.io) tools over stdio. Claude Code or
Claude Desktop becomes the pilot; quackd's executor still sits between the model and every
robot (allowlist, budgets, confirm gates, heartbeat), one executor per robot.

Works with the built-in simulator out of the box — no hardware, no extra install.

## Tools

Eight `robot_*` tools. `robot` is the name from `--robots name=<adapter>:<backend>`; omit
it (or pass `null`) to address the default robot, which is the only robot when there is
one, else the first Microduck, else the first declared.

| Tool | What it does |
|---|---|
| `robot_list` | Every robot this server fronts: name, adapter, backend, vendor, model, embodiment, mobility, manifest id and digest, loaded contract, health, and which one is the default. Call this first. |
| `robot_list_verbs(robot?)` | That robot's verbs from its own manifest: params, safety class, `canonical` name and `aliases`, whether it is `core`, and whether its current contract allows it. |
| `robot_run_verb(robot?, verb, params?)` | Run any verb through that robot's executor (`search_scan`, `go_to` or its alias `walk_to`, `kick`, `gaze`, `express`, …). Refusals come back as `ok: false`, and a verb the manifest does not list is a refusal too. |
| `robot_observe(robot?)` | The `observe` verb through the executor (it counts against the budget), returning the camera frame as a PNG image plus a one-line detection summary. |
| `robot_say(robot?, text)` | The `say` verb. No robot here has text to speech, so it degrades: one of seven tones on a Microduck, an expressive sound on a Reachy Mini, one of the duck's own sounds on an Open Duck. A robot without a `sound` intent refuses with `ok: false`. |
| `robot_load_duckfile(robot?, path)` | Adopt a `.duck` contract on one robot: its `requires` (or, for `duck: 0`, its allowlist) is checked against that robot's manifest first, then allowlist and budgets are enforced for that robot only; the body is returned as instructions. Flock ducks are refused. |
| `robot_recall(robot?)` | What that robot remembers from earlier sessions and runs: the notes a pilot saved and how its recent runs ended ([memory.md](memory.md)). Costs no step; the server's instructions ask the model to call it early. |
| `robot_remember(robot?, text, tags?)` | Keep one short fact for future sessions on that robot. Moves nothing, costs no step; the same sentence twice updates the old note. Off with `--no-memory`. |

Without a loaded `.duck`, every verb that is not `dangerous` is allowed and the session runs
on a default budget of 40 verb steps and five minutes, counted from when the server started.
Load one to get the guard rails and the task's own budget. Contracts, budgets and abort
flags are per robot: loading a contract on `duck` changes nothing for `reachy`.

Simulated robots in one fleet each get their own world; a shared arena over MCP is future
work (a flock needs a coordinator, and one MCP pilot is not one). Run a heterogeneous task
with `quackd run reachy-spots-duck-kicks` instead ([flock.md](flock.md)).

## Claude Code

Verified against the current docs (`code.claude.com/docs/en/mcp`, 2026-08). Two options.

**1. One command** (local scope by default; `--scope project` shares it via `.mcp.json`):

```bash
claude mcp add quackd -- uvx quackd serve-mcp --robot microduck:sim2d
```

**2. Project file** — commit a `.mcp.json` at the repo root:

```json
{
  "mcpServers": {
    "quackd": {
      "command": "uvx",
      "args": ["quackd", "serve-mcp", "--robot", "microduck:sim2d"]
    }
  }
}
```


(No `"type"` key: Claude Code reads an entry with `command` as a stdio server.)

Then in Claude Code: *"List the duck's verbs, then find the ball and kick it."*

> **If you are working on quackd itself**, this repo ships its own `.mcp.json`, and it says
> `uv run --no-sync` rather than `uvx` on purpose: it serves the code in your working tree
> instead of the last release, and `--no-sync` keeps the launch from re-syncing the
> environment while the previous server still holds `Scripts/quackd.exe` open on Windows.
> Run `uv sync --extra dev` once first. A server that is already running keeps the tools it
> started with, so after changing a verb or upgrading quackd, restart it (`/mcp` in Claude
> Code, or a new session) or you will be calling the old build.

## Claude Desktop

Edit `claude_desktop_config.json` — Settings → Developer → *Edit Config*:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "quackd": {
      "command": "uvx",
      "args": ["quackd", "serve-mcp", "--robot", "microduck:sim2d"]
    }
  }
}
```

Restart Claude Desktop completely. The duck appears under *Connectors → Manage connectors*.

> **Windows note.** Desktop apps often do not see your shell `PATH`. If the server does not
> start, replace `"uvx"` with its absolute path (`where uvx` in a terminal, e.g.
> `C:\\Users\\you\\.local\\bin\\uvx.exe`). Server stderr lands in
> `%APPDATA%\Claude\logs\mcp-server-quackd.log` (macOS: `~/Library/Logs/Claude/`).

## Why not from my phone yet

Both setups above are *local*. `quackd serve-mcp` speaks the `stdio` transport and nothing
else (`mcp.run(transport="stdio")` in `quackd/mcp_server.py`), so the client spawns it as a
subprocess on the same machine and talks to it over stdin and stdout. It lives exactly as
long as that process does.

Reaching it from the Claude mobile app would need a different shape: a remote connector,
which is a server that runs persistently somewhere reachable over the network, with its own
address and its own authentication. quackd is not that today, and there is no flag that makes
it one. Four things would have to land first:

- an HTTP or SSE transport option in `serve()`, instead of `stdio` only,
- a long-lived process rather than one spawned per client session,
- a reachable address for it (a tunnel, or a small always-on host next to the robot),
- authentication and session isolation, which the server does not have because it assumes
  one trusted local pilot.

None of that is built. It is on the roadmap, and it is worth wanting: the robot is the thing
you would most like to poke at from the sofa.

## Useful flags

```
quackd serve-mcp --robot microduck:sim2d --seed 7    # a different world
quackd serve-mcp --duckfile find-and-kick            # start with a contract loaded
quackd serve-mcp --dry-run                           # intents are logged, never sent
quackd serve-mcp --yes                               # allow confirm-gated verbs (no terminal to ask)
quackd serve-mcp --robot microduck:jsonrpc --address tcp://127.0.0.1:9870   # real robot, experimental
quackd serve-mcp --robots duck=microduck:sim2d,reachy=reachy_mini:mock       # a fleet: robot_* tools, one executor each
quackd serve-mcp --robot open_duck:sim2d                                     # a buildable duck, no hardware needed
```

## Driving a real Open Duck Mini from Claude

A real Open Duck Mini needs three flags, because its camera is a separate
HTTP service on the robot and its bridge wants a token. Tunnel both ports rather than
exposing them (`ssh -L 9871:127.0.0.1:9871 -L 9872:127.0.0.1:9872 your-pi`), then:

```json
{
  "mcpServers": {
    "duck": {
      "command": "uvx",
      "args": ["quackd", "serve-mcp",
               "--robot", "open_duck:bridge",
               "--address", "tcp://127.0.0.1:9871",
               "--camera-url", "http://127.0.0.1:9872/snapshot.jpg"],
      "env": {"QUACKD_DUCK_TOKEN": "the token from /etc/quackd/duck-bridge.token"}
    }
  }
}
```

The verbs Claude is offered come from what that duck reports at connect, not from the
description, so a duck with no camera or no head simply has fewer. Nothing has been run
against a real duck: [adapters/open_duck.md](adapters/open_duck.md) and its
[bring-up checklist](open-duck-hardware-checklist.md).

## The two-minute script

1. `claude mcp add quackd -- uvx quackd serve-mcp --robot microduck:sim2d` (≈20 s, first run downloads quackd)
2. Open Claude Code in any folder and ask: **"Use the quackd tools. List the verbs, grab a frame, then find the ball and kick it. Quack when you're done."**
3. Watch it call `robot_list` → `robot_list_verbs` → `robot_observe` → `robot_run_verb("search_scan")` → `robot_run_verb("go_to")` → `robot_run_verb("kick")` → `robot_say`.
4. Ask: **"Load ducks/patrol-and-quack.duck and follow it."** — now the allowlist and budgets apply, and the model has the task body as instructions.

## Safety in an MCP session

- One heartbeat per robot runs for the whole session; if a robot's transport fails, every
  later call to that robot returns `ok: false` and that robot has already been stopped.
  The other robots in the fleet carry on.
- Every robot connects at startup, in the order given; if one cannot, the server stops
  and disconnects the ones that did, rather than fronting a fleet with a hole in it.
- Confirm-gated verbs are **refused** unless the server was started with `--yes`, because
  there is no terminal to ask on. The refusal text tells the model why.
- On a Microduck the gamepad wins: upstream arbitrates authority and quackd does not fight it. On an Open Duck it does not, because quackd's own daemon replaces the gamepad the walk loop reads, so there the power switch is the only thing that always wins.
