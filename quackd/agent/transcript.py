"""Every run leaves a paper trail: `runs/<timestamp>/transcript.jsonl`, frames, a summary.

A transcript exists so a run can be argued about after the fact — which prompt, which
tool call, which result, how many tokens — and so the golden tests can pin the loop's
behaviour without an LLM in the room.
"""

from __future__ import annotations

import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image

if TYPE_CHECKING:
    from quackd.trace import TraceEvent


def new_run_dir(base: str | Path = "runs", name: str | None = None) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    suffix = f"-{name}" if name else ""
    path = Path(base) / f"{stamp}{suffix}"
    i = 1
    while path.exists():
        path = Path(base) / f"{stamp}{suffix}-{i}"
        i += 1
    path.mkdir(parents=True, exist_ok=False)
    return path


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class Transcript:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.path = run_dir / "transcript.jsonl"
        self.frames_dir = run_dir / "frames"
        self._fh = self.path.open("a", encoding="utf-8")
        self._t0 = time.monotonic()
        self.events = 0
        self.frame_count = 0

    def write(self, kind: str, **payload: Any) -> None:
        record = {"t": round(time.monotonic() - self._t0, 3), "kind": kind, **payload}
        self._fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        self._fh.flush()
        self.events += 1

    def sink(self, event: TraceEvent) -> None:
        """The transcript as a `Tracer` record: the event's kind and payload, on the
        transcript's own clock, so a `frame` written directly and an `observation` that came
        through the tracer never disagree about the time."""
        self.write(event.kind, **event.data)

    def save_frame(self, img: Image.Image, caption: str = "") -> Path:
        self.frames_dir.mkdir(exist_ok=True)
        path = self.frames_dir / f"{self.frame_count:04d}.png"
        img.save(path, format="PNG")
        self.write("frame", path=str(path.relative_to(self.run_dir)), caption=caption)
        self.frame_count += 1
        return path

    def write_summary(self, summary: dict[str, Any]) -> Path:
        path = self.run_dir / "summary.json"
        path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        return path

    def close(self) -> None:
        self._fh.close()

    @staticmethod
    def read(path: Path) -> list[dict[str, Any]]:
        with path.open(encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
