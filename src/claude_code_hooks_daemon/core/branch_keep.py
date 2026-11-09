"""Keep a merged branch: a git note on its tip (Plan 00571 DESIGN.md sections 2 and 4).

A merged branch is stale from day 0 unless somebody keeps it with a reason.
The keep is a note on the tip commit in ``refs/notes/hooks-daemon/keep``,
pushed so every clone sees it; a clone reads the remote's keeps from a
tracking ref (``refs/notes/hooks-daemon-remote/<remote>/keep``) that
:func:`fetch_keeps` refreshes. Reading is offline. A failed push leaves the
local keep standing and is reported with the command to retry.
"""

from __future__ import annotations

import calendar
import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.git_repo import run_git

logger = logging.getLogger(__name__)

KEEP_NOTES_REF: Final[str] = "refs/notes/hooks-daemon/keep"
_TRACKING_ROOT: Final[str] = "refs/notes/hooks-daemon-remote"
_ISO: Final[str] = "%Y-%m-%dT%H:%M:%SZ"
_FIELD: Final[re.Pattern[str]] = re.compile(r"^(Kept-Reason|Kept-By|Kept-At):[ \t]*(.*)$")


class BranchKeepError(Exception):
    """The keep could not be written; nothing changed."""


class BranchKeepSameReason(BranchKeepError):
    """The tip is already kept with this exact reason; a re-keep needs a new one."""


@dataclass(frozen=True)
class Keep:
    """One keep: why, who, and when (epoch seconds, UTC)."""

    reason: str
    by: str
    at: int


@dataclass(frozen=True)
class KeepResult:
    """Whether the push landed; on failure the command that retries it."""

    pushed: bool
    push_error: str | None
    retry_command: str | None


def keep_tracking_ref(remote: str) -> str:
    """The local ref that mirrors ``remote``'s keep notes."""
    return f"{_TRACKING_ROOT}/{remote}/keep"


def _epoch(stamp: str) -> int | None:
    """``Kept-At`` as epoch seconds; None (logged) when it is not a valid UTC stamp."""
    try:
        return calendar.timegm(time.strptime(stamp, _ISO))
    except ValueError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"branch_keep: Kept-At {stamp!r} is not a valid UTC stamp, so that "
            "entry is not a keep and the branch reads as unkept",
        )
    return None


def parse_keep_note(body: str) -> Keep | None:
    """The newest keep in a note body; None when it holds no complete keep.

    A body can hold several after ``notes merge -s union``; the latest ``Kept-At`` wins.
    """
    entries: list[dict[str, str]] = []
    for line in body.splitlines():
        match = _FIELD.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == "Kept-Reason":
            entries.append({})
        if entries:
            entries[-1][key] = value
    keeps: list[Keep] = []
    for entry in entries:
        at = _epoch(entry.get("Kept-At", ""))
        if entry.get("Kept-Reason") and at is not None:
            keeps.append(Keep(entry["Kept-Reason"], entry.get("Kept-By", "unknown"), at))
    return max(keeps, key=lambda keep: keep.at, default=None)


def _kept_tips(repo: Path, ref: str) -> set[str]:
    """Tips annotated in ``ref``; empty when the ref is absent."""
    result = run_git(repo, "notes", f"--ref={ref}", "list", timeout=Timeout.GIT_CONTEXT)
    if result.returncode != 0:
        return set()
    return {
        parts[1]
        for parts in (line.split() for line in result.stdout.splitlines())
        if len(parts) == 2
    }


def read_keeps(repo: Path, tips: Iterable[str], remote: str) -> dict[str, Keep]:
    """The newest keep of each of ``tips``, from the local and the tracking ref (offline)."""
    wanted = set(tips)
    found: dict[str, Keep] = {}
    for ref in (KEEP_NOTES_REF, keep_tracking_ref(remote)):
        for tip in _kept_tips(repo, ref) & wanted:
            shown = run_git(repo, "notes", f"--ref={ref}", "show", tip, timeout=Timeout.GIT_CONTEXT)
            keep = parse_keep_note(shown.stdout) if shown.returncode == 0 else None
            if keep is not None and (tip not in found or keep.at > found[tip].at):
                found[tip] = keep
    return found


def fetch_keeps(repo: Path, remote: str) -> str | None:
    """Refresh the tracking ref from ``remote``; the error text on failure, else None.

    A glob refspec: a remote that holds no keep notes succeeds and fetches nothing.
    """
    result = run_git(
        repo,
        "fetch",
        remote,
        f"+refs/notes/hooks-daemon/*:{_TRACKING_ROOT}/{remote}/*",
        timeout=Timeout.GIT_FETCH_SESSION,
    )
    if result.returncode != 0:
        return result.stderr.strip() or "git fetch failed"
    return None


def _push(repo: Path, remote: str) -> str | None:
    result = run_git(
        repo,
        "push",
        remote,
        f"{KEEP_NOTES_REF}:{KEEP_NOTES_REF}",
        timeout=Timeout.GIT_FETCH_SESSION,
    )
    return None if result.returncode == 0 else (result.stderr.strip() or "git push failed")


def _body(reason: str, user: str, now: float) -> str:
    stamp = time.strftime(_ISO, time.gmtime(now))
    return f"Kept-Reason: {reason}\nKept-By: {user}\nKept-At: {stamp}\n"


def keep_branch(
    repo: Path, tips: Iterable[str], *, reason: str, remote: str, user: str, now: float
) -> KeepResult:
    """Keep every tip of one branch with ``reason`` and push the notes.

    Raises:
        BranchKeepError: The reason is unusable or a note could not be written.
        BranchKeepSameReason: Every tip is already kept with exactly this reason.
    """
    stripped = reason.strip()
    if not stripped or "\n" in stripped:
        raise BranchKeepError("a single-line, non-empty reason is required (--reason)")
    distinct = sorted(set(tips))
    current = read_keeps(repo, distinct, remote)
    if distinct and all(tip in current and current[tip].reason == stripped for tip in distinct):
        raise BranchKeepSameReason(
            "this branch is already kept with this reason; a re-keep needs a new reason "
            "(say why it is still needed), or delete the branch"
        )
    for tip in distinct:
        added = run_git(
            repo,
            "notes",
            f"--ref={KEEP_NOTES_REF}",
            "add",
            "-f",
            "-m",
            _body(stripped, user, now),
            tip,
            timeout=Timeout.GIT_CONTEXT,
        )
        if added.returncode != 0:
            raise BranchKeepError(f"could not write the keep note: {added.stderr.strip()}")
    error = _push(repo, remote)
    if error is not None and fetch_keeps(repo, remote) is None:
        merged = run_git(
            repo,
            "notes",
            f"--ref={KEEP_NOTES_REF}",
            "merge",
            "-s",
            "union",
            keep_tracking_ref(remote),
            timeout=Timeout.GIT_CONTEXT,
        )
        if merged.returncode == 0:
            error = _push(repo, remote)
    if error is None:
        return KeepResult(True, None, None)
    return KeepResult(False, error, f"git push {remote} {KEEP_NOTES_REF}")
