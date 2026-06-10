"""Loading data from CSV uploads or Google Sheets into a DataFrame."""
from __future__ import annotations

import io

import pandas as pd

MAX_ROWS = 40_000  # agreed ceiling; guards against accidental huge uploads


def load_csv(raw: bytes, *, max_rows: int = MAX_ROWS) -> pd.DataFrame:
    """Parse CSV bytes into a DataFrame, keeping values as strings.

    We read everything as ``string`` first so the profiler and validators can
    decide types — pandas' eager type inference would otherwise hide the very
    type-inconsistencies we want to catch.
    """
    buffer = io.BytesIO(raw)
    df = pd.read_csv(buffer, dtype="string", keep_default_na=True, na_values=[""])
    _enforce_limit(df, max_rows)
    return df


def load_from_records(records: list[dict], *, max_rows: int = MAX_ROWS) -> pd.DataFrame:
    df = pd.DataFrame.from_records(records).astype("string")
    _enforce_limit(df, max_rows)
    return df


def _enforce_limit(df: pd.DataFrame, max_rows: int) -> None:
    if len(df) > max_rows:
        raise ValueError(
            f"File has {len(df)} rows, exceeding the {max_rows}-row limit."
        )
