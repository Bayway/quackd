/**
 * The page: load the duck, wire the switch, run the pilot, record the result.
 *
 * The switch is the point of this demo. With quackd on, a sentence becomes a sequence of
 * the robot's own verbs, chosen by a model and checked against a contract before anything
 * moves. With quackd off, the sentence goes nowhere — because it has nowhere to go. A
 * Microduck ships with nine learned policies and takes a twist: three numbers. That is the
 * honest "before", and it is why the off switch does not simulate a worse model or a
 * clumsier robot. It removes the layer and hands you the keyboard.
 */

import { Microduck, UPSTREAM } from "./microduck.js";
import { DEFAULT_CONTRACT, Runtime, pilot } from "./pilot.js";
import { PROVIDERS, makeProvider } from "./providers.js";
import { Recorder, shareUrl } from "./record.js";

const $ = (id) => document.getElementById(id);
const MANUAL_SPEED = 0.3, MANUAL_TURN = 1.2;

const ui = {
  loading: $("loading"), phase: $("loading-phase"), bar: $("loading-bar"),
  canvas: $("view"), readout: $("readout"), transcript: $("transcript"),
  goalForm: $("goal-form"), goal: $("goal"), run: $("run"), stopRun: $("stop-run"),
  reset: $("reset"), toggle: $("quackd-on"), toggleLabel: $("toggle-label"),
  toggleNote: $("toggle-note"), keyBox: $("key-box"), manual: $("manual"),
  provider: $("provider"), model: $("model"), key: $("key"), baseUrl: $("base-url"),
  providerNote: $("provider-note"), record: $("record"), save: $("save"), share: $("share"),
  clear: $("clear"),
};

let duck, view, runtime, recorder;
let running = null;
const held = new Set();

// ── one place every failure ends up ─────────────────────────────────────────────────────

/**
 * Show a failure instead of freezing on one. Emscripten and embind can throw a bare number
 * or a string, so `error.message` alone prints "undefined" for exactly the failures that are
 * hardest to guess at.
 */
function fail(error, where) {
  const message = String(error?.message ?? error ?? "something went wrong");
  if (!ui.loading.hidden) {
    ui.phase.textContent = message;
    ui.phase.classList.add("bad");
  }
  line("end error", `<b>${escape(where)}</b> ${escape(message)}`);
  return message;
}

addEventListener("error", (event) => fail(event.error ?? event.message, "page"));
addEventListener("unhandledrejection", (event) => fail(event.reason, "promise"));

// ── boot ────────────────────────────────────────────────────────────────────────────────

async function boot() {
  // Cheapest check first, so a missing prerequisite names itself rather than arriving as a
  // failure 45 MB later. Each of these used to be a dead page: the WebGL one threw outside
  // the try, and a blocked CDN broke the module graph before any listener was attached.
  ui.phase.textContent = "checking this browser";
  if (!globalThis.ort) {
    throw new Error(
      "onnxruntime did not arrive from cdn.jsdelivr.net. This page ships none of its own " +
        "dependencies on purpose, so a blocked CDN stops it here."
    );
  }
  if (!document.createElement("canvas").getContext("webgl2")) {
    throw new Error("this browser has no WebGL2, so the arena cannot be drawn");
  }
  // Dynamic, so three.js failing to load is a message rather than a module graph that never
  // evaluates and a page that sits on "starting" with no listeners and no error.
  const { View } = await import("./view.js");
  duck = await Microduck.load({
    onProgress: ({ phase, loaded, total }) => {
      ui.phase.textContent = `${phase} — ${loaded} of ${total}`;
      ui.bar.style.width = `${Math.round((loaded / Math.max(total, 1)) * 100)}%`;
    },
  });
  view = new View(ui.canvas, duck);
  runtime = new Runtime(duck, { onError: (error) => fail(error, "physics") });
  recorder = new Recorder(ui.canvas);
  for (const button of [ui.run, ui.reset, ui.record]) button.disabled = false;
  ui.loading.hidden = true;
  runtime.start(() => {
    view.frame();
    const [vx, vy, wz] = duck.sent;
    ui.readout.textContent =
      `twist ${vx.toFixed(2)}, ${vy.toFixed(2)}, ${wz.toFixed(2)} · ${duck.posture}` +
      (recorder.recording ? ` · ● ${recorder.seconds.toFixed(0)}s` : "");
  });
}

// ── the switch ──────────────────────────────────────────────────────────────────────────

function applyToggle() {
  const on = ui.toggle.checked;
  ui.toggleLabel.textContent = on ? "quackd is on" : "quackd is off";
  ui.toggleNote.textContent = on
    ? "An LLM reads your sentence and picks the robot's skills."
    : "Nothing here reads English. The duck takes a twist, and you are holding it.";
  ui.keyBox.hidden = !on;
  ui.manual.hidden = on;
  ui.run.textContent = on ? "Run" : "Send";
  if (runtime) {
    runtime.manual = !on;
    runtime.manualTwist = [0, 0, 0];
    duck.setTwist(0, 0, 0);
  }
  document.body.classList.toggle("no-quackd", !on);
}

ui.toggle.addEventListener("change", () => { abortRun(); applyToggle(); });

// ── running ─────────────────────────────────────────────────────────────────────────────

ui.goalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const goal = ui.goal.value.trim();
  if (!goal) return;
  if (!ui.toggle.checked) { refuse(goal); return; }
  if (running) return;
  await run(goal);
});

function refuse(goal) {
  // The whole point of the off switch: say exactly why nothing happened.
  say({ kind: "refused", goal });
}

async function run(goal) {
  let provider;
  try {
    provider = makeProvider({
      provider: ui.provider.value,
      key: ui.key.value.trim(),
      model: ui.model.value.trim(),
      baseUrl: ui.baseUrl.value.trim(),
    });
  } catch (error) {
    say({ kind: "end", outcome: "error", reason: error.message });
    return;
  }
  const controller = new AbortController();
  running = controller;
  ui.run.disabled = true;
  ui.stopRun.disabled = false;
  try {
    await pilot({
      runtime, goal, provider, contract: DEFAULT_CONTRACT,
      signal: controller.signal, onEvent: say,
    });
  } finally {
    running = null;
    ui.run.disabled = false;
    ui.stopRun.disabled = true;
    duck.setTwist(0, 0, 0);
    showShare(goal);
  }
}

function abortRun() { running?.abort(); }
ui.stopRun.addEventListener("click", abortRun);
ui.reset.addEventListener("click", () => { abortRun(); duck.reset(); say({ kind: "reset" }); });

// ── the transcript ──────────────────────────────────────────────────────────────────────

function line(className, html) {
  const item = document.createElement("li");
  item.className = className;
  item.innerHTML = html;
  ui.transcript.append(item);
  ui.transcript.scrollTop = ui.transcript.scrollHeight;  // overflow is on the list itself
}

const escape = (value) =>
  String(value).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function say(event) {
  switch (event.kind) {
    case "start":
      ui.transcript.replaceChildren();
      line("goal", `<b>goal</b> ${escape(event.goal)}
        <span class="fine">contract: ${event.contract.allow.length} verbs allowed, ${event.contract.maxSteps} steps</span>`);
      break;
    case "call":
      line("call", `<b>${escape(event.name)}</b>(${escape(JSON.stringify(event.args ?? {}))})`);
      break;
    case "result":
      line(event.ok ? "result" : "result bad", escape(event.summary));
      break;
    case "end":
      line(`end ${event.outcome}`, `<b>${escape(event.outcome)}</b> ${escape(event.reason)}`);
      break;
    case "reset":
      line("note", "the duck is back where it started");
      break;
    case "refused":
      line("refused",
        `<b>no brain attached</b> This robot understands a twist — three numbers, ` +
        `<code>vx, vy, wz</code> — and nine learned policies. It has never seen the words ` +
        `<em>${escape(event.goal)}</em>, and nothing in it can turn them into a step. ` +
        `Drive it yourself with the keys, or switch quackd on.`);
      break;
    default:
      break;
  }
}

ui.clear.addEventListener("click", () => ui.transcript.replaceChildren());

// ── manual piloting, when quackd is off ─────────────────────────────────────────────────

function manualTwist() {
  let vx = 0, vy = 0, wz = 0;
  if (held.has("KeyW")) vx += MANUAL_SPEED;
  if (held.has("KeyS")) vx -= MANUAL_SPEED;
  if (held.has("KeyA")) wz += MANUAL_TURN;
  if (held.has("KeyD")) wz -= MANUAL_TURN;
  if (held.has("Space")) { vx = 0; vy = 0; wz = 0; }
  return [vx, vy, wz];
}

addEventListener("keydown", (event) => {
  // Anything that has its own use for a key keeps it. `preventDefault` used to run before the
  // quackd-on check, so Space stopped activating every focused button and <summary> on the
  // page, in both modes, which is a WCAG 2.1.1 failure for a keyboard-only visitor.
  if (event.target?.matches?.("input, textarea, select, button, summary, a, [contenteditable]")) {
    return;
  }
  if (ui.toggle.checked || !runtime) return;
  if (["Space", "KeyW", "KeyA", "KeyS", "KeyD"].includes(event.code)) event.preventDefault();
  held.add(event.code);
  if (event.code === "KeyQ") duck.setHead((duck.head[0] ?? 0) + 0.3);
  if (event.code === "KeyE") duck.setHead((duck.head[0] ?? 0) - 0.3);
  if (event.code === "KeyK") duck.kick();
  runtime.manualTwist = manualTwist();
});
addEventListener("keyup", (event) => {
  held.delete(event.code);
  if (runtime && !ui.toggle.checked) runtime.manualTwist = manualTwist();
});

// ── camera, recording, sharing ──────────────────────────────────────────────────────────

for (const button of document.querySelectorAll("[data-camera]")) {
  button.addEventListener("click", () => {
    for (const other of document.querySelectorAll("[data-camera]")) other.classList.remove("on");
    button.classList.add("on");
    view?.setMode(button.dataset.camera);
  });
}

ui.record.addEventListener("click", async () => {
  if (!Recorder.supported) { say({ kind: "end", outcome: "error", reason: "this browser cannot record a canvas" }); return; }
  if (recorder.recording) {
    await recorder.stop();
    ui.record.textContent = "● Record";
    ui.record.classList.remove("live");
    ui.save.disabled = !recorder.blob;
    showShare(ui.goal.value);
  } else {
    recorder.start();
    ui.record.textContent = "■ Stop recording";
    ui.record.classList.add("live");
    ui.save.disabled = true;
  }
});

ui.save.addEventListener("click", () => recorder.save());

function showShare(goal) {
  ui.share.hidden = false;
  ui.share.href = shareUrl(goal, { quackd: ui.toggle.checked });
  ui.share.title = recorder?.blob
    ? "Opens X with the post written. Save the clip first and attach it there."
    : "Opens X with the post written.";
}

// ── providers ───────────────────────────────────────────────────────────────────────────

for (const [id, spec] of Object.entries(PROVIDERS)) {
  const option = document.createElement("option");
  option.value = id;
  option.textContent = spec.label;
  ui.provider.append(option);
}

function applyProvider() {
  const spec = PROVIDERS[ui.provider.value];
  ui.model.value = spec.defaultModel;
  // Cleared on every change, in both directions. Disabling the field left the value readable,
  // so a key pasted for Anthropic was still there when the visitor switched to a local server
  // and went out as a bearer token to whatever host they had typed in the box below.
  ui.key.value = "";
  ui.key.placeholder = spec.keyPlaceholder;
  ui.key.disabled = false;
  ui.baseUrl.hidden = spec.needsKey;
  if (!spec.needsKey) ui.baseUrl.value ||= spec.baseUrl;
  ui.providerNote.textContent = "";
  if (spec.note) {
    ui.providerNote.textContent = spec.note;
  } else {
    // built rather than interpolated: an href is a URL context, and escape() is not enough
    ui.providerNote.append("Need a key? ");
    const link = document.createElement("a");
    link.href = spec.keyUrl;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = spec.label;
    ui.providerNote.append(link, ".");
  }
}

ui.provider.addEventListener("change", applyProvider);
for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => { ui.goal.value = chip.textContent; ui.goal.focus(); });
}

$("model-link").href = UPSTREAM.model;
applyProvider();
applyToggle();
boot().catch((error) => fail(error, "boot"));
