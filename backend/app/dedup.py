"""Duplicate detection and merge planning.

Policy (agreed with the user):
  * "Most complete wins" — among rows in a duplicate group, keep the one with
    the fewest empty cells.
  * Merging is destructive only when a losing row holds a non-null value that
    differs from the winner. Those cases are surfaced as ``conflicts`` and
    flagged with ``discards_data=True`` so the UI can ask before deleting.
"""
from __future__ import annotations

import pandas as pd

from app.models import DuplicateGroup


def _completeness(row: pd.Series) -> int:
    """Number of non-empty cells in a row (higher == more complete)."""
    filled = row.notna()
    # treat blank/whitespace strings as empty too
    for col, val in row.items():
        if isinstance(val, str) and val.strip() == "":
            filled[col] = False
    return int(filled.sum())


def find_duplicates(
    df: pd.DataFrame, key_columns: list[str] | None = None
) -> list[DuplicateGroup]:
    """Group duplicate rows and build a merge plan for each group.

    ``key_columns`` defaults to every column (i.e. fully identical rows). Pass a
    subset (e.g. ``["email"]``) to dedupe on a business key.
    """
    if df.empty:
        return []
    keys = key_columns or list(df.columns)
    missing = [k for k in keys if k not in df.columns]
    if missing:
        raise ValueError(f"Unknown key column(s): {missing}")

    groups: list[DuplicateGroup] = []
    # normalize the key for grouping (trim strings) without mutating df
    grouped = df.groupby([df[k].map(_norm) for k in keys], dropna=False, sort=False)

    for key_vals, sub in grouped:
        if len(sub) < 2:
            continue
        winner_idx = max(sub.index, key=lambda i: _completeness(df.loc[i]))
        winner = df.loc[winner_idx]

        conflicts: list[dict] = []
        for idx in sub.index:
            if idx == winner_idx:
                continue
            losing = df.loc[idx]
            for col in df.columns:
                w_val, l_val = winner[col], losing[col]
                if _is_empty(l_val):
                    continue
                if _is_empty(w_val) or _norm(w_val) != _norm(l_val):
                    conflicts.append(
                        {
                            "column": col,
                            "winner_value": w_val,
                            "losing_value": l_val,
                            "losing_row": int(idx),
                        }
                    )

        key_dict = {k: df.loc[winner_idx, k] for k in keys}
        groups.append(
            DuplicateGroup(
                key=key_dict,
                row_indices=[int(i) for i in sub.index],
                winner_index=int(winner_idx),
                discards_data=bool(conflicts),
                conflicts=conflicts,
            )
        )
    return groups


def apply_merges(
    df: pd.DataFrame,
    groups: list[DuplicateGroup],
    approved_destructive: bool = False,
) -> pd.DataFrame:
    """Return a new DataFrame with duplicate groups collapsed to their winner.

    Non-destructive merges (no conflicting data) are always applied. Destructive
    ones are only applied when ``approved_destructive`` is True; otherwise those
    groups are left untouched so no data is silently dropped.
    """
    drop_indices: set[int] = set()
    for group in groups:
        if group.discards_data and not approved_destructive:
            continue
        for idx in group.row_indices:
            if idx != group.winner_index:
                drop_indices.add(idx)
    if not drop_indices:
        return df.copy()
    return df.drop(index=list(drop_indices)).reset_index(drop=True)


def _norm(val) -> str:
    if _is_empty(val):
        return ""
    return str(val).strip().lower()


def _is_empty(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return bool(pd.isna(val)) if not isinstance(val, str) else False
