"""Export spreadsheet rows as Simple Dublin Core XML files.

One XML file per row, bundled into a ZIP. The caller supplies a mapping from
spreadsheet column -> Dublin Core element (columns may be left unmapped), and
picks which column supplies each file's name. Cells holding several values
separated by a delimiter (default ``|``) become repeated elements.

Framework-free and unit-tested (see backend/tests/test_dublin_core.py).
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

import pandas as pd

# The 15 elements of Simple (unqualified) Dublin Core, in canonical order.
DC_ELEMENTS: list[str] = [
    "title",
    "creator",
    "subject",
    "description",
    "publisher",
    "contributor",
    "date",
    "type",
    "format",
    "identifier",
    "source",
    "language",
    "relation",
    "coverage",
    "rights",
]

# Column-name hints for auto-suggesting a mapping. Longest matching hint wins,
# so "physical description" maps to `format`, not `description`. These are only
# first guesses — the user confirms or changes every column on the mapping
# screen, so imperfect matches are harmless.
_SYNONYMS: dict[str, list[str]] = {
    "title": ["title"],
    "creator": ["creator", "author", "photographer", "artist"],
    "subject": ["subject", "topics", "topic", "keywords", "keyword", "tags"],
    "description": ["description", "abstract", "summary", "notes", "note"],
    "publisher": ["publisher"],
    "contributor": ["contributor"],
    "date": ["date", "year", "created index"],
    "type": ["dcmi resource type", "resource type", "type"],
    "format": ["physical description", "format", "extent", "mimetype", "mimetypes", "dimensions"],
    "identifier": ["accession number", "item call number", "call number", "identifier", "ark", "permalink"],
    "source": ["collection title", "super collection", "collection", "source"],
    "language": ["language", "lang"],
    "relation": ["collection guide", "relation", "related", "ispartof", "is part of"],
    "coverage": ["coverage", "place", "location", "address", "spatial", "temporal", "region"],
    "rights": ["copyright statement", "copyright holder", "access rights", "rights status", "copyright", "rights", "license"],
}

_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"\n'
    '           xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
    '           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
    '           xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/oai_dc/ '
    'http://www.openarchives.org/OAI/2.0/oai_dc.xsd">\n'
)
_FOOTER = "</oai_dc:dc>\n"


@dataclass
class ExportSummary:
    file_count: int
    blank_filenames: int       # rows whose filename column was empty (row-N used)
    renamed_collisions: int    # duplicate filenames that got a -1/-2 suffix
    skipped_empty_rows: int    # rows that produced no Dublin Core values at all

    def to_dict(self) -> dict:
        return {
            "file_count": self.file_count,
            "blank_filenames": self.blank_filenames,
            "renamed_collisions": self.renamed_collisions,
            "skipped_empty_rows": self.skipped_empty_rows,
        }


def suggest_mapping(columns: list[str]) -> dict[str, str | None]:
    """Guess a Dublin Core element for each column (or None to skip it)."""
    suggestion: dict[str, str | None] = {}
    for col in columns:
        lc = str(col).strip().lower()
        best_element: str | None = None
        best_len = 0
        for element, hints in _SYNONYMS.items():
            for hint in hints:
                if hint in lc and len(hint) > best_len:
                    best_element = element
                    best_len = len(hint)
        suggestion[col] = best_element
    return suggestion


def _is_empty(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    try:
        if pd.isna(val):
            return True
    except (TypeError, ValueError):
        pass
    return str(val).strip() == ""


def _values(cell, split: bool, delimiter: str) -> list[str]:
    """Split a cell into one or more trimmed, non-empty values."""
    if _is_empty(cell):
        return []
    text = str(cell).strip()
    if split and delimiter:
        return [p.strip() for p in text.split(delimiter) if p.strip()]
    return [text]


def row_to_dc_xml(
    row: dict,
    mapping: dict[str, str | None],
    *,
    split: bool = True,
    delimiter: str = "|",
) -> str:
    """Build one Simple Dublin Core XML document from a single row.

    ``mapping`` maps column name -> DC element (or None/"" to skip). Elements are
    emitted in canonical Dublin Core order; empty cells produce no tags.
    """
    # invert mapping to element -> [columns], preserving column order
    element_to_cols: dict[str, list[str]] = {}
    for col, element in mapping.items():
        if not element:
            continue
        if element not in DC_ELEMENTS:
            continue
        element_to_cols.setdefault(element, []).append(col)

    lines = [_HEADER]
    for element in DC_ELEMENTS:
        for col in element_to_cols.get(element, []):
            for value in _values(row.get(col), split, delimiter):
                lines.append(f"  <dc:{element}>{escape(value)}</dc:{element}>\n")
    lines.append(_FOOTER)
    return "".join(lines)


def sanitize_filename(name: str) -> str:
    """Make a safe XML filename stem (no extension) from a cell value."""
    stem = str(name).strip()
    # replace characters illegal or awkward in filenames
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"\s+", "_", stem)
    stem = stem.strip("._")
    return stem[:150] or ""


def build_dc_zip(
    df: pd.DataFrame,
    mapping: dict[str, str | None],
    filename_column: str,
    *,
    split: bool = True,
    delimiter: str = "|",
) -> tuple[bytes, ExportSummary]:
    """Produce a ZIP of one Dublin Core XML file per row, plus a summary.

    Filenames come from ``filename_column``. Blank values fall back to
    ``row-N``; duplicate names get a ``-1``/``-2`` suffix so nothing is
    overwritten.
    """
    if filename_column not in df.columns:
        raise ValueError(f"Filename column '{filename_column}' is not in the sheet.")
    if not any(mapping.get(c) for c in mapping):
        raise ValueError("No columns are mapped to a Dublin Core field yet.")

    blank_filenames = 0
    renamed_collisions = 0
    skipped_empty_rows = 0
    used_names: set[str] = set()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for position, (_, row) in enumerate(df.iterrows(), start=1):
            row_dict = row.to_dict()
            xml = row_to_dc_xml(row_dict, mapping, split=split, delimiter=delimiter)

            # a row with every mapped cell empty yields just header+footer
            if xml.count("<dc:") == 0:
                skipped_empty_rows += 1
                continue

            raw_name = row_dict.get(filename_column)
            stem = sanitize_filename(raw_name) if not _is_empty(raw_name) else ""
            if not stem:
                stem = f"row-{position}"
                blank_filenames += 1

            unique = stem
            n = 1
            while unique in used_names:
                unique = f"{stem}-{n}"
                n += 1
            if unique != stem:
                renamed_collisions += 1
            used_names.add(unique)

            zf.writestr(f"{unique}.xml", xml)

    summary = ExportSummary(
        file_count=len(used_names),
        blank_filenames=blank_filenames,
        renamed_collisions=renamed_collisions,
        skipped_empty_rows=skipped_empty_rows,
    )
    return buffer.getvalue(), summary
