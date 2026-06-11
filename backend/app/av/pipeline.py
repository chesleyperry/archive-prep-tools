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
            if tr.status == "transcribed" and tr.segments:
                result.status = TranscriptStatus.TRANSCRIBED
                transcript_text = " ".join(s.text for s in tr.segments).strip()
                srt = out_dir / f"{lid}_transcript.srt"
                rtf = out_dir / f"{lid}_transcript.rtf"
                srt.write_text(transcribe.to_srt(tr.segments), encoding="utf-8")
                rtf.write_text(transcribe.to_rtf(tr.segments), encoding="utf-8")
                result.outputs += [str(srt), str(rtf)]
            else:
                result.status = TranscriptStatus.NO_SPEECH
    except Exception as exc:  # transcription failure is per-file, not fatal
        result.status = TranscriptStatus.ERROR
        result.error = str(exc)
        return result

    # Enrichment is best-effort: a failure here must not discard transcript files.
    try:
        e = enrich(transcript_text, existing=existing, model=enrich_model)
        result.enrichment = e
        if e.content_description:
            summary = out_dir / f"{lid}_summary.txt"
            summary.write_text(e.content_description, encoding="utf-8")
            result.outputs.append(str(summary))
    except requests.RequestException as exc:
        result.enrichment = Enrichment()
        result.error = f"enrichment failed: {exc}"

    return result
