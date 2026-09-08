# PLAN.md — quackd

What is still open. Everything that has shipped is in [CHANGELOG.md](CHANGELOG.md), the
[ADRs](docs/adr/) and the git history, which record it better than a task list can.

Legend: 🔨 in progress · ⬜ todo · ⏸ blocked (with reason)

## Only a human can

Six bring-ups, one per body. Each needs hardware quackd has never touched, and each ends the
same way: flip that backend's row in [`docs/adapter-status.md`](docs/adapter-status.md), and
not before.

- ⏸ **An Open Duck Mini v2**, the most reachable of the six because you can build it. Run
  `open_duck:bridge` against a duck you built, work through
  [docs/open-duck-hardware-checklist.md](docs/open-duck-hardware-checklist.md), and confirm
  the deadman by pulling Wi-Fi mid-walk. Then the five numbers at the end of that checklist:
  boot time against the watchdog budget, camd's peak memory against its cap, the observed
  loop-rate floor, the camera's field of view against a tape measure, and the accelerometer
  upright versus on its side. The last one is what would give this robot fall detection, and
  quackd deliberately does not guess it, because a wrong fall detector fails as a confident
  "not fallen".
- ⏸ **A Microduck.** Run `--robot microduck:jsonrpc` against a real `robotd` and work through
  [docs/microduck-hardware-checklist.md](docs/microduck-hardware-checklist.md), whose step 0
  now rehearses the whole pilot in the physics simulator first. The path is built and audited:
  pinned at a commit and bumped to API v23 (it was v16 against a moving link, so the handshake
  would have refused), state actually subscribed to, and video over `webrtc://` because
  upstream serves no frames on the socket. Pre-orders opened 2026-08-27, earliest arrivals
  estimated around Christmas 2026 and later orders four to six months out.
- ⏸ **A ToddlerBot** on its safety stand, running `bridge/toddlerbot/quackd_toddlerbot_bridge.py`
  through [docs/toddlerbot-hardware-checklist.md](docs/toddlerbot-hardware-checklist.md). What
  most needs a real robot: whether the safe-pose slew is safe from a crawl, what tilt really
  means fallen, whether the neck axes are what the motor names imply, and whether a calibrated
  zero survives a restart.
- ⏸ **An XLeRobot.** Start the host (it is commented out of upstream's own package `__init__`
  and exits after an hour) and point `xlerobot-lookout` at it. What most needs a real cart: the
  camera colour order, whether `+x` is really forward, and whether the head motors are what
  upstream's agent library implies.
- ⏸ **An AlohaMini.** Start `bridge/alohamini/quackd_alohamini_host.py` rather than upstream's
  host and point `alohamini-lookout` at it. What most needs a real robot: whether `+x` is
  physically forward, the camera colour order, how fast the lift travels in mm/s, and whether
  the wrapper really does leave the arms holding.
- ⏸ **A Reachy Mini, an SO-101 arm or any rosbridge base.** `reachy_mini:sdk` (or
  `reachy-mini-daemon --mockup-sim`), `lerobot:real` against a calibrated arm, `rosbridge:ws`
  against a bridge. A flock across two machines needs a distributed clock first.

## Open here

- ⬜ **Enable GitHub Pages** (Settings → Pages → Source: GitHub Actions). The README and
  `web/README.md` both point at `rokbenko.github.io/quackd`, `.github/workflows/pages.yml` is
  in place, and until this is switched on the workflow fails and there is no live demo.
- 🔨 **Somebody has to open `web/` in a browser.** `tests/test_web.py` now checks what can be
  checked without one — the ids, the classes, the rule that was hiding nothing, static CDN
  imports, key storage, the pins and gait numbers shared with Python, `node --check` on each
  module, and the argument validator run under Node. The rendering, the DOM and the recording
  still need a person with a browser, and the four measured claims in `web/README.md` still
  come from a scratch harness that is not in the repository.
- ⬜ Flock mode does not know `open_duck` yet (`flock/runner.py` knows two adapters), and a
  hardware flock waits on Microducks shipping.
- ⏸ **A real model recording**, in either simulator, to replace a scripted-pilot asset and drop
  the label (see [docs/assets](docs/assets/README.md)). Needs a key.
- ⬜ **The browser demo is not at parity with the backend.** It has seven of the manifest's
  fifteen verbs and none of the four composites, which is what Python's own prompt tells a
  model to prefer; perception is geometric rather than the colour detector over a rendered
  frame; nothing it fetches is hash-checked, where Python checks all 41 files; and there is no
  scripted pilot, so the pre-filled goal still needs a key before anything happens. All four
  are disclosed in `web/README.md` and in the page's own observations rather than left to be
  discovered.
- ⬜ **`GAIT_FLOOR_VY` was never measured.** The forward and turning floors were; the sideways
  one is assumed equal to the training maximum, so every lateral request is sent at full
  scale. The assumption is in `GAIT_THRESHOLD`'s note and in the state's `assumptions`, and
  the fix is the same script that produced the other two.
- 🔨 **A transcript from a live local server** (Ollama, vLLM, llama.cpp). None on the dev
  machine. PR #5's contributor reports `find-and-kick` against Qwen 2.5 Coder 14B through LM
  Studio on seeds 5 and 6, both successes with memory read and written, but no transcript from
  it is in the repository, so the README says exactly that.
- ⏸ **Exercise `remember` against a cloud model.** The scripted pilot has no script for it, so
  `--provider fake` writes episodes and never a note.
- ⏸ Verify the `gpt-5`, `grok-4` and `gemini-2.5-pro` default IDs against vendor docs. All are
  overridable with `QUACKD_MODEL`.
- ⏸ Upload `docs/assets/social-preview.png` under Settings → Social preview. There is no API
  for it.

## Release checklist

The one reusable thing the shipped milestones left behind. Every release since 0.1.0 has run
this, and the per-release detail is in [CHANGELOG.md](CHANGELOG.md).

1. All four CI gates green on `main`: `ruff check`, `ruff format --check`, `mypy` on 3.11 and
   3.12, `pytest` with `QUACKD_STRICT_SEEDS=1`, plus `quackd validate ducks/*.duck`.
2. Read the release note against the code before it ships. Every release so far has found
   claims that had gone stale between writing and tagging.
3. Annotated tag, pushed with `main`.
4. GitHub Release on `main` with the wheel and the sdist attached.
5. Publish to PyPI, and check the SHA256 of both files is identical in both places.
6. `uvx --from quackd==<version> quackd run find-and-kick --provider fake` from a clean
   install, twice, so the second run reads the first one's episode.
7. Update the About description (GitHub's cap is 350 characters) and Topics (cap 20).
