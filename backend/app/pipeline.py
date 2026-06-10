"""Orchestrates the full analysis pipeline over a loaded DataFrame.

This is the single entry point the API calls. It is deliberately framework-free
so it can be unit-tested directly (see backend/tests).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.cleaning import clean_dataframe, to_csv_bytes
from app.dedup import find_duplicates
from app.models import ColumnProfile, DuplicateGroup, Issue
from app.profiling import profile_dataframe
from app.report import build_readme
from app.validation import run_validators


@dataclass
class AnalysisResult:
    source_name: str
    row_count: int
    column_count: int
    profiles: list[ColumnProfile]
    issues: list[Issue]
    duplicate_groups: list[DuplicateGroup]
    readme_markdown: str
    cleaned_csv: bytes

    def to_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "profiles": [p.to_dict() for p in self.profiles],
            "issues": [i.to_dict() for i in self.issues],
            "duplicate_groups": [g.to_dict() for g in self.duplicate_groups],
            "readme_markdown": self.readme_markdown,
        }


def analyze(
    df: pd.DataFrame,
    *,
    source_name: str,
    key_columns: list[str] | None = None,
    approved_destructive: bool = False,
) -> AnalysisResult:
    profiles = profile_dataframe(df)
    issues = run_validators(df)
    duplicate_groups = find_duplicates(df, key_columns=key_columns)

    readme = build_readme(
        source_name=source_name,
        row_count=len(df),
        profiles=profiles,
        issues=issues,
        duplicate_groups=duplicate_groups,
    )
    cleaned = clean_dataframe(
        df, duplicate_groups, approved_destructive=approved_destructive
    )

    return AnalysisResult(
        source_name=source_name,
        row_count=len(df),
        column_count=len(df.columns),
        profiles=profiles,
        issues=issues,
        duplicate_groups=duplicate_groups,
        readme_markdown=readme,
        cleaned_csv=to_csv_bytes(cleaned),
    )
