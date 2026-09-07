"""Every word the LLM reads, in one place.

The system prompt carries the contract (in prose the model can act on) and the `.duck`
body verbatim. Each turn's observation is compact and structured — features, not frames —
with the image attached separately for providers that can see. One tool call per turn is
stated here *and* enforced by the loop; saying it is not the same as trusting it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from quackd.duckfile.schema import DuckFile
from quackd.perception.base import Detection, summarize_detections
from quackd.transport.base import DuckState
from quackd.verbs.registry import Verb, VerbResult

if TYPE_CHECKING:
    from quackd.adapters.manifest import RobotManifest

DUCK_BLURB = "a small biped duck robot (25 cm, 800 g)"

DECLARE_SUCCESS = {
    "name": "declare_success",
    "description": "Call when the success criteria are met. Say which criterion and what evidence you have.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Which criterion was met, and the evidence.",
            }
        },
        "required": ["reason"],
        "additionalProperties": False,
    },
}

DECLARE_FAILURE = {
    "name": "declare_failure",
    "description": "Call when the task cannot be completed (target not found, repeated failures, an abort condition).",
    "input_schema": {
        "type": "object",
        "properties": {"reason": {"type": "string"}},
        "required": ["reason"],
        "additionalProperties": False,
    },
}

META_TOOLS = [DECLARE_SUCCESS, DECLARE_FAILURE]
META_TOOL_NAMES = {t["name"] for t in META_TOOLS}

REMEMBER = {
    "name": "remember",
    "description": (
        "Save one short fact for FUTURE runs on this robot (where things usually are, what "
        "worked, what to avoid). It does not move the robot and does not count as a step. "
        "Do not repeat what the prompt already remembers."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "One sentence, concrete and reusable, e.g. 'the ball is usually near the left wall'.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional short labels (place, object, strategy).",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}
REMEMBER_NAME = REMEMBER["name"]


def build_system_prompt(
    duck: DuckFile,
    verbs: list[Verb],
    transport_name: str,
    manifest: RobotManifest | None = None,
    memory_text: str | None = None,
) -> str:
    """`memory_text` is what the robot remembers from earlier runs (`RobotMemory.recall`);
    None means memory is off for this run, "" means on but empty."""
    fm = duck.frontmatter
    blurb = manifest.blurb if manifest is not None and manifest.blurb else DUCK_BLURB
    names = {v.name for v in verbs}
    if "walk_to" in names:
        loop_verb = "walk_to"
    elif "go_to" in names or manifest is None or manifest.provides("go_to"):
        loop_verb = "go_to" if "go_to" in names or manifest is not None else "walk_to"
    else:
        loop_verb = "search_scan"
    verb_lines = "\n".join(f"- `{v.name}`: {v.description}" for v in verbs)
    success = "\n".join(f"- {s}" for s in fm.success)
    advisory = fm.advisory_abort_conditions
    abort_lines = (
        "\n".join(f"- {a}" for a in advisory) if advisory else "- (none beyond the enforced ones)"
    )
    persona = f"\n## Persona\n{fm.persona}\n" if fm.persona else ""
    memory = ""
    if memory_text is not None:
        remembered = memory_text.strip() or "(nothing yet — this is the first run on this robot)"
        memory = f"""
## What you remember from earlier runs on this robot
{remembered}

Call `remember` (one short sentence) when you learn something worth keeping for next time:
where an object usually is, which strategy worked, what to avoid. It moves nothing and
costs no step, though it does use one of your calls. Do not save what is already listed
above.
"""
    sim_note = ""
    if transport_name == "sim2d":
        sim_note = (
            "\nYou are in the built-in 2D simulator: a cartoon top-down world. Distances are "
            "metres, the arena is about 2 m across, and the ball is orange.\n"
        )
    elif transport_name == "mujoco":
        sim_note = (
            "\nYou are in the physics simulator (MuJoCo): a 2 m arena with low walls, an orange "
            "ball that rolls when kicked, and a blue person marker. Distances are metres. This is "
            "a real biped on its own learned gait, not a drawing, so two things differ. It does "
            "not step at all below about 0.22 m/s or 1.0 rad/s, and quackd raises a smaller "
            "twist to that floor and drops a tiny one to zero. And it achieves roughly half of "
            "what it is asked. Read `pose` in the state after every move and correct from it, "
            "rather than trusting the numbers you sent.\n"
        )
    return f"""You are the brain of {blurb}. You are a high-level pilot:
you choose ONE verb per turn; the robot's own controllers handle balance and gait, and composite
verbs like `{loop_verb}` close their own loops on the camera. Do not micro-manage.

## Rules (enforced by the executor — not optional)
- Call exactly one tool per turn. Never zero, never two.
- Only these verbs are allowed: {", ".join(fm.verbs.allow)}. Anything else is refused.
- Budgets: {fm.budgets.max_steps} steps, {fm.budgets.max_minutes:g} minutes, {fm.budgets.max_llm_calls} LLM calls. The run stops when any is hit.
- Verbs marked confirm ({", ".join(fm.verbs.confirm) or "none"}) ask a human before running.
- When a success criterion is met, call `declare_success`. If the task is impossible, call `declare_failure`.

## Success criteria
{success}

## Abort conditions you must respect yourself
{abort_lines}

## Verbs
{verb_lines}
{persona}{memory}{sim_note}
## Task file: {fm.name} — {fm.description}

{duck.body}
"""


def build_observation_text(
    *,
    step: int,
    max_steps: int,
    state: DuckState,
    detections: list[Detection],
    last_verb: str | None,
    last_result: VerbResult | None,
    budget_status: str,
) -> str:
    lines = [
        f"[step {step}/{max_steps} · {budget_status}]",
        f"state: {state.summary()}",
        f"camera: {summarize_detections(detections)}",
    ]
    if last_verb is not None and last_result is not None:
        lines.append(
            f"last verb `{last_verb}`: {'ok' if last_result.ok else 'FAILED'} — {last_result.summary}"
        )
    lines.append("Choose exactly one tool.")
    return "\n".join(lines)


def observation_features(
    *,
    state: DuckState,
    detections: list[Detection],
    last_verb: str | None,
    last_result: VerbResult | None,
    allowed: list[str],
) -> dict[str, Any]:
    return {
        "state": state.model_dump(),
        "detections": [d.model_dump() for d in detections],
        "last_result": (
            {
                "verb": last_verb,
                "ok": last_result.ok,
                "summary": last_result.summary,
                "data": last_result.data,
            }
            if last_result is not None
            else None
        ),
        "allowed": allowed,
    }
