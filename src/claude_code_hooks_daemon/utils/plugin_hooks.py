"""Enabled Claude Code plugins that ship hooks (Plan 00468 G1, G2).

A plugin's hooks run beside the daemon's, as separate processes Claude Code
starts itself, so none of the daemon's handlers or its hook registration
policy applies to them. A plugin ``PreToolUse`` hook can also return
``updatedInput``, which replaces a call's input after the daemon allowed the
original. The session-start advisory and ``health`` both report from here;
the full explanation is in ``CLAUDE/ClaudeCodePlugins.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.constants.events import EventType
from claude_code_hooks_daemon.utils.claude_plugins import PluginInventory

#: The handler option naming plugins whose hooks the user has accepted.
ACKNOWLEDGED_PLUGINS_OPTION: Final[str] = "acknowledged_plugins"

_UPDATED_INPUT_NOTE: Final[str] = (
    "its PreToolUse hook can return updatedInput, which replaces a call's input "
    "after the daemon allowed the original"
)


@dataclass(frozen=True)
class PluginHooks:
    """One enabled plugin that ships hooks, and the events they cover."""

    plugin_id: str
    events: tuple[str, ...]
    acknowledged: bool

    @property
    def can_replace_input(self) -> bool:
        """Whether a hook of this plugin sees a tool call before it runs."""
        return EventType.PRE_TOOL_USE in self.events

    def describe(self) -> str:
        """``<id>: <events>``, plus the input-rewrite note for PreToolUse."""
        text = f"{self.plugin_id}: {', '.join(self.events)}"
        return f"{text} — {_UPDATED_INPUT_NOTE}" if self.can_replace_input else text


def plugins_with_hooks(
    inventory: PluginInventory, acknowledged: Iterable[str] = ()
) -> tuple[PluginHooks, ...]:
    """Every enabled plugin that registers at least one hook event."""
    accepted = set(acknowledged)
    return tuple(
        PluginHooks(plugin.plugin_id, plugin.hook_events, plugin.plugin_id in accepted)
        for plugin in inventory.enabled
        if plugin.hook_events
    )


def health_lines(inventory: PluginInventory, acknowledged: Iterable[str] = ()) -> list[str]:
    """The ``health`` section: every plugin with hooks, acknowledged or not.

    An enabled plugin the resolver could not read is listed too, because
    whatever hooks it ships are unknown rather than absent.
    """
    entries = plugins_with_hooks(inventory, acknowledged)
    lines = [
        f"  {entry.describe()}{' (acknowledged)' if entry.acknowledged else ''}"
        for entry in entries
    ]
    lines.extend(
        f"  {plugin.plugin_id}: hooks unknown, not resolved ({plugin.reason})"
        for plugin in inventory.unresolved
    )
    return lines or ["  OK — no enabled Claude Code plugin ships hooks"]
