"""Tests for TypeScriptLspNoiseStrategy."""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.constants import DaemonPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.typescript_strategy import (
    TypeScriptLspNoiseStrategy,
)

_REQUIRED = frozenset({DaemonPath.UNTRACKED_DIR, "CLAUDE/Plan", "remote-docs", "**/venv"})


class TestIdentity:
    def test_language_name(self) -> None:
        assert TypeScriptLspNoiseStrategy().language_name == "TypeScript/JavaScript"

    def test_process_names(self) -> None:
        assert TypeScriptLspNoiseStrategy().process_names == ("typescript-language-server",)


class TestIsRelevant:
    def test_relevant_with_tsconfig(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        context = RelevanceContext.probe(tmp_path)
        assert TypeScriptLspNoiseStrategy().is_relevant(context) is True

    def test_relevant_with_package_json(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        context = RelevanceContext.probe(tmp_path)
        assert TypeScriptLspNoiseStrategy().is_relevant(context) is True

    def test_not_relevant_without_marker(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        context = RelevanceContext.probe(tmp_path)
        assert TypeScriptLspNoiseStrategy().is_relevant(context) is False


class TestExcludeFinding:
    def test_complete_tsconfig_exclude_is_silent(self, tmp_path: Path) -> None:
        path = tmp_path / "tsconfig.json"
        path.write_text(json.dumps({"exclude": sorted(_REQUIRED)}), encoding="utf-8")
        lines, config_path = TypeScriptLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == path

    def test_missing_entries_are_named(self, tmp_path: Path) -> None:
        exclude = [e for e in _REQUIRED if e != DaemonPath.UNTRACKED_DIR]
        (tmp_path / "tsconfig.json").write_text(json.dumps({"exclude": exclude}), encoding="utf-8")
        lines, _ = TypeScriptLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert RuleID.LSP_CONFIG_EXCLUDE in text
        assert "TypeScript" in text
        assert f'"{DaemonPath.UNTRACKED_DIR}"' in text

    def test_falls_back_to_jsconfig_when_no_tsconfig(self, tmp_path: Path) -> None:
        path = tmp_path / "jsconfig.json"
        path.write_text(json.dumps({"exclude": sorted(_REQUIRED)}), encoding="utf-8")
        lines, config_path = TypeScriptLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == path

    def test_tsconfig_takes_priority_over_jsconfig(self, tmp_path: Path) -> None:
        ts_path = tmp_path / "tsconfig.json"
        ts_path.write_text(json.dumps({"exclude": sorted(_REQUIRED)}), encoding="utf-8")
        (tmp_path / "jsconfig.json").write_text(json.dumps({"exclude": []}), encoding="utf-8")
        lines, config_path = TypeScriptLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == ts_path

    def test_no_config_file_prints_the_minimal_file(self, tmp_path: Path) -> None:
        lines, config_path = TypeScriptLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert "no tsconfig.json or jsconfig.json" in text
        assert config_path is None

    def test_jsonc_comments_are_tolerated(self, tmp_path: Path) -> None:
        body = '{\n  // a comment\n  "exclude": ' + json.dumps(sorted(_REQUIRED)) + "\n}\n"
        path = tmp_path / "tsconfig.json"
        path.write_text(body, encoding="utf-8")
        lines, _ = TypeScriptLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []

    def test_unparseable_config_is_reported_not_raised(self, tmp_path: Path) -> None:
        (tmp_path / "tsconfig.json").write_text("{not json", encoding="utf-8")
        lines, _ = TypeScriptLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert "could not be parsed" in text


class TestAcceptanceTests:
    def test_returns_at_least_one_test_naming_the_language_and_rule(self) -> None:
        tests = TypeScriptLspNoiseStrategy().get_acceptance_tests()
        assert len(tests) >= 1
        joined = " ".join(t.title + " " + " ".join(t.expected_message_patterns) for t in tests)
        assert "TypeScript" in joined
        assert RuleID.LSP_CONFIG_EXCLUDE in joined
