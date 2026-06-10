"""Produces the cleaned DataFrame — always a copy; the original is never mutated.

Cleaning applies only *safe, non-destructive* transforms by default:
  * trim leading/trailing whitespace on string cells
  * collapse internal runs of whitespace
  * apply non-conflicting duplicate merges

Destructive duplicate merges are applied only when the caller passes
``approved_destructive=True`` (i.e. the user clicked "yes, delete").
"""
from __future__ import annotations

import pandas as pd

from app.dedup import apply_merges
from app.models import DuplicateGroup


def clean_dataframe(
    df: pd.DataFrame,
    duplicate_groups: list[DuplicateGroup] | None = None,
    *,
    approved_destructive: bool = False,
) -> pd.DataFrame:
    cleaned = df.copy()

    # 1. whitespace normalization on string columns
    for col in cleaned.columns:
        if cleaned[col].dtype == "string" or cleaned[col].dtype == object:
            cleaned[col] = (
                cleaned[col]
                .astype("string")
                .str.strip()
                .str.replace(r"\s+", " ", regex=True)
            )

    # 2. duplicate merges
    if duplicate_groups:
        cleaned = apply_merges(
            cleaned, duplicate_groups, approved_destructive=approved_destructive
        )

    return cleaned


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
