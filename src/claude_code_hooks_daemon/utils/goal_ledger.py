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
- **Atomic writes**: tmp-file + ``replace``, same idiom as the goal signal.
- **Bounded**: retired entries are pruned once the ledger exceeds a cap.
"""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

# Ledger file, placed under ``ProjectContext.daemon_untracked_dir()`` by callers.
LEDGER_FILENAME: Final[str] = "goal-ledger.json"

_ENTRIES_KEY: Final[str] = "entries"
_MAX_ENTRIES: Final[int] = 100

# Plan-status vocabulary (mirrors the plan QA status enum).
_STATUS_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\*\*Status\*\*:\s*(?P<status>[A-Za-z ]+?)\s*$", re.MULTILINE
)
_STATUS_IN_PROGRESS: Final[str] = "In Progress"
_TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {"Complete", "Completed", "Cancelled", "Superseded"}
)
_PLAN_MD_FILENAME: Final[str] = "PLAN.md"

# Retirement reasons recorded on an entry.
RETIRED_TERMINAL_STATUS: Final[str] = "terminal-status"
RETIRED_ARCHIVED: Final[str] = "archived"

# Sentinel statuses returned by ``_plan_status``.
_PLAN_MISSING: Final[str] = "missing"
_PLAN_UNREADABLE: Final[str] = "unreadable"


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
    extra: dict[str, Any] = field(default_factory=dict)


def _plan_status(plan_dir: Path, plan_number: str) -> str:
    """Return the plan's current status token, or a sentinel.

    Looks for ``{plan_number}-*/PLAN.md`` directly under ``plan_dir`` (an
    archived plan lives in a subdirectory such as ``Completed/`` and is
    therefore reported as ``missing`` here, which retires it).
    """
    try:
        folders = sorted(plan_dir.glob(f"{plan_number}-*"))
    except OSError as e:
        logger.warning("goal_ledger: cannot scan plan dir %s: %s", plan_dir, e)
        return _PLAN_UNREADABLE
    for folder in folders:
        plan_md = folder / _PLAN_MD_FILENAME
        if not plan_md.is_file():
            continue
        try:
            text = plan_md.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("goal_ledger: cannot read %s: %s", plan_md, e)
            return _PLAN_UNREADABLE
        match = _STATUS_LINE_RE.search(text)
        if match is not None:
            return match.group("status")
        return _PLAN_UNREADABLE
    return _PLAN_MISSING


class GoalLedger:
    """Read/write access to the goal ledger file. All public methods fail open."""

    def __init__(self, path: Path) -> None:
        self._path = path

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
                displaced_by=item.get("displaced_by"),
                displaced_at=item.get("displaced_at"),
                retired_at=item.get("retired_at"),
                retired_reason=item.get("retired_reason"),
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("goal_ledger: skipping malformed entry: %s", e)
            return None

    def _save(self, entries: list[GoalLedgerEntry]) -> None:
        """Atomically persist ``entries`` (pruned); failures are logged only."""
        pruned = self._prune(entries)
        payload = {_ENTRIES_KEY: [self._entry_to_dict(e) for e in pruned]}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.parent / f".{self._path.name}.{os.getpid()}.tmp"
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            tmp_path.replace(self._path)
        except OSError as e:
            logger.warning("goal_ledger: failed to write %s: %s", self._path, e)

    @staticmethod
    def _entry_to_dict(entry: GoalLedgerEntry) -> dict[str, Any]:
        data = asdict(entry)
        data.pop("extra", None)
        return data

    @staticmethod
    def _prune(entries: list[GoalLedgerEntry]) -> list[GoalLedgerEntry]:
        """Bound the ledger: drop oldest RETIRED entries first, then oldest."""
        if len(entries) <= _MAX_ENTRIES:
            return entries
        retired = sorted(
            (e for e in entries if e.retired_at is not None), key=lambda e: e.emitted_at
        )
        keep = list(entries)
        for victim in retired:
            if len(keep) <= _MAX_ENTRIES:
                break
            keep.remove(victim)
        if len(keep) > _MAX_ENTRIES:
            keep = sorted(keep, key=lambda e: e.emitted_at)[-_MAX_ENTRIES:]
        return keep

    # ── reconciliation ─────────────────────────────────────────────────────

    def _reconcile(self, entries: list[GoalLedgerEntry], plan_dir: Path) -> bool:
        """Retire entries whose plan is terminal or gone. Returns True on change."""
        changed = False
        now = time.time()
        for entry in entries:
            if entry.retired_at is not None:
                continue
            status = _plan_status(plan_dir, entry.plan_number)
            if status == _PLAN_MISSING:
                entry.retired_at = now
                entry.retired_reason = RETIRED_ARCHIVED
                changed = True
            elif status in _TERMINAL_STATUSES:
                entry.retired_at = now
                entry.retired_reason = RETIRED_TERMINAL_STATUS
                changed = True
        return changed

    # ── public API ─────────────────────────────────────────────────────────

    def record_emission(
        self, session_id: str, plan_number: str, rendered_line: str, plan_dir: Path
    ) -> list[str]:
        """Record one goal emission; return plan numbers it newly displaces.

        A displaced plan is a DIFFERENT ledgered plan that is still
        ``In Progress`` and not yet marked displaced — its ``/goal`` condition
        has just been overwritten while its work remains unfinished. A
        re-emission for the same plan (e.g. the new-session re-fire) refreshes
        the existing live entry rather than double-counting it.
        """
        now = time.time()
        entries = self.entries()
        self._reconcile(entries, plan_dir)

        displaced: list[str] = []
        for entry in entries:
            if (
                entry.plan_number != plan_number
                and entry.retired_at is None
                and entry.displaced_by is None
                and _plan_status(plan_dir, entry.plan_number) == _STATUS_IN_PROGRESS
            ):
                entry.displaced_by = plan_number
                entry.displaced_at = now
                displaced.append(entry.plan_number)

        existing = next(
            (e for e in entries if e.plan_number == plan_number and e.retired_at is None), None
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
        entries = self.entries()
        if self._reconcile(entries, plan_dir):
            self._save(entries)
        live = {
            e.plan_number
            for e in entries
            if e.retired_at is None and _plan_status(plan_dir, e.plan_number) == _STATUS_IN_PROGRESS
        }
        return sorted(live)
