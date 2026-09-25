"""PluginHooksAdvisorHandler - enabled plugins that ship hooks (Plan 00468 G1, G2).

A Claude Code plugin's hooks merge with the user and project hooks, the
daemon's among them, and run in parallel with them. The daemon never sees a
plugin hook, so none of its handlers or its hook registration policy applies
to one. A plugin ``PreToolUse`` hook can also return ``updatedInput``, which
replaces a call's input after the daemon allowed the original; a daemon deny
still wins over any plugin hook.

At the start of a new session this names each enabled plugin that ships
hooks and the events they cover, and singles out ``PreToolUse``. A plugin
listed in the ``acknowledged_plugins`` option is left out; ``hooks-daemon
health`` still lists it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.claude_plugins import resolve_enabled_plugins
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs, daemon_path
from claude_code_hooks_daemon.utils.plugin_hooks import (
    ACKNOWLEDGED_PLUGINS_OPTION,
    PluginHooks,
    plugins_with_hooks,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session


class PluginHooksAdvisorHandler(SessionStartHandlerBase):
    """Name the enabled plugins whose hooks run beside the daemon's."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLUGIN_HOOKS_ADVISOR,
            priority=Priority.PLUGIN_HOOKS_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.WORKFLOW,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )
        # Set by the registry from options.acknowledged_plugins.
        self._acknowledged_plugins: object = []
        # Claude Code's config and managed-settings dirs; None means the
        # resolver's defaults (test seams).
        self._config_dir: Path | None = None
        self._managed_dir: Path | None = None

    def _project_root(self) -> Path:
        root = getattr(self, "_workspace_root", None)
        return Path(root) if root is not None else ProjectContext.project_root()

    def _acknowledged(self) -> list[str]:
        """The acknowledged plugin ids; a value that is not a list names none."""
        value = self._acknowledged_plugins
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    def _unacknowledged(self) -> tuple[PluginHooks, ...]:
        inventory = resolve_enabled_plugins(
            self._project_root(), config_dir=self._config_dir, managed_dir=self._managed_dir
        )
        entries = plugins_with_hooks(inventory, self._acknowledged())
        return tuple(entry for entry in entries if not entry.acknowledged)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """A new session with at least one unacknowledged plugin that ships hooks."""
        return not is_resume_session(hook_input) and bool(self._unacknowledged())

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Name each plugin, its events, and what a PreToolUse hook can do."""
        entries = self._unacknowledged()
        if not entries:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        option = (
            f"handlers.session_start.{HandlerID.PLUGIN_HOOKS_ADVISOR.config_key}"
            f".options.{ACKNOWLEDGED_PLUGINS_OPTION}"
        )
        context = [
            "🔌 CLAUDE CODE PLUGIN HOOKS: these enabled plugins run their own hooks "
            "beside the daemon's. The daemon never sees them, and none of its "
            "guards or its hook policy applies to them:",
            *(f"  • {entry.describe()}" for entry in entries),
        ]
        if any(entry.can_replace_input for entry in entries):
            context.append(
                "A daemon deny still wins over any plugin hook. But when the daemon "
                "allows a call, a plugin PreToolUse hook can swap in input the daemon "
                "never judged, so such a plugin can run a call the daemon never approved."
            )
        context.append(
            f"Details: {daemon_path('CLAUDE', 'ClaudeCodePlugins.md')}. Acknowledging "
            f"a plugin is the user's decision: listing its id under `{option}` in "
            ".claude/hooks-daemon.yaml stops this advisory for it, and "
            f"`{daemon_cli_command_for_docs('health')}` still lists it."
        )
        return AdvisoryResult(decision=Decision.ALLOW, context=context)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: an enabled plugin with hooks is named at session start."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="plugin hooks advisor - names an enabled plugin that ships hooks",
                command='echo "test"',
                description=(
                    "With an enabled Claude Code plugin that ships hooks and is not "
                    "listed in acknowledged_plugins, session start names the plugin "
                    "and its hook events."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"CLAUDE CODE PLUGIN HOOKS"],
                safety_notes="Advisory only; never blocks and changes nothing.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event (new session only)",
                requires_main_thread=False,
            ),
        ]
