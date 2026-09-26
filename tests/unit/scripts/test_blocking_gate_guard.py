"""Tests for the BLOCKING release-gate skip-to-failure escalation.

Plan 00466 N39 (widened): `blocking_gate_guard.py`'s escalation used to fire
on file identity alone, with no signal distinguishing RELEASING.md's own
Step 12.0 invocation (where a skip really is an abort condition, per its own
docstring) from an ad hoc whole-suite run with no daemon running -- which
made a plain `pytest tests/` ERROR on these files instead of getting the
ordinary skip every other daemon-dependent test gets. `should_escalate_skip`
now also requires the explicit `HOOKS_DAEMON_RELEASE_GATE=1` signal that
RELEASING.md's own command block (and CI's daemon-start step) sets.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.acceptance.blocking_gate_guard import (
    _RELEASE_GATE_ENV_VAR,
    declared_blocking_gate_files,
    release_gate_invocation,
    should_escalate_skip,
)


@pytest.fixture(autouse=True)
def _clean_release_gate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with the signal absent, whatever invoked pytest."""
    monkeypatch.delenv(_RELEASE_GATE_ENV_VAR, raising=False)


class TestReleaseGateInvocation:
    def test_absent_by_default(self) -> None:
        assert release_gate_invocation() is False

    def test_true_when_set_to_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_RELEASE_GATE_ENV_VAR, "1")
        assert release_gate_invocation() is True

    def test_false_for_any_other_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only the exact declared value counts -- a stray 'true'/'yes' from
        a different convention must not silently opt a run in."""
        monkeypatch.setenv(_RELEASE_GATE_ENV_VAR, "true")
        assert release_gate_invocation() is False


class TestShouldEscalateSkip:
    def test_plain_run_does_not_escalate_a_declared_gate_file(self) -> None:
        """A plain run (no signal) must SKIP with a clear reason, not ERROR --
        even for a file RELEASING.md declares blocking."""
        declared = declared_blocking_gate_files()[0]
        assert should_escalate_skip(Path("tests/acceptance") / declared) is False

    def test_release_gate_invocation_still_escalates_a_declared_gate_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real release gate must still fail on a skip."""
        monkeypatch.setenv(_RELEASE_GATE_ENV_VAR, "1")
        declared = declared_blocking_gate_files()[0]
        assert should_escalate_skip(Path("tests/acceptance") / declared) is True

    def test_release_gate_invocation_never_escalates_an_undeclared_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The signal alone is not enough -- the file must be one of the
        declared blocking gates, or every skip anywhere would fail."""
        monkeypatch.setenv(_RELEASE_GATE_ENV_VAR, "1")
        assert should_escalate_skip(Path("tests/acceptance/test_not_a_gate.py")) is False
