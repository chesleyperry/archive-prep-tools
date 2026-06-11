"""Transcription worker — runs inside the Python 3.12 venv (worker/.venv).

Invoked as a subprocess by the host app with a 16 kHz mono WAV. Uses
faster-whisper with built-in Silero VAD to drop silence and non-speech, then
emits a single JSON object on stdout:

    {"language": "en", "status": "transcribed",
     "segments": [{"start": 0.0, "end": 3.2, "text": "...", "kind": "speech"}]}

status is "transcribed" if any speech was found, else "no_speech". Kept
dependency-isolated from the host (Python 3.14) so heavy ML wheels never need to
resolve against the host interpreter.
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="path to 16kHz mono WAV")
    ap.add_argument("--model", default="small", help="whisper model size")
    ap.add_argument("--language", default=None, help="force language, else auto")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--out", default=None,
                    help="write JSON here instead of stdout (avoids stdout "
                         "pollution from native libs like Intel MKL)")
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type)
    segments_iter, info = model.transcribe(
        args.audio,
        language=args.language,
        vad_filter=True,                       # Silero VAD: skip silence / non-speech
        vad_parameters={"min_silence_duration_ms": 500},
    )

    segments = []
    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": text,
            "kind": "speech",
        })

    out = {
        "language": info.language,
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
