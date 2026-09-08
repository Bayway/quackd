/**
 * quackd, in about two hundred lines: the loop, the verbs and the contract.
 *
 * This is the browser's version of `quackd/agent/loop.py`, `quackd/verbs/core.py` and
 * `quackd/safety.py`, kept deliberately small so the whole idea fits on one screen. The
 * model never sees a joint, a motor or a pixel. It sees a list of verbs the robot's own
 * manifest declares, one observation per turn, and a contract: which verbs are allowed,
 * how many steps it gets, and how long. It answers with exactly one verb per turn. The
 * executor checks that verb against the contract before the robot moves, and the run stops
 * when the budget is spent whatever the model thinks.
 *
 * The `Runtime` underneath owns the 50 Hz clock. Verbs ask it for simulated seconds; it
 * paces those against the wall clock so the page shows real time and a recording plays
 * back at the speed it happened.
 */

import { ACHIEVED_FRACTION, CONTROL_DT, GAIT_FLOOR, HEAD_YAW_LIMIT } from "./microduck.js";

const MOVE_RESEND_S = 0.1; // the twist is re-sent at 10 Hz or the deadman zeroes it

export class Runtime {
  constructor(duck) {
    this.duck = duck;
    this.running = false;
    this.manualTwist = [0, 0, 0];
    this.manual = false;
    this._waiters = [];
    this._onFrame = null;
  }

  start(onFrame) {
    this._onFrame = onFrame;
    if (this.running) return;
    this.running = true;
    let carry = 0;
    let previous = performance.now();
    const tick = async (now) => {
      if (!this.running) return;
      carry += Math.min(0.1, (now - previous) / 1000); // never simulate a lost tab
      previous = now;
      while (carry >= CONTROL_DT) {
        carry -= CONTROL_DT;
        if (this.manual) this.duck.setTwist(...this.manualTwist);
        await this.duck.step();
        this._wake(CONTROL_DT);
      }
      this._onFrame?.();
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  stop() { this.running = false; }

  /** Let `seconds` of simulated time pass. Verbs never touch the clock directly. */
  sleep(seconds) {
    if (seconds <= 0) return Promise.resolve();
    return new Promise((resolve) => this._waiters.push({ left: seconds, resolve }));
  }

  _wake(dt) {
    if (!this._waiters.length) return;
    const still = [];
    for (const waiter of this._waiters) {
      waiter.left -= dt;
      if (waiter.left <= 0) waiter.resolve();
      else still.push(waiter);
    }
    this._waiters = still;
  }
}

// ── the verbs, as the Microduck's manifest declares them ───────────────────────────────

export const VERBS = {
  move: {
    description:
      "Walk with a velocity for a duration. Use small values; the robot is 25 cm tall. " +
      `This body does not step below ${GAIT_FLOOR.vx} m/s or ${GAIT_FLOOR.wz} rad/s, and ` +
      `achieves about ${ACHIEVED_FRACTION} of what it is asked, so read the pose afterwards.`,
    params: {
      type: "object",
      properties: {
        vx: { type: "number", description: "Forward m/s (negative = back).", minimum: -0.3, maximum: 0.3 },
        vy: { type: "number", description: "Left m/s (negative = right).", minimum: -0.2, maximum: 0.2 },
        wz: { type: "number", description: "Turn rate rad/s (+ = left).", minimum: -1.5, maximum: 1.5 },
        duration_s: { type: "number", description: "How long to hold this velocity.", minimum: 0.1, maximum: 10 },
      },
      required: ["duration_s"],
      additionalProperties: false,
    },
    async run(runtime, p) {
      const { vx = 0, vy = 0, wz = 0, duration_s = 1 } = p;
      const slices = Math.max(1, Math.round(duration_s / MOVE_RESEND_S));
      for (let i = 0; i < slices; i++) {
        runtime.duck.setTwist(vx, vy, wz); // re-sent, exactly as the real verb does
        await runtime.sleep(duration_s / slices);
      }
      runtime.duck.setTwist(0, 0, 0);
      const sent = runtime.duck.sent;
      const note = sent.some((v, i) => Math.abs(v - [vx, vy, wz][i]) > 1e-6)
        ? ` (the gait floor turned that into ${sent.map((v) => v.toFixed(2)).join(", ")})`
        : "";
      const { x, y, theta } = runtime.duck.pose;
      return `walked vx=${vx} vy=${vy} wz=${wz} for ${duration_s}s${note}; now at ` +
        `(${x.toFixed(2)}, ${y.toFixed(2)}) facing ${((theta * 180) / Math.PI).toFixed(0)} degrees`;
    },
  },
  stop: {
    description: "Stop moving immediately (zero velocity). Always allowed.",
    params: { type: "object", properties: {}, additionalProperties: false },
    async run(runtime) {
      runtime.duck.setTwist(0, 0, 0);
      return "stopped (velocity zeroed)";
    },
  },
  report_state: {
    description: "Report the robot's state: posture, pose, what the camera can see.",
    params: { type: "object", properties: {}, additionalProperties: false },
    async run(runtime) {
      return JSON.stringify(runtime.duck.observe());
    },
  },
  gaze: {
    description: "Point the head at a bearing in degrees (+ = left), up to 60 either way.",
    params: {
      type: "object",
      properties: { bearing_deg: { type: "number", minimum: -90, maximum: 90 } },
      required: ["bearing_deg"],
      additionalProperties: false,
    },
    async run(runtime, p) {
      const clamped = runtime.duck.setHead((p.bearing_deg * Math.PI) / 180);
      await runtime.sleep(0.6); // the neck is a servo the policy drives, not a teleport
      const limit = ((HEAD_YAW_LIMIT * 180) / Math.PI).toFixed(0);
      return `looking ${p.bearing_deg} degrees${clamped ? ` (clamped to ${limit})` : ""}`;
    },
  },
  kick: {
    description:
      "Kick forward with one leg. Only connects if the ball is under 0.3 m away and roughly ahead.",
    params: {
      type: "object",
      properties: { leg: { type: "string", enum: ["left", "right"] } },
      additionalProperties: false,
    },
    async run(runtime, p) {
      runtime.duck.kick(p.leg ?? "right");
      await runtime.sleep(1.5);
      const moved = runtime.duck.lastKickBallMoved;
      return moved === null ? "kicked" : `kicked; the ball moved ${moved.toFixed(2)} m`;
    },
  },
  say: {
    description: "Say something. The robot has seven duck tones and no speech.",
    params: {
      type: "object",
      properties: { text: { type: "string", maxLength: 200 } },
      required: ["text"],
      additionalProperties: false,
    },
    async run(runtime, p) {
      runtime.said = p.text;
      return `said ${JSON.stringify(p.text)} as a quack`;
    },
  },
  stand_up: {
    description: "Recover to standing after a fall.",
    params: { type: "object", properties: {}, additionalProperties: false },
    async run(runtime) {
      runtime.duck.standUp();
      await runtime.sleep(1.0);
      return runtime.duck.posture === "standing" ? "upright" : "still down";
    },
  },
};

const META = {
  declare_success: {
    description: "Call when the goal is met. Say which part of the goal, and your evidence.",
    params: {
      type: "object",
      properties: { reason: { type: "string" } },
      required: ["reason"],
      additionalProperties: false,
    },
  },
  declare_failure: {
    description: "Call when the goal cannot be reached (repeated failures, nothing found).",
    params: {
      type: "object",
      properties: { reason: { type: "string" } },
      required: ["reason"],
      additionalProperties: false,
    },
  },
};

export const DEFAULT_CONTRACT = {
  allow: ["move", "stop", "report_state", "gaze", "kick", "say", "stand_up"],
  maxSteps: 18,
  maxMinutes: 3,
};

export function toolSchemas(contract) {
  const tools = [];
  for (const [name, verb] of Object.entries(VERBS)) {
    if (contract.allow.includes(name)) {
      tools.push({ name, description: verb.description, input_schema: verb.params });
    }
  }
  for (const [name, meta] of Object.entries(META)) {
    tools.push({ name, description: meta.description, input_schema: meta.params });
  }
  return tools;
}

export function systemPrompt(goal, contract) {
  return `You are the brain of a Microduck: a small biped duck robot, 25 cm tall, 800 g.
You are a high-level pilot. You choose ONE verb per turn; the robot's own controllers handle
balance and gait. You are in a physics simulator: a 2 m arena with low walls, an orange ball
that rolls when it is kicked, and a blue person marker. Distances are metres.

## Rules, enforced by the executor and not optional
- Call exactly one tool per turn. Never zero, never two.
- Only these verbs exist: ${contract.allow.join(", ")}. Anything else is refused.
- Budget: ${contract.maxSteps} steps and ${contract.maxMinutes} minutes. The run stops when either is spent.
- Call declare_success when the goal is met, or declare_failure when it cannot be.

## This body
It walks on a learned policy, not on arithmetic. It does not step at all below about
${GAIT_FLOOR.vx} m/s or ${GAIT_FLOOR.wz} rad/s, and it achieves about ${ACHIEVED_FRACTION} of what it is asked. Every
observation carries the pose it actually reached: steer from that, not from the numbers you
sent. To walk a shape, walk a leg, read the pose, correct, and repeat.

## The goal
${goal}`;
}

export function observationText(duck, step, contract, last) {
  const state = duck.observe();
  const lines = [
    `[step ${step}/${contract.maxSteps} - ${state.sim_time.toFixed(1)}s of ${contract.maxMinutes * 60}s]`,
    `state: posture=${state.posture} pose=(${state.pose.x}, ${state.pose.y}, ${state.pose.theta} rad) head=${state.head_yaw_deg} deg`,
    `camera: ${state.detections.length
      ? state.detections.map((d) => `${d.label} at ${d.bearing_deg} degrees, about ${d.distance_m} m`).join("; ")
      : "nothing detected"}`,
  ];
  if (last) lines.push(`last verb \`${last.name}\`: ${last.ok ? "ok" : "FAILED"} - ${last.summary}`);
  lines.push("Choose exactly one tool.");
  return lines.join("\n");
}

/** One run of the loop. `onEvent` is how the page draws the transcript. */
export async function pilot({ runtime, goal, provider, contract = DEFAULT_CONTRACT, onEvent, signal }) {
  const duck = runtime.duck;
  const history = [];
  const startedAt = duck.t;
  let last = null;
  onEvent({ kind: "start", goal, contract });

  for (let step = 0; step < contract.maxSteps; step++) {
    if (signal?.aborted) { onEvent({ kind: "end", outcome: "aborted", reason: "you stopped the run" }); return; }
    if (duck.t - startedAt > contract.maxMinutes * 60) {
      onEvent({ kind: "end", outcome: "budget", reason: "the time budget is spent" });
      return;
    }
    const observation = observationText(duck, step, contract, last);
    onEvent({ kind: "observation", text: observation, step });
    let call;
    try {
      call = await provider.step({
        system: systemPrompt(goal, contract),
        history,
        observation,
        tools: toolSchemas(contract),
      });
    } catch (error) {
      onEvent({ kind: "end", outcome: "error", reason: String(error.message || error) });
      return;
    }
    history.push({ observation, call });
    onEvent({ kind: "call", name: call.name, args: call.arguments });

    if (call.name === "declare_success" || call.name === "declare_failure") {
      onEvent({
        kind: "end",
        outcome: call.name === "declare_success" ? "success" : "failure",
        reason: call.arguments?.reason ?? "",
      });
      return;
    }
    const verb = VERBS[call.name];
    if (!verb || !contract.allow.includes(call.name)) {
      // Refused, and the run continues: the model is told and may choose differently. This
      // is the executor's job, and the reason a contract is worth having.
      last = { name: call.name, ok: false, summary: `refused: ${call.name} is not in this task's allowlist` };
      onEvent({ kind: "result", ...last });
      continue;
    }
    try {
      const summary = await verb.run(runtime, call.arguments ?? {});
      last = { name: call.name, ok: true, summary };
    } catch (error) {
      runtime.duck.setTwist(0, 0, 0); // a verb that threw leaves the robot stopped
      last = { name: call.name, ok: false, summary: String(error.message || error) };
    }
    onEvent({ kind: "result", ...last });
  }
  runtime.duck.setTwist(0, 0, 0);
  onEvent({ kind: "end", outcome: "budget", reason: `the ${contract.maxSteps} step budget is spent` });
}
