# Data-Prep Tool

A web tool that checks tabular data for quality problems and documents it before
visualization. Upload a CSV or point to a Google Sheet; the tool profiles every
column, flags empty/outlier/"fishy" cells, plans duplicate merges, and generates
a README + data dictionary — leaving your original file untouched.

> Setup and how to start the server are covered in the top-level
> [README](../README.md). This page is the deeper reference for the Data-Prep
> tool (architecture, extending it, Google Sheets).

## What it does

| Stage | Detail |
| --- | --- |
| **Ingest** | CSV upload or Google Sheet URL (OAuth, read-only). Values read as strings so type problems stay visible. Hard cap: 40,000 rows. |
| **Profile** | Per column: inferred type, fill rate, unique count, min/max/mean, sample values. |
| **Validate** | Six pluggable checks: missing values, statistical outliers (IQR), type inconsistencies, format violations (email/phone/ZIP), inconsistent categories, junk/impossible values. |
| **Dedupe** | Groups duplicate rows; keeps the *most complete* row. A merge that would discard a conflicting non-empty value is marked **review** and is never applied without explicit approval. |
| **Output** | Markdown README + column data dictionary, plus a cleaned CSV. The original is never modified. |

## Architecture

```
backend/
  app/
    main.py            FastAPI routes + serves the frontend
    pipeline.py        orchestrator (framework-free, unit-tested)
    ingest.py          CSV / record loading + row-limit guard
    profiling.py       column type inference & stats
    validation/        pluggable validator framework
      base.py          Validator ABC + registry (@register)
      checks.py        the six built-in checks
      runner.py        runs all validators, isolates failures
    dedup.py           duplicate detection + merge planning
    cleaning.py        safe transforms + merge application (copy only)
    report.py          README + data dictionary generation
    google_sheets.py   OAuth (read-only) Sheets ingestion
    models.py          shared dataclasses (Issue, ColumnProfile, ...)
  static/              no-build HTML/JS frontend (upload, results, downloads)
  tests/               pipeline smoke + unit tests
sample_data/messy.csv  fixture exercising every check
```

**Why this shape:** datasets ≤40k rows fit in memory, so pandas processes each
upload in one pass — no database, no streaming. Each request is stateless;
results are cached in-process by job id only long enough to download artifacts.

### Tests

```bash
cd backend && ../.venv/bin/python tests/test_pipeline.py
```

## Adding a new validator (incl. the future LLM check)

Validators are plugins. Drop a class into `app/validation/checks.py` (or a new
module imported by `validation/__init__.py`):

```python
@register
class MyCheck(Validator):
    name = "my_check"
    description = "What it flags."

    def check(self, df):
        # yield Issue(...) for each finding
        ...
```

The runner, README, and API pick it up automatically. The planned LLM-based
semantic check will subclass `Validator` the same way — it just calls a model
inside `check()` instead of using pandas.

## Google Sheets setup

OAuth is **read-only** by design. To enable it, create a Google Cloud project,
enable the Sheets API, download an OAuth client as
`backend/secrets/client_secret.json`. First use opens a browser consent screen;
the token caches to `backend/secrets/token.json`. See `app/google_sheets.py`.

## Notes / next steps

- **Frontend:** currently a no-build HTML/JS page (Node isn't installed here).
  Swap in a Vite + React SPA for a richer interactive merge-review screen — the
  API contract stays identical.
- **Destructive merges:** the API accepts the merge plan but the approve-and-
  apply UI loop (per-conflict confirmation) is the natural next build step.
- **LLM "fishy cell" pass:** intentionally deferred; the plugin seam is ready.
