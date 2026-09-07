"""Shared fixtures. Nothing here touches the network or needs an API key."""

from __future__ import annotations

import faulthandler
import sys
from pathlib import Path

import pytest

from quackd.duckfile.parser import load_duck
from quackd.duckfile.schema import DuckFile
from quackd.transport.mock import MockTransport
from quackd.verbs.registry import VerbRegistry, default_registry

REPO = Path(__file__).resolve().parents[1]
DUCKS = REPO / "ducks"

EXIT_GRACE_S = 120


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:
    """If the interpreter has not exited two minutes after pytest is done, dump every thread
    and force the exit. `faulthandler_timeout` watches a test; nothing watches the shutdown
    after the last one, and that is where a `zmq.Context` left unclosed by a failing test
    was garbage collected into a `term()` that waits forever, which held three macOS jobs
    for six hours with no trace of what they were doing. This names the frame.

    Unconfigure rather than sessionfinish, and a flush first: the failure report is printed
    inside sessionfinish, and `_exit` flushes nothing, so arming the timer any earlier
    turned the one line that mattered into a lost buffer."""
    sys.stdout.flush()
    sys.stderr.flush()
    faulthandler.dump_traceback_later(EXIT_GRACE_S, exit=True)


@pytest.fixture(autouse=True)
def _memory_in_tmp(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test run must never write the developer's real `~/.quackd/memory`: every test that
    runs the CLI with memory on (the default) gets a throwaway directory instead. Not inside
    `tmp_path`: tests count the run directories they make there."""
    monkeypatch.setenv("QUACKD_MEMORY_DIR", str(tmp_path_factory.mktemp("quackd-memory")))


@pytest.fixture
def registry() -> VerbRegistry:
    return default_registry()


@pytest.fixture
def mock_transport() -> MockTransport:
    return MockTransport()


@pytest.fixture
def hello_duck() -> DuckFile:
    return load_duck(str(DUCKS / "hello-world.duck"))


@pytest.fixture
def kick_duck() -> DuckFile:
    return load_duck(str(DUCKS / "find-and-kick.duck"))
