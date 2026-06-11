"""FastAPI application: upload/analyze endpoints + static frontend.

In-memory, stateless design: each request analyzes one dataset and returns the
results plus generated artifacts. Analysis results are cached briefly in memory
by job id so the frontend can download the README and cleaned CSV without
re-uploading. (Swap this for Redis/disk if you later want persistence.)
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app import ingest
from app.av import jobs as av_jobs
from app.pipeline import AnalysisResult, analyze

app = FastAPI(title="Data-Prep Tool", version="0.1.0")

# Simple in-process job cache: job_id -> AnalysisResult.
# Bounded so a long-running server doesn't leak memory.
_JOBS: dict[str, AnalysisResult] = {}
_JOB_ORDER: list[str] = []
_MAX_JOBS = 50

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _store(result: AnalysisResult) -> str:
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = result
    _JOB_ORDER.append(job_id)
    while len(_JOB_ORDER) > _MAX_JOBS:
        evicted = _JOB_ORDER.pop(0)
        _JOBS.pop(evicted, None)
    return job_id


def _get(job_id: str) -> AnalysisResult:
    result = _JOBS.get(job_id)
    if result is None:
        raise HTTPException(404, "Unknown or expired job id.")
    return result


def _parse_keys(key_columns: str | None) -> list[str] | None:
    if not key_columns:
        return None
    keys = [k.strip() for k in key_columns.split(",") if k.strip()]
    return keys or None


@app.post("/api/analyze/csv")
async def analyze_csv(
    file: UploadFile,
    key_columns: str | None = Form(default=None),
):
    """Analyze an uploaded CSV file."""
    raw = await file.read()
    try:
        df = ingest.load_csv(raw)
        result = analyze(
            df,
            source_name=file.filename or "uploaded.csv",
            key_columns=_parse_keys(key_columns),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    job_id = _store(result)
    return {"job_id": job_id, **result.to_dict()}


@app.post("/api/analyze/sheet")
async def analyze_sheet(
    url: str = Form(...),
    key_columns: str | None = Form(default=None),
):
    """Analyze a Google Sheet by URL (requires OAuth setup — see google_sheets.py)."""
    try:
        from app.google_sheets import load_sheet

        df = load_sheet(url)
        result = analyze(
            df, source_name=url, key_columns=_parse_keys(key_columns)
        )
    except FileNotFoundError as exc:
        raise HTTPException(501, str(exc))  # OAuth not configured yet
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    job_id = _store(result)
    return {"job_id": job_id, **result.to_dict()}


@app.get("/api/jobs/{job_id}/readme")
def download_readme(job_id: str):
    result = _get(job_id)
    return Response(
        content=result.readme_markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": 'attachment; filename="README.md"'},
    )


@app.get("/api/jobs/{job_id}/cleaned")
def download_cleaned(job_id: str):
    result = _get(job_id)
    return Response(
        content=result.cleaned_csv,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="cleaned.csv"'},
    )


# ---- AV File Access Preparation ----------------------------------------------

@app.post("/api/av/batch")
async def av_start_batch(
    input_dir: str = Form(...),
    output_dir: str = Form(...),
    id_column: str = Form(default="localIdentifier"),
    whisper_model: str = Form(default="small"),
    enrich_model: str = Form(default="qwen2.5:latest"),
    file: UploadFile | None = None,
):
    """Start a batch over a local media directory. Returns a job id to poll."""
    if not Path(input_dir).is_dir():
        raise HTTPException(400, f"Input directory not found: {input_dir}")
    csv_bytes = await file.read() if file is not None else None
    job_id = av_jobs.start_job(
        input_dir=input_dir,
        output_dir=output_dir,
        csv_bytes=csv_bytes,
        id_column=id_column,
        whisper_model=whisper_model,
        enrich_model=enrich_model,
    )
    return {"job_id": job_id}


@app.get("/api/av/batch/{job_id}")
def av_progress(job_id: str):
    job = av_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown or expired job id.")
    return job.progress()


@app.post("/api/av/batch/{job_id}/cancel")
def av_cancel(job_id: str):
    if not av_jobs.cancel(job_id):
        raise HTTPException(404, "Job not found or not cancellable.")
    return {"status": "cancelling"}


@app.get("/api/av/batch/{job_id}/csv")
def av_download_csv(job_id: str):
    job = av_jobs.get(job_id)
    if job is None or not job.csv_path:
        raise HTTPException(404, "No metadata CSV available yet.")
    path = Path(job.csv_path)
    return Response(
        content=path.read_bytes(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


# Serve the lightweight frontend at "/".
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
else:  # pragma: no cover

    @app.get("/", response_class=HTMLResponse)
    def _no_frontend():
        return "<h1>Backend running.</h1><p>See /docs for the API.</p>"
