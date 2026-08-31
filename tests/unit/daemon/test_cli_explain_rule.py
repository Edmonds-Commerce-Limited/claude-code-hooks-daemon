"""Tests for `hooks-daemon explain-rule` / `explain-handler` (Plan 00116 Task 6.1).

Exercised against the REAL handlers package (no fixtures/mocking) so this
is also the integration test the plan calls for: `explain-rule
R-GIT-RESET-HARD` must return `destructive_git`'s full verbose text, with
zero bespoke wiring for that handler.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_explain_handler, cmd_explain_rule

# This test file lives at tests/unit/daemon/, three levels below the repo
# root — used as a real project root (it carries a real .claude/hooks-daemon.yaml)
# so ProjectContext-dependent handlers can be exercised for real rather than
# skipped, without inventing a synthetic fixture project.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _rule_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {"rule_id": None, "list_rules": False, "project_root": None}
    values.update(overrides)
    return argparse.Namespace(**values)


def _handler_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {"name": None, "project_root": None}
    values.update(overrides)
    return argparse.Namespace(**values)


class TestCmdExplainRule:
    def test_known_id_prints_full_verbose_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = cmd_explain_rule(_rule_args(rule_id="R-GIT-RESET-HARD"))
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "R-GIT-RESET-HARD" in out
        assert "destructive_git" in out
        assert "git reset --hard" in out.lower() or "git reset --hard" in out

    def test_case_insensitive_and_prefix_tolerant(self) -> None:
        assert cmd_explain_rule(_rule_args(rule_id="git-reset-hard")) == 0

    def test_unknown_id_lists_near_matches_and_exits_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cmd_explain_rule(_rule_args(rule_id="R-GIT-RESET-HRAD"))
        assert exit_code == 1
        err = capsys.readouterr().err
        assert "R-GIT-RESET-HARD" in err
        assert "--list" in err

    def test_completely_unknown_id_still_hints_list(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cmd_explain_rule(_rule_args(rule_id="R-TOTALLY-MADE-UP-ZZZZ"))
        assert exit_code == 1
        err = capsys.readouterr().err
        assert "--list" in err

    def test_list_prints_every_rule_id(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = cmd_explain_rule(_rule_args(list_rules=True))
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "R-GIT-RESET-HARD" in out
        assert "destructive_git" in out

    def test_missing_rule_id_and_no_list_is_a_usage_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cmd_explain_rule(_rule_args())
        assert exit_code == 1
        assert capsys.readouterr().err != ""


class TestCmdExplainHandler:
    def test_known_handler_prints_rule_ids_terse_and_claude_md(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cmd_explain_handler(_handler_args(name="destructive_git"))
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "R-GIT-RESET-HARD" in out
        assert "destructive_git" in out

    def test_case_insensitive_class_name_match(self) -> None:
        assert cmd_explain_handler(_handler_args(name="DestructiveGitHandler")) == 0

    def test_unknown_handler_lists_near_matches_and_exits_1(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cmd_explain_handler(_handler_args(name="destructive_gitt"))
        assert exit_code == 1
        err = capsys.readouterr().err
        assert "destructive_git" in err


class TestProjectContextInitialisation:
    """explain-rule/explain-handler must not require a running daemon, but
    they SHOULD initialise ProjectContext when a real project root is
    available so handlers whose constructors read it are not silently
    skipped (the gap DocsGenerator avoids via get_project_path())."""

    def teardown_method(self) -> None:
        ProjectContext.reset()

    def test_explicit_project_root_initialises_project_context(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        ProjectContext.reset()
        with caplog.at_level(logging.ERROR):
            exit_code = cmd_explain_rule(_rule_args(list_rules=True, project_root=str(_REPO_ROOT)))
        assert exit_code == 0
        assert "ProjectContext not initialized" not in caplog.text
        assert ProjectContext.is_initialized()

    def test_missing_project_root_degrades_gracefully(self) -> None:
        """No project root resolvable (e.g. run outside any project) must
        still answer known lookups rather than crash."""
        ProjectContext.reset()
        exit_code = cmd_explain_rule(
            _rule_args(rule_id="R-GIT-RESET-HARD", project_root="/nonexistent-root-xyz")
        )
        assert exit_code == 0

    def test_initialize_failure_warns_on_stderr_but_still_degrades_gracefully(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A config file that resolves but fails to initialise (e.g. a bad
        project layout) must not be silently swallowed at debug level only —
        the CLI user gets a stderr warning, and the command still degrades
        gracefully rather than crashing."""
        ProjectContext.reset()

        def _raise(config_path: Path | str) -> None:
            raise ValueError("synthetic failure for test")

        monkeypatch.setattr(ProjectContext, "initialize", _raise)
        exit_code = cmd_explain_rule(_rule_args(list_rules=True, project_root=str(_REPO_ROOT)))
        assert exit_code == 0
        err = capsys.readouterr().err
        assert "could not initialise project context" in err.lower()
        assert "synthetic failure for test" in err
        assert not ProjectContext.is_initialized()
