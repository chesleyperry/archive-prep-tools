"""Shared dataclasses and enums used across the pipeline.

These are plain dataclasses (not pydantic) so the pipeline stays framework-free
and unit-testable without FastAPI. The API layer converts them to pydantic
response models in ``schemas.py``.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Issue:
    """A single data-quality finding produced by a validator.

    A column-level issue (e.g. "30% of this column is empty") leaves ``row``
    as ``None``. A cell-level issue (e.g. "this value is an outlier") sets both
    ``column`` and ``row``.
    """

    check: str               # validator name, e.g. "missing_values"
    severity: Severity
    message: str
    column: str | None = None
    row: int | None = None   # 0-based DataFrame index
    value: Any = None        # the offending value, if cell-level

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["severity"] = self.severity.value
        # numpy / pandas scalars are not JSON-serializable as-is
        d["value"] = _jsonable(self.value)
        return d


@dataclass
class ColumnProfile:
    name: str
    inferred_type: str          # "integer" | "float" | "boolean" | "datetime" | "categorical" | "text"
    non_null_count: int
    null_count: int
    fill_rate: float            # 0.0–1.0
    unique_count: int
    sample_values: list[Any]
    # numeric-only stats (None for non-numeric columns)
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["sample_values"] = [_jsonable(v) for v in self.sample_values]
        return d


@dataclass
class DuplicateGroup:
    """A set of rows considered duplicates of each other."""

    key: dict[str, Any]              # the key column values that matched
    row_indices: list[int]           # all rows in the group
    winner_index: int                # the "most complete" row we keep
    discards_data: bool              # True if merging would drop a non-null value
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    # each conflict: {"column", "winner_value", "losing_value", "losing_row"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": {k: _jsonable(v) for k, v in self.key.items()},
            "row_indices": self.row_indices,
            "winner_index": self.winner_index,
            "discards_data": self.discards_data,
            "conflicts": [
                {kk: _jsonable(vv) for kk, vv in c.items()} for c in self.conflicts
            ],
        }


def _jsonable(value: Any) -> Any:
    """Coerce numpy/pandas scalars and NaN into plain JSON-safe Python values."""
    import math

    # pandas/numpy expose .item() for scalar conversion
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and math.isnan(value):
        return None
    return value
