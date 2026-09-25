"""Tests for the plugin hooks advisory (Plan 00468 Task 4.1, G1, G2).

At the start of a new session, name each enabled Claude Code plugin that
ships hooks, since the daemon never sees those hooks, and single out a
``PreToolUse`` hook, which can replace a call's input after the daemon
allowed it. A plugin the user has acknowledged is left out. Never blocks.

Most tests hand the handler a made-up inventory. One builds a plugin in a
fake config dir and runs the real resolver, so the wiring is covered too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start import plugin_hooks_advisor
from claude_code_hooks_daemon.handlers.session_start.plugin_hooks_advisor import (
    PluginHooksAdvisorHandler,
)
from claude_code_hooks_daemon.utils.claude_plugins import (
    EnabledPlugin,
    PluginHookSource,
    PluginInventory,
    SettingsScope,
)
from claude_code_hooks_daemon.utils.session_helpers import RESUME_SESSION_MIN_TRANSCRIPT_BYTES

_NEW_SESSION: dict[str, Any] = {"hook_event_name": "SessionStart", "source": "startup"}


def _plugin(plugin_id: str, *events: str) -> EnabledPlugin:
    name, _, marketplace = plugin_id.partition("@")
    hooks = (PluginHookSource(path=None, events={event: [] for event in events}),) if events else ()
    return EnabledPlugin(
        plugin_id=plugin_id,
        name=name,
        marketplace=marketplace,
        enabled_by=SettingsScope.USER,
        install_scope="user",
        install_path=Path("/nonexistent") / name,
        version="1.0.0",
        hooks=hooks,
    )


class _Rooted(PluginHooksAdvisorHandler):
    def __init__(self, root: Path, config_dir: Path, managed_dir: Path) -> None:
        super().__init__()
        self._workspace_root = root
        self._config_dir = config_dir
        self._managed_dir = managed_dir


@pytest.fixture
def handler(tmp_path: Path) -> PluginHooksAdvisorHandler:
    (tmp_path / "project").mkdir()
    return _Rooted(tmp_path / "project", tmp_path / "config", tmp_path / "managed")


@pytest.fixture
def plugins(monkeypatch: pytest.MonkeyPatch) -> list[EnabledPlugin]:
    """The enabled plugins the handler sees; append to change them."""
    enabled: list[EnabledPlugin] = []

    def _resolve(project_root: Path, **_: Any) -> PluginInventory:
        return PluginInventory(config_dir=Path("/nonexistent"), enabled=tuple(enabled))

    monkeypatch.setattr(plugin_hooks_advisor, "resolve_enabled_plugins", _resolve)
    return enabled


def _text(handler: PluginHooksAdvisorHandler) -> str:
    result = handler.handle(_NEW_SESSION)
    assert result.decision == Decision.ALLOW
    return "\n".join(result.context)


class TestIdentity:
    def test_ids_priority_and_non_terminal(self) -> None:
        handler = PluginHooksAdvisorHandler()
        assert handler.handler_id == HandlerID.PLUGIN_HOOKS_ADVISOR
        assert handler.priority == Priority.PLUGIN_HOOKS_ADVISOR
        assert handler.terminal is False


class TestMatches:
    def test_silent_when_no_plugin_ships_hooks(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        plugins.append(_plugin("quiet@mkt"))
        assert handler.matches(_NEW_SESSION) is False

    def test_fires_for_a_plugin_with_hooks_on_a_new_session(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        plugins.append(_plugin("tidy@mkt", "Stop"))
        assert handler.matches(_NEW_SESSION) is True

    def test_silent_on_a_resumed_session(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin], tmp_path: Path
    ) -> None:
        plugins.append(_plugin("tidy@mkt", "Stop"))
        transcript = tmp_path / "session.jsonl"
        transcript.write_text("x" * (RESUME_SESSION_MIN_TRANSCRIPT_BYTES + 1))
        assert handler.matches({**_NEW_SESSION, "transcript_path": str(transcript)}) is False

    def test_silent_when_every_plugin_with_hooks_is_acknowledged(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        plugins.append(_plugin("tidy@mkt", "Stop"))
        # The registry applies each option as a private attribute.
        handler._acknowledged_plugins = ["tidy@mkt"]
        assert handler.matches(_NEW_SESSION) is False

    def test_a_malformed_acknowledgement_acknowledges_nothing(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        plugins.append(_plugin("tidy@mkt", "Stop"))
        handler._acknowledged_plugins = "tidy@mkt"
        assert handler.matches(_NEW_SESSION) is True


class TestHandle:
    def test_names_each_plugin_and_its_events(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        plugins.append(_plugin("tidy@mkt", "Stop", "SessionStart"))
        assert "tidy@mkt: SessionStart, Stop" in _text(handler)

    def test_singles_out_a_pre_tool_use_hook(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        plugins.extend([_plugin("guard@mkt", "PreToolUse"), _plugin("tidy@mkt", "Stop")])
        lines = _text(handler).splitlines()
        guard = next(line for line in lines if "guard@mkt" in line)
        tidy = next(line for line in lines if "tidy@mkt" in line)
        assert "updatedInput" in guard
        assert "updatedInput" not in tidy

    def test_says_how_to_acknowledge_and_where_to_read_more(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        plugins.append(_plugin("tidy@mkt", "Stop"))
        text = _text(handler)
        assert "handlers.session_start.plugin_hooks_advisor.options.acknowledged_plugins" in text
        assert "ClaudeCodePlugins.md" in text

    def test_leaves_out_an_acknowledged_plugin(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        plugins.extend([_plugin("tidy@mkt", "Stop"), _plugin("guard@mkt", "PreToolUse")])
        handler._acknowledged_plugins = ["tidy@mkt"]
        text = _text(handler)
        assert "guard@mkt" in text
        assert "tidy@mkt" not in text

    def test_nothing_to_say_is_an_empty_allow(
        self, handler: PluginHooksAdvisorHandler, plugins: list[EnabledPlugin]
    ) -> None:
        result = handler.handle(_NEW_SESSION)
        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestWithTheRealResolver:
    def test_a_plugin_installed_in_the_config_dir_is_named(self, tmp_path: Path) -> None:
        config = tmp_path / "config"
        root = config / "plugins" / "cache" / "mkt" / "guard" / "1.0.0"
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "guard"}))
        (root / "hooks").mkdir()
        (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": []}}))
        (config / "plugins" / "installed_plugins.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "plugins": {"guard@mkt": [{"scope": "user", "installPath": str(root)}]},
                }
            )
        )
        (tmp_path / "project").mkdir()
        handler = _Rooted(tmp_path / "project", config, tmp_path / "managed")

        assert handler.matches(_NEW_SESSION) is True
        assert "guard@mkt: PreToolUse" in _text(handler)
