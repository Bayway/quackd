"""The browser demo, checked by the only means the repository has.

Nothing in `web/` had ever been run in a browser and no job read the directory, so the page
did not work: a CSS rule kept the loading panel over the canvas for good, a blocked CDN left
a dead page with no message, and every listener was live during a 45 MB load, dereferencing
objects that did not exist yet.

None of that needs a browser to catch. What it needs is somebody checking that the ids the
JavaScript looks up exist, that the classes it toggles mean something, that a rule does not
quietly beat `hidden`, and that each module parses. This is that, in the standard library,
plus `node --check` where node is on the runner (all three GitHub images have it).

It is not a substitute for opening the page. It is the floor under it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from quackd.sim3d import upstream_api as up
from tests.conftest import REPO

WEB = REPO / "web"
SRC = WEB / "src"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "style.css").read_text(encoding="utf-8")
MODULES = sorted(SRC.glob("*.js"))

# The path the page is served from: www.quackd.org/simulator, and /simulator on this project's
# own deployment. Every local reference in the HTML is absolute under it.
MOUNT = "/simulator"


def _unmount(reference: str) -> str:
    """A reference as the browser sees it, back to a path inside `web/`."""
    return reference[len(MOUNT) + 1 :] if reference.startswith(MOUNT + "/") else reference


def _js(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def _keydown() -> str:
    """The window-level keydown listener, from its opening line to the `});` that closes it in
    column zero. The goal box has a keydown of its own for Escape, but that one is indented
    behind `ui.goal.`, so anchoring both ends to column zero picks out the page's handler."""
    found = re.search(r'^addEventListener\("keydown".*?^\}\);', _js("app.js"), re.S | re.M)
    assert found, "app.js registers no window-level keydown listener"
    return found.group(0)


ALL_JS = "\n".join(p.read_text(encoding="utf-8") for p in MODULES)


# ── the page and the script agree about what is on it ───────────────────────────────────


def test_every_id_the_javascript_looks_up_exists_in_the_page() -> None:
    ids = set(re.findall(r'\$\("([\w-]+)"\)', ALL_JS))
    ids |= set(re.findall(r'getElementById\("([\w-]+)"\)', ALL_JS))
    ids |= set(re.findall(r'querySelector\("#([\w-]+)"\)', ALL_JS))
    assert ids, "the regexes found nothing, so this test is not testing anything"
    present = set(re.findall(r'id="([\w-]+)"', HTML))
    missing = sorted(ids - present)
    assert not missing, f"web/src/*.js looks up ids that index.html does not define: {missing}"


def test_every_class_the_javascript_toggles_is_defined_somewhere() -> None:
    used = set(re.findall(r'classList\.(?:add|remove|toggle)\("([\w-]+)"', ALL_JS))
    used |= set(re.findall(r'querySelectorAll\("\.([\w-]+)"\)', ALL_JS))
    known = set(re.findall(r"\.([a-zA-Z][\w-]*)\s*[,{:]", CSS)) | set(
        re.findall(r'class="([^"]+)"', HTML)
    )
    known = {c for group in known for c in group.split()}
    missing = sorted(used - known)
    assert not missing, f"the JavaScript toggles classes nothing defines: {missing}"


def test_nothing_the_javascript_hides_is_pinned_visible_by_a_rule() -> None:
    """`[hidden]` is a user-agent rule and loses to any author rule that sets `display` at the
    same specificity. `.overlay { display: grid }` beat it, so `loading.hidden = true` left
    the loading panel covering the canvas and the entire stage bar for good."""
    assert re.search(r"\[hidden\][^{]*\{[^}]*display:\s*none\s*!important", CSS), (
        "web/style.css needs `[hidden] { display: none !important; }`: without it any rule "
        "that sets `display` on an element the script hides silently keeps it on screen"
    )


def test_the_controls_that_need_a_loaded_duck_start_disabled() -> None:
    """Every listener is attached at module scope, but `duck`, `runtime` and `recorder` only
    exist after a 45 MB load. Pressing these during it used to throw."""
    for element in ("run", "reset", "record", "save", "stop-run"):
        pattern = rf'id="{element}"[^>]*\bdisabled\b'
        assert re.search(pattern, HTML), f"#{element} must start disabled and be enabled by boot"


def test_the_goal_form_cannot_navigate_away_with_what_was_typed_in_it() -> None:
    """If the module never evaluates, a plain form submits on Enter and puts the visitor's
    sentence into the URL and the Referer."""
    form = re.search(r"<form[^>]*id=\"goal-form\"[^>]*>", HTML)
    assert form and 'method="dialog"' in form.group(0)
    assert not re.search(r'<input id="goal"[^>]*\bname=', HTML)


# ── the brand on the page is the one this repository holds ──────────────────────────────


def test_the_header_wears_the_vendored_duck_mark_and_not_an_emoji() -> None:
    """The header and the favicon were both a 🦆: the emoji in a `<span aria-hidden>`, and the
    same emoji drawn into an inline-SVG data URI for the tab. A logo rendered out of the
    visitor's emoji font is a different logo on every machine that opens the page, and quackd
    has a mark of its own. It is in `web/assets` now, with the two icon sizes beside it."""
    chrome = HTML.split("</header>")[0]
    assert "🦆" not in chrome, (
        "the duck emoji is back in the head or the header. The mark is "
        "web/assets/duck-mark.png and the icons are the two PNGs beside it"
    )
    header = re.search(r"<header\b.*?</header>", HTML, re.S)
    assert header, "index.html has no <header>, so this test cannot see what it wears"
    assert re.search(rf'<img[^>]+src="{MOUNT}/assets/duck-mark\.png"', header.group(0)), (
        "the header does not carry web/assets/duck-mark.png"
    )
    icon = re.search(r'<link[^>]*rel="icon"[^>]*>', HTML)
    assert icon and f"{MOUNT}/assets/favicon-96.png" in icon.group(0), (
        "the tab icon is not the vendored PNG favicon"
    )
    assert f'href="{MOUNT}/assets/apple-touch-icon.png"' in HTML, "nothing links the home-screen icon"


def test_every_asset_the_page_asks_for_is_a_file_in_this_directory() -> None:
    """The deploy is a copy of `web/` and nothing reads the HTML on the way out, so a mistyped
    `src` is a broken mark in production and a green build here. Every local reference the page
    makes has to resolve on disk, under the mount prefix the deploy serves it from."""
    referenced = set(re.findall(r'(?:src|href)="(?!https?:|data:|mailto:|#)([^"]+)"', HTML))
    assert referenced, "the regex found no local references, so this test is not testing anything"
    missing = sorted(
        ref for ref in referenced if not (WEB / _unmount(ref).split("?")[0]).is_file()
    )
    assert not missing, f"index.html points at files that web/ does not hold: {missing}"


def test_every_local_reference_is_absolute_under_the_mount() -> None:
    """The page is served at www.quackd.org/simulator, and quackd-web sets `trailingSlash: false`
    — so the browser lands on `/simulator` with no slash, and a *relative* `style.css` resolves
    to `/style.css`, which is the landing page's root and not this directory at all. The HTML
    would arrive and every asset under it would 404. Relative paths cannot come back."""
    referenced = set(re.findall(r'(?:src|href)="(?!https?:|data:|mailto:|#)([^"]+)"', HTML))
    assert referenced, "the regex found no local references, so this test is not testing anything"
    relative = sorted(ref for ref in referenced if not ref.startswith(MOUNT + "/"))
    assert not relative, (
        f"these references are relative and will break behind the /simulator mount: {relative}"
    )


def test_the_deploy_answers_on_the_mount_it_tells_the_browser_to_use() -> None:
    """Two projects serve this page: quackd-web proxies /simulator/* through to this one, and
    this one is also reachable on its own deployment URL. The HTML asks for /simulator/... in
    both cases, so this project has to answer there as well as at its root, or the direct
    deployment serves an unstyled page with no script."""
    config = json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))
    sources = {rule["source"] for rule in config.get("rewrites", [])}
    assert f"{MOUNT}/:path*" in sources, (
        f"vercel.json must rewrite {MOUNT}/:path* to /:path*, or every asset 404s on the "
        f"deployment's own URL: {sorted(sources)}"
    )


# ── two ways to drive, and both of them always live ─────────────────────────────────────


def test_the_keyboard_is_not_gated_behind_the_quackd_switch() -> None:
    """The switch used to be exclusive: `runtime.manual = !on` inside applyToggle, an early
    return on `ui.toggle.checked` at the top of the keydown handler, and the cockpit hidden
    while quackd was on. So the page's own argument arrived as an either/or, and a visitor had
    to flip a mode before a key did anything at all. The switch decides one thing now — whether
    anything here reads English — and the keyboard was never that layer."""
    app = _js("app.js")
    body = _keydown()
    for gate in ("toggle", "checked", "quackd-on"):
        assert gate not in body, (
            f"the keydown handler reads `{gate}`: driving must not depend on the switch, which "
            f"is the whole of the dual-control claim the page makes"
        )
    apply_toggle = re.search(r"^function applyToggle\(\).*?^\}", app, re.S | re.M)
    assert apply_toggle, "app.js has no applyToggle(), which is where the old gate lived"
    assert not re.search(r"runtime\.manual\s*=", apply_toggle.group(0)), (
        "applyToggle() takes the twist lease again; the lease belongs to the run, not the switch"
    )
    assert not re.search(r"manual\w*\.hidden\s*=", app), (
        "something hides the cockpit again. It is permanent, and its adjacency to the goal box "
        "is the argument the page makes by proximity instead of by copy"
    )
    assert not re.search(r'id="manual"[^>]*\bhidden\b', HTML), "#manual ships hidden"


def test_a_key_that_moves_the_robot_takes_it_and_a_key_that_only_reads_does_not() -> None:
    """Barge-in is what makes the two controls live rather than merely both present: a drive
    key pressed during a run takes the robot at once and the transcript says which key did it,
    while `O` and the camera keys leave the run alone. The rule is exactly that — a key barges
    in if and only if it would move the robot."""
    app = _js("app.js")
    body = _keydown()

    def keyset(name: str) -> set[str]:
        found = re.search(rf"{name} = new Set\(\[([^\]]*)\]", app)
        assert found, f"app.js no longer declares {name}"
        return set(re.findall(r'"(\w+)"', found.group(1)))

    motor, read = keyset("MOTOR"), keyset("READ")
    assert {"KeyW", "KeyA", "KeyS", "KeyD", "Space"} <= motor, (
        "the drive keys are not all in MOTOR, so pressing one mid-run takes the robot from nobody"
    )
    assert not motor & read, "a key cannot both take the robot and leave the run alone"
    assert re.search(r"if \(motor\).*bargeIn\(", body), (
        "the keydown handler no longer barges in on a motor key"
    )
    assert "bargeIn" not in body.split("if (motor)")[0], (
        "something barges in before the motor test, so a read-only key would stop a run"
    )
    barge = re.search(r"^function bargeIn\(.*?^\}", app, re.S | re.M)
    assert barge, "app.js has no bargeIn()"
    for piece, why in (
        (".abort(", "cancel the run, which would otherwise race the hand for the twist"),
        ('giveTwistTo("hand")', "hand the twist over, which is the handover itself"),
        ('"handover"', "tell the transcript a key took the controls"),
    ):
        assert piece in barge.group(0), f"bargeIn() does not {why}"


def test_a_focused_control_keeps_the_keys_that_are_its_own() -> None:
    """WCAG 2.1.1: Space activates a focused button or `<summary>`, and W typed into the goal
    box is a letter. `preventDefault` ran before this guard once, and the drive keys took both.
    Now that the keyboard never sleeps, the guard is the only thing separating typing a
    sentence from driving."""
    app = _js("app.js")
    typing = re.search(r'TYPING = "([^"]+)"', app)
    assert typing, "app.js no longer declares the TYPING selector the guard reads"
    for control in ("input", "textarea", "button", "summary"):
        assert control in typing.group(1), f"{control} is not in TYPING, so it loses its own keys"
    # comments stripped: the handler's own comment names `preventDefault` while explaining
    # why the guard has to come first, and reading that as code inverts the order it describes
    body = re.sub(r"^\s*//.*$", "", _keydown(), flags=re.M)
    assert "TYPING" in body, "the keydown handler no longer defers to a focused control"
    assert body.index("TYPING") < body.index("preventDefault"), (
        "preventDefault runs before the TYPING guard, which is exactly how Space stopped "
        "activating focused buttons the first time"
    )


def test_an_abandoned_turn_stops_being_billed_for() -> None:
    """Barge-in and Stop abort the run, and the run's signal has to reach both the sleep inside
    a verb and the request in flight. It reached neither: a ten second `move` ran to completion
    after Stop, and the answer nobody wanted arrived seconds later against the visitor's key."""
    providers = _js("providers.js")
    calls = providers.count("await fetch(")
    assert calls, "providers.js makes no fetch, so this test is not testing anything"
    assert providers.count("signal,") == calls, (
        f"web/src/providers.js makes {calls} requests and passes the AbortSignal to "
        f"{providers.count('signal,')} of them"
    )
    assert re.search(r"verb\.run\([^)]*signal", _js("pilot.js")), (
        "pilot.js does not pass the signal into the verb, so Runtime.sleep's abort listener is "
        "dead code and an aborted verb runs to the end"
    )


# ── failures have somewhere to go ───────────────────────────────────────────────────────


def test_the_page_reports_a_failure_rather_than_freezing_on_one() -> None:
    app = _js("app.js")
    assert 'addEventListener("unhandledrejection"' in app
    assert 'addEventListener("error"' in app
    assert re.search(r"boot\(\)\.catch\(", app), "a bare boot() leaves a dead page and no message"


def test_no_module_reached_from_the_page_imports_a_cdn_statically() -> None:
    """A static import of a blocked host takes down the whole module graph before a single
    listener is attached: no page, no error, nothing to read. The heavy dependency is loaded
    inside boot, where a rejection can be shown."""
    app = _js("app.js")
    static_cdn = re.findall(r'^\s*import\s[^;]*from\s+"(https?://[^"]+)"', app, re.M)
    assert not static_cdn, f"app.js statically imports {static_cdn}; import it inside boot()"
    assert 'await import("./view.js")' in app, "three.js rides on view.js, so that one is dynamic"


# ── the key, which is the visitor's ─────────────────────────────────────────────────────


def test_the_api_key_is_never_stored_anywhere() -> None:
    """SECURITY.md says the key lives in the form field and the request, and nowhere else."""
    for banned in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
        assert banned not in ALL_JS, f"web/src/*.js touches {banned}; the key must not be stored"
    assert "console.log" not in ALL_JS, "a logged request is a logged key"


def test_switching_provider_clears_the_key_field() -> None:
    """Disabling the input left its value readable, so a key pasted for one vendor was still
    there when the visitor switched to a local server and went out as a bearer token to
    whatever host was in the free-text box."""
    assert re.search(r'ui\.key\.value\s*=\s*""', _js("app.js"))


def test_a_key_is_only_ever_sent_over_https_or_to_this_machine() -> None:
    providers = _js("providers.js")
    assert "export function localBaseUrl" in providers
    assert "localBaseUrl(" in providers.split("export function localBaseUrl")[0], (
        "localBaseUrl is defined but never used, so the base URL is still unchecked"
    )


# ── the two copies of upstream's contract stay in step ──────────────────────────────────


def test_the_browser_pins_the_same_upstream_commits_python_does() -> None:
    """`docs/architecture.md` calls keeping this copy in step "the standing cost of it
    existing". This is that cost, paid once."""
    js = _js("microduck.js")
    for label, pin in (("microduck_rl", up.PIN), ("microduck-policies", up.POLICIES_PIN)):
        assert pin in js, (
            f"web/src/microduck.js does not pin {label} at {pin}, which is what "
            f"quackd/sim3d/upstream_api.py fetches. Paste it."
        )


def test_the_browser_uses_the_same_gait_numbers_python_does() -> None:
    from quackd.sim3d import gait

    js = _js("microduck.js")
    floor = re.search(r"GAIT_FLOOR\s*=\s*\{([^}]*)\}", js)
    assert floor, "web/src/microduck.js no longer declares GAIT_FLOOR"
    # compared as numbers, not as their spelling: 0.30 and 0.3 are the same floor
    got = {k: float(v) for k, v in re.findall(r"(\w+):\s*([\d.]+)", floor.group(1))}
    want = {"vx": gait.GAIT_FLOOR_VX, "vy": gait.GAIT_FLOOR_VY, "wz": gait.GAIT_FLOOR_WZ}
    assert got == want, (
        f"the browser walks on {got}, and quackd/sim3d/gait.py sends the real duck {want}"
    )
    achieved = re.search(r"ACHIEVED_FRACTION\s*=\s*([\d.]+)", js)
    assert achieved and float(achieved.group(1)) == gait.ACHIEVED_FRACTION


# ── the arena is quackd's, and still the arena the verbs aim at ─────────────────────────


def test_the_person_marker_is_no_longer_a_blue_tube_and_is_still_the_target() -> None:
    """It was one cylinder in `0.24 0.35 0.86` — Python's blue, which over there is
    load-bearing: `quackd/sim3d/render.py` finds a person by that exact hue, so `scene.py` has
    to paint one. Nothing in the browser reads a pixel, `observe()` measures against the body's
    own position, and so the only thing that blue did here was read as a stray tube. It is a
    plinth, a post and a head in the brand's purple now — and every handle the rest of the demo
    holds it by is untouched: the body's name, and the `person` label observe() publishes for
    the "Walk to the person and quack" example to aim at."""
    js = _js("microduck.js")
    assert "0.24 0.35 0.86" not in js, (
        "the person marker is Python's detector blue again. That hue is load-bearing in "
        "quackd/sim3d/scene.py and decorative here, so here it can be quackd's own"
    )
    marker = re.search(r'<body name="person".*?</body>', js, re.S)
    assert marker, (
        'the arena XML defines no static body named "person"; observe() reports that name and '
        "the example chip on the page walks to it"
    )
    named = re.findall(r'rgba="\$\{(\w+)\}"', marker.group(0))
    assert named, "the person marker's geoms carry no colour of their own"
    palette = dict(re.findall(r'(\w+)\s*=\s*"([\d.]+ [\d.]+ [\d.]+ [\d.]+)"', js))
    for name in named:
        assert name in palette, f"{name} is used in the arena XML and defined nowhere"
        red, green, blue, _alpha = (float(value) for value in palette[name].split())
        assert blue > green and red > green, (
            f"{name} is {palette[name]}, which is not on quackd's purple axis: green at or "
            f"above red and blue is some other colour's marker"
        )
    assert 'label: "person"' in js, "observe() no longer labels the marker `person`"


def test_the_demo_claims_no_more_policies_than_it_downloads() -> None:
    """Two ONNX files load: one stands the duck up and one walks it. The kick is quackd's own
    scripted impulse, as the comment above it says, and copy promising a shelf of learned
    skills is a claim the download does not support."""
    # what is fetched, not what is named: the comment above `kick` names a third file,
    # `ball_kick_left.onnx`, precisely to say that it did nothing and is not used
    policies = set(re.findall(r"POLICIES\}/(\w+)\.onnx", _js("microduck.js")))
    assert policies == {"alpha_walking", "alpha_stand"}, (
        f"web/src/microduck.js loads {sorted(policies)}; the page and web/README.md say two"
    )
    readme = (WEB / "README.md").read_text(encoding="utf-8")
    for text, where in ((HTML, "index.html"), (readme, "web/README.md")):
        assert not re.search(r"nine[^.]{0,40}polic", text, re.I), (
            f"{where} promises nine policies, and this demo fetches {len(policies)}"
        )


# ── it parses ───────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_each_module_parses_as_javascript(module: Path) -> None:
    """The only thing here that would catch a typo. `node --check` alone parses as CommonJS
    and rejects `import`, so the source goes in on stdin as a module."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this machine; the GitHub runners all have one")
    done = subprocess.run(
        [node, "--input-type=module", "--check"],
        input=module.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        encoding="utf-8",  # the sources carry em-dashes and the Windows locale is not utf-8
    )
    assert done.returncode == 0, f"{module.name} does not parse:\n{done.stderr}"


def test_the_page_loads_every_module_it_ships() -> None:
    """A module nothing imports is dead weight nobody will notice has rotted."""
    entry = re.search(rf'<script[^>]*src="{MOUNT}/(src/[\w.]+)"', HTML)
    assert entry, "index.html loads no module"
    reachable = {entry.group(1).split("/")[-1]}
    frontier = list(reachable)
    while frontier:
        current = frontier.pop()
        for name in re.findall(r'import[^;]*from\s+"\./([\w.]+)"', _js(current)):
            if name not in reachable:
                reachable.add(name)
                frontier.append(name)
        for name in re.findall(r'await import\("\./([\w.]+)"\)', _js(current)):
            if name not in reachable:
                reachable.add(name)
                frontier.append(name)
    orphans = sorted({p.name for p in MODULES} - reachable)
    assert not orphans, f"web/src holds modules the page never loads: {orphans}"


def test_the_deploy_config_serves_this_directory_and_builds_nothing() -> None:
    """`web/` has no build step on purpose: every dependency is a CDN URL fetched at run time,
    so the deploy is a copy. A host that guessed a framework from the Python at the repo root
    would try to build quackd instead."""
    config = json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))
    assert config["outputDirectory"] == "web"
    assert config["framework"] is None, "no framework: this is a folder, not an app to build"
    for step in ("buildCommand", "installCommand"):
        assert config.get(step), f"{step} must be stubbed out, or the host builds the repo root"


def test_the_demo_says_what_it_stands_in_for() -> None:
    """The browser fakes perception geometrically rather than running Python's colour detector
    on a rendered frame, and it hashes nothing. Both are fine, undisclosed is not."""
    readme = (WEB / "README.md").read_text(encoding="utf-8")
    assert "geometric" in readme.lower() or "ground truth" in readme.lower(), (
        "web/README.md should say that perception here is geometric, not the colour detector "
        "Python runs on a rendered head-camera frame"
    )


def test_the_upstream_licence_is_named_on_the_page_that_downloads_it() -> None:
    """The visitor's browser fetches CC BY-NC-SA meshes. The page has to say so."""
    assert "BY-SA-NC" in HTML or "BY-NC-SA" in HTML


def test_the_browser_refuses_the_arguments_python_refuses() -> None:
    """The one check here that runs the code rather than reading it.

    The verb schemas were sent to the vendor and never enforced locally, so a model that
    ignored one got what it asked for: `duration_s: 1e6` became ten million awaited slices and
    hung the tab, and `duration_s: "soon"` produced NaN, ran no loop and reported success.
    Python rejects both with pydantic before the verb runs.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this machine; the GitHub runners all have one")
    script = f"""
    import {{ checkParams, VERBS }} from {json.dumps((SRC / "pilot.js").as_uri())};
    const out = {{}};
    out.huge = checkParams(VERBS.move.params, {{ duration_s: 1e6 }});
    out.notANumber = checkParams(VERBS.move.params, {{ duration_s: "soon" }});
    out.outOfRange = checkParams(VERBS.move.params, {{ vx: 99, duration_s: 1 }});
    out.unknown = checkParams(VERBS.move.params, {{ nope: 1 }});
    out.fine = checkParams(VERBS.move.params, {{ duration_s: 2, vx: 0.2 }});
    out.empty = checkParams(VERBS.move.params, {{}});
    out.longSay = checkParams(VERBS.say.params, {{ text: "x".repeat(500) }});
    out.badLeg = checkParams(VERBS.kick.params, {{ leg: "middle" }});
    console.log(JSON.stringify(out));
    """
    done = subprocess.run(
        [node, "--input-type=module"],
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    assert "at most 10" in got["huge"]
    assert "finite number" in got["notANumber"]
    assert "at most 0.3" in got["outOfRange"]
    assert "nope" in got["unknown"]
    assert "at most 200" in got["longSay"]
    assert "left, right" in got["badLeg"]
    assert got["fine"] is None
    assert got["empty"] is None, "Python's MoveParams requires nothing, so neither may this"
