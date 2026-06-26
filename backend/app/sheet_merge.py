"""Merge a *new* spreadsheet into a *master* spreadsheet (an "upsert").

Rules (agreed with the user, 2026-06-25):
  * Rows are matched across the two sheets on one or more **key columns**.
  * **Fill blanks:** where the master cell is empty and the new sheet has a
    value, copy it in.
  * **Longer wins:** where both have a value but they differ, the *longer*
    (more detailed) value wins. Equal-length-but-different values keep the
    master's and are reported as "differences not applied" so nothing is lost
    silently.
  * **New rows:** keys present in the new sheet but not the master are appended.
  * **New columns:** columns present in the new sheet but not the master are
    added.

The master file is never modified in place — this returns a *new* merged frame
plus a full change report so every edit is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.dedup import _is_empty, _norm  # shared empty/normalize helpers
from app.models import _jsonable


@dataclass
class CellChange:
    key: dict[str, Any]
    column: str
    old_value: Any
    new_value: Any
    reason: str  # "filled_blank" | "longer_wins"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": {k: _jsonable(v) for k, v in self.key.items()},
            "column": self.column,
            "old_value": _jsonable(self.old_value),
            "new_value": _jsonable(self.new_value),
            "reason": self.reason,
        }


@dataclass
class KeptDifference:
    """A genuine disagreement where the master was kept (new value not longer)."""

    key: dict[str, Any]
    column: str
    master_value: Any
    new_value: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": {k: _jsonable(v) for k, v in self.key.items()},
            "column": self.column,
            "master_value": _jsonable(self.master_value),
            "new_value": _jsonable(self.new_value),
        }


@dataclass
class MergeResult:
    key_columns: list[str]
    master_row_count: int
    new_row_count: int
    merged_row_count: int
    rows_added: int
    rows_updated: int
    columns_added: list[str]
    cells_filled: int
    cells_updated: int
    differences_kept: int
    changes: list[CellChange]
    kept_differences: list[KeptDifference]
    warnings: list[str]
    merged_csv: bytes = b""
    report_markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        # cap the detail lists so a huge merge doesn't return a giant payload
        return {
            "key_columns": self.key_columns,
            "master_row_count": self.master_row_count,
            "new_row_count": self.new_row_count,
            "merged_row_count": self.merged_row_count,
            "rows_added": self.rows_added,
            "rows_updated": self.rows_updated,
            "columns_added": self.columns_added,
            "cells_filled": self.cells_filled,
            "cells_updated": self.cells_updated,
            "differences_kept": self.differences_kept,
            "warnings": self.warnings,
            "changes": [c.to_dict() for c in self.changes[:500]],
            "kept_differences": [k.to_dict() for k in self.kept_differences[:500]],
        }


def _key_tuple(row: pd.Series, key_columns: list[str]) -> tuple:
    return tuple(_norm(row[k]) for k in key_columns)


def _value_len(val: Any) -> int:
    return len(str(val).strip())


def merge_sheets(
    master: pd.DataFrame,
    new: pd.DataFrame,
    key_columns: list[str],
) -> MergeResult:
    """Merge ``new`` into ``master`` and return the merged frame + change report."""
    if not key_columns:
        raise ValueError("At least one key column is required to match records.")
    for side, df in (("master", master), ("new", new)):
        missing = [k for k in key_columns if k not in df.columns]
        if missing:
            raise ValueError(f"Key column(s) {missing} not found in the {side} sheet.")

    merged = master.copy()
    warnings: list[str] = []

    # 1. add any columns the new sheet has that the master lacks
    columns_added = [c for c in new.columns if c not in merged.columns]
    for col in columns_added:
        merged[col] = pd.array([pd.NA] * len(merged), dtype="string")

    # 2. index the master by key (first occurrence wins on duplicate keys)
    master_key_to_idx: dict[tuple, Any] = {}
    dup_master_keys = 0
    for idx in merged.index:
        k = _key_tuple(merged.loc[idx], key_columns)
        if "" in k:  # blank key — can't match reliably
            continue
        if k in master_key_to_idx:
            dup_master_keys += 1
            continue
        master_key_to_idx[k] = idx
    if dup_master_keys:
        warnings.append(
            f"{dup_master_keys} master row(s) share a key value; only the first "
            "of each was used for matching."
        )

    changes: list[CellChange] = []
    kept: list[KeptDifference] = []
    new_rows: list[dict] = []
    updated_row_keys: set[tuple] = set()
    blank_new_keys = 0

    for nidx in new.index:
        nrow = new.loc[nidx]
        k = _key_tuple(nrow, key_columns)
        key_dict = {kc: nrow[kc] for kc in key_columns}
        has_key = "" not in k

        if has_key and k in master_key_to_idx:
            midx = master_key_to_idx[k]
            for col in new.columns:
                nval = nrow[col]
                if _is_empty(nval):
                    continue
                mval = merged.loc[midx, col]
                if _is_empty(mval):
                    merged.loc[midx, col] = nval
                    changes.append(
                        CellChange(key_dict, col, mval, nval, "filled_blank")
                    )
                    updated_row_keys.add(k)
                elif _norm(mval) == _norm(nval):
                    continue
                elif _value_len(nval) > _value_len(mval):
                    merged.loc[midx, col] = nval
                    changes.append(
                        CellChange(key_dict, col, mval, nval, "longer_wins")
                    )
                    updated_row_keys.add(k)
                else:
                    kept.append(KeptDifference(key_dict, col, mval, nval))
        else:
            # No usable key, or a key the master doesn't have -> brand-new row.
            # Rows with a blank key can't be matched to anything, so they are
            # inherently new data and are added (never dropped).
            if not has_key:
                blank_new_keys += 1
            row = {col: nrow[col] if col in new.columns else pd.NA for col in merged.columns}
            new_rows.append(row)

    if blank_new_keys:
        warnings.append(
            f"{blank_new_keys} new row(s) had a blank key value and were added as "
            "new rows (they can't be matched to existing records)."
        )

    if new_rows:
        merged = pd.concat(
            [merged, pd.DataFrame(new_rows, columns=merged.columns)],
            ignore_index=True,
        )

    cells_filled = sum(1 for c in changes if c.reason == "filled_blank")
    cells_updated = sum(1 for c in changes if c.reason == "longer_wins")

    result = MergeResult(
        key_columns=key_columns,
        master_row_count=len(master),
        new_row_count=len(new),
        merged_row_count=len(merged),
        rows_added=len(new_rows),
        rows_updated=len(updated_row_keys),
        columns_added=columns_added,
        cells_filled=cells_filled,
        cells_updated=cells_updated,
        differences_kept=len(kept),
        changes=changes,
        kept_differences=kept,
        warnings=warnings,
    )
    result.merged_csv = merged.to_csv(index=False).encode("utf-8")
    result.report_markdown = build_merge_report(result)
    return result


def build_merge_report(r: MergeResult) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out: list[str] = []
    out.append("# Spreadsheet merge report\n")
    out.append(f"_Generated {generated} by the data-prep tool._\n")
    out.append("## Summary\n")
    out.append(f"- **Matched on:** {', '.join(f'`{k}`' for k in r.key_columns)}")
    out.append(f"- **Master rows:** {r.master_row_count} → **Merged rows:** {r.merged_row_count}")
    out.append(f"- **New rows added:** {r.rows_added}")
    out.append(f"- **Existing rows updated:** {r.rows_updated}")
    out.append(f"- **Blank cells filled:** {r.cells_filled}")
    out.append(f"- **Cells replaced (new was more detailed):** {r.cells_updated}")
    out.append(
        f"- **New columns added:** {len(r.columns_added)}"
        + (f" ({', '.join(r.columns_added)})" if r.columns_added else "")
    )
    out.append(
        f"- **Differences kept as-is (new value not longer):** {r.differences_kept}\n"
    )

    if r.warnings:
        out.append("## Warnings\n")
        for w in r.warnings:
            out.append(f"- {w}")
        out.append("")

    out.append("## Changes applied\n")
    if not r.changes:
        out.append("No cells were changed.\n")
    else:
        out.append("| Row key | Column | Was | Now | Reason |")
        out.append("| --- | --- | --- | --- | --- |")
        for c in r.changes[:200]:
            keystr = ", ".join(f"{k}={v}" for k, v in c.key.items())
            was = "(blank)" if c.reason == "filled_blank" else c.old_value
            out.append(f"| {keystr} | `{c.column}` | {was} | {c.new_value} | {c.reason} |")
        if len(r.changes) > 200:
            out.append(f"| … | | | | {len(r.changes) - 200} more |")
        out.append("")

    out.append("## Differences kept (please review)\n")
    if not r.kept_differences:
        out.append("None — no genuine disagreements were left unresolved.\n")
    else:
        out.append(
            "These cells differ between the two sheets, but the new value was not "
            "longer, so the master was kept. Review in case the new value is better.\n"
        )
        out.append("| Row key | Column | Master kept | New (ignored) |")
        out.append("| --- | --- | --- | --- |")
        for d in r.kept_differences[:200]:
            keystr = ", ".join(f"{k}={v}" for k, v in d.key.items())
            out.append(f"| {keystr} | `{d.column}` | {d.master_value} | {d.new_value} |")
        if len(r.kept_differences) > 200:
            out.append(f"| … | | | {len(r.kept_differences) - 200} more |")
        out.append("")

    return "\n".join(out)
