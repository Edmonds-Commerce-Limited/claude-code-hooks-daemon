"""Plan fact-check bookkeeping: what changed in a plan since it was last checked.

Plan 00480 Tasks 4.1/4.2. The ``plan_fact_check_feed`` handler feeds the
debouncer; when a plan's edits go quiet, :func:`process_quiet_plan` runs.

**Delivery.** The daemon runs no model (Plan 00480 open question 1, option a).
The debounce fire (:func:`process_quiet_plan`) dispatches nothing: it computes
the diff since the last fact-checked content and stores it as a *pending
fact-check* record (:class:`PendingFactCheck`). The next hook event calls
:func:`deliver_pending`, which hands the session an instruction to dispatch the
``plan-fact-checker`` agent with that diff, once per record. Only delivery calls
:meth:`PlanFactCheckState.record_checked`: firing never advances the
"last checked" content, because nothing has been checked yet.

State lives under the daemon's untracked directory, one pair of JSON files per
plan folder (``<folder>.checked.json`` and ``<folder>.pending.json``), written
atomically (tmp + ``Path.replace``).

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
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from claude_code_hooks_daemon.utils.path_containment import path_relative_to
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

STATE_SUBDIR: Final[str] = "plan-fact-check"
CHECKED_SUFFIX: Final[str] = ".checked.json"
PENDING_SUFFIX: Final[str] = ".pending.json"
UNREADABLE_SUFFIX: Final[str] = ".unreadable"
DIFF_SUFFIX: Final[str] = ".diff"
FACT_CHECKER_AGENT: Final[str] = "plan-fact-checker"

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
        files: The plan content the diff leads to; becomes the checked content on delivery.
    """

    folder: str
    content_hash: str
    diff: str
    trigger_count: int
    recorded_at: float
    plan_root: str
    files: dict[str, str]


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
        return CheckedSnapshot(
            content_hash=content_hash, files={str(k): str(v) for k, v in files.items()}
        )

    def record_checked(self, folder: str, files: Mapping[str, str]) -> None:
        """Record ``files`` as the last fact-checked content of ``folder``.

        Called by delivery once a check has actually been delivered; never by
        the debounce fire.
        """
        self._write(
            self._path(folder, CHECKED_SUFFIX),
            {"content_hash": snapshot_hash(files), "files": dict(files)},
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
            )
        except (KeyError, ValueError) as exc:
            raise PlanFactCheckStateError(f"malformed pending state {path}: {exc}") from exc

    def store_pending(self, pending: PendingFactCheck) -> None:
        """Store (replacing any earlier) the pending fact-check for its plan."""
        self._write(self._path(pending.folder, PENDING_SUFFIX), asdict(pending))

    def clear_pending(self, folder: str) -> None:
        """Drop the pending fact-check of ``folder`` (it has been delivered)."""
        self._path(folder, PENDING_SUFFIX).unlink(missing_ok=True)

    def claim_pending(self, folder: str) -> Path:
        """Take the owed record of ``folder`` for delivery and return where it now is.

        The record is renamed to a name only the caller holds. A rename is atomic,
        so of two events that both listed the record exactly one succeeds.

        Raises:
            FileNotFoundError: If the record is gone, because another event took it.
        """
        path = self._path(folder, PENDING_SUFFIX)
        claimed = unique_temp_path(path)
        path.replace(claimed)
        return claimed

    def read_claimed(self, claimed: Path) -> PendingFactCheck:
        """The record held at ``claimed`` (from :meth:`claim_pending`).

        Raises:
            PlanFactCheckStateError: If the record is corrupt.
        """
        return self._parse_pending(claimed)

    def set_aside_pending(self, folder: str, claimed: Path | None = None) -> Path:
        """Rename an unreadable pending record to ``<name>.unreadable`` and return its path.

        Renamed rather than deleted so the bytes stay inspectable; the new name
        no longer ends in the pending suffix, so it is never listed or re-read.
        ``claimed`` is the record's current path when it was taken for delivery.
        """
        path = self._path(folder, PENDING_SUFFIX)
        aside = path.with_name(path.name + UNREADABLE_SUFFIX)
        (path if claimed is None else claimed).replace(aside)
        return aside

    def pending_folders(self) -> list[str]:
        """Folders with an owed fact-check, sorted; cheap enough for every hook event."""
        if not self._dir.is_dir():
            return []
        return sorted(
            p.name.removesuffix(PENDING_SUFFIX) for p in self._dir.glob(f"*{PENDING_SUFFIX}")
        )

    def diff_path(self, folder: str) -> Path:
        """Where the diff handed to the fact-checker agent is written."""
        return self._path(folder, DIFF_SUFFIX)

    def write_diff(self, folder: str, diff: str) -> Path:
        """Write ``diff`` for the agent to read and return its path."""
        path = self.diff_path(folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(diff, encoding="utf-8")
        return path


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
        has vanished or its content equals the last fact-checked content.
    """
    if not plan_root.is_dir():
        logger.info("plan_fact_check: %s is gone; nothing to check", folder)
        return None
    snapshot = snapshot_plan(plan_root)
    content_hash = snapshot_hash(snapshot)
    checked = state.read_checked(folder)
    if checked is not None and checked.content_hash == content_hash:
        logger.info("plan_fact_check: %s unchanged since last check", folder)
        return None
    baseline = checked.files if checked is not None else {}
    pending = PendingFactCheck(
        folder=folder,
        content_hash=content_hash,
        diff=snapshot_diff(baseline, snapshot),
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
        "(it checks only the claims that diff adds or changes).\n"
        "Treat every REFUTED claim in its report as work to fix, not background: for each, "
        "name the claim, the evidence and the file, then correct the plan (or the code) "
        "before you carry on. This is a report only; nothing is blocked."
    )


def deliver_pending(state: PlanFactCheckState) -> list[str]:
    """Turn every owed fact-check into a session instruction, once each.

    For each pending record: write its diff for the agent, record the plan
    content as checked (firing alone never does), drop the record, and return
    the rendered instruction.

    Each record is first CLAIMED (:meth:`PlanFactCheckState.claim_pending`), so
    two events that run at once cannot both deliver it: the one that loses the
    claim finds the record gone and skips it.

    A record that cannot be read (corrupt, or written by an earlier build that
    stored no ``files``) is set aside by :meth:`PlanFactCheckState.set_aside_pending`
    with one WARNING, and delivery carries on with the next record.
    """
    messages: list[str] = []
    for folder in state.pending_folders():
        try:
            claimed = state.claim_pending(folder)
        except FileNotFoundError:
            logger.debug("plan_fact_check: %s was taken by another event", folder)
            continue
        try:
            pending = state.read_claimed(claimed)
        except PlanFactCheckStateError as exc:
            aside = state.set_aside_pending(folder, claimed)
            logger.warning(
                "plan_fact_check: set aside unreadable pending record as %s: %s", aside, exc
            )
            continue
        diff_path = state.write_diff(folder, pending.diff)
        state.record_checked(folder, pending.files)
        claimed.unlink(missing_ok=True)
        messages.append(render_instruction(pending, diff_path))
    return messages
