"""RelayBinaryCheckerHandler - a configured relay whose binary is unusable (Plan 00474 N523).

Unless ``daemon.transport.relay_enabled`` is false (the opt-out to the legacy
transport; an absent key is the default, on), the forwarders hand relay-eligible
hooks to the Rust relay binary. When that binary is missing or cannot run
(``relay_deploy.relay_binary_defect``), those hooks run on the fallback
transport. This handler says it at session start, naming the path and the
command that provisions the binary, and starts the ``transport on``
provisioning detached (``install.relay_repair``), once per cause. The repair
never runs in the hook: the answer reports that it started, is running, or
what it recorded, and a repair that failed is reported at every session start.

Silent when the relay is disabled, there is no config file (the daemon is not
set up for this project), or the binary can run (Lean
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
from claude_code_hooks_daemon.daemon.paths import get_untracked_dir
from claude_code_hooks_daemon.install.background_sync import SyncStatus
from claude_code_hooks_daemon.install.relay_deploy import (
    missing_configured_relay_binary,
    relay_binary_defect,
    relay_binary_missing_warning,
)
from claude_code_hooks_daemon.install.relay_repair import (
    RepairNotice,
    SpawnFn,
    spawn_detached,
    start_relay_repair,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command
from claude_code_hooks_daemon.version import __version__


def _repair_line(notice: RepairNotice, fix: str) -> str:
    """The second line of the warning: what the background repair of this cause did."""
    if notice.failure is not None:
        return f"WARNING: {notice.failure}. Run: {fix}"
    if notice.started:
        return (
            f"Relay repair started in the background (log: {notice.log_path}); "
            f"if the next session still warns, run: {fix}"
        )
    record = notice.record
    if record is None:
        return (
            f"WARNING: the relay repair state file {notice.state_path} vanished while "
            f"it was read. Run: {fix}"
        )
    retry = (
        f"It is not retried automatically for this cause. Run: {fix} "
        f"(or delete {record.state_path} to have it retried at the next session start)."
    )
    if record.status is SyncStatus.RUNNING:
        return (
            f"Relay repair is running in the background (log: {record.log_path}); "
            f"if the next session still warns, run: {fix}"
        )
    if record.status is SyncStatus.SYNCED:
        return (
            f"WARNING: a background relay repair of this cause recorded success "
            f"({record.detail}), yet the binary is unusable again. {retry}"
        )
    return (
        f"WARNING: the background relay repair FAILED: {record.detail} "
        f"(log: {record.log_path}). {retry}"
    )


class RelayBinaryCheckerHandler(SessionStartHandlerBase):
    """Warn when the relay is enabled but its binary is missing or cannot run."""

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
        #: Starts the detached repair; replaced in tests so nothing builds.
        self.spawn_repair: SpawnFn = spawn_detached

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
        if not config_path.is_file():
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
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
        fix = daemon_cli_command("transport", "on")
        defect = relay_binary_defect(binary)
        if defect is None:
            # Repaired between the two checks: nothing to report.
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        warning = relay_binary_missing_warning(binary, fix)
        notice = start_relay_repair(
            root,
            binary,
            defect,
            untracked_dir=get_untracked_dir(root),
            version=__version__,
            spawn_fn=self.spawn_repair,
        )
        return AdvisoryResult(
            decision=Decision.ALLOW,
            context=[f"WARNING: {warning}", _repair_line(notice, fix)],
        )

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: an enabled relay with no binary is reported at session start."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="relay binary checker - names an enabled relay whose binary is unusable",
                command='echo "test"',
                description=(
                    "With daemon.transport.relay_enabled true and the relay binary "
                    "missing or unable to run, session start prints one WARNING "
                    "naming the binary path and the fix command (transport on), and "
                    "a second line saying the repair was started in the background "
                    "(once per cause) or what that repair recorded. "
                    "Silent when the relay is disabled or the binary can run."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"binary is missing or cannot run"],
                safety_notes=(
                    "Advisory only - the repair runs detached, never in the hook, "
                    "and never deletes the binary."
                ),
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event (new session only)",
                requires_main_thread=False,
            ),
        ]

    def get_claude_md(self) -> str | None:
        """No resident guidance: the warning names its own fix when it fires."""
        return None
