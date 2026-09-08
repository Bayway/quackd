# The browser demo

A static page that puts a Microduck in front of you with no install: type a sentence, and a
model you bring the key for turns it into the robot's own skills while quackd decides what
it is allowed to do. The keyboard is live the whole time, next to the box you type in, so the
two ways of driving a robot sit a centimetre apart. It is the same idea as
`quackd run --goal "..." --robot microduck:mujoco`, with the same physics and the same
walking policy, in six modules of plain JavaScript with no build step instead of Python.

It is meant to live at **<https://www.quackd.org>**, deployed from this directory by Vercel.
It is not there yet: that domain currently serves the quackd-web landing page, which is a
separate project, so read the address as where this is going rather than where it is. There
is no build step either way: `vercel.json` at the repository root serves `web/` as it stands,
because everything heavy here is a CDN URL the page fetches at run time.

## Running it locally

There is no build step and no dependencies to install. It needs a server only because
browsers refuse ES modules over `file://`:

```bash
python -m http.server 8000 --directory web
# then open http://localhost:8000
```

## What loads, and from where

Nothing in this directory is a robot. Everything heavy is fetched by the visitor's browser
from whoever owns it, which is also how the licences stay clean — the Microduck's 3D model
files are CC BY-NC-SA and quackd redistributes none of them.

| What | From | Size |
|---|---|---|
| MuJoCo, compiled to WebAssembly | `@mujoco/mujoco` 3.12.0 on jsDelivr (Apache-2.0) | 10 MB |
| onnxruntime-web, to run the policy | jsDelivr (MIT) | 13 MB |
| three.js, to draw it | jsDelivr (MIT) | 0.7 MB |
| `robot_walk.xml` and 38 STL meshes | `pollen-robotics/microduck_rl` at a pinned commit | 22 MB |
| `alpha_walking.onnx`, `alpha_stand.onnx` | `pollen-robotics/microduck-policies` (Apache-2.0) | 1.6 MB |

About 45 MB the first time, cached by the browser afterwards. Both upstream hosts send
`Access-Control-Allow-Origin: *`, so no proxy is involved.

Two smaller origins joined that list with the restyle: `fonts.googleapis.com` serves the
stylesheet for Nunito Sans and DM Mono and `fonts.gstatic.com` the faces themselves. They are
named in `SECURITY.md` with the rest. Neither serves script, so neither can execute in the
page the way the jsDelivr tags can, and both families have a full fallback stack behind them
in `style.css`, so a visitor who blocks them loses the typeface and nothing else.

What the page does serve from this directory is three PNGs, and they are quackd's own:
`assets/duck-mark.png` is the mark in the header and on the loading panel,
`assets/favicon-96.png` is the tab icon and `assets/apple-touch-icon.png` the home-screen
one. They replaced a 🦆 emoji and an inline-SVG favicon built around the same emoji. There
are no other images: the arena is drawn with WebGL and the film grain is a data URI.

## Your API key

It is read from an input, kept in a variable for the life of the tab, and sent straight to
the vendor from your browser. It is never stored, never logged, and there is no server here
to proxy it through. Every call is billed to you.

- **Anthropic** needs the `anthropic-dangerous-direct-browser-access: true` header, which
  the page sends. That header is exactly what its name says: your key is in a web page.
- **Gemini** and **OpenAI** work with their normal browser CORS.
- **Local models** need no key. Ollama must be told to accept the page:
  `OLLAMA_ORIGINS=* ollama serve`. Any OpenAI-compatible server (llama.cpp, vLLM, LM Studio)
  works the same way — change the base URL. Browsers treat `http://localhost` as trustworthy,
  so an https page may call it.

## Two hands on the same duck

The sentence box and the keyboard are both live, always, and neither takes turns with the
other. There is no mode to flip before you can drive.

The keys write a twist — `vx, vy, wz` — and a head angle, which is the entire interface the
hardware has. `W`/`S` walk, `A`/`D` turn, `Shift` with `A`/`D` strafes instead of turning,
`Q`/`E` look left and right, `G` centres the head, `Space` stops (a latch, not a term in the
twist: a key you are physically holding is dropped and has to be pressed again), `K` kicks,
`R` stands the duck up after a fall, `O` reads the state into the log, `1`/`2` change camera
and `Esc` hands the keyboard back to the arena from wherever focus is. The legend on the
page is that same list, and the keycaps
light up as you hold them.

Underneath there are exactly two learned policies: `alpha_stand` stands the duck up and
`alpha_walking` walks it. The kick is quackd's own scripted impulse and not a policy. None of
it reads English.

## The switch, and what it decides now

`quackd is on` runs the loop: a system prompt carrying the contract, one verb per turn, an
executor that checks the verb against the allowlist before the robot moves, and a budget that
ends the run whatever the model thinks.

`quackd is off` removes that layer, and only that layer. The physics, the robot and its two
policies are identical; what is gone is anything that reads English, so typing a sentence
gets the honest answer — this robot takes three numbers and a head angle, and it has never
seen your words. It is not a rigged comparison against a worse model: there is no model,
because before quackd there was nowhere to put one.

What the switch no longer decides is whether you may drive. It used to: the cockpit was
hidden while quackd was on and the keydown handler returned early on the toggle's state, so
the demo's argument arrived as an either/or. The keyboard was never the layer, and it is not
gated on the layer any more.

## Barge-in

A key that would move the robot takes it, mid-run, at once. The run is aborted, the request
to the model is aborted with it — the signal reaches `fetch`, so an abandoned turn stops
being billed — and the transcript records the handover with the key that did it. A key that
only reads (`O`, and the camera keys) never barges in: you can inspect the state or change
the view without stopping the run. That is the whole rule — a key takes control if and only
if it would move the robot.

The handover itself is one flag, not a negotiation. `Runtime.start` re-asserts the hand's
twist every 20 ms control tick, immediately before the physics reads it, while the pilot
writes at most at 10 Hz between ticks, so setting `runtime.manual` synchronously in the
keydown handler is the handover; the abort that follows is bookkeeping. The invariant is
`runtime.manual === (running === null)`.

## What has been checked, and what has not

`web/src/microduck.js` and `web/src/pilot.js` were exercised under Node against the real
model and the real policy: the duck walks, the gait floor maps a twist the way the Python
backend does, a scripted pilot walks a square and closes it to 10 cm, and an unallowed verb
is refused while the run continues. That harness is a scratch script and is not in this
repository, so those four results are one measurement on one machine rather than something
you or CI can re-run — and both files have changed since, in the abort path and in the
arena's geometry, with nothing in this repository able to re-run it.

The rendering, the DOM and the recording have only been read, not run: they need a browser,
and the first person to open the page is the test. That now covers the newest work as well —
the dual control, the barge-in, the keycaps, the restyled page and the vendored mark have all
been reasoned about rather than watched. Nobody has yet held `W` in a real browser.

`tests/test_web.py` is the floor under that. It runs in the ordinary suite, with no browser:
every id the JavaScript looks up exists in the page, nothing it hides is pinned visible by a
rule, no module reached from the page imports a CDN statically, the key is stored nowhere,
each module parses under `node --check`, every asset the page asks for is on disk here, the
header carries the vendored mark rather than an emoji, the keydown handler reads nothing
about the switch, and the person marker is neither the old blue nor renamed. It is not the
same as opening the page.

Four things here are deliberately not what the Python backend does, and none is a bug:

- **Perception is geometric.** The bearing and distance in each observation are read from the
  simulator's ground truth inside a 90 degree cone out to 1.6 m, with no occlusion, so a ball
  behind the person is still seen. Python renders the head camera and runs a colour detector
  over the pixels. The page says so in the transcript as well as here.
- **The person marker is purple here and blue in Python.** `quackd/sim3d/scene.py` picks that
  blue because `render.py`'s HSV detector looks for it: over there the colour is how the duck
  sees a person at all. Nothing in the browser reads a pixel, so the marker is a plinth, a
  slimmer post and a spherical head in quackd's own purple instead of a detector target. It
  is still one static body called `person`, still a metre tall, still standing on a footprint
  the width of the old cylinder and still measured from the body's own position, so
  `observe()`, the `person` label and the "walk to the person and quack" example all aim at
  exactly what they did.
- **Nothing fetched is hash-checked.** Python verifies all 41 files against a recorded sha256
  before MuJoCo or onnxruntime sees a byte. The browser trusts the two hosts and the transport.
- **A seed means the same distributions, not the same layout.** The arena here is laid out by a
  xorshift and in Python by numpy's PCG64. The spawn ranges and the rejection rules match; the
  stream does not, so seed 3 is a different arena in each.

## Layout

| File | What it is |
|---|---|
| `index.html` | the page: the fonts, the onnxruntime tag, the copy, the keycap legend |
| `style.css` | hand-authored, in the quackd-web design language |
| `assets/` | quackd's own mark: the header logo, the favicon, the touch icon |
| `src/microduck.js` | the robot: MJCF, the 50 Hz loop, the policy, the gait floor |
| `src/pilot.js` | quackd itself: the clock, the verbs, the contract, the loop |
| `src/providers.js` | one tool call from Anthropic, OpenAI, Gemini or a local server |
| `src/view.js` | three.js built from the compiled model's own geoms |
| `src/record.js` | canvas capture, and the post the Share button writes |
| `src/app.js` | the page: the switch, the keyboard, the barge-in, the transcript |
