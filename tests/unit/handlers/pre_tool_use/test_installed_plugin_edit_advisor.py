"""Tests for InstalledPluginEditAdvisorHandler (Plan 00468 G16).

Claude Code keeps an installed plugin's files under
``<config dir>/plugins/cache/`` and each marketplace's clone under
``<config dir>/plugins/marketplaces/``. An edit there is silently replaced on
the next plugin update, and it changes a third-party prompt or script the user
trusted as published. The daemon says so, and never blocks: sometimes the
edit is a deliberate, local experiment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.installed_plugin_edit_advisor import (
    InstalledPluginEditAdvisorHandler,
)


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".claude"


@pytest.fixture()
def handler(config_dir: Path) -> InstalledPluginEditAdvisorHandler:
    handler = InstalledPluginEditAdvisorHandler()
    handler._config_dir = config_dir
    return handler


def _write(path: Path, tool: str = "Write") -> dict[str, Any]:
    return {"tool_name": tool, "tool_input": {"file_path": str(path), "content": "x"}}


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestIdentity:
    def test_it_is_advisory_and_never_terminal(
        self, handler: InstalledPluginEditAdvisorHandler
    ) -> None:
        assert handler.terminal is False
        assert HandlerTag.ADVISORY in handler.tags


class TestWhatItNotices:
    def test_an_edit_in_the_plugin_cache_is_noticed(
        self, handler: InstalledPluginEditAdvisorHandler, config_dir: Path
    ) -> None:
        target = config_dir / "plugins" / "cache" / "mkt" / "p" / "1.0.0" / "agents" / "x.md"
        assert handler.matches(_write(target, tool="Edit")) is True

    def test_a_write_in_a_marketplace_clone_is_noticed(
        self, handler: InstalledPluginEditAdvisorHandler, config_dir: Path
    ) -> None:
        target = config_dir / "plugins" / "marketplaces" / "mkt" / "plugins" / "p" / "SKILL.md"
        assert handler.matches(_write(target)) is True

    def test_a_bash_write_into_the_cache_is_noticed(
        self, handler: InstalledPluginEditAdvisorHandler, config_dir: Path
    ) -> None:
        target = config_dir / "plugins" / "cache" / "mkt" / "p" / "1.0.0" / "hooks" / "run.sh"
        assert handler.matches(_bash(f"echo hi > {target}")) is True

    def test_the_session_home_from_the_transcript_counts_too(
        self, handler: InstalledPluginEditAdvisorHandler, tmp_path: Path
    ) -> None:
        session_home = tmp_path / "other" / ".claude"
        hook_input = _write(session_home / "plugins" / "cache" / "mkt" / "p" / "a.md")
        hook_input["transcript_path"] = str(session_home / "projects" / "-repo" / "s.jsonl")
        assert handler.matches(hook_input) is True

    def test_a_symlinked_home_is_matched_by_its_real_path(
        self, tmp_path: Path, config_dir: Path
    ) -> None:
        real = tmp_path / "project" / ".claude" / "ccy"
        (real / "plugins" / "cache").mkdir(parents=True)
        config_dir.parent.mkdir(parents=True)
        config_dir.symlink_to(real)
        handler = InstalledPluginEditAdvisorHandler()
        handler._config_dir = config_dir
        assert handler.matches(_write(real / "plugins" / "cache" / "m" / "p" / "a.md")) is True


class TestWhatItLeavesAlone:
    def test_the_plugin_data_dir_is_the_plugins_own_store(
        self, handler: InstalledPluginEditAdvisorHandler, config_dir: Path
    ) -> None:
        target = config_dir / "plugins" / "data" / "p" / "state.json"
        assert handler.matches(_write(target)) is False

    def test_a_project_file_is_not_a_plugin_file(
        self, handler: InstalledPluginEditAdvisorHandler, tmp_path: Path
    ) -> None:
        assert handler.matches(_write(tmp_path / "project" / "src" / "a.py")) is False

    def test_a_read_is_never_noticed(
        self, handler: InstalledPluginEditAdvisorHandler, config_dir: Path
    ) -> None:
        target = config_dir / "plugins" / "cache" / "mkt" / "p" / "1.0.0" / "agents" / "x.md"
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": str(target)}}
        assert handler.matches(hook_input) is False


class TestTheAdvice:
    def test_it_allows_and_names_the_file_and_the_way_out(
        self, handler: InstalledPluginEditAdvisorHandler, config_dir: Path
    ) -> None:
        target = config_dir / "plugins" / "cache" / "mkt" / "p" / "1.0.0" / "agents" / "x.md"
        result = handler.handle(_write(target, tool="Edit"))
        assert result.decision is Decision.ALLOW
        text = "\n".join(result.context)
        assert str(target) in text
        assert "update" in text
        assert "fork" in text.lower()
        assert "upstream" in text.lower()
