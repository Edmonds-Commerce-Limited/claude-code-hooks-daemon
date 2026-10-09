"""Plan fact-check bookkeeping: what changed in a plan since it was last checked.

Plan 00480 Tasks 4.1/4.2. The ``plan_fact_check_feed`` handler feeds the
debouncer; when a plan's edits go quiet, :func:`process_quiet_plan` runs.

**Delivery.** The daemon runs no model (Plan 00480 open question 1, option a).
The debounce fire (:func:`process_quiet_plan`) dispatches nothing: it computes
the diff since the last fact-checked content and stores it as a *pending
fact-check* record (:class:`PendingFactCheck`). The next hook event calls
:func:`deliver_pending`, which hands the session an instruction to dispatch the
``plan-fact-checker`` agent with that diff and keeps the record as an *offered*
one. The daemon cannot see whether the instruction reached the session, so the
"last checked" content advances only in :func:`confirm_dispatch`, when the
session is seen dispatching the agent on that diff. An offer nobody acts on is
re-offered after :data:`REOFFER_AFTER_SECONDS`, up to :data:`MAX_OFFERS` times,
and is then dropped without advancing anything, so the content stays owed.

**First sight and corrections.** A plan with no checked content yet records a
baseline and owes nothing. A small edit within :data:`CORRECTION_WINDOW_SECONDS`
of a confirmed check is taken to be a correction of that check's findings: it is
absorbed into the checked content instead of owing the next check.

State lives under the daemon's untracked directory, one set of JSON files per
plan folder (``<folder>.checked.json``, ``.pending.json`` and ``.offered.json``),
written atomically (tmp + ``Path.replace``).

The tracked content of a plan is its markdown files, excluding the
``subagent-reports/`` tree (the fact checker's own output would otherwise
re-trigger the check forever) and ``JOURNAL/`` (an append-only narrative, not a
set of claims).
"""

import difflib
import hashlib
import json
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Final

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_containment import path_relative_to
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

STATE_SUBDIR: Final[str] = "plan-fact-check"
CHECKED_SUFFIX: Final[str] = ".checked.json"
PENDING_SUFFIX: Final[str] = ".pending.json"
OFFERED_SUFFIX: Final[str] = ".offered.json"
UNREADABLE_SUFFIX: Final[str] = ".unreadable"
DIFF_SUFFIX: Final[str] = ".diff"
FACT_CHECKER_AGENT: Final[str] = "plan-fact-checker"
ARCHIVE_DIR: Final[str] = "Completed"

#: An offer nobody confirmed is offered again after this many seconds.
REOFFER_AFTER_SECONDS: Final[float] = 300.0
#: Offers made for one record before it is dropped (the content stays owed).
MAX_OFFERS: Final[int] = 3
#: A small edit this soon after a confirmed check is a correction, not a new claim.
CORRECTION_WINDOW_SECONDS: Final[float] = 600.0
#: Added plus removed lines above which an edit is never taken for a correction.
CORRECTION_MAX_CHANGED_LINES: Final[int] = 20

#: Directory names inside a plan folder whose files are never fact-checked.
EXCLUDED_SEGMENTS: Final[frozenset[str]] = frozenset({"subagent-reports", "JOURNAL"})
TRACKED_SUFFIX: Final[str] = ".md"

_FOLDER_PATTERN_TEMPLATE: Final[str] = r"{plan_dir}/(?P<folder>\d+-[^/]+)/(?P<rest>.+)$"


@dataclass(frozen=True)
class PlanFolderMatch:
    """A path that belongs to a tracked document of one plan folder."""

    folder: str
    plan_root: Path


def plan_folder_match(file_path: str, plan_dir: str) -> PlanFolderMatch | None:
    """The plan folder ``file_path`` is a tracked document of, or ``None``.

    Args:
        file_path: Path of a written file (absolute in practice).
        plan_dir: Configured plan directory, e.g. ``CLAUDE/Plan``.

    Returns:
        A match for ``<plan_dir>/<digits>-<name>/<tracked document>``. Archived
        plans (``<plan_dir>/Completed/...``) never match, because the folder
        must follow ``plan_dir`` directly, and excluded subtrees and non-markdown
        files are not tracked documents.
    """
    normalized = file_path.replace("\\", "/")
    pattern = re.compile(_FOLDER_PATTERN_TEMPLATE.format(plan_dir=re.escape(plan_dir)))
    match = pattern.search(normalized)
    if match is None:
        return None
    rest = PurePosixPath(match.group("rest"))
    if rest.suffix != TRACKED_SUFFIX or EXCLUDED_SEGMENTS.intersection(rest.parts[:-1]):
        return None
    folder = match.group("folder")
    plan_root = Path(normalized[: match.start("rest")].rstrip("/"))
    return PlanFolderMatch(folder=folder, plan_root=plan_root)


def snapshot_plan(plan_root: Path) -> dict[str, str]:
    """Relative path -> text of every tracked document under ``plan_root``."""
    snapshot: dict[str, str] = {}
    for path in sorted(plan_root.rglob(f"*{TRACKED_SUFFIX}")):
        relative = path_relative_to(path, plan_root)
        if EXCLUDED_SEGMENTS.intersection(relative.parts[:-1]) or not path.is_file():
            continue
        snapshot[relative.as_posix()] = path.read_text(encoding="utf-8", errors="replace")
    return snapshot


def snapshot_hash(files: Mapping[str, str]) -> str:
    """Stable SHA-256 over file names and contents."""
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[name].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def snapshot_diff(old: Mapping[str, str], new: Mapping[str, str]) -> str:
    """Unified diff of ``new`` against ``old``, over the union of file names."""
    chunks: list[str] = []
    for name in sorted(set(old) | set(new)):
        before = old.get(name, "").splitlines(keepends=True)
        after = new.get(name, "").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(before, after, fromfile=f"a/{name}", tofile=f"b/{name}"))
    return "".join(chunks)


class PlanFactCheckStateError(Exception):
    """A state file exists but cannot be trusted; delete it to reset that plan."""


@dataclass(frozen=True)
class CheckedSnapshot:
    """The content of a plan the last time it was fact-checked."""

    content_hash: str
    files: dict[str, str]
    checked_at: float | None = None


@dataclass(frozen=True)
class PendingFactCheck:
    """A fact-check that is owed but not yet delivered.

    Attributes:
        folder: The plan folder name.
        content_hash: Hash of the plan content the diff leads to.
        diff: Unified diff since the last fact-checked content.
        trigger_count: Edits coalesced into the debounce fire.
        recorded_at: Wall-clock seconds when the record was stored.
        plan_root: The plan folder on disk, so delivery can name its documents.
        files: The plan content the diff leads to; becomes the checked content on confirmation.
        offers: How many times the instruction has been handed to the session.
        offered_at: Wall-clock seconds of the latest offer (0.0 while only pending).
    """

    folder: str
    content_hash: str
    diff: str
    trigger_count: int
    recorded_at: float
    plan_root: str
    files: dict[str, str]
    offers: int = 0
    offered_at: float = 0.0


class PlanFactCheckState:
    """Per-plan state files under one directory."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = state_dir

    @property
    def state_dir(self) -> Path:
        """The directory holding every state file."""
        return self._dir

    def _path(self, folder: str, suffix: str) -> Path:
        if "/" in folder or folder.startswith("."):
            raise ValueError(f"not a plan folder name: {folder!r}")
        return self._dir / f"{folder}{suffix}"

    def _write(self, path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = unique_temp_path(path)
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)

    def _read(self, path: Path) -> dict[str, object]:
        """Parse one state file; raises :class:`PlanFactCheckStateError` if corrupt."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PlanFactCheckStateError(f"unreadable state {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise PlanFactCheckStateError(f"state {path} is not a JSON object")
        return data

    def read_checked(self, folder: str) -> CheckedSnapshot | None:
        """The last fact-checked content of ``folder``; ``None`` if none was recorded.

        Raises:
            PlanFactCheckStateError: If the state file exists but is corrupt.
        """
        path = self._path(folder, CHECKED_SUFFIX)
        if not path.is_file():
            return None
        data = self._read(path)
        files = data.get("files")
        content_hash = data.get("content_hash")
        if not isinstance(files, dict) or not isinstance(content_hash, str):
            raise PlanFactCheckStateError(f"malformed checked state {path}")
        checked_at = data.get("checked_at")
        return CheckedSnapshot(
            content_hash=content_hash,
            files={str(k): str(v) for k, v in files.items()},
            checked_at=float(checked_at) if isinstance(checked_at, int | float) else None,
        )

    def record_checked(
        self, folder: str, files: Mapping[str, str], checked_at: float | None = None
    ) -> None:
        """Record ``files`` as the last fact-checked content of ``folder``.

        Called when the session is seen dispatching the checker, or to record a
        baseline or an absorbed correction; never by the debounce fire.
        ``checked_at`` is when a check was confirmed (``None`` for a baseline).
        """
        self._write(
            self._path(folder, CHECKED_SUFFIX),
            {
                "content_hash": snapshot_hash(files),
                "files": dict(files),
                "checked_at": checked_at,
            },
        )

    def read_pending(self, folder: str) -> PendingFactCheck | None:
        """The owed-but-undelivered fact-check of ``folder``; ``None`` if none is owed.

        Raises:
            PlanFactCheckStateError: If the state file exists but is corrupt.
        """
        path = self._path(folder, PENDING_SUFFIX)
        if not path.is_file():
            return None
        return self._parse_pending(path)

    def _parse_pending(self, path: Path) -> PendingFactCheck:
        """Parse the pending record at ``path``; raises if it is corrupt."""
        data = self._read(path)
        files = data.get("files")
        if not isinstance(files, dict):
            raise PlanFactCheckStateError(f"malformed pending state {path}: no files")
        try:
            return PendingFactCheck(
                folder=str(data["folder"]),
                content_hash=str(data["content_hash"]),
                diff=str(data["diff"]),
                trigger_count=int(str(data["trigger_count"])),
                recorded_at=float(str(data["recorded_at"])),
                plan_root=str(data["plan_root"]),
                files={str(k): str(v) for k, v in files.items()},
                offers=int(str(data.get("offers", 0))),
                offered_at=float(str(data.get("offered_at", 0.0))),
            )
        except (KeyError, ValueError) as exc:
            raise PlanFactCheckStateError(f"malformed pending state {path}: {exc}") from exc

    def store_pending(self, pending: PendingFactCheck) -> None:
        """Store (replacing any earlier) the pending fact-check for its plan."""
        self._write(self._path(pending.folder, PENDING_SUFFIX), asdict(pending))

    def clear_pending(self, folder: str) -> None:
        """Drop the pending fact-check of ``folder``."""
        self._path(folder, PENDING_SUFFIX).unlink(missing_ok=True)

    def claim_pending(self, folder: str, suffix: str = PENDING_SUFFIX) -> Path:
        """Take the owed (or, with ``OFFERED_SUFFIX``, offered) record of ``folder``.

        The record is renamed to a name only the caller holds. A rename is atomic,
        so of two events that both listed the record exactly one succeeds.

        Raises:
            FileNotFoundError: If the record is gone, because another event took it.
        """
        path = self._path(folder, suffix)
        claimed = unique_temp_path(path)
        path.replace(claimed)
        return claimed

    def offer(self, pending: PendingFactCheck) -> None:
        """Store (replacing any earlier) the offered record: handed to the session, unconfirmed."""
        self._write(self._path(pending.folder, OFFERED_SUFFIX), asdict(pending))

    def read_offered(self, folder: str) -> PendingFactCheck | None:
        """The offered-but-unconfirmed fact-check of ``folder``, or ``None``.

        Raises:
            PlanFactCheckStateError: If the state file exists but is corrupt.
        """
        path = self._path(folder, OFFERED_SUFFIX)
        return self._parse_pending(path) if path.is_file() else None

    def clear_offered(self, folder: str) -> None:
        """Drop the offered record of ``folder``."""
        self._path(folder, OFFERED_SUFFIX).unlink(missing_ok=True)

    def offered_folders(self) -> list[str]:
        """Folders with an offered, unconfirmed fact-check, sorted."""
        return self._folders(OFFERED_SUFFIX)

    def offered_due(self, now: float) -> list[str]:
        """Offered folders whose offer is older than :data:`REOFFER_AFTER_SECONDS`.

        An unreadable record counts as due, so delivery reaches it and sets it aside.
        """
        due: list[str] = []
        for folder in self.offered_folders():
            try:
                offered = self.read_offered(folder)
            except PlanFactCheckStateError:
                due.append(folder)
                continue
            if offered is not None and offered.offered_at <= now - REOFFER_AFTER_SECONDS:
                due.append(folder)
        return due

    def outstanding(self, folder: str) -> bool:
        """True when ``folder`` has a check owed or offered and not yet confirmed."""
        return (
            self._path(folder, PENDING_SUFFIX).is_file()
            or self._path(folder, OFFERED_SUFFIX).is_file()
        )

    def _folders(self, suffix: str) -> list[str]:
        if not self._dir.is_dir():
            return []
        return sorted(p.name.removesuffix(suffix) for p in self._dir.glob(f"*{suffix}"))

    def read_claimed(self, claimed: Path) -> PendingFactCheck:
        """The record held at ``claimed`` (from :meth:`claim_pending`).

        Raises:
            PlanFactCheckStateError: If the record is corrupt.
        """
        return self._parse_pending(claimed)

    def set_aside(self, folder: str, suffix: str, claimed: Path | None = None) -> Path:
        """Rename an unreadable ``suffix`` record to ``<name>.unreadable`` and return its path.

        Renamed rather than deleted so the bytes stay inspectable; the new name
        no longer ends in the record suffix, so it is never listed or re-read.
        ``claimed`` is the record's current path when it was taken for delivery.
        """
        path = self._path(folder, suffix)
        aside = path.with_name(path.name + UNREADABLE_SUFFIX)
        (path if claimed is None else claimed).replace(aside)
        return aside

    def pending_folders(self) -> list[str]:
        """Folders with an owed fact-check, sorted; cheap enough for every hook event."""
        return self._folders(PENDING_SUFFIX)

    def diff_path(self, folder: str) -> Path:
        """Where the diff handed to the fact-checker agent is written."""
        return self._path(folder, DIFF_SUFFIX)

    def write_diff(self, folder: str, diff: str) -> Path:
        """Write ``diff`` for the agent to read and return its path."""
        path = self.diff_path(folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(diff, encoding="utf-8")
        return path


def _changed_line_count(diff: str) -> int:
    """Added plus removed lines of a unified diff, headers excluded."""
    return sum(
        1
        for line in diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def _is_correction(checked: CheckedSnapshot, diff: str, now: float) -> bool:
    """True when ``diff`` is a small edit soon after a confirmed check.

    Fixing a checker's finding is itself a plan edit; checking that fix would
    prompt another fix. One check covers its burst and the corrections it
    prompts: an edit of at most :data:`CORRECTION_MAX_CHANGED_LINES` lines
    within :data:`CORRECTION_WINDOW_SECONDS` of the confirmed check is absorbed.
    """
    if checked.checked_at is None:
        return False
    return (
        0 <= now - checked.checked_at < CORRECTION_WINDOW_SECONDS
        and _changed_line_count(diff) <= CORRECTION_MAX_CHANGED_LINES
    )


def resolve_plan_root(plan_root: Path, folder: str) -> Path | None:
    """Where the plan folder is now: its recorded path, its ``Completed/`` home, or ``None``."""
    if plan_root.is_dir():
        return plan_root
    archived = plan_root.parent / ARCHIVE_DIR / folder
    return archived if archived.is_dir() else None


def process_quiet_plan(
    plan_root: Path,
    folder: str,
    state: PlanFactCheckState,
    *,
    trigger_count: int,
    now: float,
) -> PendingFactCheck | None:
    """Handle a plan whose edits went quiet: store what is owed, dispatch nothing.

    Args:
        plan_root: The plan folder on disk.
        folder: The plan folder name (state key).
        state: Where the checked and pending records live.
        trigger_count: Edits coalesced into this fire.
        now: Wall-clock seconds for the record.

    Returns:
        The stored :class:`PendingFactCheck`, or ``None`` when the plan folder
        has vanished, this is the first sight of the plan (a baseline is
        recorded), its content equals the last fact-checked content, or the
        edit is a small correction soon after a confirmed check (absorbed).
    """
    if not plan_root.is_dir():
        logger.info("plan_fact_check: %s is gone; nothing to check", folder)
        return None
    snapshot = snapshot_plan(plan_root)
    content_hash = snapshot_hash(snapshot)
    checked = state.read_checked(folder)
    if checked is None:
        state.record_checked(folder, snapshot)
        logger.info("plan_fact_check: %s first sight; baseline recorded, nothing owed", folder)
        return None
    if checked.content_hash == content_hash:
        logger.info("plan_fact_check: %s unchanged since last check", folder)
        return None
    diff = snapshot_diff(checked.files, snapshot)
    if _is_correction(checked, diff, now) and not state.outstanding(folder):
        # Keep the original checked_at, so the window does not slide while edits continue.
        state.record_checked(folder, snapshot, checked_at=checked.checked_at)
        logger.info("plan_fact_check: %s small edit soon after a check; absorbed", folder)
        return None
    pending = PendingFactCheck(
        folder=folder,
        content_hash=content_hash,
        diff=diff,
        trigger_count=trigger_count,
        recorded_at=now,
        plan_root=str(plan_root),
        files=snapshot,
    )
    state.store_pending(pending)
    logger.info(
        "plan_fact_check: %s quiet after %d edit(s); pending fact-check stored (not delivered)",
        folder,
        trigger_count,
    )
    return pending


def render_instruction(pending: PendingFactCheck, diff_path: Path) -> str:
    """The work item handed to the session for one owed fact-check.

    The daemon runs no model: it asks the session to dispatch the agent, and to
    treat what comes back as work, not scenery.
    """
    plan_file = Path(pending.plan_root) / "PLAN.md"
    return (
        f"PLAN FACT-CHECK OWED for {pending.folder} "
        f"({pending.trigger_count} edit(s) went quiet).\n"
        f"Dispatch the `{FACT_CHECKER_AGENT}` agent now on `{plan_file}`, giving it the diff "
        f"of what changed since the last checked content at `{diff_path}` "
        "(it checks only the claims that diff adds or changes). Put that diff path in the "
        "agent's prompt: seeing it there is how the daemon learns the check was taken up.\n"
        "Treat every REFUTED claim in its report as work to fix, not background: for each, "
        "name the claim, the evidence and the file, then correct the plan (or the code) "
        "before you carry on. This is a report only; nothing is blocked."
    )


def _take(
    state: PlanFactCheckState, folder: str, suffix: str
) -> tuple[PendingFactCheck, Path] | None:
    """Claim the ``suffix`` record of ``folder`` and read it; ``None`` if gone or unreadable.

    Claiming (:meth:`PlanFactCheckState.claim_pending`) means two events that run
    at once cannot both take a record: the loser finds it gone. A record that
    cannot be read (corrupt, or written by an earlier build that stored no
    ``files``) is set aside with one WARNING.
    """
    try:
        claimed = state.claim_pending(folder, suffix)
    except FileNotFoundError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"record for {folder} was claimed by another event, which delivers it",
            level=logging.DEBUG,
        )
        return None
    try:
        return state.read_claimed(claimed), claimed
    except PlanFactCheckStateError as exc:
        aside = state.set_aside(folder, suffix, claimed)
        logger.warning("plan_fact_check: set aside unreadable record as %s: %s", aside, exc)
        return None


def _hand_over(
    state: PlanFactCheckState, pending: PendingFactCheck, claimed: Path, now: float
) -> str | None:
    """Offer ``pending`` to the session: write its diff, keep it as offered, render it.

    Nothing is recorded as checked here: the daemon cannot see whether the text
    arrives. Returns ``None`` (and drops the record, leaving the content owed)
    when the plan is gone or the offer cap is reached.
    """
    folder = pending.folder
    root = resolve_plan_root(Path(pending.plan_root), folder)
    if root is None:
        logger.info("plan_fact_check: %s is gone; dropping its fact-check", folder)
    elif pending.offers >= MAX_OFFERS:
        logger.warning(
            "plan_fact_check: %s offered %d times without the checker being dispatched; "
            "dropping the offer (its content stays owed)",
            folder,
            pending.offers,
        )
    else:
        offered = replace(
            pending, plan_root=str(root), offers=pending.offers + 1, offered_at=now
        )
        diff_path = state.write_diff(folder, offered.diff)
        state.offer(offered)
        claimed.unlink(missing_ok=True)
        return render_instruction(offered, diff_path)
    state.clear_offered(folder)
    claimed.unlink(missing_ok=True)
    return None


def deliver_pending(state: PlanFactCheckState, now: float | None = None) -> list[str]:
    """Turn every owed fact-check into a session instruction, and re-offer stale offers.

    A pending record is handed over (:func:`_hand_over`) and kept as an offered
    record until :func:`confirm_dispatch` sees the checker dispatched. An
    offered record older than :data:`REOFFER_AFTER_SECONDS` is handed over
    again, up to :data:`MAX_OFFERS` times, so a lost message does not lose the
    check. ``now`` defaults to the wall clock.
    """
    moment = time.time() if now is None else now
    messages: list[str] = []
    batches = (
        (state.pending_folders(), PENDING_SUFFIX),
        (state.offered_due(moment), OFFERED_SUFFIX),
    )
    for folders, suffix in batches:
        for folder in folders:
            taken = _take(state, folder, suffix)
            message = None if taken is None else _hand_over(state, *taken, now=moment)
            if message is not None:
                messages.append(message)
    return messages


def confirm_dispatch(state: PlanFactCheckState, prompt: str, now: float) -> list[str]:
    """Record as checked every offered plan whose diff path appears in ``prompt``.

    Called when the session dispatches the ``plan-fact-checker`` agent: that is
    the evidence the instruction arrived and was acted on. Returns the confirmed
    folders.
    """
    confirmed: list[str] = []
    for folder in state.offered_folders():
        try:
            offered = state.read_offered(folder)
        except PlanFactCheckStateError as exc:
            aside = state.set_aside(folder, OFFERED_SUFFIX)
            logger.warning("plan_fact_check: set aside unreadable record as %s: %s", aside, exc)
            continue
        if offered is None or str(state.diff_path(folder)) not in prompt:
            continue
        state.record_checked(folder, offered.files, checked_at=now)
        state.clear_offered(folder)
        confirmed.append(folder)
    return confirmed
