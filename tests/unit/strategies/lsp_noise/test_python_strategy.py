"""Tests for PythonLspNoiseStrategy."""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.constants import DaemonPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.python_strategy import (
    PythonLspNoiseStrategy,
)

_REQUIRED = frozenset({DaemonPath.UNTRACKED_DIR, "CLAUDE/Plan", "remote-docs", "**/venv"})


def _write_config(root: Path, exclude: list[str] | None) -> Path:
    body: dict[str, object] = {"venvPath": ".", "venv": ".venv"}
    if exclude is not None:
        body["exclude"] = exclude
    path = root / "pyrightconfig.json"
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


class TestIdentity:
    def test_language_name(self) -> None:
        assert PythonLspNoiseStrategy().language_name == "Python"

    def test_process_names(self) -> None:
        assert PythonLspNoiseStrategy().process_names == ("pyright-langserver",)


class TestIsRelevant:
    def test_relevant_with_pyproject_marker(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        context = RelevanceContext.probe(tmp_path)
        assert PythonLspNoiseStrategy().is_relevant(context) is True

    def test_not_relevant_without_marker(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        context = RelevanceContext.probe(tmp_path)
        assert PythonLspNoiseStrategy().is_relevant(context) is False


class TestExcludeFinding:
    def test_complete_exclude_is_silent(self, tmp_path: Path) -> None:
        _write_config(tmp_path, sorted(_REQUIRED))
        lines, config_path = PythonLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == tmp_path / "pyrightconfig.json"

    def test_missing_entries_are_named(self, tmp_path: Path) -> None:
        exclude = [e for e in _REQUIRED if e != DaemonPath.UNTRACKED_DIR]
        _write_config(tmp_path, exclude)
        lines, _ = PythonLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert RuleID.LSP_CONFIG_EXCLUDE in text
        assert "Python" in text
        assert f'"{DaemonPath.UNTRACKED_DIR}"' in text

    def test_no_config_file_prints_the_minimal_file(self, tmp_path: Path) -> None:
        lines, config_path = PythonLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert "no pyright config" in text
        assert config_path is None

    def test_pyproject_tool_table_is_read_when_no_json_config(self, tmp_path: Path) -> None:
        entries = "".join(f'  "{e}",\n' for e in sorted(_REQUIRED))
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            f"[project]\nname = 'x'\n\n[tool.pyright]\nexclude = [\n{entries}]\n",
            encoding="utf-8",
        )
        lines, config_path = PythonLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == pyproject

    def test_unparseable_config_is_reported_not_raised(self, tmp_path: Path) -> None:
        (tmp_path / "pyrightconfig.json").write_text("{not json", encoding="utf-8")
        lines, _ = PythonLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert "could not be parsed" in text


class TestAcceptanceTests:
    def test_returns_at_least_one_test_naming_the_language_and_rule(self) -> None:
        tests = PythonLspNoiseStrategy().get_acceptance_tests()
        assert len(tests) >= 1
        joined = " ".join(t.title + " " + " ".join(t.expected_message_patterns) for t in tests)
        assert "Python" in joined
        assert RuleID.LSP_CONFIG_EXCLUDE in joined
