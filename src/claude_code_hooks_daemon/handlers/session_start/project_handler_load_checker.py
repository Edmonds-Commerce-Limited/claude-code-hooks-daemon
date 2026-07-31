"""ProjectHandlerLoadCheckerHandler - loud alert for skipped project handlers.

Project handlers that fail to load (e.g. an upgrade introduced a new required
abstract method an older handler does not implement) are skipped by the daemon
so it can still start — the safe choice. Historically that skip was *silent*:
only a load-time log line nobody reads at session start. An agent could then
work an entire session believing protections were live when they were not.

This SessionStart handler (Plan 00143) closes the observability gap. It reads
the health state the running daemon persisted at startup
(``daemon.project_handler_health``) and, whenever one or more project handlers
failed to load, injects a loud, unmissable "PROJECT PROTECTION DEGRADED" alert
into the agent's context. It stays completely silent when every project handler
loaded (Lean SessionStart), so healthy projects gain no new noise.

Because the state reflects the *running* daemon, the alert keeps firing every
session until the handler is fixed AND the daemon restarted — which is exactly
the remediation the alert asks for. Advisory only — it never blocks.
"""

from __future__ import annotations

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command


def _restart_cmd() -> str:
    """Restart command surfaced in the alert and the CLAUDE.md guidance.

    Computed on demand (Plan 00192): the wrapper path depends on the install
    mode, which ``ProjectContext`` only knows after daemon startup.
    """
    return daemon_cli_command("restart")


def _validate_cmd() -> str:
    """Diagnostic command for the degraded-protection alert."""
    return daemon_cli_command("validate-project-handlers")


class ProjectHandlerLoadCheckerHandler(Handler):
    """Loudly alert at session start when project handlers failed to load.

    Reads the persisted load-failure state and injects a high-visibility
    degraded-protection warning while any failure persists. Silent when clean.
    Advisory only — reports as context, never blocks.
    """

    def __init__(self) -> None:
        """Initialise the project-handler load checker handler."""
        super().__init__(
            handler_id=HandlerID.PROJECT_HANDLER_LOAD_CHECKER,
            priority=Priority.PROJECT_HANDLER_LOAD_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.WORKFLOW,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )

    @staticmethod
    def _read_state() -> Any:
        """Read the persisted project-handler health state.

        Imported lazily to avoid any import-time coupling between the handlers
        package and the daemon package.
        """
        from claude_code_hooks_daemon.daemon.project_handler_health import (
            read_load_failures,
        )

        return read_load_failures()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only fire when project-handler loading is degraded.

        Fires on every session (new and resumed) while a failure persists — a
        protection regression is important enough that a resumed session must
        be told too. Stays silent when healthy.

        Args:
            hook_input: Hook input dictionary (unused — state is on disk)

        Returns:
            True iff one or more project handlers failed to load.
        """
        return bool(self._read_state().is_degraded)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Inject the loud degraded-protection alert.

        Args:
            hook_input: Hook input dictionary

        Returns:
            HookResult with ALLOW decision and the alert as advisory context.
        """
        state = self._read_state()
        if not state.is_degraded:
            # Lean SessionStart: say nothing on a healthy project.
            return HookResult(decision=Decision.ALLOW, context=[])

        failed_count = state.failed_count
        lines: list[str] = [
            "🚨 PROJECT PROTECTION DEGRADED 🚨",
            "",
            f"{failed_count} project handler(s) FAILED to load and are NOT "
            "protecting this session:",
        ]
        for failure in state.failures:
            lines.append(f"  - {failure.event_dir}/{failure.filename} ({failure.reason})")
        lines.extend(
            [
                "",
                "These protections are OFF. Fix the handler(s), then restart the "
                f"daemon (`{_restart_cmd()}`) before continuing — the alert clears "
                "only once a restart reloads them. Do NOT assume normal guardrails "
                "are in force.",
                "",
                f"Diagnose each failure with: `{_validate_cmd()}`",
            ]
        )

        return HookResult(decision=Decision.ALLOW, context=lines)

    def get_claude_md(self) -> str | None:
        """Return agent-facing guidance for the degraded-protection alert."""
        return (
            "## project_handler_load_checker — project protection degraded alert\n"
            "\n"
            "At session start this handler reports any **project handlers** "
            "(`.claude/project-handlers/`) that FAILED to load in the running "
            "daemon. A skipped handler is a silently-disabled protection — the "
            "alert exists so you never assume a guardrail is active when it is "
            "not.\n"
            "\n"
            "### When you see `🚨 PROJECT PROTECTION DEGRADED 🚨`\n"
            "\n"
            "1. **Do not assume normal guardrails are in force.** The listed "
            "handlers are OFF for this session.\n"
            f"2. **Diagnose** each failure: `{_validate_cmd()}` names the file, "
            "the missing method, and the daemon version that introduced it.\n"
            "3. **Fix** the handler(s) — usually adding a required method stub "
            "(e.g. `get_claude_md`) that a daemon upgrade made mandatory.\n"
            f"4. **Restart the daemon** (`{_restart_cmd()}`). The alert reflects "
            "the *running* daemon, so it clears only after a restart reloads the "
            "fixed handlers — fixing the file alone is not enough.\n"
            "\n"
            "The handler is silent when every project handler loads, so seeing "
            "this alert always means real action is required.\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="project handler load checker - alerts on degraded protection",
                command='echo "test"',
                description=(
                    "When a project handler failed to load, a new session shows a "
                    "PROJECT PROTECTION DEGRADED alert listing the skipped handlers."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"PROJECT PROTECTION DEGRADED"],
                safety_notes=(
                    "Advisory handler - warns but does not block. Requires a "
                    "project handler that fails to load (degraded state) to fire."
                ),
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event with a failed project handler",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
