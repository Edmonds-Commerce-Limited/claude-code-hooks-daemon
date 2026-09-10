"""Tests for RustLspNoiseStrategy."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.constants import DaemonPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.rust_strategy import RustLspNoiseStrategy

_REQUIRED = frozenset({DaemonPath.UNTRACKED_DIR, "CLAUDE/Plan", "remote-docs", "**/venv"})


def _cargo_toml(root: Path) -> Path:
    path = root / "Cargo.toml"
    path.write_text('[package]\nname = "project"\nversion = "0.1.0"\n', encoding="utf-8")
    return path


class TestIdentity:
    def test_language_name(self) -> None:
        assert RustLspNoiseStrategy().language_name == "Rust"

    def test_process_names(self) -> None:
        assert RustLspNoiseStrategy().process_names == ("rust-analyzer",)


class TestIsRelevant:
    def test_relevant_with_cargo_toml(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        _cargo_toml(tmp_path)
        context = RelevanceContext.probe(tmp_path)
        assert RustLspNoiseStrategy().is_relevant(context) is True

    def test_not_relevant_without_marker(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        context = RelevanceContext.probe(tmp_path)
        assert RustLspNoiseStrategy().is_relevant(context) is False


class TestExcludeFinding:
    def test_no_cargo_toml_is_silent(self, tmp_path: Path) -> None:
        lines, config_path = RustLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path is None

    def test_clean_tree_with_no_rust_files_is_silent(self, tmp_path: Path) -> None:
        cargo_toml = _cargo_toml(tmp_path)
        (tmp_path / "untracked").mkdir()
        (tmp_path / "untracked" / "notes.txt").write_text("x", encoding="utf-8")
        lines, config_path = RustLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == cargo_toml

    def test_a_rust_file_in_a_required_tree_is_reported(self, tmp_path: Path) -> None:
        _cargo_toml(tmp_path)
        stray = tmp_path / "untracked" / "worktree" / "main.rs"
        stray.parent.mkdir(parents=True)
        stray.write_text("fn main() {}\n", encoding="utf-8")
        lines, _ = RustLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert RuleID.LSP_CONFIG_EXCLUDE in text
        assert "Rust" in text
        assert DaemonPath.UNTRACKED_DIR in text
        assert "[workspace]" in text


class TestAcceptanceTests:
    def test_returns_at_least_one_test_naming_the_language_and_rule(self) -> None:
        tests = RustLspNoiseStrategy().get_acceptance_tests()
        assert len(tests) >= 1
        joined = " ".join(t.title + " " + " ".join(t.expected_message_patterns) for t in tests)
        assert "Rust" in joined
        assert RuleID.LSP_CONFIG_EXCLUDE in joined
