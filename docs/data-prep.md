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

## Dublin Core XML export

After analyzing a spreadsheet, the results page offers **Export to Dublin Core
XML**: one Simple Dublin Core (`oai_dc`) XML file per row, bundled into a ZIP.

Workflow:
1. Each column gets a dropdown mapping it to one of the 15 Dublin Core elements
   (or *skip*). The tool pre-fills a best guess from the column name; you adjust.
2. Pick which column names each file. Blank values fall back to `row-N`;
   duplicate names get a `-1`/`-2` suffix so nothing is overwritten.
3. Cells holding several values separated by `|` become repeated elements
   (e.g. two `<dc:creator>`). Empty cells produce no tags; special characters
   are XML-escaped.

Code: `app/dublin_core.py` (framework-free, tested in
`tests/test_dublin_core.py`). API: `GET /api/jobs/{id}/dc-mapping` returns the
columns, the 15 elements, and the suggested mapping; `POST /api/jobs/{id}/dc-export`
takes the mapping (JSON), the filename column, and a split-values flag, and
returns the ZIP. Multiple columns may map to the same element.

## Draft Merritt manifest export

Below the Dublin Core card, **Export draft Merritt manifest** writes a UTF-8 CSV
with one row per object and the exact headers Merritt expects, in order:

    nfo:fileName, mrt:localIdentifier, mrt:creator, mrt:title, mrt:date

Five dropdowns map each manifest field to a spreadsheet column (name-based best
guess pre-filled; the filename field prefers a column like "Primary File Name"
while a bare "Filename" is guessed for the local identifier). When a cell holds
several values separated by `|`, **only the first value** is used, since each
manifest field takes one value. Rows where every mapped field is empty are
skipped.

Code: `app/merritt_manifest.py` (framework-free, tested in
`tests/test_merritt_manifest.py`). API: `GET /api/jobs/{id}/manifest-mapping`
returns the columns, the field definitions, and the suggested mapping;
`POST /api/jobs/{id}/manifest-export` takes the mapping (JSON) and returns the CSV.

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
