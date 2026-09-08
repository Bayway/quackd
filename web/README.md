# The browser demo

A static page that puts a Microduck in front of you with no install: type a sentence, and a
model you bring the key for turns it into the robot's own skills while quackd decides what
it is allowed to do. It is the same idea as `quackd run --goal "..." --robot microduck:mujoco`,
with the same physics and the same walking policy, in six modules of plain JavaScript with no
build step instead of Python.

Live at **https://rokbenko.github.io/quackd/** once Pages is enabled on the repository
(Settings → Pages → Source: GitHub Actions; `.github/workflows/pages.yml` does the rest).

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

## The switch

`quackd is on` runs the loop: a system prompt carrying the contract, one verb per turn, an
executor that checks the verb against the allowlist before the robot moves, and a budget
that ends the run whatever the model thinks.

`quackd is off` removes that layer, and only that layer. The physics, the robot and its
walking policy are identical; what is gone is anything that reads English. Typing a sentence
then gets the honest answer — this robot takes a twist, three numbers — and you drive it
yourself with `W A S D`. It is not a rigged comparison against a worse model: there is no
model, because before quackd there was nowhere to put one.

## What has been checked, and what has not

`web/src/microduck.js` and `web/src/pilot.js` are exercised under Node against the real
model and the real policy: the duck walks, the gait floor maps a twist the way the Python
backend does, a scripted pilot walks a square and closes it to 10 cm, and an unallowed verb
is refused while the run continues. That harness is a scratch script and is not in this
repository, so those four results are one measurement on one machine rather than something you
or CI can re-run. The rendering, the DOM and the recording have only been read, not run: they
need a browser, and the first person to open the page is the test.

`tests/test_web.py` is the floor under that. It runs in the ordinary suite, with no browser:
every id the JavaScript looks up exists in the page, nothing it hides is pinned visible by a
rule, no module reached from the page imports a CDN statically, the key is stored nowhere, and
each module parses under `node --check`. It is not the same as opening the page.

Two things here are deliberately not what the Python backend does, and neither is a bug:

- **Perception is geometric.** The bearing and distance in each observation are read from the
  simulator's ground truth inside a 90 degree cone out to 1.6 m, with no occlusion, so a ball
  behind the person is still seen. Python renders the head camera and runs a colour detector
  over the pixels. The page says so in the transcript as well as here.
- **Nothing fetched is hash-checked.** Python verifies all 41 files against a recorded sha256
  before MuJoCo or onnxruntime sees a byte. The browser trusts the two hosts and the transport.

## Layout

| File | What it is |
|---|---|
| `src/microduck.js` | the robot: MJCF, the 50 Hz loop, the policy, the gait floor |
| `src/pilot.js` | quackd itself: the clock, the verbs, the contract, the loop |
| `src/providers.js` | one tool call from Anthropic, OpenAI, Gemini or a local server |
| `src/view.js` | three.js built from the compiled model's own geoms |
| `src/record.js` | canvas capture, and the post the Share button writes |
| `src/app.js` | the page: the switch, the keyboard, the transcript |
