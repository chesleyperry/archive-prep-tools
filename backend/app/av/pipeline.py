"""Per-file orchestration: probe -> transcribe -> enrich -> write outputs.

Framework-free and side-effecting only through the given ``output_dir`` so it
can be unit-tested directly. Mirrors the structure of backend/app/pipeline.py.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import requests

from app.av import probe, transcribe
from app.av.enrich import DEFAULT_MODEL, enrich
from app.av.models import Enrichment, FileResult, TranscriptStatus


def process_file(
    media_path: str | Path,
    existing: dict[str, str] | None = None,
    *,
    output_dir: str | Path,
    whisper_model: str = "small",
    enrich_model: str = DEFAULT_MODEL,
    language: str | None = None,
    known_entities: str = "",
) -> FileResult:
    """Run the full pipeline for one media file and write its derivatives.

    Outputs are written incrementally to ``output_dir`` as they are produced, so
    a crash on a later file never loses earlier files' work.
    """
    media_path = Path(media_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lid = probe.local_identifier(media_path)
    result = FileResult(
        local_identifier=lid,
        source_path=str(media_path),
        status=TranscriptStatus.NO_AUDIO,
        duration_seconds=probe.get_duration(media_path),
    )

    transcript_text = ""
    try:
        if probe.has_audio_stream(media_path):
            tmp = Path(tempfile.mkdtemp(prefix="avprep_"))
            try:
                wav = probe.extract_wav(media_path, dest_dir=tmp)
                tr = transcribe.transcribe(wav, model=whisper_model, language=language)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

            result.segments = tr.segments
            result.language = tr.language

            speech_segs = [s for s in tr.segments if s.kind == "speech"]
            music_segs = [s for s in tr.segments if s.kind == "music"]

            if speech_segs:
                if music_segs:
                    result.status = TranscriptStatus.PARTIAL
                else:
                    result.status = TranscriptStatus.TRANSCRIBED
                transcript_text = " ".join(s.text for s in speech_segs).strip()
                srt = out_dir / f"{lid}_transcript.srt"
                rtf = out_dir / f"{lid}_transcript.rtf"
                srt.write_text(transcribe.to_srt(speech_segs), encoding="utf-8")
                rtf.write_text(transcribe.to_rtf(speech_segs), encoding="utf-8")
                result.outputs += [str(srt), str(rtf)]
            elif music_segs:
                result.status = TranscriptStatus.MUSIC_ONLY
            else:
                result.status = TranscriptStatus.NO_SPEECH
    except Exception as exc:  # transcription failure is per-file, not fatal
        result.status = TranscriptStatus.ERROR
        result.error = str(exc)
        return result

    # Enrichment is best-effort: a failure here must not discard transcript files.
    # content_description goes into the CSV only — no separate summary file is written.
    try:
        e = enrich(
            transcript_text,
            existing=existing,
            model=enrich_model,
            known_entities=known_entities,
        )
        result.enrichment = e
    except requests.RequestException as exc:
        result.enrichment = Enrichment()
        result.error = f"enrichment failed: {exc}"

    return result
