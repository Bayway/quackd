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


def _js(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


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
    entry = re.search(r'<script[^>]*src="(src/[\w.]+)"', HTML)
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


def test_the_pages_workflow_publishes_the_directory_and_does_not_cancel_a_deploy() -> None:
    workflow = (REPO / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "path: web" in workflow
    assert "cancel-in-progress: false" in workflow, (
        "that concurrency group guards a deployment: cancelling one halfway leaves the site "
        "on a half-uploaded version"
    )


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
    assert json.dumps  # keeps the import honest if the assertion above is ever relaxed


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
