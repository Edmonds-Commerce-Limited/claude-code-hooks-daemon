"""Tests for GoLspNoiseStrategy."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.constants import DaemonPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.go_strategy import GoLspNoiseStrategy

_REQUIRED = frozenset({DaemonPath.UNTRACKED_DIR, "CLAUDE/Plan", "remote-docs", "**/venv"})


def _go_mod(root: Path) -> Path:
    path = root / "go.mod"
    path.write_text("module example.com/project\n\ngo 1.22\n", encoding="utf-8")
    return path


class TestIdentity:
    def test_language_name(self) -> None:
        assert GoLspNoiseStrategy().language_name == "Go"

    def test_process_names(self) -> None:
        assert GoLspNoiseStrategy().process_names == ("gopls",)


class TestIsRelevant:
    def test_relevant_with_go_mod(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        _go_mod(tmp_path)
        context = RelevanceContext.probe(tmp_path)
        assert GoLspNoiseStrategy().is_relevant(context) is True

    def test_not_relevant_without_marker(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        context = RelevanceContext.probe(tmp_path)
        assert GoLspNoiseStrategy().is_relevant(context) is False


class TestExcludeFinding:
    def test_no_go_mod_is_silent(self, tmp_path: Path) -> None:
        lines, config_path = GoLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path is None

    def test_clean_tree_with_no_go_files_is_silent(self, tmp_path: Path) -> None:
        go_mod = _go_mod(tmp_path)
        (tmp_path / "untracked").mkdir()
        (tmp_path / "untracked" / "notes.txt").write_text("x", encoding="utf-8")
        lines, config_path = GoLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == go_mod

    def test_a_go_file_in_a_required_tree_is_reported(self, tmp_path: Path) -> None:
        _go_mod(tmp_path)
        stray = tmp_path / "untracked" / "worktree" / "main.go"
        stray.parent.mkdir(parents=True)
        stray.write_text("package main\n", encoding="utf-8")
        lines, _ = GoLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert RuleID.LSP_CONFIG_EXCLUDE in text
        assert "Go" in text
        assert DaemonPath.UNTRACKED_DIR in text

    def test_go_files_inside_a_pruned_vendored_dir_are_not_reported(self, tmp_path: Path) -> None:
        _go_mod(tmp_path)
        nested = tmp_path / "untracked" / "venv" / "lib.go"
        nested.parent.mkdir(parents=True)
        nested.write_text("package lib\n", encoding="utf-8")
        lines, _ = GoLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        # untracked/venv is itself a required entry (**/venv) reported on its own,
        # not double-counted via the untracked walk pruning into it.
        text = "\n".join(lines)
        assert text.count(DaemonPath.UNTRACKED_DIR) <= 1


class TestAcceptanceTests:
    def test_returns_at_least_one_test_naming_the_language_and_rule(self) -> None:
        tests = GoLspNoiseStrategy().get_acceptance_tests()
        assert len(tests) >= 1
        joined = " ".join(t.title + " " + " ".join(t.expected_message_patterns) for t in tests)
        assert "Go" in joined
        assert RuleID.LSP_CONFIG_EXCLUDE in joined
