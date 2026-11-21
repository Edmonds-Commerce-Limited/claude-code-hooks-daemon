"""ScratchSweepHandler - the session's scratch directory at SessionStart (Plan 00627).

DESIGN.md section 7: each session works in its own directory under the scratch
root of the checkout it starts in, ``untracked/scratch/s-<UTC>-<sid8>/``, with a
daemon-written manifest recording the session id, birth, checkout and branch.
This handler creates it (idempotent per session id, so resume and compact reuse
it) and announces it as "your scratch directory", with the ``scratch new``
command that makes a recorded entry inside it.

It fires on every source because a compaction drops the earlier announcement.
It never raises and never blocks: a failure to create the directory is said in
one line, and an unusable session id is silent. Section 10 names this ONE
handler for the scratch summary too: :func:`render_inventory_report` reads only
the cached inventory, and each run starts a background refresh of it.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import Config, ScratchCapsConfig
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.paths import DaemonPath, ProjectPath
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.scratch_caps import CapLevel
from claude_code_hooks_daemon.core.scratch_inventory import (
    INVENTORY_FILE,
    InventoryReading,
    inventory_caps,
    read_inventory,
)
from claude_code_hooks_daemon.core.scratch_session import (
    SessionError,
    check_session_id,
    ensure_session_dir,
)
from claude_code_hooks_daemon.core.session_start_tiers import (
    SessionStartVerifiable,
    SessionTier,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.git_repo import GitRepo
from claude_code_hooks_daemon.utils.git_sync import current_branch
from claude_code_hooks_daemon.utils.scratch_dir import ensure_scratch_dir

logger = logging.getLogger(__name__)

_ICON = "🗒️"

#: An inventory older than this is said to be stale.
STALE_AFTER_SECONDS: Final[float] = 24 * 3600.0
#: An archive expiring within this window is announced with its restore command.
EXPIRY_WINDOW_SECONDS: Final[float] = 48 * 3600.0
_MAX_LISTED: Final[int] = 10


def _start_refresh(project_root: Path) -> None:
    """Refresh the cached inventory in a background thread; never raises."""
    from claude_code_hooks_daemon.daemon.cli import start_scratch_inventory_refresh

    try:
        start_scratch_inventory_refresh(project_root)
    except Exception:
        logger.exception("scratch inventory refresh not started")


def _linked_component(checkout: Path) -> str | None:
    """The first of ``untracked/`` and ``untracked/scratch/`` that is a symlink, else None.

    The sweep refuses a root that leaves ``untracked/`` once links resolve, so
    a session directory made through a link would sit where nothing ever
    sweeps it. It is not created, and the reason is said instead.
    """
    for relative in (DaemonPath.UNTRACKED_DIR, ProjectPath.SCRATCH_DIR):
        if (checkout / relative).is_symlink():
            return str(relative)
    return None


def _caps_config(project_root: Path) -> ScratchCapsConfig:
    """The project's ``scratch.caps``; the defaults when the config cannot be read."""
    try:
        config = Config.load_or_default(project_root / ".claude" / "hooks-daemon.yaml")
    except (OSError, ValueError) as exc:
        logger.info("scratch caps: config unreadable (%s); using defaults", type(exc).__name__)
        return ScratchCapsConfig()
    return config.scratch.caps


def _problem_lines(reading: InventoryReading, now: float) -> list[str]:
    inventory = reading.inventory
    if inventory is None:
        return [
            f"{_ICON} Scratch inventory {reading.problem}: the counts below are unknown; "
            "a refresh has been started."
        ]
    lines: list[str] = []
    if inventory.incomplete:
        reasons = "; ".join(inventory.incomplete_reasons) or "no reason recorded"
        lines.append(f"{_ICON} Scratch inventory is incomplete ({reasons}): counts are a floor.")
    age = now - inventory.generated_at
    if age > STALE_AFTER_SECONDS:
        lines.append(f"{_ICON} Scratch inventory is stale ({age / 3600:.0f}h old); refreshing.")
    return lines


def render_inventory_report(
    reading: InventoryReading, caps: ScratchCapsConfig, *, now: float
) -> list[str]:
    """The SessionStart scratch report, from the cached inventory only.

    Silent when the inventory is complete, fresh, has nothing due to file, no
    archive about to expire and every cap below warn; never silent when the
    inventory is missing, unreadable, incomplete or stale.
    """
    lines = _problem_lines(reading, now)
    inventory = reading.inventory
    if inventory is None:
        return lines
    overdue = [entry for entry in inventory.entries if entry.due and entry.filing_command]
    expiring = [
        archive
        for archive in inventory.archives
        if archive.expires_at - now <= EXPIRY_WINDOW_SECONDS
    ]
    cap_report = inventory_caps(inventory, caps)
    over = cap_report.at_or_above(CapLevel.WARN)
    if not (lines or overdue or expiring or over):
        return []
    verdicts = Counter(entry.verdict for entry in inventory.entries)
    counts = ", ".join(f"{verdict} {count}" for verdict, count in sorted(verdicts.items()))
    lines.append(f"{_ICON} Scratch entries by verdict: {counts or 'none'}")
    if overdue:
        lines.append(f"   Overdue, to file ({len(overdue)}):")
        lines.extend(f"     {e.name}: `{e.filing_command}`" for e in overdue[:_MAX_LISTED])
    if expiring:
        lines.append(f"   Archives expiring within {EXPIRY_WINDOW_SECONDS / 3600:.0f}h:")
        lines.extend(
            f"     {a.archive_id} ({', '.join(a.original_paths)}): `{a.restore_command}`"
            for a in expiring[:_MAX_LISTED]
        )
    for check in over:
        enforced = "" if cap_report.enforce else " (advise only)"
        lines.append(
            f"   Cap {check.key}: {check.count} is at {check.level.name} "
            f"(warn {check.warn}, block {check.block}){enforced}; run "
            f"`{daemon_cli_command_for_docs('scratch-sweep')} --apply`."
        )
    return lines


def sweep_action_required(reading: InventoryReading, caps: ScratchCapsConfig) -> bool:
    """Whether the must-do list should carry "run ``scratch-sweep --apply``".

    True when an entry is due or any cap is at warn or worse (DESIGN section
    10). An inventory that cannot be read says nothing either way, so it adds
    no must-do item; the SessionStart report already says it is missing.
    """
    inventory = reading.inventory
    if inventory is None:
        return False
    if any(entry.due for entry in inventory.entries):
        return True
    return bool(inventory_caps(inventory, caps).at_or_above(CapLevel.WARN))


class ScratchSweepHandler(SessionStartVerifiable, SessionStartHandlerBase):
    """Create and announce this session's scratch directory."""

    def __init__(self) -> None:
        # INFO is the floor: the verifier raises the handler to ACTION_REQUIRED
        # while the sweep has work, which puts it on the must-do list.
        SessionStartVerifiable.__init__(self, declared_tier=SessionTier.INFO)
        SessionStartHandlerBase.__init__(
            self,
            handler_id=HandlerID.SCRATCH_SWEEP,
            priority=Priority.SCRATCH_SWEEP,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL, HandlerTag.WORKFLOW],
        )

    def _get_project_root(self) -> Path:
        try:
            return ProjectContext.project_root()
        except RuntimeError:
            logger.debug("ProjectContext not initialised; using cwd for the scratch directory")
            return Path.cwd()

    def _checkout(self, hook_input: dict[str, Any]) -> Path:
        """The checkout the session starts in: its cwd's worktree of THIS project, else the project root."""
        project_root = self._get_project_root()
        cwd = hook_input.get(HookInputField.CWD)
        if not isinstance(cwd, str) or not cwd:
            return project_root
        found = GitRepo.resolve_for(Path(cwd))
        project = GitRepo.resolve_for(project_root)
        if found is None or project is None:
            return project_root
        if found.main_worktree_root().resolve() != project.main_worktree_root().resolve():
            return project_root
        return found.root

    def verify_still_needed(self) -> bool:
        """True while an entry is due or a cap is at warn; reads the cached inventory only."""
        project_root = self._get_project_root()
        reading = read_inventory(project_root / DaemonPath.UNTRACKED_DIR / INVENTORY_FILE)
        return sweep_action_required(reading, _caps_config(project_root))

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every source: compact drops the earlier announcement."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Create the directory if absent and say where it is; one line on failure."""
        session_id = hook_input.get(HookInputField.SESSION_ID)
        if not isinstance(session_id, str):
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        try:
            check_session_id(session_id)
        except SessionError:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        checkout = self._checkout(hook_input)
        try:
            linked = _linked_component(checkout)
            if linked is not None:
                raise SessionError(f"{linked} is a symlink, which the sweep never follows")
            ensure_scratch_dir(checkout)
            made = ensure_session_dir(
                checkout / ProjectPath.SCRATCH_DIR,
                session_id,
                now=datetime.now(UTC),
                checkout=str(checkout),
                branch=current_branch(checkout),
            )
        except (SessionError, OSError) as exc:
            reason = str(exc) if isinstance(exc, SessionError) else type(exc).__name__
            logger.info("scratch session directory not created: %s", reason)
            return AdvisoryResult(
                decision=Decision.ALLOW,
                context=[f"{_ICON} Scratch session directory not created: {reason}"],
            )
        command = daemon_cli_command_for_docs("scratch", "new")
        project_root = self._get_project_root()
        reading = read_inventory(project_root / DaemonPath.UNTRACKED_DIR / INVENTORY_FILE)
        report = render_inventory_report(reading, _caps_config(project_root), now=time.time())
        _start_refresh(project_root)
        return AdvisoryResult(
            decision=Decision.ALLOW,
            context=[
                f"{_ICON} Your scratch directory: {made.path}",
                f"   Make each piece of throwaway work an entry in it: `{command} <name> "
                "--purpose '...' [--plan NNNNN]` prints the path. Entries expire after "
                "their TTL; anything worth keeping is filed where git carries it.",
                *report,
            ],
        )

    def get_claude_md(self) -> str | None:
        """The session scratch directory is a standing convention."""
        command = daemon_cli_command_for_docs("scratch", "new")
        return (
            "## scratch_sweep — your session's scratch directory\n\n"
            "At every SessionStart the daemon creates (once per session id) and announces "
            "`untracked/scratch/s-<UTC>-<first 8 of the session id>/` in the checkout the "
            "session starts in, with a daemon-written `.scratch-session.json` manifest. Put "
            f"throwaway work there as entries made by `{command} <name> --purpose '...' "
            "[--plan NNNNN] [--ttl-hours N]`, which records each entry's birth, purpose, plan "
            "and TTL and prints its path; a sub-agent in a worktree gets the same directory "
            "name in its own checkout. Scratch expires: anything worth keeping is filed where "
            "git carries it (a plan's `subagent-reports/`, a journal entry, a test). "
            "The same handler then reports, from the cached "
            "`untracked/scratch-inventory.json` only (refreshed in the background at each "
            "SessionStart and by every `scratch-sweep --apply` run), the entries by verdict, the "
            "overdue entries with their filing command, archives expiring within 48h with "
            "their restore command, and any cap at warn or block. It is silent when all of "
            "that is clean, and always speaks when the inventory is missing, incomplete or "
            "stale. Advisory only; never blocks."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance test: the directory is announced, never blocks."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="scratch sweep - announces the session scratch directory",
                command='echo "test"',
                description=(
                    "On SessionStart the handler creates this session's directory under "
                    "untracked/scratch/ (idempotent) and announces it as 'Your scratch "
                    "directory', with the `scratch new` command. It never blocks."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Your scratch directory|scratch session directory"],
                safety_notes="Creates one ignored directory under untracked/scratch/",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
