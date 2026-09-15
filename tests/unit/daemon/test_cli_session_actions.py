"""Tests for `hooks-daemon session-actions` (Plan 00416 Task 1.2).

Exercised against the REAL handlers package and this repo's own
`.claude/hooks-daemon.yaml`, the same integration-test convention
`test_cli_status_line_explained.py` uses. None of this repo's 25 shipped
SessionStart handlers implements a verifier yet (Task 2.1/2.2 wires real
ones in) -- so the baseline expectation against the real package is an EMPTY
list, and the positive case is exercised by monkeypatching a real handler
class the same way `test_cli_status_line_explained.py` monkeypatches
`explain_segment`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_session_actions

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "project_root": str(_REPO_ROOT),
        "output_format": "text",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture(autouse=True)
def _reset_project_context() -> Any:
    ProjectContext.reset()
    yield
    ProjectContext.reset()


class TestBaselineIsEmpty:
    """Anti-inflation guarantee, exercised end-to-end: nothing in this repo's
    shipped handler set has a verifier yet, so nothing is ACTION_REQUIRED."""

    def test_exit_code_zero(self) -> None:
        assert cmd_session_actions(_args()) == 0

    def test_no_items_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_session_actions(_args())
        out = capsys.readouterr().out
        assert "no action" in out.lower() or "0 " in out.lower()

    def test_json_output_is_an_empty_list(self) -> None:
        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = cmd_session_actions(_args(output_format="json"))
        finally:
            sys.stdout = old_stdout
        assert exit_code == 0
        assert json.loads(captured.getvalue()) == []


class TestAFailingVerifierIsReported:
    def test_lists_exactly_the_failing_verifier_item(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
            ProjectHandlerLoadCheckerHandler,
        )

        monkeypatch.setattr(
            ProjectHandlerLoadCheckerHandler,
            "verify_still_needed",
            lambda self: True,
            raising=False,
        )
        exit_code = cmd_session_actions(_args())
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "project_handler_load_checker" in out

    def test_a_passing_verifier_is_not_listed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
            ProjectHandlerLoadCheckerHandler,
        )

        monkeypatch.setattr(
            ProjectHandlerLoadCheckerHandler,
            "verify_still_needed",
            lambda self: False,
            raising=False,
        )
        cmd_session_actions(_args())
        out = capsys.readouterr().out
        assert "project_handler_load_checker" not in out

    def test_json_output_carries_the_config_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import io
        import sys

        from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
            ProjectHandlerLoadCheckerHandler,
        )

        monkeypatch.setattr(
            ProjectHandlerLoadCheckerHandler,
            "verify_still_needed",
            lambda self: True,
            raising=False,
        )
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            cmd_session_actions(_args(output_format="json"))
        finally:
            sys.stdout = old_stdout
        payload = json.loads(captured.getvalue())
        config_keys = {entry["config_key"] for entry in payload}
        assert "project_handler_load_checker" in config_keys


class TestRobustness:
    def test_missing_project_root_degrades_gracefully(self) -> None:
        exit_code = cmd_session_actions(_args(project_root="/nonexistent-root-xyz"))
        assert exit_code == 0

    def test_a_raising_verifier_does_not_hide_other_handlers(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Mirrors the plan's boundary: a defect in one handler's verifier
        must not take down session start or hide other handlers' output."""
        from claude_code_hooks_daemon.handlers.session_start.docs_qa_sweep import (
            DocsQaSweepHandler,
        )
        from claude_code_hooks_daemon.handlers.session_start.project_handler_load_checker import (
            ProjectHandlerLoadCheckerHandler,
        )

        def _raise(self: Any) -> bool:
            raise RuntimeError("synthetic failure for test")

        monkeypatch.setattr(DocsQaSweepHandler, "verify_still_needed", _raise, raising=False)
        monkeypatch.setattr(
            ProjectHandlerLoadCheckerHandler,
            "verify_still_needed",
            lambda self: True,
            raising=False,
        )

        exit_code = cmd_session_actions(_args())
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "project_handler_load_checker" in out
