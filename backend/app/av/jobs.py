"""Batch job manager: runs the pipeline over a directory in a background thread.

Holds progress in-process (like backend/app/main.py's job cache) and rewrites
the batch CSV after every file, so polling sees live progress and a crash keeps
all completed work on disk.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app import ingest
from app.av import probe
from app.av.enrich import DEFAULT_MODEL
from app.av.merge import DEFAULT_ID_COLUMN, merge_results, output_filename, to_csv_bytes
from app.av.models import FileResult
from app.av.pipeline import process_file


@dataclass
class Job:
    id: str
    input_dir: str
    output_dir: str
    id_column: str = DEFAULT_ID_COLUMN
    whisper_model: str = "small"
    enrich_model: str = DEFAULT_MODEL
    known_entities: str = ""
    status: str = "queued"        # queued|running|done|cancelled|error
    total: int = 0
    completed: int = 0
    current: str = ""
    csv_path: str | None = None
    error: str | None = None
    results: list[FileResult] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def progress(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "current": self.current,
            "csv_filename": Path(self.csv_path).name if self.csv_path else None,
            "error": self.error,
            "results": [r.to_dict() for r in self.results],
        }


_JOBS: dict[str, Job] = {}
_ORDER: list[str] = []
_MAX_JOBS = 20


def get(job_id: str) -> Job | None:
    return _JOBS.get(job_id)


def cancel(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if job and job.status in ("queued", "running"):
        job.cancel_event.set()
        return True
    return False


def start_job(
    *,
    input_dir: str,
    output_dir: str,
    csv_bytes: bytes | None,
    id_column: str = DEFAULT_ID_COLUMN,
    whisper_model: str = "small",
    enrich_model: str = DEFAULT_MODEL,
    known_entities: str = "",
) -> str:
    job = Job(
        id=uuid.uuid4().hex,
        input_dir=input_dir,
        output_dir=output_dir,
        id_column=id_column,
        whisper_model=whisper_model,
        enrich_model=enrich_model,
        known_entities=known_entities,
    )
    _JOBS[job.id] = job
    _ORDER.append(job.id)
    while len(_ORDER) > _MAX_JOBS:
        _JOBS.pop(_ORDER.pop(0), None)
    threading.Thread(target=_run, args=(job, csv_bytes), daemon=True).start()
    return job.id


def _load_original(csv_bytes: bytes | None, id_column: str) -> pd.DataFrame:
    if csv_bytes:
        return ingest.load_csv(csv_bytes)
    return pd.DataFrame(columns=[id_column]).astype("string")


def _existing_rows(df: pd.DataFrame, id_column: str) -> dict[str, dict[str, str]]:
    if id_column not in df.columns:
        return {}
    rows: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        rid = row.get(id_column)
        if pd.isna(rid):
            continue
        rows[str(rid)] = {
            c: ("" if pd.isna(row[c]) else str(row[c]))
            for c in df.columns if c != id_column
        }
    return rows


def _write_csv(job: Job, original: pd.DataFrame) -> None:
    merged = merge_results(original, job.results, id_column=job.id_column)
    out = Path(job.output_dir) / output_filename()
    out.write_bytes(to_csv_bytes(merged))
    job.csv_path = str(out)


def _run(job: Job, csv_bytes: bytes | None) -> None:
    try:
        original = _load_original(csv_bytes, job.id_column)
        existing = _existing_rows(original, job.id_column)
        media = probe.discover_media(job.input_dir)
        job.total = len(media)
        job.status = "running"
        Path(job.output_dir).mkdir(parents=True, exist_ok=True)

        for path in media:
            if job.cancel_event.is_set():
                job.status = "cancelled"
                break
            job.current = path.name
            res = process_file(
                path,
                existing.get(probe.local_identifier(path), {}),
                output_dir=job.output_dir,
                whisper_model=job.whisper_model,
                enrich_model=job.enrich_model,
                known_entities=job.known_entities,
            )
            job.results.append(res)
            job.completed += 1
            _write_csv(job, original)   # incremental, crash-resilient

        _write_csv(job, original)       # final (also covers the empty-batch case)
        if job.status == "running":
            job.status = "done"
        job.current = ""
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
