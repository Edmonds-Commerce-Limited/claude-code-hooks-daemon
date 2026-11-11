"""Park a branch: an empty trailer commit at its tip (Plan 00558 Task 4.3, DESIGN section 5).

``git commit-tree`` writes a commit with the tip's own tree plus the
``Parked-Reason``/``Parked-By`` trailers (``Unparked`` to clear), and
``git update-ref <ref> <new> <old>`` moves the branch only if its tip has not
moved meanwhile. No checkout is needed. When ``commit.gpgsign`` is true the commit
is signed (``commit-tree`` ignores that key itself); a failed signing aborts the
park before any ref moves. The branch is then pushed with a plain
fast-forward ``git push``; a failed push leaves the local park standing and
is reported with the command to retry.

The park record in git config is the park itself, written before any push. The
trailer commit and the push are optional: ``commit=False`` records the park with
the tip untouched (and so never pushes), ``push=False`` commits but does not push.
A park with no commit is local to this clone: no other checkout can see it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import run_git

_HEADS = "refs/heads/"
_REMOTES = "refs/remotes/"

#: ``branch-park`` exit status for a park that stands locally but was not pushed.
EXIT_PARKED_NOT_PUSHED = 3

#: ``git config`` exit status for "no such key".
_CONFIG_KEY_ABSENT = 1

_GPGSIGN_KEY = "commit.gpgsign"
_SIGN_FLAG = "-S"
_SIGNING_HINT = (
    "commit.gpgsign is true here, so the park commit must be signed: check user.signingkey, "
    "gpg.format and gpg.program, or unset commit.gpgsign for this repository"
)

_SHA_KEY = "hooksDaemonParked"
_REASON_KEY = "hooksDaemonParkedReason"
_AT_KEY = "hooksDaemonParkedAt"
_BY_KEY = "hooksDaemonParkedBy"
_RECORD_KEYS = (_SHA_KEY, _REASON_KEY, _AT_KEY, _BY_KEY)


class BranchParkError(Exception):
    """The park could not be written; nothing changed."""


class BranchParkSameReason(BranchParkError):
    """The tip already carries this exact ``Parked-Reason``; a re-park needs a new one."""


@dataclass(frozen=True)
class ParkResult:
    """The new tip and whether the fast-forward push landed."""

    sha: str
    pushed: bool
    push_error: str | None
    retry_command: str | None
    #: No push was attempted by choice (no commit, or push off): the park is this clone's alone.
    local_only: bool = False


@dataclass(frozen=True)
class ParkRecord:
    """The local park record of a branch: the park commit, why, when and by whom."""

    sha: str
    reason: str
    parked_at: int
    parked_by: str


def _record_key(name: str, key: str) -> str:
    return f"branch.{name}.{key}"


def write_park_record(repo: Path, name: str, record: ParkRecord) -> None:
    """Write the park record into git config, before any push is attempted."""
    values = {
        _SHA_KEY: record.sha,
        _REASON_KEY: record.reason,
        _AT_KEY: str(record.parked_at),
        _BY_KEY: record.parked_by,
    }
    for key, value in values.items():
        _git_out(repo, "config", _record_key(name, key), value)


def read_park_record(repo: Path, name: str) -> ParkRecord | None:
    """The park record of ``name``; None when it has none (or an incomplete one)."""
    values: dict[str, str] = {}
    for key in _RECORD_KEYS:
        result = run_git(repo, "config", "--get", _record_key(name, key))
        if result.returncode == _CONFIG_KEY_ABSENT:
            return None
        if result.returncode != 0:
            raise BranchParkError(f"git config {_record_key(name, key)} failed: {result.stderr}")
        values[key] = result.stdout.strip()
    return ParkRecord(values[_SHA_KEY], values[_REASON_KEY], int(values[_AT_KEY]), values[_BY_KEY])


def clear_park_record(repo: Path, name: str) -> ParkRecord | None:
    """Remove the park record of ``name`` and return it, or None when it had none."""
    record = read_park_record(repo, name)
    if record is None:
        return None
    for key in _RECORD_KEYS:
        run_git(repo, "config", "--unset-all", _record_key(name, key))
    return record


def _recorded_park_names(repo: Path) -> list[str]:
    """Every branch that carries a park record (git lower-cases the key's last segment)."""
    result = run_git(repo, "config", "--get-regexp", rf"^branch\..+\.{_SHA_KEY.lower()}$")
    if result.returncode == _CONFIG_KEY_ABSENT:
        return []
    if result.returncode != 0:
        raise BranchParkError(f"git config --get-regexp failed: {result.stderr.strip()}")
    prefix, suffix = "branch.", f".{_SHA_KEY.lower()}"
    names: list[str] = []
    for line in result.stdout.splitlines():
        key = line.split(" ", 1)[0]
        names.append(key[len(prefix) : -len(suffix)])
    return names


def announce_ended_parks(repo: Path) -> list[str]:
    """Report each park that has ended, then remove its record, so it is said once.

    A park ends when the branch gained new work (its tip is no longer the park
    commit) or is gone. A merge clears its record itself and says so
    (``cleanup_after_merge``). The line is the one the merge path prints:
    ``Park cleared: <name> (<reason>)``. Nothing is reported for a park that
    still stands.
    """
    lines: list[str] = []
    for name in _recorded_park_names(repo):
        record = read_park_record(repo, name)
        if record is None:
            continue
        tip = run_git(repo, "rev-parse", "--verify", "--quiet", f"{_HEADS}{name}^{{commit}}")
        if tip.returncode == 0 and tip.stdout.strip() == record.sha:
            continue
        clear_park_record(repo, name)
        lines.append(f"Park cleared: {name} ({record.reason})")
    return lines


def _git_out(repo: Path, *args: str) -> str:
    result = run_git(repo, *args)
    if result.returncode != 0:
        raise BranchParkError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _message(reason: str | None, user: str, *, clear: bool) -> str:
    if clear:
        return f"Unpark branch\n\nUnparked: {user}\n"
    return f"Park branch: {reason}\n\nParked-Reason: {reason}\nParked-By: {user}\n"


def _refuse_same_reason(repo: Path, tip: str, name: str, reason: str) -> None:
    """Raise when ``tip`` is already parked with exactly ``reason``.

    A re-park with the same reason would add an empty commit that renews the
    park's age without anyone saying why the work is still waiting.
    """
    current = run_git(
        repo,
        "log",
        "-1",
        "--format=%(trailers:key=Parked-Reason,valueonly,unfold)",
        tip,
    )
    if current.returncode == 0 and current.stdout.strip() == reason:
        raise BranchParkSameReason(
            f"{name} is already parked with this reason; a re-park needs a new reason "
            "(say why it is still waiting), or merge or delete the branch"
        )


def _write_park_commit(repo: Path, parent: str, reason: str, *, clear: bool) -> str:
    """A trailer commit on ``parent``'s own tree; returns its sha."""
    tree = _git_out(repo, "rev-parse", f"{parent}^{{tree}}")
    user = run_git(repo, "config", "user.name").stdout.strip() or "unknown"
    args = ["commit-tree", tree, "-p", parent, "-m", _message(reason, user, clear=clear)]
    if not _signing_requested(repo):
        return _git_out(repo, *args)
    result = run_git(repo, *args, _SIGN_FLAG)
    if result.returncode != 0:
        raise BranchParkError(
            f"signing the park commit failed, so nothing was changed: {result.stderr.strip()}. "
            f"{_SIGNING_HINT}"
        )
    return result.stdout.strip()


def _signing_requested(repo: Path) -> bool:
    """True when the repository asks for signed commits (``commit.gpgsign``).

    ``git commit-tree`` does not read that key itself, so the park asks for it.
    """
    result = run_git(repo, "config", "--type=bool", "--get", _GPGSIGN_KEY)
    if result.returncode == _CONFIG_KEY_ABSENT:
        return False
    if result.returncode != 0:
        raise BranchParkError(f"git config {_GPGSIGN_KEY} failed: {result.stderr.strip()}")
    return result.stdout.strip() == "true"


def _keep_refused_remote_park(
    repo: Path, name: str, remote: str, new: str, reason: str, clear: bool, stderr: str
) -> ParkResult:
    """Keep a remote-only park whose push failed: a local branch at ``new`` plus the record.

    The park then stands locally exactly as it does for a local branch, so the
    pool counts, the retry command and the exit status all agree with that path.
    """
    created = run_git(repo, "update-ref", f"{_HEADS}{name}", new, "")
    if created.returncode != 0:
        raise BranchParkError(
            f"push of {name} to {remote} failed and the park could not be kept locally: "
            f"{created.stderr.strip()}"
        )
    _record_park(repo, name, new, reason, clear=clear)
    return ParkResult(new, False, stderr.strip() or "git push failed", f"git push {remote} {name}")


def _record_park(repo: Path, name: str, sha: str, reason: str, *, clear: bool) -> None:
    """Write the park record of a fresh park, or remove it on an unpark."""
    if clear:
        clear_park_record(repo, name)
        return
    user = run_git(repo, "config", "user.name").stdout.strip() or "unknown"
    write_park_record(repo, name, ParkRecord(sha, reason, int(time.time()), user))


def _park_remote_only(
    repo: Path,
    name: str,
    remote: str,
    remote_ref: str,
    old: str,
    reason: str,
    *,
    clear: bool,
) -> ParkResult:
    """Park a branch only ``remote`` holds, with no local branch.

    The park commit is pushed as a plain fast-forward. On success no local branch
    exists and the remote-tracking ref follows the push so the inventory sees the
    park without a fetch. A failed push keeps the park in a local branch with its
    record (``_keep_refused_remote_park``).
    """
    if not clear:
        _refuse_same_reason(repo, old, name, reason)
    new = _write_park_commit(repo, old, reason, clear=clear)
    pushed = run_git(
        repo,
        "push",
        remote,
        f"{new}:{_HEADS}{name}",
        timeout=Timeout.GIT_FETCH_SESSION,
    )
    if pushed.returncode != 0:
        return _keep_refused_remote_park(repo, name, remote, new, reason, clear, pushed.stderr)
    # ``git push`` already advances the tracking ref when the remote has the default
    # fetch refspec; setting it to ``new`` is idempotent and covers a remote without one.
    moved = run_git(repo, "update-ref", remote_ref, new)
    if moved.returncode != 0:
        raise BranchParkError(
            f"{name} was parked on {remote} but {remote_ref} could not follow: "
            f"{moved.stderr.strip()}"
        )
    return ParkResult(new, True, None, None)


def _is_record_only_park(repo: Path, name: str, tip: str) -> bool:
    """True when ``tip`` is the recorded park of ``name`` and carries no park trailer."""
    record = read_park_record(repo, name)
    if record is None or record.sha != tip:
        return False
    trailers = run_git(
        repo, "log", "-1", "--format=%(trailers:key=Parked-Reason,valueonly,unfold)", tip
    )
    return trailers.returncode == 0 and not trailers.stdout.strip()


def _park_record_only(repo: Path, name: str, tip: str, reason: str) -> ParkResult:
    """Record the park of ``name`` at its unchanged ``tip``: no commit, no push."""
    existing = read_park_record(repo, name)
    if existing is not None and existing.sha == tip and existing.reason == reason:
        raise BranchParkSameReason(
            f"{name} is already parked with this reason; a re-park needs a new reason "
            "(say why it is still waiting), or merge or delete the branch"
        )
    _refuse_same_reason(repo, tip, name, reason)
    _record_park(repo, name, tip, reason, clear=False)
    return ParkResult(tip, False, None, None, local_only=True)


def park_branch(
    repo: Path,
    name: str,
    *,
    reason: str | None,
    remote: str,
    clear: bool = False,
    commit: bool = True,
    push: bool = True,
) -> ParkResult:
    """Park (or, with ``clear``, unpark) branch ``name`` and push it.

    A branch with no local ref but a ``<remote>/<name>`` tracking ref is parked on
    the remote alone (no local branch is created).

    With ``commit=False`` the park is only the record in git config (the tip is
    untouched, so QA run on it stays valid) and nothing is pushed: such a park is
    local to this clone. With ``push=False`` the trailer commit is written but the
    branch is not pushed. Clearing a record-only park just removes the record.

    Raises:
        BranchParkError: The reason is unusable, the branch is missing, the tip
            moved while the park commit was written, or a record-only park was
            asked of a branch no local ref holds.
    """
    stripped = reason.strip() if reason is not None else ""
    if not clear and (not stripped or "\n" in stripped):
        raise BranchParkError("a single-line, non-empty reason is required (--reason)")
    ref = f"{_HEADS}{name}"
    verified = run_git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    remote_ref = f"{_REMOTES}{remote}/{name}"
    if verified.returncode != 0:
        if not commit and not clear:
            raise BranchParkError(
                f"a park with no commit needs a local branch, and {name} has none"
            )
        remote_tip = run_git(repo, "rev-parse", "--verify", "--quiet", f"{remote_ref}^{{commit}}")
        if remote_tip.returncode != 0:
            raise BranchParkError(f"no local branch {name} and no {remote}/{name}")
        return _park_remote_only(
            repo, name, remote, remote_ref, remote_tip.stdout.strip(), stripped, clear=clear
        )
    old = verified.stdout.strip()
    if clear and _is_record_only_park(repo, name, old):
        clear_park_record(repo, name)
        return ParkResult(old, False, None, None, local_only=True)
    if not clear and not commit:
        return _park_record_only(repo, name, old, stripped)
    if not clear:
        _refuse_same_reason(repo, old, name, stripped)
    new = _write_park_commit(repo, old, stripped, clear=clear)
    moved = run_git(repo, "update-ref", ref, new, old)
    if moved.returncode != 0:
        raise BranchParkError(
            f"{name} moved while parking; nothing changed: {moved.stderr.strip()}"
        )
    _record_park(repo, name, new, stripped, clear=clear)
    if not push:
        return ParkResult(new, False, None, None, local_only=True)
    retry = f"git push {remote} {name}"
    pushed = run_git(repo, "push", remote, name, timeout=Timeout.GIT_FETCH_SESSION)
    if pushed.returncode != 0:
        return ParkResult(new, False, pushed.stderr.strip() or "git push failed", retry)
    return ParkResult(new, True, None, None)
