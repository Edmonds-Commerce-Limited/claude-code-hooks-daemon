"""Tests for `hooks-daemon status-line-explained` / `explain-status-line` (Plan 00369).

Exercised against the REAL handlers package and this repo's own
`.claude/hooks-daemon.yaml` (no fixtures/mocking) -- the same integration-test
convention `test_cli_explain_rule.py` uses, and for the same reason: this
project's config is a real project root with real enabled/disabled status-line
handlers to render.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_status_line_explained

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


class TestTextOutput:
    def test_exit_code_zero(self) -> None:
        assert cmd_status_line_explained(_args()) == 0

    def test_prints_a_reference_icon_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_status_line_explained(_args())
        out = capsys.readouterr().out
        assert "reference" in out.lower()

    def test_prints_every_enabled_handlers_name_and_current_value(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_status_line_explained(_args())
        out = capsys.readouterr().out
        # current_time is always enabled by default and has no config entry
        # disabling it in this repo's config.
        assert "Current Time" in out
        assert "What it is" in out or "what it is" in out.lower()

    def test_prints_a_not_enabled_section_for_disabled_handlers(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """This repo's own config enables every status-line handler (dogfood
        exception for daemon_stats/context_sidecar), so a real run never
        exercises the disabled-section rendering -- exercised directly
        against the renderer with a synthetic disabled entry instead."""
        from claude_code_hooks_daemon.core.segment_explanation import SegmentExplanation
        from claude_code_hooks_daemon.daemon.cli import (
            _render_status_line_explained_text,
            _StatusLineSegmentEntry,
        )

        enabled_entry = _StatusLineSegmentEntry(
            config_key="current_time", class_name="CurrentTimeHandler", enabled=True, priority=10
        )
        enabled_entry.explanation = SegmentExplanation(
            glyphs=("🕐",), name="Current Time", what_it_is="x", how_to_read="x", current_value="x"
        )
        disabled_entry = _StatusLineSegmentEntry(
            config_key="daemon_stats", class_name="DaemonStatsHandler", enabled=False, priority=30
        )

        _render_status_line_explained_text([enabled_entry, disabled_entry])
        out = capsys.readouterr().out
        assert "Not enabled" in out
        assert "daemon_stats" in out


class TestJsonOutput:
    def test_json_output_parses_and_has_every_handler(self) -> None:
        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            exit_code = cmd_status_line_explained(_args(output_format="json"))
        finally:
            sys.stdout = old_stdout
        assert exit_code == 0
        payload = json.loads(captured.getvalue())
        assert isinstance(payload, list)
        assert len(payload) == 14
        names = {entry["name"] for entry in payload}
        assert "Current Time" in names

    def test_every_json_entry_has_the_expected_shape(self) -> None:
        import io
        import sys

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            cmd_status_line_explained(_args(output_format="json"))
        finally:
            sys.stdout = old_stdout
        payload = json.loads(captured.getvalue())
        expected_keys = {
            "config_key",
            "enabled",
            "priority",
            "glyphs",
            "name",
            "what_it_is",
            "how_to_read",
            "current_value",
        }
        for entry in payload:
            assert expected_keys <= set(entry.keys())


class TestRobustness:
    def test_missing_project_root_degrades_gracefully(self) -> None:
        exit_code = cmd_status_line_explained(_args(project_root="/nonexistent-root-xyz"))
        assert exit_code == 0

    def test_a_broken_explain_segment_does_not_hide_every_other_handler(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Mirrors collect_handler_rules' one-broken-handler-must-not-hide-the-rest
        contract."""
        from claude_code_hooks_daemon.handlers.status_line.current_time import (
            CurrentTimeHandler,
        )

        def _raise(self: CurrentTimeHandler) -> None:
            raise RuntimeError("synthetic failure for test")

        monkeypatch.setattr(CurrentTimeHandler, "explain_segment", _raise)
        exit_code = cmd_status_line_explained(_args())
        assert exit_code == 0
        out = capsys.readouterr().out
        # Some OTHER handler's name still made it through.
        assert "Git Branch" in out or "Environment Indicator" in out
