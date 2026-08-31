"""Tests for `hooks-daemon explain-rule` / `explain-handler` (Plan 00116 Task 6.1).

Exercised against the REAL handlers package (no fixtures/mocking) so this
is also the integration test the plan calls for: `explain-rule
R-GIT-RESET-HARD` must return `destructive_git`'s full verbose text, with
zero bespoke wiring for that handler.
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_explain_handler, cmd_explain_rule


def _rule_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {"rule_id": None, "list_rules": False}
    values.update(overrides)
    return argparse.Namespace(**values)


def _handler_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {"name": None}
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
