# Adapters: write one in a day

An adapter is how a robot joins quackd. It answers one question, "what is this body and
what can it do", as a `RobotManifest`, and it moves the body through intents the robot's
own controllers execute. Everything else (the loop, the executor, the `.duck` contract,
the MCP server, flocks) is shared. quackd ships seven: `microduck`, `reachy_mini`,
`lerobot`, `rosbridge`, `open_duck`, `xlerobot` and `alohamini`. This page is the recipe; [ADR-0017](adr/0017-robot-adapters-and-manifest.md),
[ADR-0018](adr/0018-core-verbs-extensions-aliases.md) and
[ADR-0022](adr/0022-per-adapter-upstream-refs.md) are the reasons.

## The shape

```
quackd/adapters/<name>/
  __init__.py       # the manifest, the adapter class, and the four functions the factory calls
  verbs.py          # extension verbs and named preconditions (only if the robot has any)
  mock.py           # a backend that runs offline and does what the test says
  <real>.py         # the SDK backend, EXPERIMENTAL until run against the target
  upstream_api.py   # every SDK name you spell, VERIFIED or UNVERIFIED, with a pinned link
docs/adapters/<name>.md
tests/test_<name>_adapter.py
```

Some robots have no network API to talk to at all. The Open Duck Mini v2 is one: its
runtime reads a local gamepad and nothing else, so the adapter needed a companion daemon
that runs on the robot, in `bridge/<name>/`. Three rules if you find yourself there. It
must never import quackd, because quackd's dependencies do not belong on a 512 MB board.
It ships in the sdist and never in the wheel, so `packages` stays `["quackd"]`. And it
should be testable with no hardware, which in practice means a `--fake` mode and a pure
core the tests can drive directly.

The four module functions, the same on every adapter package:

```python
# static: no SDK import, no socket
def describe(backend: str, robot_id: str | None = None) -> RobotManifest: ...


# extension verbs and core overrides, keyed by canonical name
def implementations() -> dict[str, Verb]: ...


# named predicates the manifest references
def conditions() -> dict[str, Precondition]: ...


# the backend, imported lazily
def make(
    backend: str,
    *,
    robot_id=None,
    seed=None,
    address=None,
    live=False,
    camera_url=None,
    token=None,
) -> RobotAdapter: ...
```

`describe()` is what `quackd validate --robot`, `quackd list-verbs --robot`, `quackd
announce` and `doctor` use, so it must never import an SDK. `make()` imports the backend
module lazily. Add one row to `_ADAPTERS` in `quackd/adapters/factory.py` (backends,
status line, the pip extra, the module `doctor` probes by metadata) and the name works
everywhere `--robot` does.

## The manifest decides what exists

A verb that is not in the manifest does not exist: not in the registry, not in the MCP
tool list, not in `.duck` validation, not in the prompt. So the manifest is where honesty
lives. The rules, enforced by the model itself ([manifest-spec.md](manifest-spec.md)):

- **Core verbs need what they need.** `observe` needs a camera; `move` and `go_to` need
  the `twist` intent and mobility; `search_scan` needs a camera and either `twist` or
  `gaze`; `say` needs `sound`. Declare a core verb the body cannot support and the
  manifest refuses to build.
- **Extension verbs are the robot's own** (`kick`, `express`, `move_joints`). Declare
  them with `verb_spec(verb, core=False)` and supply the implementation from
  `implementations()`. Reusing a name another robot uses (`gaze` on the Microduck and on
  the Reachy) is how `requires: [gaze]` is satisfied by both.
- **`stop` is universal**: present on every manifest, always allowed, never gated.
- **Aliases are not yours to declare.** `get_frame`, `walk_to` and `walk` live in
  `quackd/verbs/aliases.py`; a manifest names the canonical verb.
- **Preconditions are names**, with the predicate supplied by the adapter's
  `conditions()`: `{"kick": ["standing"]}` means the executor asks your `standing(state)`
  before every kick.
- **`safety_authority` says who stops the body when quackd goes quiet.** `native: none,
  deadman: false` is a legitimate answer; a wrong `deadman: true` is not.
- **`limits`** are what the core verbs clamp to (`max_vx`, `max_vy`, `max_wz`,
  `gaze_yaw_deg`); leave one out and the schema bound applies.
- **`digest()`** is the capability fingerprint discovery advertises; it ignores `id` and
  `backend`, so the same robot over `sim2d` and `mock` hashes the same.

## The adapter class

A `RobotAdapter` is a `DuckTransport` plus self-description. Wrap your backend and
delegate: `connect()` returns the manifest, `disconnect()`/`close()` release it,
`get_state()` returns a `DuckState` (`posture="unknown"` is fine for a body without
postures; `holding` is for grippers), `get_frame()` returns a PIL image or `None`,
`send_intent()` maps an `Intent` to the SDK, `health()` is informational and never
raises, `heartbeat()` is the watchdog and raises `HeartbeatError`. Copy
`quackd/adapters/rosbridge/__init__.py` for the smallest complete example.

Intents are the whole vocabulary between verbs and backends: `move` (a twist), `look`
(a gaze point), `sound`, `do` (a named skill, `express:cheerful1`, `policy:pick:cup`),
`joint`, `gripper`, `enable`, `pose`, `stop`. A backend answers each with an `Ack`; a
refusal is data (`accepted=False, reason=...`), never an exception.

## Backends: mock first, the SDK last

Write `mock` before anything else. It runs offline, records intents, serves a synthetic
frame if the body has a camera, and lets every verb, every executor gate and the detector
run in the test suite. Then the SDK backend:

- import the SDK **inside `connect()`**, and raise `AdapterNotInstalled(name, "quackd[extra]")`
  on `ImportError`, so a machine without the extra still validates, lists and mocks the robot;
- serialise SDK calls under one lock in a worker thread with a deadline unless you have
  read that the SDK is thread-safe;
- never send the SDK's "go limp" call (`disable_motors`, `disable_torque`, `relax`); stop
  means stop, not collapse;
- take injectable clients (`client=`, `robot=`, `ros=`) so the tests exercise the mapping
  with fakes;
- add the extra to `pyproject.toml` (with a `python_version` marker if the SDK needs
  one) and the module to `doctor.py`'s `EXTRAS` (metadata-only if importing it is heavy).
  An adapter whose robot side is a daemon you ship needs no extra at all, because nothing
  heavy is imported on the laptop: `open_duck` declares none.

## `upstream_api.py`: never guess a name

Every SDK name you spell lives in one file as an `UpstreamRef(name, status, source, note)`
with a permalink to a pinned commit and line. `VERIFIED` means you read it there;
`UNVERIFIED` means it is your assumption, and the note says what quackd does about it.
`tests/test_upstream_api.py` takes one row per adapter: the module, the files allowed to
touch its UNVERIFIED identifiers (the backend and `doctor.py`), and the source prefixes
every link must start with. `docs/adapters/<name>.md` must list every ref's name (a test
checks) and carry the pin and the word "never" until someone has run it for real.

## Status is a promise

The README's status table and [adapter-status.md](adapter-status.md) get ✅ only for what
was exercised against its real target by us. A new adapter arrives 🧪 for its SDK backend
and stays 🧪 until a human runs it on hardware and the transcript says so. Nothing in
this repository claims a robot moved unless one did.

## The checklist

1. `quackd/adapters/<name>/__init__.py` with the manifest, the adapter class and the four functions.
2. `mock.py`, and a test that runs every verb through an `Executor` on it.
3. `upstream_api.py` with pinned links; a row in `tests/test_upstream_api.py`.
4. The SDK backend, lazily imported, injectable, with a test on fakes and a test that the
   missing extra names itself.
5. A row in `_ADAPTERS`, the extra in `pyproject.toml` (`uv lock`), the module in `doctor.py`.
6. `docs/adapters/<name>.md` (every ref name, the pin, "never"), a row in the README status
   table and in `adapter-status.md`, a CHANGELOG entry, a `docs/architecture.md` mention.
7. The gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run quackd validate ducks/*.duck`.
