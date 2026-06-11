"""Audio probing and extraction via ffmpeg/ffprobe (host side).

ffmpeg lives on the host (already installed); the ML worker only ever sees a
normalized 16 kHz mono WAV, so it never needs media codecs of its own.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

MEDIA_EXTENSIONS = {".mp3", ".mp4", ".m4a", ".wav", ".mov", ".aac", ".flac"}

# faster-whisper expects 16 kHz mono PCM.
_TARGET_RATE = 16000


def has_audio_stream(path: str | Path) -> bool:
    """True if ffprobe reports at least one audio stream."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "json",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False
    try:
        return bool(json.loads(proc.stdout or "{}").get("streams"))
    except json.JSONDecodeError:
        return False


def extract_wav(path: str | Path, dest_dir: str | Path | None = None) -> Path:
    """Decode the audio track to a 16 kHz mono WAV and return its path.

    Caller owns the returned file; pass ``dest_dir`` to control where it lands
    (otherwise a tempdir is used).
    """
    src = Path(path)
    out_dir = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(prefix="avprep_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}.16k.wav"
    proc = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y",
            "-i", str(src),
            "-vn",                      # drop video
            "-ac", "1",                 # mono
            "-ar", str(_TARGET_RATE),   # 16 kHz
            "-c:a", "pcm_s16le",
            str(out),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {src.name}: {proc.stderr.strip()[-500:]}")
    return out


def discover_media(input_dir: str | Path) -> list[Path]:
    """Return media files in ``input_dir`` (non-recursive), sorted by name."""
    base = Path(input_dir)
    if not base.is_dir():
        raise NotADirectoryError(f"Not a directory: {base}")
    return sorted(
        p for p in base.iterdir()
        if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS
    )


def local_identifier(path: str | Path) -> str:
    """The unique ID = filename without extension."""
    return Path(path).stem
