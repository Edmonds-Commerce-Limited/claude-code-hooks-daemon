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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.plan_qa.model import TERMINAL_STATUSES, PlanDoc, PlanStatus

logger = logging.getLogger(__name__)

# Ledger file, placed under ``ProjectContext.daemon_untracked_dir()`` by callers.
LEDGER_FILENAME: Final[str] = "goal-ledger.json"
_LOCK_SUFFIX: Final[str] = ".lock"
# Owner read/write only — consistent with the daemon's private-state posture.
_PRIVATE_FILE_MODE: Final[int] = 0o600
_LOCK_FILE_MODE: Final[int] = _PRIVATE_FILE_MODE

_ENTRIES_KEY: Final[str] = "entries"
# RV3-n2: sessions that have EVER performed a real emission
# (record_emission), tracked as its OWN ledger-wide, bounded, order-
# preserving list -- independent of any per-entry field, so it survives
# both record_emission overwriting an entry's single session_id (the
# latest re-flipper wins there) and _prune dropping the entry entirely.
# Deliberately NOT touched by reassert_session (see session_has_entries).
_EVER_RECORDED_KEY: Final[str] = "ever_recorded_sessions"
_MAX_ENTRIES: Final[int] = 100
# Same order of magnitude as _MAX_ENTRIES, but a distinct cap: one SESSION
# can persist across many entries over the ledger's lifetime, so bounding
# it to the entry cap would undercount long-lived, frequently-flipping
# sessions.
_MAX_EVER_RECORDED_SESSIONS: Final[int] = 200
# RV3-m5: bounds ONE entry's owner set, distinct from _MAX_ENTRIES above
# (which bounds the number of ENTRIES). A rolling ledger plan touched by
# dozens of teammates can otherwise accumulate owners without bound, each
# one a combined-signal write on every later terminal transition.
_MAX_OWNERS_PER_ENTRY: Final[int] = 50

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
    """One recorded goal emission and its lifecycle markers.

    ``session_id`` names the session that produced the most recent real
    emission (:meth:`GoalLedger.record_emission`) — display/debugging only.
    Ownership for every read that decides "does THIS session have a stake
    in this plan's goal" is ``sessions`` instead (review RV-M1): the set of
    every session ever handed this plan's goal, additive from both a real
    emission and a resumed-session reassertion. A single-valued transfer
    (the pre-fix shape) let a later session's reassertion strip the
    original flipping session of the only fact that let it retract its OWN
    signal when the plan went terminal; additive membership means BOTH
    sessions keep their claim, and a terminal write can refresh/clear every
    one of them, not just whichever session's write happened to trigger it.
    """

    plan_number: str
    session_id: str
    rendered_line: str
    emitted_at: float
    displaced_by: str | None = None
    displaced_at: float | None = None
    retired_at: float | None = None
    retired_reason: str | None = None
    sessions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LivePlanRef:
    """One still-live ledgered plan, resolved against the plan directory.

    Feeds ``goal_injection``'s combined-``/goal`` renderer (Plan 00299),
    which needs the plan's title (parsed from ``plan_text``) and folder to
    build a rendered line — without a second directory scan of its own.
    """

    plan_number: str
    plan_folder: str
    plan_text: str


def _add_bounded(items: list[str], value: str, cap: int) -> None:
    """Append ``value`` to ``items`` if absent, evicting the OLDEST entry
    (index 0) when doing so would exceed ``cap``. Shared by every bounded,
    order-preserving membership list this module grows: RV3-m5's per-entry
    ``sessions`` owner set, and RV3-n2's ledger-wide ``ever_recorded_sessions``.
    """
    if value in items:
        return
    if len(items) >= cap:
        del items[0]
    items.append(value)


def _add_owner(sessions: list[str], session_id: str) -> None:
    """Append ``session_id`` to ``sessions`` if absent, with FIFO eviction
    of the OLDEST owner at :data:`_MAX_OWNERS_PER_ENTRY` (RV3-m5). Shared by
    :meth:`GoalLedger.record_emission` and :meth:`GoalLedger.reassert_session`
    -- both grow the same additive ``sessions`` set and both need the same
    bound.
    """
    _add_bounded(sessions, session_id, _MAX_OWNERS_PER_ENTRY)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _candidate_folders(plan_dir: Path, plan_number: str) -> list[Path] | None:
    """Sorted ``<plan_number>-*`` folders under ``plan_dir``, or None on OSError."""
    try:
        return sorted(plan_dir.glob(f"{plan_number}-*"))
    except OSError as e:
        logger.warning("goal_ledger: cannot scan plan dir %s: %s", plan_dir, e)
        return None


def _find_plan_md_text(plan_dir: Path, plan_number: str) -> tuple[str, str] | None:
    """Return ``(folder_name, plan_md_text)`` for the first readable match.

    Used by :meth:`GoalLedger.live_plan_refs` to resolve a live plan's
    folder/title source without a second directory scan; unreadable
    candidates are skipped (mirrors ``_plan_state``'s tolerance).
    """
    if not plan_dir.is_dir():
        return None
    folders = _candidate_folders(plan_dir, plan_number)
    if folders is None:
        return None
    for folder in folders:
        plan_md = folder / _PLAN_MD_FILENAME
        if not plan_md.is_file():
            continue
        try:
            text = plan_md.read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            # RV3-m8: ValueError catches read_text's UnicodeDecodeError too
            # (a non-UTF-8 PLAN.md), the same tolerance review RV-m5 gave
            # the ledger file itself -- a binary/corrupt sibling plan must
            # not crash a live plan's own refresh.
            logger.warning("goal_ledger: cannot read %s: %s", plan_md, e)
            continue
        return folder.name, text
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
    folders = _candidate_folders(plan_dir, plan_number)
    if folders is None:
        return _STATE_UNREADABLE
    for folder in folders:
        plan_md = folder / _PLAN_MD_FILENAME
        if not plan_md.is_file():
            continue
        try:
            text = plan_md.read_text(encoding="utf-8")
        except (OSError, ValueError) as e:
            # RV3-m8: same ValueError tolerance as _find_plan_md_text above.
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

    def _load_raw(self) -> Any:
        """Parse the raw ledger JSON (any shape); ``None`` on any read/parse
        failure, including a missing file.

        Review RV-m5: ``ValueError`` (not just ``json.JSONDecodeError``) is
        caught alongside ``OSError`` so a ledger file that is valid bytes but
        not valid UTF-8 (``read_text``'s ``UnicodeDecodeError``, itself a
        ``ValueError`` subclass) is treated as corrupt like any other
        unreadable ledger, rather than raising past this fail-open API. This
        repo runs the daemon in ``strict_mode``, where an uncaught exception
        here would DENY every PLAN.md edit with a system error.

        Shared by :meth:`entries` and :meth:`_parse_ever_recorded` (RV3-n2)
        so a caller needing BOTH reads the file once, not twice.
        """
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            logger.warning("goal_ledger: unreadable ledger %s: %s", self._path, e)
            return None

    def entries(self) -> list[GoalLedgerEntry]:
        """Load all entries; an unreadable or corrupt ledger yields ``[]``."""
        return self._parse_entries(self._load_raw())

    def _parse_entries(self, raw: Any) -> list[GoalLedgerEntry]:
        # ``raw is None`` means _load_raw already handled (and, for a real
        # read/parse error, already logged) the failure -- a missing file is
        # the ordinary "no ledger written yet" case and must stay silent, so
        # only a SUCCESSFULLY parsed but wrongly-shaped payload warns here.
        if raw is None:
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
    def _parse_ever_recorded(raw: Any) -> list[str]:
        """RV3-n2: the ledger-wide "ever recorded" session list from a raw
        parse. No warning on absence -- an old ledger written before this
        key existed, or a brand-new one, is not malformed.
        """
        if not isinstance(raw, dict):
            return []
        raw_sessions = raw.get(_EVER_RECORDED_KEY)
        if not isinstance(raw_sessions, list):
            return []
        return [str(s) for s in raw_sessions]

    @staticmethod
    def _parse_entry(item: Any) -> GoalLedgerEntry | None:
        if not isinstance(item, dict):
            return None
        try:
            session_id = str(item.get("session_id", ""))
            raw_sessions = item.get("sessions")
            if isinstance(raw_sessions, list) and raw_sessions:
                sessions = [str(s) for s in raw_sessions]
            elif session_id:
                # Pre-RV-M1 ledger on disk: back-fill from the single owner
                # field so an entry written before this schema change is not
                # silently treated as ownerless.
                sessions = [session_id]
            else:
                sessions = []
            return GoalLedgerEntry(
                plan_number=str(item["plan_number"]),
                session_id=session_id,
                rendered_line=str(item.get("rendered_line", "")),
                emitted_at=float(item.get("emitted_at", 0.0)),
                displaced_by=_optional_str(item.get("displaced_by")),
                displaced_at=_optional_float(item.get("displaced_at")),
                retired_at=_optional_float(item.get("retired_at")),
                retired_reason=_optional_str(item.get("retired_reason")),
                sessions=sessions,
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("goal_ledger: skipping malformed entry: %s", e)
            return None

    def _save(self, entries: list[GoalLedgerEntry], ever_recorded: list[str]) -> None:
        """Atomically persist ``entries`` (pruned) and ``ever_recorded``
        (RV3-n2, defensively capped here too); failures are logged only.

        The tmp filename carries a uuid, not a pid: hook events run on
        concurrent THREADS of the one daemon process, so a pid-only suffix
        would let two writers share a tmp path and corrupt each other.
        """
        pruned = self._prune(entries)
        payload = {
            _ENTRIES_KEY: [asdict(e) for e in pruned],
            _EVER_RECORDED_KEY: ever_recorded[-_MAX_EVER_RECORDED_SESSIONS:],
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.parent / f".{self._path.name}.{uuid.uuid4().hex}.tmp"
            # Owner-only, matching the 0600 lock file and the daemon's
            # private-state posture (v3.55.0 release code review).
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _PRIVATE_FILE_MODE)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload))
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
            raw = self._load_raw()
            entries = self._parse_entries(raw)
            ever_recorded = self._parse_ever_recorded(raw)
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
                _add_owner(existing.sessions, session_id)
            else:
                entries.append(
                    GoalLedgerEntry(
                        plan_number=plan_number,
                        session_id=session_id,
                        rendered_line=rendered_line,
                        emitted_at=now,
                        sessions=[session_id],
                    )
                )
            if session_id:
                _add_bounded(ever_recorded, session_id, _MAX_EVER_RECORDED_SESSIONS)
            self._save(entries, ever_recorded)
        return sorted(displaced)

    def has_live_entry(self, session_id: str, plan_number: str) -> bool:
        """True when a not-yet-retired entry exists that THIS session owns.

        Read-only, no reconciliation, no lock. Review M2: a caller deciding
        whether ITS session is responsible for a plan needs an answer that
        survives a process restart -- an in-memory latch does not, since a
        fresh process starts with none. The persisted ledger does: an entry
        written before a restart is still on disk, unaffected by the
        restart, so this is the question to ask instead of any in-memory
        state.

        Review RV-M1: ownership is membership in ``sessions``, not equality
        against the single ``session_id`` field -- a session that later
        reasserted the SAME plan must not make the original flipping
        session's own membership disappear.
        """
        return any(
            e.plan_number == plan_number and session_id in e.sessions and e.retired_at is None
            for e in self.entries()
        )

    def owning_sessions(self, plan_number: str) -> list[str]:
        """Every session with a stake in this plan's goal right now.

        Review RV-M1/RV-m2: feeds a terminal-write caller that must refresh
        or clear EACH owning session's own signal, not just whichever
        session's write happened to trigger the check -- the pre-fix
        single-owner design meant a session that reasserted ownership away
        from the original flipping session left that session's own goal
        stuck forever. An entry retired a moment ago with
        ``RETIRED_TERMINAL_STATUS`` is included too (not just a still-live
        one): a concurrent reconciliation racing between this plan's
        terminal write landing on disk and this read must not silently
        suppress every owning session's retraction just because it won the
        race to reconcile first.

        RV3-M1: answers from the LIVE entry when one exists (at most one
        ever does -- ``record_emission`` only reuses a not-yet-retired
        entry, so a reopened plan appends a NEW one rather than reviving
        the old), or else the MOST RECENTLY retired terminal entry.
        ``record_emission`` appends a fresh entry every time a retired plan
        is reopened, so a plan with more than one completed lifecycle has
        several retired entries for the same ``plan_number`` -- answering
        from the first one in the list handed a reopened-and-recompleted
        plan's retraction to the ORIGINAL session instead of whoever
        actually reopened and recompleted it.
        """
        matches = [e for e in self.entries() if e.plan_number == plan_number]
        live = next((e for e in matches if e.retired_at is None), None)
        if live is not None:
            return list(live.sessions)
        retired_terminal = [e for e in matches if e.retired_reason == RETIRED_TERMINAL_STATUS]
        if not retired_terminal:
            return []
        most_recent = max(retired_terminal, key=lambda e: e.retired_at or 0.0)
        return list(most_recent.sessions)

    def is_plan_live(self, plan_number: str) -> bool:
        """True when a not-yet-retired entry exists for this plan number.

        Read-only, no reconciliation, no lock -- same posture as
        :meth:`has_live_entry`, but ownership-independent: RV3-m6's Write
        flip detector needs "has ANYONE already ledgered this plan as
        started", which git HEAD cannot answer when the flip landed on
        disk before it was committed.
        """
        return any(e.plan_number == plan_number and e.retired_at is None for e in self.entries())

    def session_has_entries(self, session_id: str) -> bool:
        """True when the ledger has EVER recorded a real emission
        (:meth:`record_emission`) for this session.

        Review M3: distinguishes a genuinely NEW session (no entries at
        all, so nothing here has told it about any goal yet) from a session
        that already went through the injection flow itself (which does not
        need re-arming — it already has its own live signal).

        RV3-n2: answered from a ledger-wide, bounded ``ever_recorded_sessions``
        set (:data:`_EVER_RECORDED_KEY`), not any per-entry field. The
        previous implementation read the single ``session_id`` field on any
        entry, which is not actually what it means: ``record_emission``
        OVERWRITES that field with whoever re-emits for the SAME plan next
        (so a session whose plan was later re-flipped by someone else wrongly
        counted as new again), and ``_prune`` can drop the entry out of the
        ledger entirely once it exceeds its cap (silently losing the record
        along with it). The durable set survives both.

        Deliberately NOT populated by :meth:`reassert_session` -- a session
        that has only ever been ADDED to another plan's ownership, without
        ever performing a real emission of its own, is not "new" in the
        sense this method exists to detect (Plan 00269's own motivating
        case: nothing here should stop it from also becoming a stakeholder
        of a second, unrelated live plan it is asked to track).
        """
        return session_id in self._parse_ever_recorded(self._load_raw())

    def reassert_session(self, session_id: str, plan_number: str) -> bool:
        """Add ``session_id`` to a still-live entry's set of owning sessions.

        Review M3: restores Plan 00269's "the goal survives a session
        restart" intent for a session that resumes an already-ledgered plan
        without a real flip, WITHOUT the side effects a full
        :meth:`record_emission` would have — no displacement of any OTHER
        live plan, because none of the bookkeeping that computes
        displacement runs here at all. Returns ``True`` (and updates the
        entry) only when a not-yet-retired entry for ``plan_number`` exists;
        ``False`` means there is nothing this ledger can vouch for, and the
        caller must not treat the touch as a resumed goal.

        Review RV-M1: this is ADDITIVE, not a transfer — ``session_id`` is
        added to ``sessions`` alongside whoever already owns the entry,
        never replacing them. A transfer (the pre-fix shape) broke the
        original flipping session's own retraction the moment a second
        session touched the plan: ``has_live_entry``'s ownership check
        stopped matching it, so its own goal signal could never be cleared
        when the plan went terminal. The idempotent no-op here (calling this
        again for a session already in ``sessions``) is deliberate: the
        caller latches in memory to avoid the redundant write, not this
        method, which stays simple and safe to call repeatedly.
        """
        with self._locked():
            raw = self._load_raw()
            entries = self._parse_entries(raw)
            existing = next(
                (e for e in entries if e.plan_number == plan_number and e.retired_at is None),
                None,
            )
            if existing is None:
                return False
            _add_owner(existing.sessions, session_id)
            existing.emitted_at = time.time()
            # RV3-n2: ever_recorded is preserved UNCHANGED here -- a
            # reassertion is deliberately not a "real emission" (see
            # session_has_entries).
            self._save(entries, self._parse_ever_recorded(raw))
        return True

    def live_plan_numbers(self, plan_dir: Path) -> list[str]:
        """Return ledgered plans still ``In Progress``; persists retirements.

        Displaced-but-unfinished plans ARE included — they are exactly the
        goals the single ``/goal`` slot has forgotten and the Stop handler
        must still defend.
        """
        with self._locked():
            raw = self._load_raw()
            entries = self._parse_entries(raw)
            changed, states = self._reconcile(entries, plan_dir)
            if changed:
                self._save(entries, self._parse_ever_recorded(raw))
        live = {
            e.plan_number
            for e in entries
            if e.retired_at is None and states.get(e.plan_number) == _STATE_IN_PROGRESS
        }
        return sorted(live)

    def live_plan_refs(self, plan_dir: Path) -> list[LivePlanRef]:
        """Like :meth:`live_plan_numbers`, resolved with folder + PLAN.md text.

        A live plan number whose folder/PLAN.md cannot be re-read (deleted
        between reconciliation and this call, permission error) is skipped
        rather than raising — the caller renders a combined signal from
        whatever it CAN resolve; a single unreadable plan must not blank
        out every other still-live plan's goal.
        """
        refs: list[LivePlanRef] = []
        for plan_number in self.live_plan_numbers(plan_dir):
            found = _find_plan_md_text(plan_dir, plan_number)
            if found is None:
                continue
            folder, text = found
            refs.append(LivePlanRef(plan_number=plan_number, plan_folder=folder, plan_text=text))
        return refs
