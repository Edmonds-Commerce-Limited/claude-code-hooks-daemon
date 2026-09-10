"""Tests for PhpLspNoiseStrategy.

Ground truth (Plan 00368, owner correction): Claude Code's official `php-lsp`
marketplace plugin launches `intelephense --stdio` with NO `settings` or
`initializationOptions` at all (verified against
`anthropics/claude-plugins-official`'s `.claude-plugin/marketplace.json`),
and intelephense itself reads no project-root config file for
`files.exclude` - it is a pure client-delivered LSP setting
(`intelephense-docs/gettingStarted.md`: `"scope": "resource"`, no file
alternative). The only real per-project knob is a project-scoped LSP plugin
that re-registers `.php` with its own `settings` block - "first server
registered" wins the extension (`plugins-reference.md`), so a project
plugin under `.claude/plugins/` genuinely overrides the marketplace one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import DaemonPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.php_strategy import PhpLspNoiseStrategy

_REQUIRED = frozenset({DaemonPath.UNTRACKED_DIR, "CLAUDE/Plan", "remote-docs"})


def _write_lsp_json(root: Path, plugin_name: str, exclude: list[str] | None) -> Path:
    plugin_dir = root / ".claude" / "plugins" / plugin_name
    plugin_dir.mkdir(parents=True)
    server: dict[str, Any] = {
        "command": "intelephense",
        "args": ["--stdio"],
        "extensionToLanguage": {".php": "php"},
    }
    if exclude is not None:
        server["settings"] = {"intelephense.files.exclude": exclude}
    body = {"intelephense": server}
    path = plugin_dir / ".lsp.json"
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


class TestIdentity:
    def test_language_name(self) -> None:
        assert PhpLspNoiseStrategy().language_name == "PHP"

    def test_process_names(self) -> None:
        assert PhpLspNoiseStrategy().process_names == ("intelephense",)


class TestIsRelevant:
    def test_relevant_with_composer_json(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
        context = RelevanceContext.probe(tmp_path)
        assert PhpLspNoiseStrategy().is_relevant(context) is True

    def test_not_relevant_without_marker(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core.relevance import RelevanceContext

        context = RelevanceContext.probe(tmp_path)
        assert PhpLspNoiseStrategy().is_relevant(context) is False


class TestExcludeFinding:
    def test_no_project_plugins_dir_is_reported(self, tmp_path: Path) -> None:
        lines, config_path = PhpLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert RuleID.LSP_CONFIG_EXCLUDE in text
        assert "PHP" in text
        assert "intelephense" in text
        assert "no per-project file" in text
        assert config_path is None

    def test_no_php_registering_plugin_is_reported(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "plugins").mkdir(parents=True)
        lines, config_path = PhpLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines != []
        assert config_path is None

    def test_complete_override_is_silent(self, tmp_path: Path) -> None:
        path = _write_lsp_json(tmp_path, "lsp-noise-php-exclude", sorted(_REQUIRED))
        lines, config_path = PhpLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == path

    def test_incomplete_override_names_the_missing_entries(self, tmp_path: Path) -> None:
        exclude = [e for e in _REQUIRED if e != DaemonPath.UNTRACKED_DIR]
        path = _write_lsp_json(tmp_path, "lsp-noise-php-exclude", exclude)
        lines, config_path = PhpLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert RuleID.LSP_CONFIG_EXCLUDE in text
        assert DaemonPath.UNTRACKED_DIR in text
        assert config_path == path

    def test_inline_plugin_json_lsp_servers_is_read(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / ".claude" / "plugins" / "my-php-override"
        plugin_dir.mkdir(parents=True)
        body = {
            "name": "my-php-override",
            "lspServers": {
                "intelephense": {
                    "command": "intelephense",
                    "extensionToLanguage": {".php": "php"},
                    "settings": {"intelephense.files.exclude": sorted(_REQUIRED)},
                }
            },
        }
        path = plugin_dir / "plugin.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        lines, config_path = PhpLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines == []
        assert config_path == path

    def test_a_server_not_registering_php_is_ignored(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / ".claude" / "plugins" / "unrelated"
        plugin_dir.mkdir(parents=True)
        body = {"go": {"command": "gopls", "extensionToLanguage": {".go": "go"}}}
        (plugin_dir / ".lsp.json").write_text(json.dumps(body), encoding="utf-8")
        lines, config_path = PhpLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines != []
        assert config_path is None

    def test_malformed_plugin_file_is_skipped_not_raised(self, tmp_path: Path) -> None:
        plugin_dir = tmp_path / ".claude" / "plugins" / "broken"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / ".lsp.json").write_text("{not json", encoding="utf-8")
        lines, config_path = PhpLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        assert lines != []
        assert config_path is None

    def test_finding_prints_a_paste_ready_lsp_json_snippet(self, tmp_path: Path) -> None:
        lines, _ = PhpLspNoiseStrategy().exclude_finding(tmp_path, _REQUIRED)
        text = "\n".join(lines)
        assert "intelephense" in text
        assert '"command"' in text
        assert '"extensionToLanguage"' in text
        for entry in _REQUIRED:
            assert f'"{entry}"' in text


class TestAcceptanceTests:
    def test_returns_at_least_one_test_naming_the_language_and_rule(self) -> None:
        tests = PhpLspNoiseStrategy().get_acceptance_tests()
        assert len(tests) >= 1
        joined = " ".join(t.title + " " + " ".join(t.expected_message_patterns) for t in tests)
        assert "PHP" in joined
        assert RuleID.LSP_CONFIG_EXCLUDE in joined
