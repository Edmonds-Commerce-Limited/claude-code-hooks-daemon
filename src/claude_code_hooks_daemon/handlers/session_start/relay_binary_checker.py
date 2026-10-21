"""RelayBinaryCheckerHandler - a configured relay whose binary is unusable (Plan 00474 N523).

With ``daemon.transport.relay_enabled: true`` the forwarders hand relay-eligible
hooks to the Rust relay binary. When that binary is missing or not executable,
those hooks run on the fallback transport, and only ``transport on`` and the
status line used to say so. This handler says it at session start, naming the
path and the command that provisions the binary.

Silent when the relay is disabled or the binary is an executable file (Lean
SessionStart, Plan 00128). A config this handler cannot read is reported, not
treated as "relay disabled": whether the relay works is then unknown, and the
owner's rule for this repository is no silent fallbacks (Plan 00529).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.install.relay_deploy import (
    missing_configured_relay_binary,
    relay_binary_missing_warning,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command


class RelayBinaryCheckerHandler(SessionStartHandlerBase):
    """Warn when the relay is enabled but its binary is missing or not executable."""

    def __init__(self) -> None:
        """Initialise as a non-terminal, silent-when-clean advisory."""
        super().__init__(
            handler_id=HandlerID.RELAY_BINARY_CHECKER,
            priority=Priority.RELAY_BINARY_CHECKER,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.ENVIRONMENT,
                HandlerTag.NON_TERMINAL,
            ],
        )
        #: Set in tests so the check needs no initialised ProjectContext.
        self.workspace_root: Path | None = None

    def _project_root(self) -> Path | None:
        """The project root, or None when the daemon has not initialised one."""
        if self.workspace_root is not None:
            return self.workspace_root
        if not ProjectContext.is_initialized():
            return None
        return ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every session start, including resumes: a deleted binary outlives a session."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """One WARNING line when the configured relay binary is unusable; else nothing."""
        root = self._project_root()
        if root is None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        config_path = root / ".claude" / "hooks-daemon.yaml"
        try:
            transport = Config.load_or_default(config_path).daemon.transport
        except (ValidationError, OSError, ValueError) as exc:
            reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            return AdvisoryResult(
                decision=Decision.ALLOW,
                context=[
                    f"WARNING: relay_binary_checker could not read daemon.transport from "
                    f"{config_path} ({reason}), so whether the relay binary is usable "
                    "is unknown."
                ],
            )
        binary = missing_configured_relay_binary(root, transport)
        if binary is None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        warning = relay_binary_missing_warning(binary, daemon_cli_command("transport", "on"))
        return AdvisoryResult(decision=Decision.ALLOW, context=[f"WARNING: {warning}"])

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: an enabled relay with no binary is reported at session start."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="relay binary checker - names an enabled relay whose binary is unusable",
                command='echo "test"',
                description=(
                    "With daemon.transport.relay_enabled true and the relay binary "
                    "missing or not executable, session start prints one WARNING "
                    "naming the binary path and the fix command (transport on). "
                    "Silent when the relay is disabled or the binary is executable."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"binary is missing or not executable"],
                safety_notes="Advisory only - never builds or deletes the binary.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event (new session only)",
                requires_main_thread=False,
            ),
        ]

    def get_claude_md(self) -> str | None:
        """No resident guidance: the warning names its own fix when it fires."""
        return None
