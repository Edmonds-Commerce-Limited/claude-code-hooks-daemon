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

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_config_write import (
    GitConfigLockError,
    run_git_config_write,
)
from claude_code_hooks_daemon.utils.git_repo import read_blobs, run_git
from claude_code_hooks_daemon.utils.load_scaling import scaled_timeout
from claude_code_hooks_daemon.utils.remote_refs import remote_git_env

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400
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
#: A parked-at epoch: an optional sign, then at most 18 ASCII digits, which
#: ``int()`` always reads (it refuses a string past 4300 digits).
_INTEGER = re.compile(r"[+-]?[0-9]{1,18}")


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
    # Git offers no multi-key write in one invocation, so each key waits out the
    # shared config lock on its own (N621).
    for key, value in values.items():
        _config_write(repo, _record_key(name, key), value)


def read_park_record(repo: Path, name: str) -> ParkRecord | None:
    """The park record of ``name``; None when it has none (or an incomplete one)."""
    return read_park_records(repo).get(name)


def read_park_records(repo: Path) -> dict[str, ParkRecord]:
    """Every complete, readable park record in ``repo``, by branch name, in ONE git process.

    A branch with an incomplete record, or one whose ``ParkedAt`` is not an integer,
    is left out: an unreadable record is not a park, so every guard judges that
    branch as unparked, which is never laxer than the record it could not read.
    """
    pattern = rf"^branch\..+\.({'|'.join(k.lower() for k in _RECORD_KEYS)})$"
    result = run_git(repo, "config", "-z", "--get-regexp", pattern)
    if result.returncode == _CONFIG_KEY_ABSENT:
        return {}
    if result.returncode != 0:
        raise BranchParkError(f"git config --get-regexp failed: {result.stderr.strip()}")
    fields: dict[str, dict[str, str]] = {}
    for entry in result.stdout.split("\0"):
        key, _sep, value = entry.partition("\n")
        if not key.startswith("branch."):
            continue
        name, _dot, leaf = key[len("branch.") :].rpartition(".")
        fields.setdefault(name, {})[leaf] = value
    records: dict[str, ParkRecord] = {}
    for name, found in fields.items():
        record = _record_from_fields(name, found)
        if record is not None:
            records[name] = record
    return records


def _record_from_fields(name: str, found: dict[str, str]) -> ParkRecord | None:
    """The record held by the lower-cased config leaves in ``found``, or None."""
    leaves = [key.lower() for key in _RECORD_KEYS]
    if any(leaf not in found for leaf in leaves):
        return None
    sha, reason, at, by = (found[leaf] for leaf in leaves)
    if _INTEGER.fullmatch(at.strip()) is None:
        logger.warning("park record of %s has a non-integer %s; ignored", name, _AT_KEY)
        return None
    return ParkRecord(sha.strip(), reason.strip(), int(at.strip()), by.strip())


def clear_park_record(repo: Path, name: str) -> ParkRecord | None:
    """Remove the park record of ``name`` and return it, or None when it had none."""
    record = read_park_record(repo, name)
    if record is None:
        return None
    for key in _RECORD_KEYS:
        _config_write(repo, "--unset-all", _record_key(name, key))
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


def park_covers_tip(
    park: ParkRecord,
    tip: str,
    *,
    max_age_days: int,
    is_ancestor: Callable[[str, str], bool],
) -> bool:
    """Whether ``park`` still covers a branch whose tip is ``tip`` (Plan 00640).

    The one rule every park consumer applies: the tip is the parked commit, or the
    parked commit is an ancestor of it (later commits land on top of a park), and
    the park is no older than ``max_age_days``. ``is_ancestor(park_sha, tip)`` is
    supplied by the caller so each keeps its own git budget; it must answer False
    when git cannot say, so a failure ends the park rather than extending it.
    """
    if park.sha == tip:
        return True
    if (time.time() - park.parked_at) / _SECONDS_PER_DAY > max_age_days:
        return False
    return is_ancestor(park.sha, tip)


def announce_ended_parks(repo: Path, *, max_age_days: int) -> list[str]:
    """Report each park that has ended, then remove its record, so it is said once.

    A park ends when the branch is gone, its tip does not build on the park
    commit (rewritten or unrelated history), or it outlived ``max_age_days``
    (:func:`park_covers_tip`); later commits on top of the park commit do not end
    it. A merge clears its record itself and says so (``cleanup_after_merge``).
    The line is the one the merge path prints: ``Park cleared: <name> (<reason>)``.
    Nothing is reported for a park that still stands.
    """

    def is_ancestor(ancestor: str, descendant: str) -> bool:
        probe = run_git(repo, "merge-base", "--is-ancestor", ancestor, descendant)
        return probe.returncode == 0

    lines: list[str] = []
    for name in _recorded_park_names(repo):
        record = read_park_record(repo, name)
        if record is None:
            continue
        tip = run_git(repo, "rev-parse", "--verify", "--quiet", f"{_HEADS}{name}^{{commit}}")
        if tip.returncode == 0 and park_covers_tip(
            record, tip.stdout.strip(), max_age_days=max_age_days, is_ancestor=is_ancestor
        ):
            continue
        clear_park_record(repo, name)
        lines.append(f"Park cleared: {name} ({record.reason})")
    return lines


def _config_write(repo: Path, *args: str) -> None:
    """``git config <args>`` waiting out ``config.lock``; a failure is a park error."""
    try:
        result = run_git_config_write(repo, *args)
    except GitConfigLockError as exc:
        raise BranchParkError(str(exc)) from exc
    if result.returncode != 0:
        raise BranchParkError(f"git config failed: {result.stderr.strip()}")


def _git_out(repo: Path, *args: str) -> str:
    result = run_git(repo, *args)
    if result.returncode != 0:
        raise BranchParkError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _message(reason: str | None, user: str, *, clear: bool) -> str:
    if clear:
        return f"{_UNPARK_SUBJECT}\n\n{_UNPARKED_BY}{user}\n"
    return f"{_PARK_SUBJECT}{reason}\n\nParked-Reason: {reason}\n{_PARKED_BY}{user}\n"


_PARK_SUBJECT = "Park branch: "
_UNPARK_SUBJECT = "Unpark branch"
_PARKED_BY = "Parked-By: "
_UNPARKED_BY = "Unparked: "


def is_park_message(message: str) -> bool:
    """Whether ``message`` is exactly what :func:`_message` writes for a park or an unpark.

    The reason and user are read back out of the message and the writer's own text is
    rebuilt from them, so any other wording, line or trailer is not a park message.
    """
    text = message.strip()
    lines = text.split("\n")
    if lines[0].startswith(_PARK_SUBJECT) and lines[-1].startswith(_PARKED_BY):
        reason = lines[0].removeprefix(_PARK_SUBJECT)
        user = lines[-1].removeprefix(_PARKED_BY)
        return text == _message(reason, user, clear=False).strip()
    if lines[0] == _UNPARK_SUBJECT and lines[-1].startswith(_UNPARKED_BY):
        user = lines[-1].removeprefix(_UNPARKED_BY)
        return text == _message(None, user, clear=True).strip()
    return False


# --- the park-commit classifier (Plan 00617) ------------------------------------------

_WALK_UNIT = "\x1f"
_WALK_FIELDS = 4
_BOUNDARY_MARK = "-"
_WALK_FORMAT = "--format=%m%x1f%H%x1f%T%x1f%P"
#: Tip trailers that can mark a park commit; only a ref carrying one can be residue.
_TIP_MARK_FORMAT = (
    "--format=%(refname)%00%(trailers:key=Parked-Reason,valueonly,unfold)"
    "%(trailers:key=Unparked,valueonly,unfold)"
)


@dataclass(frozen=True)
class ParkWalk:
    """The commits of ``target..tip``, which of them are park commits, and the merge count.

    ``empties`` are the commits that change nothing: ONE parent and that parent's
    tree, whatever their message (Plan 00622). Every park commit is one of them.
    """

    commits: tuple[str, ...]
    parks: frozenset[str]
    merges: int
    empties: frozenset[str] = frozenset()

    @property
    def is_residue(self) -> bool:
        """Every commit is a park commit, and there is at least one (:func:`is_park_residue`)."""
        return bool(self.parks) and len(self.commits) == len(self.parks)

    @property
    def is_content_free(self) -> bool:
        """Every commit is empty, and there is at least one (:func:`is_content_free`)."""
        return bool(self.commits) and len(self.commits) == len(self.empties)


@dataclass(frozen=True)
class _RangeShape:
    """``target..tip`` read structurally: each commit with its parents, and the empty ones."""

    in_range: tuple[tuple[str, tuple[str, ...]], ...]
    empties: tuple[str, ...]


#: The commit-graph is a cache git fills a commit's tree and parents from when it
#: reaches that commit through a parent, so a forged graph (the repository's or an
#: alternate store's) can make a content commit read as empty or drop it from the
#: range (Plan 00622 R2-1). The walk turns it off; ``GIT_TEST_COMMIT_GRAPH`` would
#: override the config, so it is pinned off too. The stored objects decide anyway.
_NO_COMMIT_GRAPH: tuple[str, ...] = ("-c", "core.commitGraph=false")
_NO_COMMIT_GRAPH_ENV: dict[str, str] = {"GIT_TEST_COMMIT_GRAPH": "0"}
_HEADER_END = b"\n\n"
_TREE_HEADER = b"tree "
_PARENT_HEADER = b"parent "


def _stored_header(body: bytes) -> tuple[str, tuple[str, ...]] | None:
    """The ``tree`` and ``parent`` headers of a raw commit object; None if it has no tree.

    Only the header block is read (up to the first blank line), so a message line that
    starts with ``parent`` is never taken for one, and a continuation line (a signature)
    starts with a space and matches neither.
    """
    header = body.split(_HEADER_END, 1)[0]
    tree: str | None = None
    parents: list[str] = []
    for line in header.split(b"\n"):
        if line.startswith(_TREE_HEADER) and tree is None:
            tree = line[len(_TREE_HEADER) :].decode("ascii", "replace")
        elif line.startswith(_PARENT_HEADER):
            parents.append(line[len(_PARENT_HEADER) :].decode("ascii", "replace"))
    return None if tree is None else (tree, tuple(parents))


def _stored_objects_agree(
    repo: Path,
    trees: dict[str, str],
    candidates: list[tuple[str, tuple[str, ...]]],
    timeout: float,
) -> bool:
    """Whether the STORED commits back every tree the walk reported and each empty candidate.

    One ``cat-file --batch`` read of the raw commit objects, which no commit-graph,
    replace ref or graft can change. Every walked commit's stored tree must be the
    walk's; each empty candidate's stored parents must be exactly the walk's one
    parent, so a forged parent cannot hide a commit beneath it. A commit that is not
    a candidate already counts as content, so its parents are not compared: a shallow
    clone's cut commit reads as parentless while its stored header names a parent.
    A failed read or a missing object is a no.
    """
    stored = read_blobs(repo, list(trees), timeout=timeout)
    if stored is None:
        return False
    headers: dict[str, tuple[str, tuple[str, ...]]] = {}
    for sha in trees:
        body = stored.get(sha)
        parsed = None if body is None else _stored_header(body)
        if parsed is None or parsed[0] != trees[sha]:
            return False
        headers[sha] = parsed
    return all(headers[sha][1] == parents for sha, parents in candidates)


def _walk_shape(repo: Path, target: str, tip: str, timeout: float) -> _RangeShape | None:
    """Shas, trees and parents of ``target..tip`` (no free text); None on any git failure.

    A commit is empty when it has exactly one parent and that parent's tree. A merge
    is never empty, even with its first parent's tree (``-s ours`` carries a whole
    side history), and a root commit has nothing to be empty against. Every tree and
    parent the walk reports is confirmed against the stored commit objects before any
    commit is called empty (:func:`_stored_objects_agree`).
    """
    log = run_git(
        repo,
        *_NO_COMMIT_GRAPH,
        "log",
        "--boundary",
        _WALK_FORMAT,
        f"{target}..{tip}",
        timeout=timeout,
        env=_NO_COMMIT_GRAPH_ENV,
    )
    if log.returncode != 0:
        return None
    trees: dict[str, str] = {}
    in_range: list[tuple[str, str, tuple[str, ...]]] = []
    for line in log.stdout.split("\n"):
        if not line:
            continue
        parts = line.split(_WALK_UNIT)
        if len(parts) != _WALK_FIELDS:
            return None
        mark, sha, tree, parents = parts
        trees[sha] = tree
        if mark != _BOUNDARY_MARK:
            in_range.append((sha, tree, tuple(parents.split())))
    candidates: list[tuple[str, tuple[str, ...]]] = [
        (sha, parents)
        for sha, tree, parents in in_range
        if len(parents) == 1 and parents[0] in trees and trees[parents[0]] == tree
    ]
    if trees and not _stored_objects_agree(repo, trees, candidates, timeout):
        return None
    empties = tuple(sha for sha, _parents in candidates)
    return _RangeShape(
        in_range=tuple((sha, parents) for sha, _tree, parents in in_range), empties=empties
    )


def is_content_free(
    repo: Path, tip: str, target: str, *, timeout: float = Timeout.GIT_CONTEXT
) -> bool | None:
    """Whether every commit ``tip`` has beyond ``target`` is empty (at least one); None on failure.

    Then ``tip``'s tree is a tree ``target``'s history holds, and a delete loses only
    those commits' messages. The message plays no part: an empty commit of any wording
    qualifies, and a commit that changes a file never does, whatever it is called.
    None when git cannot say, which every caller reads as unproven (fail closed).
    """
    shape = _walk_shape(repo, target, tip, timeout)
    if shape is None:
        return None
    return bool(shape.in_range) and len(shape.empties) == len(shape.in_range)


def _park_bodies_match(repo: Path, shas: list[str], timeout: float) -> set[str] | None:
    """Which of ``shas`` carry exactly the park writer's message; None when git cannot say.

    One ``git log --no-walk=unsorted -z`` call. Each NUL-separated record must start
    with the sha asked for, in order, and the count must match, so a message holding a
    NUL (or anything else) can never pass itself off as another commit's record.
    """
    if not shas:
        return set()
    log = run_git(
        repo, "log", "--no-walk=unsorted", "-z", "--format=%H%n%B", *shas, timeout=timeout
    )
    if log.returncode != 0:
        return None
    records = log.stdout.removesuffix("\0").split("\0")
    if len(records) != len(shas):
        return None
    matched: set[str] = set()
    for sha, record in zip(shas, records, strict=True):
        head, _, body = record.partition("\n")
        if head != sha:
            return None
        if is_park_message(body):
            matched.add(sha)
    return matched


def walk_park_range(repo: Path, target: str, tip: str, *, timeout: float) -> ParkWalk | None:
    """Walk ``target..tip`` and name its park commits; None on any git failure.

    A park commit is one the park writer wrote: its message is exactly the writer's
    (:func:`is_park_message`), it has ONE parent, and its tree is that parent's tree,
    so it changes nothing. The structural walk carries no free text (shas only); the
    messages of the few tree-identical candidates are then read in one framed call.
    """
    shape = _walk_shape(repo, target, tip, timeout)
    if shape is None:
        return None
    parks = _park_bodies_match(repo, list(shape.empties), timeout)
    if parks is None:
        return None
    return ParkWalk(
        commits=tuple(sha for sha, _parents in shape.in_range),
        parks=frozenset(parks),
        merges=sum(1 for _sha, parents in shape.in_range if len(parents) > 1),
        empties=frozenset(shape.empties),
    )


def is_park_residue(
    repo: Path, tip: str, target: str, *, timeout: float = Timeout.GIT_CONTEXT
) -> bool:
    """Whether ``tip`` differs from ``target`` ONLY by park commits (at least one).

    The one test every branch consumer asks: then the work is in ``target`` and a
    delete loses nothing but the park markers. False on any git failure (fail closed),
    for a tip with no park commit, and when any commit beyond ``target`` is not a
    park commit (:func:`walk_park_range`).
    """
    walked = walk_park_range(repo, target, tip, timeout=timeout)
    return walked is not None and walked.is_residue


def park_marked_refs(repo: Path, refnames: list[str], *, timeout: float) -> set[str]:
    """Which of ``refnames`` have a tip carrying a park or unpark trailer: one call.

    Only those can be park residue, so the walk is paid for no other ref. A failed
    listing marks nothing, which leaves the ref to the other proofs: the safe direction.
    """
    if not refnames:
        return set()
    listing = run_git(repo, "for-each-ref", _TIP_MARK_FORMAT, *refnames, timeout=timeout)
    if listing.returncode != 0:
        return set()
    marked: set[str] = set()
    for line in listing.stdout.split("\n"):
        refname, _, trailers = line.partition("\0")
        if refname and trailers.strip():
            marked.add(refname)
    return marked


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


def _restore_tip(
    repo: Path, ref: str, name: str, old: str, new: str, cause: BranchParkError
) -> BranchParkError:
    """Move ``ref`` back to ``old`` after its record could not be written; the error to raise.

    The park commit has already moved the branch; without a record the park does
    not stand, so the error's "nothing changed" has to be made true.
    """
    back = run_git(repo, "update-ref", ref, old, new)
    if back.returncode != 0:
        return BranchParkError(
            f"{name} was moved to the park commit {new} but its record could not be written "
            f"({cause}) and the branch could not be moved back: {back.stderr.strip()}"
        )
    return BranchParkError(f"{cause}; the branch was put back, nothing changed")


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
        timeout=scaled_timeout(Timeout.GIT_FETCH_SESSION, Timeout.GIT_FETCH_SESSION_MAX),
        env=remote_git_env(),
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
    try:
        _record_park(repo, name, new, stripped, clear=clear)
    except BranchParkError as exc:
        raise _restore_tip(repo, ref, name, old, new, exc) from exc
    if not push:
        return ParkResult(new, False, None, None, local_only=True)
    retry = f"git push {remote} {name}"
    pushed = run_git(
        repo,
        "push",
        remote,
        name,
        timeout=scaled_timeout(Timeout.GIT_FETCH_SESSION, Timeout.GIT_FETCH_SESSION_MAX),
        env=remote_git_env(),
    )
    if pushed.returncode != 0:
        return ParkResult(new, False, pushed.stderr.strip() or "git push failed", retry)
    return ParkResult(new, True, None, None)
