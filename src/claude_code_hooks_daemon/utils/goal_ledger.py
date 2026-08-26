"""Daemon-side goal ledger (Plan 00276).

Claude Code's ``/goal`` slot holds exactly ONE session-scoped condition, so
under concurrent plan execution each newly injected goal silently displaces
the previous one. This ledger is the daemon-side memory of every goal the
``goal_injection`` handler emits: it detects displacement (a new goal while a
prior ledgered plan is still ``In Progress``), lets the Stop handler defend
EVERY still-live ledgered goal, and retires entries when their plan reaches a
terminal status or leaves the active plan directory.

Contract:

- **Fail-open**: a missing, corrupt, or unwritable ledger never raises out of
  the public API — failures are logged and behave as an empty ledger.
- **Concurrency-safe**: hook events dispatch on concurrent threads of the one
  daemon process, so every public read-modify-write holds an exclusive
  ``flock`` on a sibling lock file (same idiom as the daemon start sequence),
  and the atomic-replace tmp file is unique per writer, not per process.
- **Status parsing is delegated** to :class:`plan_qa.model.PlanDoc` — the
  tested parser that handles date qualifiers, trailing icons, and fenced
  code blocks — never a hand-rolled regex.
- **Bounded**: retired entries are pruned once the ledger exceeds a cap.
"""

import fcntl
import json
import logging
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.plan_qa.model import TERMINAL_STATUSES, PlanDoc, PlanStatus

logger = logging.getLogger(__name__)

# Ledger file, placed under ``ProjectContext.daemon_untracked_dir()`` by callers.
LEDGER_FILENAME: Final[str] = "goal-ledger.json"
_LOCK_SUFFIX: Final[str] = ".lock"
# Owner read/write only — consistent with the daemon's private-state posture.
_LOCK_FILE_MODE: Final[int] = 0o600

_ENTRIES_KEY: Final[str] = "entries"
_MAX_ENTRIES: Final[int] = 100

_PLAN_MD_FILENAME: Final[str] = "PLAN.md"

# Retirement reasons recorded on an entry.
RETIRED_TERMINAL_STATUS: Final[str] = "terminal-status"
RETIRED_ARCHIVED: Final[str] = "archived"

# Per-plan states computed by ``_plan_state``.
_STATE_IN_PROGRESS: Final[str] = "in-progress"
_STATE_TERMINAL: Final[str] = "terminal"
_STATE_OTHER: Final[str] = "other"
_STATE_MISSING: Final[str] = "missing"
_STATE_UNREADABLE: Final[str] = "unreadable"


def resolve_plan_dir(project_root: Path, configured: str | None) -> Path:
    """Resolve the active plan directory from the plan-workflow config.

    ``configured`` is the ``track_plans_in_project`` value the registry
    injects into planning-tagged handlers (``plan_workflow.directory``); when
    absent, the config model's own default is used — no second copy of the
    literal here.
    """
    from claude_code_hooks_daemon.config.models import PlanWorkflowConfig

    return project_root / (configured or PlanWorkflowConfig().directory)


@dataclass
class GoalLedgerEntry:
    """One recorded goal emission and its lifecycle markers."""

    plan_number: str
    session_id: str
    rendered_line: str
    emitted_at: float
    displaced_by: str | None = None
    displaced_at: float | None = None
    retired_at: float | None = None
    retired_reason: str | None = None


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plan_state(plan_dir: Path, plan_number: str) -> str:
    """Classify the plan's current state for ledger reconciliation.

    ``missing`` is asserted ONLY when ``plan_dir`` itself exists but holds no
    matching folder — a genuinely archived/removed plan. A nonexistent or
    unscannable ``plan_dir`` (wrong config, transient IO error) reports
    ``unreadable``, which never retires anything: retirement is persisted, so
    a misresolved directory must not wipe the ledger on the first consult.
    """
    if not plan_dir.is_dir():
        return _STATE_UNREADABLE
    try:
        folders = sorted(plan_dir.glob(f"{plan_number}-*"))
    except OSError as e:
        logger.warning("goal_ledger: cannot scan plan dir %s: %s", plan_dir, e)
        return _STATE_UNREADABLE
    for folder in folders:
        plan_md = folder / _PLAN_MD_FILENAME
        if not plan_md.is_file():
            continue
        try:
            text = plan_md.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("goal_ledger: cannot read %s: %s", plan_md, e)
            return _STATE_UNREADABLE
        doc = PlanDoc.parse(text)
        if doc.status is None:
            return _STATE_UNREADABLE
        if doc.status in TERMINAL_STATUSES:
            return _STATE_TERMINAL
        if doc.status is PlanStatus.IN_PROGRESS:
            return _STATE_IN_PROGRESS
        return _STATE_OTHER
    return _STATE_MISSING


class GoalLedger:
    """Read/write access to the goal ledger file. All public methods fail open."""

    def __init__(self, path: Path) -> None:
        self._path = path

    # ── locking ────────────────────────────────────────────────────────────

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold an exclusive flock over the whole read-modify-write.

        Fail-open: if the lock file cannot be created or locked, proceed
        unlocked (logged) — a degraded write beats breaking the tool call.
        The file handle is closed in the finally block.
        """
        lock_path = self._path.parent / f"{self._path.name}{_LOCK_SUFFIX}"
        lock_fd: int | None = None
        locked = False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, _LOCK_FILE_MODE)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            locked = True
        except OSError as e:
            logger.warning("goal_ledger: proceeding without lock on %s: %s", lock_path, e)
        try:
            yield
        finally:
            if lock_fd is not None:
                if locked:
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    except OSError as e:
                        logger.warning("goal_ledger: unlock failed on %s: %s", lock_path, e)
                os.close(lock_fd)

    # ── persistence ────────────────────────────────────────────────────────

    def entries(self) -> list[GoalLedgerEntry]:
        """Load all entries; an unreadable or corrupt ledger yields ``[]``."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("goal_ledger: unreadable ledger %s: %s", self._path, e)
            return []
        raw_entries = raw.get(_ENTRIES_KEY) if isinstance(raw, dict) else None
        if not isinstance(raw_entries, list):
            logger.warning("goal_ledger: malformed ledger %s; treating as empty", self._path)
            return []
        parsed: list[GoalLedgerEntry] = []
        for item in raw_entries:
            entry = self._parse_entry(item)
            if entry is not None:
                parsed.append(entry)
        return parsed

    @staticmethod
    def _parse_entry(item: Any) -> GoalLedgerEntry | None:
        if not isinstance(item, dict):
            return None
        try:
            return GoalLedgerEntry(
                plan_number=str(item["plan_number"]),
                session_id=str(item.get("session_id", "")),
                rendered_line=str(item.get("rendered_line", "")),
                emitted_at=float(item.get("emitted_at", 0.0)),
                displaced_by=_optional_str(item.get("displaced_by")),
                displaced_at=_optional_float(item.get("displaced_at")),
                retired_at=_optional_float(item.get("retired_at")),
                retired_reason=_optional_str(item.get("retired_reason")),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("goal_ledger: skipping malformed entry: %s", e)
            return None

    def _save(self, entries: list[GoalLedgerEntry]) -> None:
        """Atomically persist ``entries`` (pruned); failures are logged only.

        The tmp filename carries a uuid, not a pid: hook events run on
        concurrent THREADS of the one daemon process, so a pid-only suffix
        would let two writers share a tmp path and corrupt each other.
        """
        pruned = self._prune(entries)
        payload = {_ENTRIES_KEY: [asdict(e) for e in pruned]}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.parent / f".{self._path.name}.{uuid.uuid4().hex}.tmp"
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(self._path)
        except OSError as e:
            logger.warning("goal_ledger: failed to write %s: %s", self._path, e)

    @staticmethod
    def _prune(entries: list[GoalLedgerEntry]) -> list[GoalLedgerEntry]:
        """Bound the ledger: drop oldest RETIRED entries first, then oldest.

        Victims are removed by IDENTITY, never by equality — two entries with
        identical field values must not cause the wrong one to be dropped.
        """
        if len(entries) <= _MAX_ENTRIES:
            return entries
        retired_oldest_first = sorted(
            (e for e in entries if e.retired_at is not None), key=lambda e: e.emitted_at
        )
        excess = len(entries) - _MAX_ENTRIES
        victim_ids = {id(victim) for victim in retired_oldest_first[:excess]}
        keep = [e for e in entries if id(e) not in victim_ids]
        if len(keep) > _MAX_ENTRIES:
            keep = sorted(keep, key=lambda e: e.emitted_at)[-_MAX_ENTRIES:]
        return keep

    # ── reconciliation ─────────────────────────────────────────────────────

    def _reconcile(
        self, entries: list[GoalLedgerEntry], plan_dir: Path
    ) -> tuple[bool, dict[str, str]]:
        """Retire entries whose plan is terminal or gone.

        Returns ``(changed, states)`` where ``states`` maps each visited plan
        number to its computed state, so callers never re-derive it.
        """
        changed = False
        now = time.time()
        states: dict[str, str] = {}
        for entry in entries:
            if entry.plan_number not in states:
                states[entry.plan_number] = _plan_state(plan_dir, entry.plan_number)
            if entry.retired_at is not None:
                continue
            state = states[entry.plan_number]
            if state == _STATE_MISSING:
                entry.retired_at = now
                entry.retired_reason = RETIRED_ARCHIVED
                changed = True
            elif state == _STATE_TERMINAL:
                entry.retired_at = now
                entry.retired_reason = RETIRED_TERMINAL_STATUS
                changed = True
        return changed, states

    # ── public API ─────────────────────────────────────────────────────────

    def record_emission(
        self, session_id: str, plan_number: str, rendered_line: str, plan_dir: Path
    ) -> list[str]:
        """Record one goal emission; return plan numbers it newly displaces.

        A displaced plan is a DIFFERENT ledgered plan that is still
        ``In Progress`` and not yet marked displaced — its ``/goal`` condition
        has been overwritten while its work remains unfinished. A re-emission
        for the same plan (e.g. the new-session re-fire) refreshes the
        existing live entry rather than double-counting it.
        """
        with self._locked():
            now = time.time()
            entries = self.entries()
            _, states = self._reconcile(entries, plan_dir)

            displaced: list[str] = []
            for entry in entries:
                if (
                    entry.plan_number != plan_number
                    and entry.retired_at is None
                    and entry.displaced_by is None
                    and states.get(entry.plan_number) == _STATE_IN_PROGRESS
                ):
                    entry.displaced_by = plan_number
                    entry.displaced_at = now
                    displaced.append(entry.plan_number)

            existing = next(
                (e for e in entries if e.plan_number == plan_number and e.retired_at is None),
                None,
            )
            if existing is not None:
                existing.session_id = session_id
                existing.rendered_line = rendered_line
                existing.emitted_at = now
                # A re-emission re-arms the /goal slot for this plan.
                existing.displaced_by = None
                existing.displaced_at = None
            else:
                entries.append(
                    GoalLedgerEntry(
                        plan_number=plan_number,
                        session_id=session_id,
                        rendered_line=rendered_line,
                        emitted_at=now,
                    )
                )
            self._save(entries)
        return sorted(displaced)

    def live_plan_numbers(self, plan_dir: Path) -> list[str]:
        """Return ledgered plans still ``In Progress``; persists retirements.

        Displaced-but-unfinished plans ARE included — they are exactly the
        goals the single ``/goal`` slot has forgotten and the Stop handler
        must still defend.
        """
        with self._locked():
            entries = self.entries()
            changed, states = self._reconcile(entries, plan_dir)
            if changed:
                self._save(entries)
        live = {
            e.plan_number
            for e in entries
            if e.retired_at is None and states.get(e.plan_number) == _STATE_IN_PROGRESS
        }
        return sorted(live)
