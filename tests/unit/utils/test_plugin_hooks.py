"""Tests for the enabled plugins that ship hooks (Plan 00468 Task 4.1, G1, G2).

Built from hand-made inventories: which plugins are enabled, and which hook
events each registers, is the resolver's job and is tested with it.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.utils.claude_plugins import (
    EnabledPlugin,
    PluginHookSource,
    PluginInventory,
    SettingsScope,
    UnresolvedPlugin,
)
from claude_code_hooks_daemon.utils.plugin_hooks import (
    health_lines,
    plugins_with_hooks,
)


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


def _inventory(
    *plugins: EnabledPlugin, unresolved: tuple[UnresolvedPlugin, ...] = ()
) -> PluginInventory:
    return PluginInventory(config_dir=Path("/nonexistent"), enabled=plugins, unresolved=unresolved)


class TestPluginsWithHooks:
    def test_only_plugins_that_ship_hooks_are_listed(self) -> None:
        inventory = _inventory(_plugin("quiet@mkt"), _plugin("loud@mkt", "Stop"))
        assert [entry.plugin_id for entry in plugins_with_hooks(inventory)] == ["loud@mkt"]

    def test_each_entry_carries_its_events(self) -> None:
        inventory = _inventory(_plugin("p@mkt", "Stop", "PreToolUse"))
        assert plugins_with_hooks(inventory)[0].events == ("PreToolUse", "Stop")

    def test_a_pre_tool_use_hook_can_replace_input(self) -> None:
        inventory = _inventory(_plugin("guard@mkt", "PreToolUse"), _plugin("tidy@mkt", "Stop"))
        replacing = {
            entry.plugin_id: entry.can_replace_input for entry in plugins_with_hooks(inventory)
        }
        assert replacing == {"guard@mkt": True, "tidy@mkt": False}

    def test_an_acknowledged_plugin_is_marked(self) -> None:
        inventory = _inventory(_plugin("a@mkt", "Stop"), _plugin("b@mkt", "Stop"))
        entries = plugins_with_hooks(inventory, acknowledged=["b@mkt"])
        assert {entry.plugin_id: entry.acknowledged for entry in entries} == {
            "a@mkt": False,
            "b@mkt": True,
        }


class TestHealthLines:
    def test_no_hooks_says_so(self) -> None:
        assert health_lines(_inventory(_plugin("quiet@mkt"))) == [
            "  OK — no enabled Claude Code plugin ships hooks"
        ]

    def test_each_plugin_with_hooks_is_named_with_its_events(self) -> None:
        lines = health_lines(_inventory(_plugin("tidy@mkt", "Stop", "SessionStart")))
        assert any("tidy@mkt" in line and "SessionStart, Stop" in line for line in lines)

    def test_a_pre_tool_use_plugin_names_the_input_rewrite(self) -> None:
        text = "\n".join(health_lines(_inventory(_plugin("guard@mkt", "PreToolUse"))))
        assert "updatedInput" in text

    def test_an_acknowledged_plugin_is_still_listed_and_marked(self) -> None:
        lines = health_lines(_inventory(_plugin("tidy@mkt", "Stop")), acknowledged=["tidy@mkt"])
        assert any("tidy@mkt" in line and "acknowledged" in line for line in lines)

    def test_an_unresolved_plugin_is_named_because_its_hooks_are_unknown(self) -> None:
        unresolved = (UnresolvedPlugin("ghost@mkt", SettingsScope.USER, "not installed"),)
        text = "\n".join(health_lines(_inventory(unresolved=unresolved)))
        assert "ghost@mkt" in text
        assert "not installed" in text
