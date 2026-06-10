"""Runs every registered validator over a DataFrame and collects issues."""
from __future__ import annotations

import pandas as pd

from app.models import Issue
from app.validation.base import iter_validators


def run_validators(df: pd.DataFrame, **options) -> list[Issue]:
    """Execute all registered validators and return a flat list of issues.

    A misbehaving validator is isolated: its failure is recorded as an Issue
    rather than aborting the whole run.
    """
    issues: list[Issue] = []
    for validator in iter_validators(**options):
        try:
            issues.extend(validator.check(df))
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the run
            from app.models import Severity

            issues.append(
                Issue(
                    check=validator.name,
                    severity=Severity.ERROR,
                    message=f"Validator '{validator.name}' failed: {exc}",
                )
            )
    return issues
