"""``health`` lists the enabled Claude Code plugins that ship hooks (Plan 00468 Task 4.1).

The session-start advisory leaves out a plugin the user has acknowledged;
``health`` lists every one, marks the acknowledged ones, and never changes
its exit code for them.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.cli import cmd_health
from claude_code_hooks_daemon.daemon.project_handler_health import ProjectHandlerHealthState
from claude_code_hooks_daemon.utils.claude_plugins import (
    EnabledPlugin,
    PluginHookSource,
    PluginInventory,
    SettingsScope,
)

_ACKNOWLEDGING_CONFIG = (
    "version: '1.0'\n"
    "handlers:\n"
    "  session_start:\n"
    "    plugin_hooks_advisor:\n"
    "      options:\n"
    "        acknowledged_plugins: [tidy@mkt]\n"
)

_HEALTHY_RESPONSE: dict[str, Any] = {
    "result": {
        "status": "healthy",
        "stats": {},
        "handlers": {"session_start": 1},
    }
}


def _plugin(plugin_id: str, *events: str) -> EnabledPlugin:
    name, _, marketplace = plugin_id.partition("@")
    return EnabledPlugin(
        plugin_id=plugin_id,
        name=name,
        marketplace=marketplace,
        enabled_by=SettingsScope.USER,
        install_scope="user",
        install_path=Path("/nonexistent") / name,
        version="1.0.0",
        hooks=(PluginHookSource(path=None, events={event: [] for event in events}),),
    )


def _health(tmp_path: Path, config: str, *plugins: EnabledPlugin) -> int:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(config, encoding="utf-8")
    inventory = PluginInventory(config_dir=Path("/nonexistent"), enabled=plugins)
    with (
        patch.object(cli, "read_pid_file", return_value=12345),
        patch.object(cli, "get_project_path", return_value=tmp_path),
        patch.object(cli, "send_daemon_request", return_value=_HEALTHY_RESPONSE),
        patch.object(cli, "check_hook_registration_warnings", return_value=[]),
        patch.object(
            cli,
            "_read_project_handler_health",
            return_value=ProjectHandlerHealthState(failures=[], loaded_count=0),
        ),
        patch.object(cli, "resolve_enabled_plugins", return_value=inventory),
    ):
        return cmd_health(argparse.Namespace(project_root=tmp_path))


class TestHealthPluginHooks:
    def test_lists_each_plugin_with_hooks_and_marks_the_acknowledged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _health(
            tmp_path,
            _ACKNOWLEDGING_CONFIG,
            _plugin("tidy@mkt", "Stop"),
            _plugin("guard@mkt", "PreToolUse"),
        )
        out = capsys.readouterr().out
        section = out.split("Claude Code plugin hooks:", 1)[1]
        tidy = next(line for line in section.splitlines() if "tidy@mkt" in line)
        guard = next(line for line in section.splitlines() if "guard@mkt" in line)
        assert "acknowledged" in tidy
        assert "acknowledged" not in guard
        assert "updatedInput" in guard
        assert code == 0

    def test_an_unreadable_config_still_lists_the_plugins(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _health(tmp_path, "handlers: [not, a, mapping]\n", _plugin("tidy@mkt", "Stop"))
        section = capsys.readouterr().out.split("Claude Code plugin hooks:", 1)[1]
        assert "tidy@mkt" in section
        assert "acknowledged" not in section.split("tidy@mkt", 1)[1].splitlines()[0]
        assert code == 0
