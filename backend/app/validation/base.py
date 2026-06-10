"""Validator base class and registry.

A validator inspects a DataFrame and yields :class:`Issue` objects. Keep each
validator focused on one concern so issues stay actionable and the README can
group them clearly.
"""
from __future__ import annotations

import abc
from typing import Iterable, Iterator, Type

import pandas as pd

from app.models import Issue

# name -> Validator subclass
REGISTRY: dict[str, Type["Validator"]] = {}


def register(cls: Type["Validator"]) -> Type["Validator"]:
    """Class decorator that adds a validator to the global registry."""
    name = cls.name
    if not name:
        raise ValueError(f"{cls.__name__} must define a non-empty `name`")
    if name in REGISTRY:
        raise ValueError(f"Duplicate validator name: {name!r}")
    REGISTRY[name] = cls
    return cls


class Validator(abc.ABC):
    """Base class for all data-quality checks.

    Subclasses set :attr:`name` and :attr:`description` and implement
    :meth:`check`. The future LLM-based check will subclass this too — it just
    happens to call out to a model inside ``check`` instead of using pandas.
    """

    #: stable identifier, appears in Issue.check and in the README
    name: str = ""
    #: human-readable one-liner shown in the data dictionary / README
    description: str = ""

    def __init__(self, **options) -> None:
        # Per-run tuning (e.g. outlier thresholds) flows in here.
        self.options = options

    @abc.abstractmethod
    def check(self, df: pd.DataFrame) -> Iterable[Issue]:
        """Yield issues found in ``df``."""
        raise NotImplementedError


def iter_validators(**options) -> Iterator[Validator]:
    """Instantiate every registered validator (sorted for stable output)."""
    for name in sorted(REGISTRY):
        yield REGISTRY[name](**options)
