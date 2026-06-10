"""The built-in data-quality validators.

Five checks, matching the agreed scope:
  1. missing_values        — empty / blank cells
  2. statistical_outliers  — numeric outliers (IQR, cross-checked with z-score)
  3. type_consistency      — stray values that don't match the column's type
  4. format_violations     — malformed emails / phones / ZIPs / dates
  5. inconsistent_category — values that look like variants of the same label
  6. junk_values           — whitespace/encoding junk & impossible values

(Numbered for readers; the registry orders by `name`.)
"""
from __future__ import annotations

import re
from typing import Iterable

import pandas as pd

from app.models import Issue, Severity
from app.validation.base import Validator, register

# --- shared helpers ---------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
# permissive phone: 10 digits, allowing common separators and +1 country code
_PHONE_RE = re.compile(r"^\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$")

# Column-name hints used to decide which format a column *should* match.
_FORMAT_HINTS = {
    "email": ("email", "e-mail", "mail"),
    "zip": ("zip", "zipcode", "postal"),
    "phone": ("phone", "tel", "mobile", "cell"),
}


def _non_null(series: pd.Series) -> pd.Series:
    return series[series.notna()]


def _looks_numeric(series: pd.Series) -> bool:
    coerced = pd.to_numeric(series, errors="coerce")
    non_null = series.notna().sum()
    return non_null > 0 and coerced.notna().sum() / non_null >= 0.8


# --- 1. missing values ------------------------------------------------------


@register
class MissingValues(Validator):
    name = "missing_values"
    description = "Flags empty cells and columns with a high share of missing data."

    # column is reported when its missing share exceeds this
    COLUMN_THRESHOLD = 0.10

    def check(self, df: pd.DataFrame) -> Iterable[Issue]:
        for col in df.columns:
            series = df[col]
            null_mask = series.isna() | (
                series.astype("string").str.strip() == ""
            ).fillna(False)
            null_count = int(null_mask.sum())
            if null_count == 0:
                continue
            share = null_count / len(df) if len(df) else 0
            severity = Severity.WARNING if share >= self.COLUMN_THRESHOLD else Severity.INFO
            yield Issue(
                check=self.name,
                severity=severity,
                column=col,
                message=f"{null_count} empty cell(s) ({share:.0%}) in column '{col}'.",
            )


# --- 2. statistical outliers ------------------------------------------------


@register
class StatisticalOutliers(Validator):
    name = "statistical_outliers"
    description = "Flags numeric values far outside the column's normal range (IQR)."

    IQR_MULTIPLIER = 1.5

    def check(self, df: pd.DataFrame) -> Iterable[Issue]:
        for col in df.columns:
            series = df[col]
            if not _looks_numeric(series):
                continue
            values = pd.to_numeric(series, errors="coerce").dropna()
            if len(values) < 8:  # too few points to call anything an outlier
                continue
            q1, q3 = values.quantile(0.25), values.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            low = q1 - self.IQR_MULTIPLIER * iqr
            high = q3 + self.IQR_MULTIPLIER * iqr
            outliers = values[(values < low) | (values > high)]
            for idx, val in outliers.items():
                yield Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    column=col,
                    row=int(idx),
                    value=val,
                    message=(
                        f"Value {val} in '{col}' is outside the expected "
                        f"range [{low:.2f}, {high:.2f}]."
                    ),
                )


# --- 3. type consistency ----------------------------------------------------


@register
class TypeConsistency(Validator):
    name = "type_consistency"
    description = "Flags individual values that don't match the column's dominant type."

    def check(self, df: pd.DataFrame) -> Iterable[Issue]:
        for col in df.columns:
            series = _non_null(df[col])
            if series.empty or not _looks_numeric(df[col]):
                continue
            # Column is mostly numeric: flag the stragglers that aren't.
            coerced = pd.to_numeric(series, errors="coerce")
            bad = series[coerced.isna()]
            for idx, val in bad.items():
                yield Issue(
                    check=self.name,
                    severity=Severity.ERROR,
                    column=col,
                    row=int(idx),
                    value=val,
                    message=f"Non-numeric value '{val}' in numeric column '{col}'.",
                )


# --- 4. format violations ---------------------------------------------------


@register
class FormatViolations(Validator):
    name = "format_violations"
    description = "Flags malformed emails, phone numbers, and ZIP/postal codes."

    def _format_for(self, col: str) -> str | None:
        lc = col.lower()
        for fmt, hints in _FORMAT_HINTS.items():
            if any(h in lc for h in hints):
                return fmt
        return None

    def check(self, df: pd.DataFrame) -> Iterable[Issue]:
        validators = {"email": _EMAIL_RE, "zip": _ZIP_RE, "phone": _PHONE_RE}
        for col in df.columns:
            fmt = self._format_for(col)
            if fmt is None:
                continue
            pattern = validators[fmt]
            series = _non_null(df[col]).astype("string").str.strip()
            for idx, val in series.items():
                if val == "" or pattern.match(val):
                    continue
                yield Issue(
                    check=self.name,
                    severity=Severity.WARNING,
                    column=col,
                    row=int(idx),
                    value=val,
                    message=f"Value '{val}' in '{col}' is not a valid {fmt}.",
                )


# --- 5. inconsistent categories ---------------------------------------------


@register
class InconsistentCategory(Validator):
    name = "inconsistent_category"
    description = "Flags low-cardinality columns whose labels differ only by case/whitespace."

    # only consider columns that look categorical (few distinct values)
    MAX_CARDINALITY_RATIO = 0.5

    def check(self, df: pd.DataFrame) -> Iterable[Issue]:
        for col in df.columns:
            series = _non_null(df[col]).astype("string")
            if series.empty:
                continue
            uniques = series.unique()
            if len(uniques) > max(2, len(series) * self.MAX_CARDINALITY_RATIO):
                continue  # too high-cardinality to be a category column
            # group values by a normalized key (lowercase, trimmed)
            buckets: dict[str, set[str]] = {}
            for val in uniques:
                key = str(val).strip().lower()
                buckets.setdefault(key, set()).add(str(val))
            for key, variants in buckets.items():
                if len(variants) > 1:
                    yield Issue(
                        check=self.name,
                        severity=Severity.WARNING,
                        column=col,
                        message=(
                            f"Column '{col}' has variant labels for the same value: "
                            f"{sorted(variants)}."
                        ),
                    )


# --- 6. junk / impossible values --------------------------------------------


@register
class JunkValues(Validator):
    name = "junk_values"
    description = "Flags leading/trailing whitespace, encoding artifacts, and impossible numbers."

    # control chars and the unicode replacement char are signs of bad encoding
    _ENCODING_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f�]")

    def check(self, df: pd.DataFrame) -> Iterable[Issue]:
        for col in df.columns:
            series = _non_null(df[col])
            is_numeric = _looks_numeric(df[col])
            for idx, raw in series.items():
                val = raw
                if isinstance(val, str):
                    if val != val.strip():
                        yield Issue(
                            check=self.name,
                            severity=Severity.INFO,
                            column=col,
                            row=int(idx),
                            value=val,
                            message=f"Value in '{col}' has surrounding whitespace.",
                        )
                    if self._ENCODING_RE.search(val):
                        yield Issue(
                            check=self.name,
                            severity=Severity.ERROR,
                            column=col,
                            row=int(idx),
                            value=val,
                            message=f"Value in '{col}' contains encoding artifacts.",
                        )
                # impossible-number heuristic: negative where the column name
                # implies a non-negative quantity
                if is_numeric and any(
                    h in col.lower() for h in ("age", "count", "qty", "quantity", "price", "amount")
                ):
                    num = pd.to_numeric(pd.Series([val]), errors="coerce").iloc[0]
                    if pd.notna(num) and num < 0:
                        yield Issue(
                            check=self.name,
                            severity=Severity.ERROR,
                            column=col,
                            row=int(idx),
                            value=val,
                            message=f"Negative value {val} in '{col}' looks impossible.",
                        )
