"""Per-column profiling: type inference, fill rate, cardinality, samples."""
from __future__ import annotations

import pandas as pd

from app.models import ColumnProfile


def _infer_type(series: pd.Series) -> str:
    non_null = series.dropna()
    if non_null.empty:
        return "text"

    # boolean-like
    lowered = non_null.astype("string").str.strip().str.lower()
    if set(lowered.unique()).issubset({"true", "false", "0", "1", "yes", "no"}):
        return "boolean"

    coerced_num = pd.to_numeric(non_null, errors="coerce")
    if coerced_num.notna().mean() >= 0.8:
        # integer vs float
        if (coerced_num.dropna() % 1 == 0).all():
            return "integer"
        return "float"

    coerced_dt = pd.to_datetime(non_null, errors="coerce", format="mixed")
    if coerced_dt.notna().mean() >= 0.8:
        return "datetime"

    # categorical if cardinality is low relative to row count
    if non_null.nunique() <= max(2, len(non_null) * 0.5):
        return "categorical"
    return "text"


def profile_column(series: pd.Series) -> ColumnProfile:
    non_null = series.dropna()
    inferred = _infer_type(series)

    minimum = maximum = mean = None
    if inferred in {"integer", "float"}:
        nums = pd.to_numeric(non_null, errors="coerce").dropna()
        if not nums.empty:
            minimum = float(nums.min())
            maximum = float(nums.max())
            mean = float(nums.mean())

    samples = non_null.unique()[:5].tolist()

    return ColumnProfile(
        name=str(series.name),
        inferred_type=inferred,
        non_null_count=int(non_null.shape[0]),
        null_count=int(series.isna().sum()),
        fill_rate=round(non_null.shape[0] / len(series), 4) if len(series) else 0.0,
        unique_count=int(non_null.nunique()),
        sample_values=samples,
        minimum=minimum,
        maximum=maximum,
        mean=mean,
    )


def profile_dataframe(df: pd.DataFrame) -> list[ColumnProfile]:
    return [profile_column(df[col]) for col in df.columns]
