"""Smoke + unit tests for the analysis pipeline.

Run from backend/ with:  python -m pytest   (or python tests/test_pipeline.py)
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.dedup import apply_merges, find_duplicates  # noqa: E402
from app.pipeline import analyze  # noqa: E402
from app.profiling import profile_dataframe  # noqa: E402
from app.validation import run_validators  # noqa: E402


def _sample() -> pd.DataFrame:
    path = os.path.join(os.path.dirname(__file__), "..", "..", "sample_data", "messy.csv")
    return pd.read_csv(path, dtype="string", na_values=[""])


def test_profiling_infers_types():
    df = _sample()
    profiles = {p.name: p for p in profile_dataframe(df)}
    assert profiles["age"].inferred_type in {"integer", "float"}
    assert profiles["email"].inferred_type == "text"
    assert profiles["state"].inferred_type == "categorical"


def test_validators_find_known_issues():
    df = _sample()
    issues = run_validators(df)
    checks = {i.check for i in issues}
    # bad email (carol[at]…), bad amount ('abc'), negative age, outlier amount,
    # CA/California/calif variants, empty cells — all present in the fixture.
    assert "format_violations" in checks
    assert "type_consistency" in checks
    assert "statistical_outliers" in checks
    assert "inconsistent_category" in checks
    assert "missing_values" in checks


def test_duplicates_keep_most_complete():
    # Two pairs keyed on email:
    #   safe@   — identical except one row has a blank cell the other fills in,
    #             so merging only *adds* info → non-destructive.
    #   clash@  — the two rows disagree on a non-empty value → destructive.
    df = pd.DataFrame(
        {
            "email": ["safe@x.com", "safe@x.com", "clash@x.com", "clash@x.com"],
            "name": ["Sam", "Sam", "Dana", "Dana"],
            "phone": [pd.NA, "555-1212", "555-0001", "555-9999"],
        },
        dtype="string",
    )
    groups = {g.key["email"]: g for g in find_duplicates(df, key_columns=["email"])}
    assert groups["safe@x.com"].discards_data is False
    # winner is the more complete row (the one with the phone filled in)
    assert df.loc[groups["safe@x.com"].winner_index, "phone"] == "555-1212"
    assert groups["clash@x.com"].discards_data is True


def test_apply_merges_respects_approval():
    df = pd.DataFrame(
        {
            "email": ["safe@x.com", "safe@x.com", "clash@x.com", "clash@x.com"],
            "name": ["Sam", "Sam", "Dana", "Dana"],
            "phone": [pd.NA, "555-1212", "555-0001", "555-9999"],
        },
        dtype="string",
    )
    groups = find_duplicates(df, key_columns=["email"])
    safe = apply_merges(df, groups, approved_destructive=False)
    aggressive = apply_merges(df, groups, approved_destructive=True)
    # Without approval, only the non-destructive group collapses (4 -> 3).
    # With approval, the destructive group collapses too (-> 2).
    assert len(safe) == 3
    assert len(aggressive) == 2


def test_full_pipeline_produces_artifacts():
    df = _sample()
    result = analyze(df, source_name="messy.csv", key_columns=["email"])
    assert "# Data documentation" in result.readme_markdown
    assert result.cleaned_csv.startswith(b"id,name,email")
    assert result.row_count == len(df)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All tests passed.")
