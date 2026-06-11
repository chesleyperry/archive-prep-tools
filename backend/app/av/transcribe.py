"""Host-side transcription: drive the 3.12 worker and write SRT/RTF (host side)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from app.av.models import Segment

# worker/.venv/bin/python and worker/transcribe_worker.py, relative to repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER_PYTHON = _REPO_ROOT / "worker" / ".venv" / "bin" / "python"
WORKER_SCRIPT = _REPO_ROOT / "worker" / "transcribe_worker.py"


class TranscriptionResult:
    def __init__(self, segments: list[Segment], language: str | None, status: str):
        self.segments = segments
        self.language = language
        self.status = status            # "transcribed" | "no_speech"


def transcribe(wav_path: str | Path, *, model: str = "small",
               language: str | None = None) -> TranscriptionResult:
    """Run the worker subprocess on a WAV and parse its JSON output."""
    if not WORKER_PYTHON.exists():
        raise FileNotFoundError(
            f"Worker venv not found at {WORKER_PYTHON}. Run worker/setup.sh."
        )
    # The worker writes JSON to a file (not stdout) so native-lib chatter
    # (e.g. Intel MKL warnings printed to stdout) can't corrupt the payload.
    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="avprep_tr_")
    os.close(fd)
    cmd = [str(WORKER_PYTHON), str(WORKER_SCRIPT), "--audio", str(wav_path),
           "--model", model, "--out", out_path]
    if language:
        cmd += ["--language", language]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Worker failed: {proc.stderr.strip()[-500:]}")
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
    finally:
        Path(out_path).unlink(missing_ok=True)
    segments = [Segment(**s) for s in data.get("segments", [])]
    return TranscriptionResult(segments, data.get("language"), data.get("status"))


# ---- transcript serialization -------------------------------------------------

def _ts(seconds: float) -> str:
    """Seconds -> SRT timestamp HH:MM:SS,mmm."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: list[Segment]) -> str:
    blocks = []
    for i, seg in enumerate(segments, start=1):
        blocks.append(f"{i}\n{_ts(seg.start)} --> {_ts(seg.end)}\n{seg.text}\n")
    return "\n".join(blocks)


def _rtf_escape(text: str) -> str:
    out = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    # Escape non-ASCII as \uN? for portable RTF.
    return "".join(c if ord(c) < 128 else f"\\u{ord(c)}?" for c in out)


def to_rtf(segments: list[Segment]) -> str:
    """Readable continuous-prose transcript as a minimal RTF document."""
    body = " ".join(seg.text for seg in segments).strip()
    escaped = _rtf_escape(body).replace("\n", "\\par\n")
    return (
        "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Helvetica;}}\n"
        "\\fs24\n" + escaped + "\n}"
    )
