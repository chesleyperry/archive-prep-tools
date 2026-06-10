"""Pluggable data-quality validators.

Every check is a :class:`~app.validation.base.Validator` registered with the
``@register`` decorator. The runner discovers them from the registry, so adding
a new check (e.g. a future LLM-based semantic check) means writing one class —
no changes to the runner or API.
"""
from . import checks  # noqa: F401  (import for side-effect: registers validators)
from .base import REGISTRY, Validator, register
from .runner import run_validators

__all__ = ["Validator", "register", "REGISTRY", "run_validators"]
