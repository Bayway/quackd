# Learned verbs (v2) — this is the shape; nothing here runs yet

**Status: reserved extension point.** The registry interface exists and is tested with a
dummy; no policy executes. PRs welcome — especially from people with a GPU and a duck.

## The idea

Today every verb is either a shipped robot behaviour or Python over shipped behaviours.
v2 adds a third kind: a **learned verb** = an ONNX policy plus metadata that registers as
one more verb, so the LLM can call `moonwalk` exactly like it calls `kick`. The LLM's job
(pick a verb) does not change; the vocabulary grows.

The training story is [Eureka](https://eureka-research.github.io/) /
[DrEureka](https://eureka-research.github.io/dr-eureka/)-style: an LLM writes a reward
function for a described skill, [`microduck_rl`](https://github.com/pollen-robotics/microduck_rl)
(mjlab / MuJoCo Warp + PPO) trains it, the export produces an ONNX policy, and quackd
registers it. quackd's part is the last step.

## The shape today

```python
from quackd.verbs.learned import LearnedVerbSpec, register_learned_verb
from quackd.verbs.registry import default_registry

spec = LearnedVerbSpec(
    name="moonwalk",
    description="Walk backwards smoothly for two seconds.",
    policy_path="policies/moonwalk.onnx",  # obs[1,61] -> actions[1,14], 50 Hz (upstream's contract)
    timeout_s=5.0,
    metadata={"reward": "eureka:v3", "trained_on": "mjlab 2026-08"},
)
verb = register_learned_verb(default_registry(), spec, runner=None)
```

`default_registry()` is the Microduck manifest's registry, which matters: a verb
that is not in a robot's manifest does not exist for that robot, so registering a learned
verb into a registry is only half the story. For it to be offered to the model, allowed by a
`.duck`, or listed by MCP on a given body, that body's manifest has to declare it. When
learned verbs ship for real, the spec becomes a `VerbSpec` in the owning adapter's manifest
([adapters.md](adapters.md), [manifest-spec.md](manifest-spec.md)); until then treat the call
above as a registry-level sketch, not a supported path on an arbitrary robot. A shipped
example of the shape already exists in a different guise: `pick` on the LeRobot arm is one
skill intent that the arm's own learned policy executes ([adapters/lerobot.md](adapters/lerobot.md)).

- `safety_class` is always `confirm`: an unproven policy asks a human first.
- `runner` is `async (spec, ctx) -> VerbResult`. Without one the verb explains that it is a
  v2 feature and fails cleanly (tested).
- A `.duck` can already *declare* them under `learned_verbs:` (parsed, validated, and
  rejected by `quackd validate` in v0.1 so nobody ships a file that silently does nothing).

## What upstream's policies look like (VERIFIED, 2026-08-28)

Every shipped policy is `obs[1,61] → actions[1,14]` at 50 Hz: 48 proprioception values +
a 13-value command `[vel(3), head(4), body(6)]`; the observation normaliser is baked into
the ONNX at export. `robotd` checks the shape at load and points at policies by role in
`robotd.toml` (`[policy] walk = ...`). Roles today: walking, standing, sit↔stand, ground
pick, kick left/right, roller, roller crouch, roulade.

## What has to exist before a runner is real

1. **A way to run a policy on the robot on demand.** Today `robotd` loads a fixed set of
   roles from config at startup. A learned verb needs either an upstream "policy slot" that
   can be hot-swapped over the socket (not designed yet), or a `robotd.toml` edit + restart
   (slow, but real). Track upstream; do not guess.
2. **A sim runner** for `sim2d` is out of scope — the cartoon has no joints. A MuJoCo
   backend (fetching upstream's CC BY-NC-SA meshes at runtime, never vendored — see
   [licenses.md](licenses.md)) is the honest place to run learned verbs before hardware.
3. **Provenance.** `metadata` should carry the reward text, the training run, and the
   eval numbers, so a `.duck` author knows what they are allowing.

## How to help

- Prototype a runner against `microduck_rl`'s evaluation env and open a PR that keeps
  `tests/test_registry.py::test_learned_verb_registers_and_runs` green.
- If you are upstream: a hot-swappable policy slot over the socket is the one API this
  needs. We will track it in `upstream_api.py` the day it is designed.
