"""ToolDisableAdvisorHandler - never-want tools vs actual settings (Plan 00293).

Opt-in advisory (ships disabled). A project can declare tools it never wants
in ``tool_policy.never_want``; that declaration only changes what reports
RECOMMEND. This handler closes the loop at session start: for each declared
tool it checks whether the source-level disable is actually present in
``.claude/settings.json`` and, when it is not, names the exact change — it
never edits settings itself. When the disable IS in place for Artifact, it
points at ``artifact_publish_blocker``'s own ``source_disable`` option so the
enforcement story is kept in one deliberate place.

Detection is deliberately narrow and honest: it recognises the documented
switches only (``enableArtifact: false`` for Artifact; a bare tool name in
``permissions.deny`` for any tool). A disable applied elsewhere — user-level
settings, an env var, managed settings — is invisible to a project-file scan,
so the advisory words its findings as "not found in project settings", never
"not disabled".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.config.models import Config, ToolPolicyConfig
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.tool_report.costs import disable_route_for

logger = logging.getLogger(__name__)

_ENABLE_ARTIFACT_KEY = "enableArtifact"


class ToolDisableAdvisorHandler(SessionStartHandlerBase):
    """Advise when a declared never-want tool is not disabled at source."""

    def __init__(self) -> None:
        """Initialise as a non-terminal, ships-disabled advisory."""
        super().__init__(
            handler_id=HandlerID.TOOL_DISABLE_ADVISOR,
            priority=Priority.TOOL_DISABLE_ADVISOR,
            terminal=False,
        )

    def get_default_enabled(self) -> bool:
        """Opt-in: the advisory is off until the project turns it on."""
        return False

    def _project_root(self) -> Path:
        root = getattr(self, "_workspace_root", None)
        return Path(root) if root is not None else ProjectContext.project_root()

    def _tool_policy(self) -> ToolPolicyConfig:
        config_path = self._project_root() / ".claude" / "hooks-daemon.yaml"
        return Config.load_or_default(config_path).tool_policy

    def _load_settings(self) -> dict[str, Any]:
        """The project's settings.json as a dict; empty on any problem."""
        settings_path = self._project_root() / ".claude" / "settings.json"
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.debug("tool_disable_advisor: cannot read %s: %s", settings_path, exc)
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _is_disabled(tool: str, settings: dict[str, Any]) -> bool:
        """Is the documented project-settings disable present for this tool?"""
        permissions = settings.get("permissions")
        deny = permissions.get("deny", []) if isinstance(permissions, dict) else []
        if isinstance(deny, list) and tool in deny:
            return True
        if tool == "Artifact":
            return settings.get(_ENABLE_ARTIFACT_KEY) is False
        return False

    def _blocker_source_disable_on(self) -> bool:
        """Is artifact_publish_blocker's own enforcement option enabled?"""
        config_path = self._project_root() / ".claude" / "hooks-daemon.yaml"
        handler_config = Config.load_or_default(config_path).handlers.pre_tool_use.get(
            "artifact_publish_blocker", {}
        )
        # The parsed value is a HandlerConfig in a validated config, but a raw
        # dict survives round-tripping through extra="allow" event blocks.
        options = getattr(handler_config, "options", None)
        if options is None and isinstance(handler_config, dict):
            options = handler_config.get("options", {})
        return isinstance(options, dict) and options.get("source_disable") is True

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire only when the project has declared at least one never-want."""
        return bool(self._tool_policy().never_want)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Compare each declaration against project settings and advise."""
        if not self.matches(hook_input):
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        settings = self._load_settings()
        missing: list[str] = []
        satisfied: list[str] = []
        for entry in self._tool_policy().never_want:
            reason = f" ({entry.reason})" if entry.reason else ""
            if self._is_disabled(entry.tool, settings):
                satisfied.append(f"  • {entry.tool}: source disable in place{reason}")
                if entry.tool == "Artifact" and not self._blocker_source_disable_on():
                    satisfied.append(
                        "    The daemon can also enforce this so it never regresses: "
                        "`handlers.pre_tool_use.artifact_publish_blocker.options."
                        "source_disable: true` (and once the disable holds, that "
                        "blocker is only a backstop)."
                    )
            else:
                missing.append(
                    f"  • {entry.tool}{reason}: no source disable found in project "
                    f"settings — {disable_route_for(entry.tool)}"
                )

        if not missing and not satisfied:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        context = ["🔧 Tool policy check (tool_policy.never_want):"]
        if missing:
            context.append("Declared never-want tools NOT disabled at source:")
            context.extend(missing)
            context.append(
                "Apply the named settings change yourself only if the USER has "
                "asked for it — otherwise surface this to them. This advisory "
                "never edits settings."
            )
        if satisfied:
            context.extend(satisfied)
        return AdvisoryResult(decision=Decision.ALLOW, context=context)

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: a declared never-want without its disable advises."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="tool disable advisor - reports undisabled never-want at session start",
                command='echo "test"',
                description=(
                    "With tool_policy.never_want declaring a tool whose source "
                    "disable is absent from .claude/settings.json, session start "
                    "carries an advisory naming the exact settings change."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Tool policy check|never_want"],
                safety_notes="Advisory only — never edits settings, never blocks.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event (new session only)",
                requires_main_thread=False,
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## tool_disable_advisor — declared never-want tools are checked at "
            "session start\n\n"
            "Opt-in advisory (ships disabled). When the project declares tools in "
            "`tool_policy.never_want`, this handler checks at session start whether "
            "each one's source-level disable is actually present in "
            "`.claude/settings.json` (`enableArtifact: false` for Artifact; a bare "
            "tool name in `permissions.deny` otherwise). A missing disable is "
            "reported with the exact settings change; nothing is ever edited "
            "automatically. Detection reads PROJECT settings only, so a disable "
            "applied at user or managed level is reported as not-found rather than "
            "asserted absent. Pairs with `bin/hooks-daemon tool-report`, which "
            "recommends candidates from transcript usage."
        )
