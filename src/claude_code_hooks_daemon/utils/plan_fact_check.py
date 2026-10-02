"""Plan fact-check bookkeeping: what changed in a plan since it was last checked.

Plan 00480 Tasks 4.1/4.2. The ``plan_fact_check_feed`` handler feeds the
debouncer; when a plan's edits go quiet, :func:`process_quiet_plan` runs.

**Delivery boundary.** Who runs the fact check, and how its verdict reaches the
session, is an open owner question (Plan 00480 open question 1). This module
therefore does NO dispatch. It computes the diff since the last fact-checked
content and stores it as a *pending fact-check* record
(:class:`PendingFactCheck`) for a later task to deliver. Only delivery may call
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
    """

    folder: str
    content_hash: str
    diff: str
    trigger_count: int
    recorded_at: float


class PlanFactCheckState:
    """Per-plan state files under one directory."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = state_dir

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
        data = self._read(path)
        try:
            return PendingFactCheck(
                folder=str(data["folder"]),
                content_hash=str(data["content_hash"]),
                diff=str(data["diff"]),
                trigger_count=int(str(data["trigger_count"])),
                recorded_at=float(str(data["recorded_at"])),
            )
        except (KeyError, ValueError) as exc:
            raise PlanFactCheckStateError(f"malformed pending state {path}: {exc}") from exc

    def store_pending(self, pending: PendingFactCheck) -> None:
        """Store (replacing any earlier) the pending fact-check for its plan."""
        self._write(self._path(pending.folder, PENDING_SUFFIX), asdict(pending))


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
    )
    state.store_pending(pending)
    logger.info(
        "plan_fact_check: %s quiet after %d edit(s); pending fact-check stored (not delivered)",
        folder,
        trigger_count,
    )
    return pending
