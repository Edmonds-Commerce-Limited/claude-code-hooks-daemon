"""InstalledPluginEditAdvisorHandler - a write into an installed Claude Code plugin.

Plan 00468 G16. Claude Code keeps each installed plugin's files under
``<config dir>/plugins/cache/`` and each marketplace's clone under
``<config dir>/plugins/marketplaces/``. An edit there is replaced without a
word on the next plugin update, and it quietly changes a third-party prompt,
hook or script the user trusted as published. The obvious case: a read-only
plugin agent told to write a report, where adding ``Write`` to its ``tools:``
looks like the fix.

Advisory, never blocking: a local experiment on an installed plugin is
sometimes exactly what is wanted. The plugin's data dir
(``<config dir>/plugins/data/``) is the plugin's own writable store, and is
left alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_write_targets, get_file_path
from claude_code_hooks_daemon.utils.claude_config import claude_config_dir, session_config_dir
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

#: Where Claude Code keeps installed plugin files, under its config dir.
_PLUGINS_DIRNAME: Final[str] = "plugins"
_INSTALLED_PLUGIN_DIRNAMES: Final[tuple[str, str]] = ("cache", "marketplaces")

_NOTEBOOK_PATH_KEY: Final[str] = "notebook_path"


class InstalledPluginEditAdvisorHandler(PreToolUseHandlerBase):
    """Say so when a write lands in an installed Claude Code plugin's files.

    Checks a ``Write``/``Edit``/``NotebookEdit`` target and every path a Bash
    command plainly writes against ``plugins/cache/`` and
    ``plugins/marketplaces/`` under the daemon's Claude config dir and the
    session's own (read from the payload's transcript path). Both the path as
    written and its resolved form are compared, so a home symlinked into the
    project (ccy) is recognised either way.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.INSTALLED_PLUGIN_EDIT_ADVISOR,
            priority=Priority.INSTALLED_PLUGIN_EDIT_ADVISOR,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        # Claude Code's config dir; None means claude_config_dir() (test seam).
        self._config_dir: Path | None = None

    def _installed_plugin_dirs(self, hook_input: dict[str, Any]) -> list[Path]:
        homes = [self._config_dir if self._config_dir is not None else claude_config_dir()]
        session_home = session_config_dir(hook_input.get(HookInputField.TRANSCRIPT_PATH))
        if session_home is not None:
            homes.append(session_home)
        return [
            home / _PLUGINS_DIRNAME / name for home in homes for name in _INSTALLED_PLUGIN_DIRNAMES
        ]

    @staticmethod
    def _targets(hook_input: dict[str, Any]) -> list[str]:
        if hook_input.get(HookInputField.TOOL_NAME) == ToolName.BASH:
            return get_bash_write_targets(hook_input)
        named = get_file_path(hook_input)
        if named is None and hook_input.get(HookInputField.TOOL_NAME) == ToolName.NOTEBOOK_EDIT:
            tool_input = hook_input.get(HookInputField.TOOL_INPUT)
            candidate = tool_input.get(_NOTEBOOK_PATH_KEY) if isinstance(tool_input, dict) else None
            named = candidate if isinstance(candidate, str) else None
        return [named] if named else []

    def _plugin_files(self, hook_input: dict[str, Any]) -> list[str]:
        """The absolute write targets that lie in an installed plugin's files."""
        directories = self._installed_plugin_dirs(hook_input)
        found: list[str] = []
        for target in self._targets(hook_input):
            path = Path(target)
            if not path.is_absolute() or target in found:
                continue
            resolved = path.resolve()
            if any(
                path.is_relative_to(directory) or resolved.is_relative_to(directory.resolve())
                for directory in directories
            ):
                found.append(target)
        return found

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when this call writes into an installed plugin's files."""
        return bool(self._plugin_files(hook_input))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Allow, and say what happens to the change and what to do instead."""
        listed = "\n".join(f"  - {path}" for path in self._plugin_files(hook_input))
        return GatingResult(
            decision=Decision.ALLOW,
            context=[
                "INSTALLED CLAUDE CODE PLUGIN FILE: this call writes into an installed "
                f"plugin's own files:\n{listed}\n\n"
                "Claude Code replaces these files on the next plugin update, so the "
                "change is lost without a word. It also changes a prompt, hook or script "
                "you trusted as the plugin's author published it.\n\n"
                "To keep a change: fork the plugin and install your fork, or file the "
                "change upstream. The plugin's own writable store is "
                "`plugins/data/<plugin>/`, which this does not cover.\n\n"
                "Advisory only; proceeding."
            ],
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the installed plugin edit advisor."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        project_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path("plugin-advisor-probe.md"),
                "content": "probe",
            },
        )

        return [
            AcceptanceTest(
                title="Edit of an installed plugin file is advised",
                harness_cannot_produce=(
                    "The advisory needs a real write target under the Claude config "
                    "dir's plugins/cache/, which differs per machine and must not be "
                    "modified by an acceptance run. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_installed_plugin_edit_advisor.py."
                ),
                command=(
                    "Use the Edit tool on any file under ~/.claude/plugins/cache/ "
                    "(or $CLAUDE_CONFIG_DIR/plugins/cache/), then revert the change"
                ),
                description="An edit to an installed plugin's files draws an advisory",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"INSTALLED CLAUDE CODE PLUGIN FILE", r"upstream"],
                safety_notes="Advisory only. Revert the probe edit afterwards.",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse with Edit tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="Write inside the project (near-miss allow)",
                command=project_probe.as_instruction(),
                tool_payload=project_probe,
                description="Stays silent for a file that is not part of an installed plugin",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Negative case: an advisory on every write would be ignored.",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse with Write tool",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
