"""The supervise tests never see the ambient ccy environment (00466 N63).

A ccy session exports its own supervisor tuning. A test that reads it passes
in CI and fails in-session, so the autouse fixture clears the whole namespace.
These tests pin both halves: the fixture really clears it, and every
environment variable the supervisor defines lives inside that namespace.
"""

from __future__ import annotations

import os

import pytest

from tests.unit.supervise._load import load_supervisor_module
from tests.unit.supervise.conftest import AMBIENT_ENV_PREFIXES

_mod = load_supervisor_module()


def _supervisor_env_var_names() -> dict[str, str]:
    return {
        attr: value
        for attr, value in vars(_mod).items()
        if attr.startswith("_") and "_ENV" in attr and isinstance(value, str) and value.isupper()
    }


def test_supervisor_defines_env_vars() -> None:
    assert "CCY_MIN_EFFORT_LEVELS" in _supervisor_env_var_names().values()


def test_every_supervisor_env_var_is_in_the_cleared_namespace() -> None:
    outside = {
        attr: value
        for attr, value in _supervisor_env_var_names().items()
        if not value.startswith(AMBIENT_ENV_PREFIXES)
    }
    assert outside == {}


def test_no_ambient_supervisor_variable_is_visible() -> None:
    leaked = [name for name in os.environ if name.startswith(AMBIENT_ENV_PREFIXES)]
    assert leaked == []


def test_a_session_minimum_would_change_the_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCY_MIN_EFFORT_LEVELS", "fable=low,opus=medium")
    session_value = _mod._min_effort_levels_from_env()
    monkeypatch.delenv("CCY_MIN_EFFORT_LEVELS")
    assert _mod._min_effort_levels_from_env() != session_value
