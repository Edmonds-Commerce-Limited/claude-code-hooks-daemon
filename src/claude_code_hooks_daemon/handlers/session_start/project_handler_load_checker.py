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

from collections.abc import Mapping, Sequence
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.session_start_tiers import (
    SessionStartVerifiable,
    SessionTier,
)
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)

#: Subcommands named once, rendered twice (Plan 00244). The runtime alert and
#: the resident CLAUDE.md guidance quote the same commands but need different
#: path forms, so the SUBCOMMAND is the single source of truth and the builder
#: choice belongs to the destination.
_RESTART_SUBCOMMAND: Final[str] = "restart"
_VALIDATE_SUBCOMMAND: Final[str] = "validate-project-handlers"
_HEALTH_SUBCOMMAND: Final[str] = "health"


def _restart_cmd() -> str:
    """Restart command surfaced in the RUNTIME alert — absolute.

    Computed on demand (Plan 00192): the wrapper path depends on the install
    mode, which ``ProjectContext`` only knows after daemon startup.
    """
    return daemon_cli_command(_RESTART_SUBCOMMAND)


def _validate_cmd() -> str:
    """Diagnostic command for the RUNTIME degraded-protection alert — absolute."""
    return daemon_cli_command(_VALIDATE_SUBCOMMAND)


class ProjectHandlerLoadCheckerHandler(SessionStartVerifiable, SessionStartHandlerBase):
    """Loudly alert at session start when project handlers failed to load.

    Reads the persisted load-failure state and injects a high-visibility
    degraded-protection warning while any failure persists. Silent when clean.
    Advisory only — reports as context, never blocks.
    """

    def __init__(self) -> None:
        """Initialise the project-handler load checker handler."""
        # ACTION_SUGGESTED is the floor, not the ceiling: whenever the verifier
        # below reports a genuinely degraded session, `compute_tier` raises this
        # to ACTION_REQUIRED. The declared value only governs the case where
        # the state cannot be read at all (Plan 00416 Task 2.2).
        SessionStartVerifiable.__init__(self, declared_tier=SessionTier.ACTION_SUGGESTED)
        SessionStartHandlerBase.__init__(
            self,
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
        # Built-in handlers whose options the registry could not collect,
        # keyed `<EventType>.<config_key>`. Injected by `register_all` (Plan
        # 00466 N19), which selects this handler by declaring the attribute.
        self._option_failures: Mapping[str, str] = {}
        # Config values the daemon runs with other than as written, each with
        # its fix. Injected by `register_all` (Plan 00466 round 3) the same way.
        self._config_problems: Sequence[str] = ()

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

    def verify_still_needed(self) -> bool:
        """True while project handlers are still failing to load.

        The admission test for ACTION_REQUIRED is not "is this worth saying"
        but "is this session objectively mis-configured". A degraded load
        means guards the project DECLARED are simply off, and an agent reading
        past the notice works without protections it has every reason to
        assume are in force. That is a broken session, not an improvable one.

        Read-only by construction: it reads the same persisted state the alert
        renders from, and writes nothing. That matters because a tier is also
        computed by `hooks-daemon session-actions`, which a human runs to
        inspect a session without changing it.

        A built-in handler running on its defaults because its options could
        not be collected is the same kind of broken session, so it counts too.

        Returns:
            True iff a project handler failed to load or a built-in handler
            is running without its configured options.
        """
        return self._is_degraded()

    def _is_degraded(self) -> bool:
        return bool(self._option_failures) or bool(self._read_state().is_degraded)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Only fire when project-handler loading is degraded, or a config
        value is not in force as written.

        Fires on every session (new and resumed) while a failure persists — a
        protection regression is important enough that a resumed session must
        be told too. Stays silent when healthy.

        Args:
            hook_input: Hook input dictionary (unused — state is on disk)

        Returns:
            True iff a project handler failed to load, a built-in handler is
            running without its configured options, or a config value is not
            in force as written.
        """
        return self._is_degraded() or bool(self._config_problems)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Inject the loud degraded-protection alert.

        Args:
            hook_input: Hook input dictionary

        Returns:
            AdvisoryResult with ALLOW decision and the alert as advisory context.
        """
        # Lean SessionStart: each part says nothing when it is healthy.
        lines = (
            self._project_handler_lines()
            + self._option_failure_lines()
            + self._config_problem_lines()
        )
        return AdvisoryResult(decision=Decision.ALLOW, context=lines)

    def _config_problem_lines(self) -> list[str]:
        """Name each config value the daemon runs with other than as written.

        Not a degraded session: the daemon chose the safe value and every
        guard is on. The config says something it is not doing, and a
        warning only in the daemon log goes unseen (Plan 00466 round 3).
        """
        if not self._config_problems:
            return []
        lines = [
            f"⚠️ CONFIG VALUE NOT IN FORCE: {len(self._config_problems)} setting(s) in "
            ".claude/hooks-daemon.yaml are running at a different value than written:",
        ]
        lines.extend(f"  - {problem}" for problem in self._config_problems)
        lines.append(
            f"Fix the config, then restart the daemon (`{_restart_cmd()}`); "
            f"`{daemon_cli_command(_HEALTH_SUBCOMMAND)}` lists the same settings."
        )
        return lines

    def _option_failure_lines(self) -> list[str]:
        """Name each built-in handler running on its defaults (Plan 00466 N19)."""
        if not self._option_failures:
            return []
        lines = [
            f"⚠️ HANDLER OPTIONS NOT APPLIED: {len(self._option_failures)} handler(s) "
            "are running on their defaults, ignoring the options configured for them:",
        ]
        for handler_key, reason in self._option_failures.items():
            lines.append(f"  - {handler_key} ({reason})")
        lines.append(
            "This is a daemon defect, not a config mistake. The daemon log has the "
            f"traceback, and `{daemon_cli_command(_HEALTH_SUBCOMMAND)}` lists the same handlers."
        )
        return lines

    def _project_handler_lines(self) -> list[str]:
        """The project-handler load-failure alert, or nothing when all loaded."""
        state = self._read_state()
        if not state.is_degraded:
            return []

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
        return lines

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
            f"2. **Diagnose** each failure: "
            f"`{daemon_cli_command_for_docs(_VALIDATE_SUBCOMMAND)}` names the file, "
            "the missing method, and the daemon version that introduced it.\n"
            "3. **Fix** the handler(s) — usually adding a required method stub "
            "(e.g. `get_claude_md`) that a daemon upgrade made mandatory.\n"
            f"4. **Restart the daemon** "
            f"(`{daemon_cli_command_for_docs(_RESTART_SUBCOMMAND)}`). The alert reflects "
            "the *running* daemon, so it clears only after a restart reloads the "
            "fixed handlers — fixing the file alone is not enough.\n"
            "\n"
            "### When you see `⚠️ HANDLER OPTIONS NOT APPLIED`\n"
            "\n"
            "The named built-in handlers are running on their defaults, so the "
            "options configured for them are not in force. This is a daemon "
            "defect: report it with the traceback from the daemon log.\n"
            "\n"
            "### When you see `⚠️ CONFIG VALUE NOT IN FORCE`\n"
            "\n"
            "The daemon started, with every guard on, but runs the named setting "
            "at a safe value instead of the one written in "
            "`.claude/hooks-daemon.yaml`. Each line says why and what to set; "
            "change the config and restart the daemon to clear it.\n"
            "\n"
            "The handler is silent when every project handler loads, every "
            "built-in handler has its options and every setting is in force as "
            "written, so seeing any of these alerts always means real action is "
            "required.\n"
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
