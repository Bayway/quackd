"""Docs that make promises about code are checked against the code."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

from quackd.transport import upstream_api as up
from quackd.verbs.registry import default_registry

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")


def test_adapter_status_lists_every_microduck_upstream_ref() -> None:
    doc = (REPO / "docs" / "adapter-status.md").read_text(encoding="utf-8")
    missing = [ref.name for ref in up.all_refs() if ref.name not in doc]
    assert not missing, f"docs/adapter-status.md is missing: {missing}"
    from quackd.adapters.factory import BACKENDS

    for adapter, backends in BACKENDS.items():
        for backend in backends:
            assert f"`{adapter}:{backend}`" in doc, f"adapter-status.md lacks {adapter}:{backend}"
    # the old page is a redirect, not a stale copy
    old = (REPO / "docs" / "transport-status.md").read_text(encoding="utf-8")
    assert "adapter-status.md" in old and "VERIFIED (read" not in old


def test_adapter_guide_and_manifest_spec_match_the_code() -> None:
    from quackd.adapters.factory import ADAPTER_NAMES
    from quackd.verbs.core import REQUIREMENTS

    guide = (REPO / "docs" / "adapters.md").read_text(encoding="utf-8")
    for name in ADAPTER_NAMES:
        assert f"`{name}`" in guide, f"docs/adapters.md does not mention {name}"
    for fn in ("describe", "implementations", "conditions", "make"):
        assert f"def {fn}(" in guide
    spec = (REPO / "docs" / "manifest-spec.md").read_text(encoding="utf-8")
    for verb in REQUIREMENTS:
        assert f"`{verb}`" in spec, f"docs/manifest-spec.md does not list core verb {verb}"
    assert "manifest.schema.json" in spec and "digest()" in spec


@pytest.mark.parametrize(
    "adapter",
    ["reachy_mini", "lerobot", "rosbridge", "open_duck", "xlerobot", "alohamini", "toddlerbot"],
)
def test_adapter_doc_lists_every_upstream_ref(adapter: str) -> None:
    api = importlib.import_module(f"quackd.adapters.{adapter}.upstream_api")
    doc = (REPO / "docs" / "adapters" / f"{adapter}.md").read_text(encoding="utf-8")
    missing = [ref.name for ref in api.all_refs() if ref.name not in doc]
    assert not missing, f"docs/adapters/{adapter}.md is missing: {missing}"
    assert api.PIN[:7] in doc and "never" in doc.lower()  # the honesty label


def test_readme_promises() -> None:
    for needle in (
        "not affiliated with or endorsed by Pollen Robotics",
        "claude mcp add quackd",
        "dr-eureka",
        "github.com/pollen-robotics/microduck_rl",
        "--goal",
        "--provider fake",
        "biped",
        "pronounced",
        "Any LLM, one <code>.duck</code> file",
        "Non goals for now",
        "--provider openai",
        "--provider gemini",
        "--provider grok",
        "--provider ollama",
        "docs/local-llms.md",
        "| Local models (",
        "--flock",
        "flock-kick",
        "docs/flock.md",
    ):
        assert needle in README, needle
    assert "quadruped" not in README.lower()
    for hype in ("revolutionary", "world's first", "fully autonomous", "swarm intelligence"):
        assert hype not in README.lower(), hype


#: The one line in the README allowed a dash, matched exactly and nowhere else: the signature
#: on the author's own note. A signature is the one place an em dash is typographically right
#: rather than lazy punctuation, and it is one line, so it earns an exact-match exception
#: instead of a loosened rule. Changing the wording of that line brings the rule back.
DASH_EXEMPT_LINES = frozenset({"> — Rok Benko, August 2026"})


def test_readme_punctuation_style() -> None:
    """House style: no semicolons and no dashes used as punctuation (em/en dash, ' - ').

    Fenced code blocks are exempt (YAML lists, shell comments, JSON are what they are), and so
    is each line in `DASH_EXEMPT_LINES`, by exact match. Semicolons have no exceptions."""
    prose = re.sub(r"```.*?```", "", README, flags=re.S)
    for i, line in enumerate(prose.splitlines(), 1):
        assert ";" not in line, f"README:{i}: semicolon"
        if line.strip() in DASH_EXEMPT_LINES:
            continue
        for dash in ("—", "–", " - "):  # noqa: RUF001  (em dash, en dash, spaced hyphen)
            assert dash not in line, f"README:{i}: dash punctuation {dash!r}"


def test_the_dash_exemption_is_still_earning_its_place() -> None:
    """An exception nobody uses is a rule with a hole in it.

    If the signature is reworded or removed, this fails and the exemption comes out with it,
    rather than sitting in the file granting a dash to a line that no longer exists."""
    prose = re.sub(r"```.*?```", "", README, flags=re.S)
    lines = {line.strip() for line in prose.splitlines()}
    unused = sorted(DASH_EXEMPT_LINES - lines)
    assert not unused, f"DASH_EXEMPT_LINES no longer matches the README: {unused}"


def test_readme_ends_with_license_section() -> None:
    prose = re.sub(r"```.*?```", "", README, flags=re.S)  # ignore headings inside code blocks
    headings = re.findall(r"^## (.+)$", prose, flags=re.M)
    assert headings[-1] == "License", headings
    # a blank line (<br>) before every section, for breathing room on GitHub
    assert prose.count("<br>\n\n## ") == len(headings), "every H2 needs a <br> before it"


def test_readme_images_are_absolute_and_exist() -> None:
    srcs = re.findall(r'<img[^>]+src="([^"]+)"', README) + re.findall(
        r"!\[[^\]]*\]\(([^)\s]+)", README
    )
    assert srcs, "README has no images"
    raw = "https://raw.githubusercontent.com/rokbenko/quackd/main/"
    for src in srcs:
        assert src.startswith("https://"), f"relative image breaks on PyPI: {src}"
        if src.startswith(raw):
            path = src[len(raw) :].split("?", 1)[0]  # ?v=N busts GitHub's image cache
            assert (REPO / path).exists(), f"missing asset {src}"


def test_readme_verbs_match_registry() -> None:
    for name in default_registry().names():
        assert f"`{name}`" in README, f"README does not mention verb {name}"


def test_mcp_doc_lists_every_tool() -> None:
    from quackd.mcp_server import TOOL_NAMES

    doc = (REPO / "docs" / "mcp.md").read_text(encoding="utf-8")
    missing = [name for name in TOOL_NAMES if f"`{name}" not in doc]
    assert not missing, f"docs/mcp.md is missing: {missing}"
    assert "--robots" in doc and "--robots" in README


def test_mcp_json_is_a_stdio_server() -> None:
    from quackd.adapters.factory import BACKENDS

    cfg = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))
    server = cfg["mcpServers"]["quackd"]
    assert "command" in server and "type" not in server
    args = server["args"]
    assert "serve-mcp" in args
    # the robot it names has to exist, or opening the repo greets you with a stack trace
    adapter, _, backend = args[args.index("--robot") + 1].partition(":")
    assert backend in BACKENDS.get(adapter, ()), f".mcp.json names {adapter}:{backend}"
    # This is the repo's own config, so it runs the code you are editing, not the release.
    # `uv run` alone re-syncs on launch and loses to the running server's hold on
    # Scripts/quackd.exe on Windows, so the repo pins --no-sync. Users get `uvx` (docs/mcp.md).
    if server["command"] == "uv" and args[0] == "run":
        assert "--no-sync" in args, "uv run re-syncs and fights the server it is launching"


def test_adr_links_resolve() -> None:
    for md in (REPO / "docs").rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        for target in re.findall(r"\]\((adr/[^)]+\.md)\)", text):
            assert (REPO / "docs" / target).exists(), f"{md.name} links to missing {target}"


# ── counts, so a release cannot ship a number the code disagrees with ────────────────────

_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def _prose(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def _living_docs() -> list[Path]:
    """Every document that describes quackd as it is now.

    CHANGELOG, PLAN and the ADRs and design notes are excluded: they record what was true
    when they were written, and correcting a number in them would be falsifying history."""
    return [
        path
        for path in sorted(REPO.glob("*.md")) + sorted((REPO / "docs").rglob("*.md"))
        if path.name not in ("CHANGELOG.md", "PLAN.md") and not {"design", "adr"} & set(path.parts)
    ]


@pytest.mark.parametrize("name", ["README.md", "docs/adapters.md", "docs/faq.md", "LAUNCH.md"])
def test_no_document_claims_the_wrong_number_of_adapters(name: str) -> None:
    """Half of the 0.5 documentation audit was stale counts that no test could see.

    "four adapters" was written in six places while five shipped. This does not police
    prose, only the specific claim that quackd has N adapters."""
    from quackd.adapters.factory import ADAPTER_NAMES

    right = _NUMBER_WORDS[len(ADAPTER_NAMES)]
    prose = _prose((REPO / name).read_text(encoding="utf-8")).lower()
    # only claim shapes that are unambiguously about how many adapters exist. "two robots
    # under one contract" is a heterogeneous flock, not a count of adapters.
    shapes = ("{w} adapters", "{w} robots supported", "{w} robots today")
    for count, word in _NUMBER_WORDS.items():
        if count == len(ADAPTER_NAMES):
            continue
        for shape in shapes:
            claim = shape.format(w=word)
            assert claim not in prose, (
                f"{name} says {claim!r}; quackd ships {right} ({', '.join(ADAPTER_NAMES)})"
            )


def test_the_pypi_summary_names_every_robot() -> None:
    """The one sentence on the PyPI page shipped 0.5 without the Open Duck Mini in it.

    That line and the keywords are how someone searching for their robot finds quackd, and
    nothing in the test suite had ever read pyproject.toml."""
    import tomllib

    from quackd.adapters.factory import ADAPTER_NAMES

    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    haystack = (project["description"] + " " + " ".join(project["keywords"])).lower()
    # the summary names bodies, not adapter identifiers: microduck -> "microduck",
    # open_duck -> "open duck", rosbridge -> "ros"
    for adapter in ADAPTER_NAMES:
        needle = {"open_duck": "open duck", "rosbridge": "ros", "reachy_mini": "reachy"}.get(
            adapter, adapter
        )
        assert needle in haystack, (
            f"pyproject describes quackd without {needle!r}; it ships a {adapter} adapter"
        )


def test_the_readme_starter_table_lists_every_bundled_duck() -> None:
    """`open-duck-lookout` shipped in 0.5 and appeared nowhere in the README."""
    from quackd.duckfile.parser import list_bundled_ducks

    missing = [p.stem for p in list_bundled_ducks() if f"`{p.stem}`" not in README]
    assert not missing, f"README does not mention: {missing}"


def test_no_living_document_quotes_an_exact_test_count() -> None:
    """CONTRIBUTING said 445 while 451 ran, and no test could see it.

    Collecting the suite to check a number would cost every run eight seconds for a fact
    nobody reads, so the rule is simply not to quote one outside the history files, where
    a count is a record of what was true on the day and must not be rewritten."""
    for path in _living_docs():
        for claim in re.findall(r"\b\d{2,4} tests?\b", _prose(path.read_text(encoding="utf-8"))):
            pytest.fail(f"{path.name} quotes {claim!r}; say 'the whole suite' and let CI count")


def test_no_document_still_promises_a_removal_that_happened() -> None:
    """0.4 said `--transport` and the duck_* tools go in 0.5. They did, so nothing should
    still be promising it, and nothing should still be offering them."""
    from quackd.mcp_server import TOOL_NAMES

    assert not [n for n in TOOL_NAMES if n.startswith("duck_")]
    # a table title and a TransportError still told users to pass it, and no doc test could
    # see a Python string, so the same rule now covers the source that prints to a terminal
    for src in sorted((REPO / "quackd").rglob("*.py")):
        assert "--transport" not in src.read_text(encoding="utf-8"), (
            f"quackd/{src.relative_to(REPO / 'quackd').as_posix()} still offers --transport"
        )
    for path in _living_docs():
        text = _prose(path.read_text(encoding="utf-8"))
        assert "--transport" not in text, f"{path.name} still documents --transport"
        for promise in ("go away in 0.5", "gone in 0.5", "are removed in 0.5", "for one release"):
            assert promise not in text, f"{path.name} still promises {promise!r}, which happened"


def test_no_living_document_claims_the_wrong_number_of_mcp_tools() -> None:
    """The guard above proves nothing still *offers* a removed tool. It could not see a
    document still *describing* one, so architecture.md went through the whole of 0.5 saying
    the server carried the old count plus the duck_* aliases that release deleted, and into
    0.6, which added two more tools. Two README sentences, a --robots help string, a module
    docstring and a test docstring carried the old count for the same reason: nothing counted
    them. This file is scanned too, which is why the stale wordings are described here rather
    than quoted."""
    from quackd.mcp_server import TOOL_NAMES

    right = _NUMBER_WORDS[len(TOOL_NAMES)]
    # 0.5 learned that a doc-only guard cannot see a Python string a user reads: the count
    # was also stale in a `--robots` help text, a module docstring and a test's docstring
    # this file is skipped because it has to spell the wordings it forbids in order to
    # forbid them; every other source file and living document is fair game
    here = Path(__file__).resolve()
    sources = [
        p
        for p in sorted((REPO / "quackd").rglob("*.py")) + sorted((REPO / "tests").glob("*.py"))
        if p.resolve() != here
    ]
    for path in _living_docs() + sources:
        text = path.read_text(encoding="utf-8")
        haystack = (_prose(text) if path.suffix == ".md" else text).lower()
        for count, word in _NUMBER_WORDS.items():
            if count == len(TOOL_NAMES):
                continue
            for shape in (f"{word} `robot_*` tools", f"{word} robot_* tools"):
                assert shape not in haystack, (
                    f"{path.name} says {shape!r}; the server registers {right} "
                    f"({', '.join(TOOL_NAMES)})"
                )
        # anything that still describes the removed aliases as present, in any wording
        for stale in ("duck_* tools kept as aliases", "`duck_*` tools kept as aliases"):
            assert stale not in haystack, f"{path.name} describes the duck_* aliases as present"


# ── the guard that was missing twice ────────────────────────────────────────────────────


def test_the_architecture_diagram_names_every_adapter() -> None:
    """`_prose()` strips fenced blocks before every other doc guard, so the mermaid diagram
    is invisible to all of them by construction.

    That is not hypothetical. `docs/design/memory.md` records 0.6 fixing exactly this defect
    ("the README's architecture diagram listed four adapters and omitted `open_duck` and its
    `bridge` backend, which the adapter-count guard could not see because it reads the phrase
    'N adapters' and not a list"). Nothing was added to catch it, so it came back three
    adapters later. This is that guard.
    """
    from quackd.adapters.factory import ADAPTER_NAMES, BACKENDS

    node = next((line for line in README.splitlines() if 'ADAPTER["robot adapter' in line), None)
    assert node is not None, "the architecture diagram's adapter node has moved or gone"

    # The names as a SET, split on the separator, not as substrings. `"lerobot" in node` is
    # satisfied by the `xlerobot` entry, so a substring check cannot see `lerobot` go missing,
    # which is the one adapter whose name is contained in another's.
    listed = {n.strip() for n in node.split("<br/>")[1].split("·")}
    missing = [name for name in ADAPTER_NAMES if name not in listed]
    assert not missing, f"the architecture diagram does not name: {missing} (has {listed})"
    extra = [name for name in listed if name and name not in ADAPTER_NAMES]
    assert not extra, f"the architecture diagram names adapters that do not exist: {extra}"

    #: Backends are listed by their bare name in that node, so every distinct one must appear.
    kinds = {backend for backends in BACKENDS.values() for backend in backends}
    absent = sorted(k for k in kinds if k not in node)
    assert not absent, f"the architecture diagram does not name the backends: {absent}"


def test_no_fenced_block_names_a_stale_subset_of_the_adapters() -> None:
    """The general form of the same hole: any fenced block that enumerates most of the
    adapters has to enumerate all of them, or it is a list somebody forgot to update."""
    from quackd.adapters.factory import ADAPTER_NAMES

    for doc in [REPO / "README.md", *sorted((REPO / "docs").rglob("*.md"))]:
        text = doc.read_text(encoding="utf-8")
        for block in re.findall(r"```.*?```", text, flags=re.S):
            named = [n for n in ADAPTER_NAMES if n in block]
            if len(named) < len(ADAPTER_NAMES) - 2:
                continue  # not an enumeration, just a couple of examples
            missing = [n for n in ADAPTER_NAMES if n not in block]
            assert not missing, (
                f"{doc.relative_to(REPO)}: a fenced block names {len(named)} adapters "
                f"and omits {missing}"
            )


#: The README's verb table names bodies, not adapter ids, so the mapping is written down.
_VERB_TABLE_ROWS = {
    "microduck": "| Microduck |",
    "reachy_mini": "| Reachy Mini |",
    "lerobot": "| LeRobot arm |",
    "rosbridge": "| rosbridge base |",
    "open_duck": "| Open Duck Mini v2 |",
    "xlerobot": "| XLeRobot |",
    "alohamini": "| AlohaMini |",
    "toddlerbot": "| ToddlerBot |",
}

_CORE_VERBS = frozenset(
    {"observe", "report_state", "stop", "say", "move", "go_to", "search_scan", "approach_and"}
)


def test_the_readme_verb_table_has_a_row_per_body_listing_its_real_verbs() -> None:
    """The other list-shaped thing no guard could see.

    `test_readme_verbs_match_registry` only checks that each *core* verb appears somewhere in
    the whole README, so a body could be added with its own verbs and never get a row. Four
    were: Open Duck Mini, XLeRobot, AlohaMini and ToddlerBot all shipped verbs of their own
    with nothing in the table.
    """
    import asyncio

    from quackd.adapters.factory import ADAPTER_NAMES, make_adapter

    assert set(_VERB_TABLE_ROWS) == set(ADAPTER_NAMES), "the row map has drifted from the code"

    offline = {"microduck": "sim2d", "lerobot": "mock", "rosbridge": "mock"}
    for adapter in ADAPTER_NAMES:
        backend = offline.get(adapter, "mock")
        manifest = asyncio.run(make_adapter(f"{adapter}:{backend}", seed=0).connect())
        own = sorted(set(manifest.verb_names()) - _CORE_VERBS)
        prefix = _VERB_TABLE_ROWS[adapter]
        row = next((line for line in README.splitlines() if line.startswith(prefix)), None)
        assert row is not None, f"the verb table has no row for {adapter}"
        if not own:
            continue  # a body with nothing of its own says so in prose
        # The verbs cell only. Searching the whole row lets the description satisfy it, and
        # these descriptions name verbs: the first version of this guard passed happily with
        # two of the ToddlerBot's three verbs deleted from the cell.
        cell = row.split("|")[2]
        missing = [v for v in own if f"`{v}`" not in cell]
        assert not missing, f"the {adapter} row does not list its own verbs: {missing}"
        # And the other direction, which is the drift that happens when a verb is deleted from
        # an adapter and nobody remembers the README.
        listed = {chunk.strip() for chunk in cell.split("`") if chunk.strip()}
        gone = [v for v in listed if v not in own and v not in _CORE_VERBS]
        assert not gone, f"the {adapter} row lists verbs the robot no longer has: {gone}"
