"""Export a draft Merritt ingest manifest as a UTF-8 CSV.

One row per object, with the exact column headers Merritt expects:

    nfo:fileName, mrt:localIdentifier, mrt:creator, mrt:title, mrt:date

The caller maps each manifest field to a spreadsheet column. When a cell holds
several values separated by a delimiter (default ``|``), only the first value is
used (one value per manifest field).

Framework-free and unit-tested (see backend/tests/test_merritt_manifest.py).
"""
from __future__ import annotations

import csv
import io

import pandas as pd

# (field key, friendly label for the UI, exact Merritt CSV header) in output order.
MANIFEST_FIELDS: list[tuple[str, str, str]] = [
    ("filename", "Digital object filename", "nfo:fileName"),
    ("local_identifier", "Local identifier", "mrt:localIdentifier"),
    ("creator", "Creator", "mrt:creator"),
    ("title", "Title", "mrt:title"),
    ("date", "Date", "mrt:date"),
]

# Column-name hints for the auto-suggested mapping. Exact matches win over
# substring matches; among exacts, the longest hint wins (so the manifest
# `filename` prefers a column like "Primary File Name" over a bare "Filename",
# leaving "Filename" to serve as the local identifier). The user confirms or
# changes every field on screen, so imperfect guesses are harmless.
_SYNONYMS: dict[str, list[str]] = {
    "filename": [
        "nfo:filename", "primary file name", "primary filename",
        "file name", "filename", "object file name", "digital file name",
    ],
    "local_identifier": [
        "mrt:localidentifier", "object local id", "local identifier",
        "localidentifier", "local id", "identifier", "filename",
    ],
    "creator": ["mrt:creator", "creator", "author", "photographer", "artist"],
    "title": ["mrt:title", "title"],
    "date": ["mrt:date", "date created index", "date created", "date", "year"],
}


def suggest_manifest_mapping(columns: list[str]) -> dict[str, str | None]:
    """Guess which spreadsheet column feeds each manifest field (or None)."""
    suggestion: dict[str, str | None] = {}
    for key, _, _ in MANIFEST_FIELDS:
        synonyms = _SYNONYMS[key]
        best: str | None = None
        best_score = -1
        for col in columns:
            lc = str(col).strip().lower()
            for syn in synonyms:
                if lc == syn:
                    score = 1000 + len(syn)   # exact match, longer hint wins ties
                elif syn in lc:
                    score = len(syn)
                else:
                    continue
                if score > best_score:
                    best_score = score
                    best = col
        suggestion[key] = best
    return suggestion


def _first_value(cell, delimiter: str = "|") -> str:
    """Return the first non-empty value in a cell (splitting on ``delimiter``)."""
    if cell is None:
        return ""
    try:
        if pd.isna(cell):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(cell).strip()
    if not text:
        return ""
    if delimiter and delimiter in text:
        for part in text.split(delimiter):
            if part.strip():
                return part.strip()
        return ""
    return text


def build_manifest_csv(
    df: pd.DataFrame,
    mapping: dict[str, str | None],
    *,
    delimiter: str = "|",
) -> tuple[bytes, dict]:
    """Build the manifest CSV (UTF-8) and a small summary.

    ``mapping`` maps each manifest field key (filename, local_identifier,
    creator, title, date) to a spreadsheet column name (or empty to leave the
    column blank). Rows where every mapped field is empty are skipped.
    """
    if not any(mapping.get(key) for key, _, _ in MANIFEST_FIELDS):
        raise ValueError("No manifest fields are mapped to a column yet.")

    headers = [header for _, _, header in MANIFEST_FIELDS]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)

    row_count = 0
    skipped_empty = 0
    for _, row in df.iterrows():
        values = []
        for key, _, _ in MANIFEST_FIELDS:
            col = mapping.get(key)
            if col and col in df.columns:
                values.append(_first_value(row.get(col), delimiter))
            else:
                values.append("")
        if not any(values):
            skipped_empty += 1
            continue
        writer.writerow(values)
        row_count += 1

    summary = {"row_count": row_count, "skipped_empty_rows": skipped_empty}
    return buffer.getvalue().encode("utf-8"), summary
