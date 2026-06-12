"""Transcription worker — runs inside the Python 3.12 venv (worker/.venv).

Uses Apple's MLX Whisper (`mlx_whisper`), which runs on the M2 Max GPU/ANE via
Metal — typically 5-10x faster than CPU faster-whisper. Invoked as a subprocess
by the host with a 16 kHz mono WAV; emits a single JSON object to the `--out`
file (NOT stdout, which native libs can pollute):

    {"language": "en", "status": "transcribed",
     "segments": [{"start": 0.0, "end": 3.2, "text": "...", "kind": "speech"}]}

status is "transcribed" if any speech text was produced, else "no_speech".
"""
from __future__ import annotations

import argparse
import json
import sys

# Friendly size -> mlx-community Hugging Face repo. A value containing "/" is
# treated as an explicit repo and passed through unchanged.
MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}


def _is_music(seg: dict) -> bool:
    """True if a Whisper segment looks like singing or non-speech audio.

    Uses three signals that Whisper already computes:
    - no_speech_prob > 0.6: Whisper itself doubts this is speech
    - musical note characters (♪ ♫) in the transcribed text
    - compression_ratio > 2.4: highly repetitive text (common music artifact)
    """
    text = (seg.get("text") or "").strip()
    if seg.get("no_speech_prob", 0.0) > 0.6:
        return True
    if "♪" in text or "♫" in text:
        return True
    if seg.get("compression_ratio", 0.0) > 2.4:
        return True
    return False


def resolve_repo(model: str) -> str:
    if "/" in model:
        return model
    return MODEL_REPOS.get(model, MODEL_REPOS["small"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="path to 16kHz mono WAV")
    ap.add_argument("--model", default="small", help="size (tiny..large-v3) or HF repo")
    ap.add_argument("--language", default=None, help="force language, else auto")
    ap.add_argument("--out", default=None, help="write JSON here instead of stdout")
    args = ap.parse_args()

    import mlx_whisper

    result = mlx_whisper.transcribe(
        args.audio,
        path_or_hf_repo=resolve_repo(args.model),
        language=args.language,
    )

    segments = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if _is_music(seg):
            # Keep a placeholder so the host knows a music span exists here.
            segments.append({
                "start": round(float(seg["start"]), 3),
                "end": round(float(seg["end"]), 3),
                "text": "",
                "kind": "music",
            })
        elif text:
            segments.append({
                "start": round(float(seg["start"]), 3),
                "end": round(float(seg["end"]), 3),
                "text": text,
                "kind": "speech",
            })

    speech = sum(1 for s in segments if s["kind"] == "speech")
    music = sum(1 for s in segments if s["kind"] == "music")
    if speech and music:
        status = "partial"
    elif speech:
        status = "transcribed"
    elif music:
        status = "music_only"
    else:
        status = "no_speech"

    out = {
        "language": result.get("language"),
        "status": status,
        "segments": segments,
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh)
    else:
        json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
