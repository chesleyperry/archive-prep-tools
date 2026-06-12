"""Merge per-file enrichment into the user's CSV (host side).

Adds new columns only — the user's existing data is never overwritten. Rows are
matched on the unique ID (filename without extension). Media files with no
matching CSV row are appended as new rows; CSV rows with no media file are kept
untouched with the new columns left blank.
"""
from __future__ import annotations

import datetime as _dt
import io

import pandas as pd

from app.av.models import Enrichment, FileResult
from app.av.probe import format_duration

DEFAULT_ID_COLUMN = "localIdentifier"

# New columns this tool adds. Order = column order in the output CSV.
NEW_COLUMNS = [
    "duration",
    "suggested_title",
    "suggested_date",
    "content_description",
    "persons",
    "places",
    "music_titles",
    "poem_titles",
    "book_titles",
    "transcript_status",
]


def results_to_frame(results: list[FileResult], id_column: str) -> pd.DataFrame:
    rows = []
    for r in results:
        e = r.enrichment or Enrichment()
        rows.append({
            id_column: r.local_identifier,
            "duration": format_duration(r.duration_seconds),
            "suggested_title": e.suggested_title,
            "suggested_date": e.suggested_date,
            "content_description": e.content_description,
            "persons": "; ".join(e.persons),
            "places": "; ".join(e.places),
            "music_titles": "; ".join(e.music_titles),
            "poem_titles": "; ".join(e.poem_titles),
            "book_titles": "; ".join(e.book_titles),
            "transcript_status": r.status.value,
        })
    return pd.DataFrame(rows, columns=[id_column, *NEW_COLUMNS]).astype("string")


def merge_results(
    original: pd.DataFrame,
    results: list[FileResult],
    *,
    id_column: str = DEFAULT_ID_COLUMN,
) -> pd.DataFrame:
    """Return ``original`` with the new columns joined on ``id_column``.

    The original columns and row order are preserved; new columns are appended.
    """
    if id_column not in original.columns:
        raise ValueError(
            f"Join column '{id_column}' not found in CSV (have: "
            f"{', '.join(original.columns)})."
        )
    # Guard against accidental overwrite if a new column name already exists.
    collisions = [c for c in NEW_COLUMNS if c in original.columns]
    if collisions:
        raise ValueError(f"CSV already contains tool columns: {', '.join(collisions)}")

    new_df = results_to_frame(results, id_column)
    merged = original.merge(new_df, on=id_column, how="left")

    matched = set(original[id_column].dropna())
    extra = new_df[~new_df[id_column].isin(matched)]
    if not extra.empty:
        merged = pd.concat([merged, extra], ignore_index=True)
    return merged


def output_filename(today: _dt.date | None = None) -> str:
    today = today or _dt.date.today()
    return f"AV_metadata_{today.isoformat()}.csv"


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")
