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
        if not text:
            continue
        segments.append({
            "start": round(float(seg["start"]), 3),
            "end": round(float(seg["end"]), 3),
            "text": text,
            "kind": "speech",
        })

    out = {
        "language": result.get("language"),
        "status": "transcribed" if segments else "no_speech",
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
