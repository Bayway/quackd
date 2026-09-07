"""The sim2d acceptance sweep, on the physics simulator: with the scripted pilot,
`find-and-kick` succeeds on seeds 0..9, and the world's own ball telemetry agrees.

Skipped without `quackd[mujoco]` or without an OpenGL context, because the composite verbs
steer on rendered frames and there is nothing to steer on without one.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytest.importorskip("mujoco")

from quackd.adapters.microduck import MicroduckAdapter
from quackd.agent.loop import RunConfig, run_duck
from quackd.agent.providers.fake import FakeProvider
from quackd.duckfile.parser import load_duck
from quackd.perception.color_blob import ColorBlobDetector
from quackd.sim2d.recorder import FrameRecorder
from quackd.sim3d.world import MujocoWorld
from quackd.transport.mujoco import MujocoTransport

SEEDS = range(10)
MIN_SUCCESSES = 10 if os.environ.get("QUACKD_STRICT_SEEDS") == "1" else 8


async def test_find_and_kick_acceptance_in_mujoco(tmp_path: Path) -> None:
    probe = MujocoWorld(seed=0)
    try:
        probe.renderer(64)
    except Exception:
        pytest.skip("no OpenGL context for offscreen rendering")
    finally:
        probe.close()
    duck = load_duck("find-and-kick")
    successes = 0
    report = []
    for seed in SEEDS:
        transport = MujocoTransport(seed=seed, body="puppet")
        adapter = MicroduckAdapter(transport)
        recorder = FrameRecorder(adapter, size=96) if seed == 0 else None
        t0 = time.perf_counter()
        result = await run_duck(
            RunConfig(
                duck=duck,
                provider=FakeProvider.for_duck("find-and-kick"),
                transport=adapter,
                detector=ColorBlobDetector(),
                runs_dir=tmp_path,
                on_frame=recorder.capture if recorder else None,
            )
        )
        wall = time.perf_counter() - t0
        truth = transport.world.ball_displacement_m
        ok = result.outcome == "success" and truth >= 0.3
        successes += ok
        report.append(
            f"seed {seed}: {result.outcome} truth={truth:.2f} m steps={result.steps} {wall:.1f}s"
        )
        assert wall < 60, report[-1]
        assert (result.run_dir / "transcript.jsonl").exists()
        if recorder is not None:
            gif = recorder.save_gif(result.run_dir / "run.gif")
            assert gif.exists() and gif.stat().st_size > 1000
            assert len(recorder.frames) > 5
    assert successes >= MIN_SUCCESSES, "\n".join(report)
