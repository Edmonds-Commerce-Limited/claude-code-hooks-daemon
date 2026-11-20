"""Classify every repository inside a scratch entry (Plan 00627 Tasks 2.1 and 2.2).

DESIGN.md section 3.3. Each ``.git`` marker the walk found, and each bare
repository (a directory holding ``HEAD``, ``objects/`` and ``refs/``), is one of:

- REGISTERED_WORKTREE: its directory is in the project's ``git worktree list``.
  PROTECTED: removal is ``git worktree remove`` and its guard, never a tree delete.
- OUTSIDE_POINTING: a ``.git`` file (or ``commondir``) whose target is outside the
  entry, or a git directory with no marker that is not provably bare (N2: its
  config lacks ``bare = true`` or it holds an ``index``, so its work tree may be
  elsewhere). PROTECTED: it is part of another repository.
- RELATED: it has a remote, is shallow, borrows objects, or has a root commit or
  ref tip the project's object database holds. R6: it is PROTECTED unless it is
  clean (no staged change, every worktree change a remote-held blob), has no
  stash, and every ref tip and HEAD is contained by a LIVE-verified remote tip
  of the project. Then its git directory and tracked files are covered by P4.
- STANDALONE: none of the above. Disposable (proof P7 covers its work tree and
  git directory), the coordinator's ruling applying the owner's "scratch repo
  ... no value" (DESIGN.md section 0). Files beside it are judged on their own.
- BROKEN: anything that could not be judged. The entry is STUCK.

A repository's linked worktrees (``<common>/worktrees/<id>``) are judged with
it: one outside the entry, or missing, protects it whatever its kind (a
standalone one becomes OUTSIDE_POINTING), and each worktree's ``HEAD`` joins a
related clone's tip set.

Standalone must be proved for every marker: any other kind decides the entry.
Every git failure, timeout or unparseable answer is BROKEN, never STANDALONE,
and never a proof. A git operation in progress (a lock file, ``MERGE_HEAD``, a
``rebase-*`` directory) is BROKEN.

Git inside a nested repository is untrusted. Its config is read first, from the
project, with ``git config --file ... --no-includes``; any key outside
:data:`_ALLOWED_CONFIG` stops the classification before git runs there. Every
nested call names ``--git-dir`` and ``--work-tree`` (so git never walks up to
the project), reads no global or system config, takes no optional lock, and runs
no hook or fsmonitor (:data:`NESTED_GIT_ENV`, :data:`NESTED_GIT_FLAGS`).
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import os
import re
import shlex
import stat
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core.branch_records import (
    CREATED_KEY,
    CREATOR_KEY,
    ROUTE_KEY,
    TOUCHED_KEY,
)
from claude_code_hooks_daemon.utils.git_repo import (
    GitResult,
    parse_worktree_porcelain,
    run_git,
)
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to
from claude_code_hooks_daemon.utils.remote_refs import parse_listing, remote_git_env


class GitRunner(Protocol):
    """``run_git``'s shape, so tests can inject failures."""

    def __call__(
        self, cwd: Path, *args: str, timeout: float = ..., env: Mapping[str, str] | None = ...
    ) -> GitResult: ...


#: ``(project, remote, branch names) -> {name: live tip}``; an absent name is unverified.
LiveTips = Callable[[Path, str, list[str]], dict[str, str]]

#: The environment of every git run inside a nested repository.
NESTED_GIT_ENV: Final[Mapping[str, str]] = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_COUNT": "0",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_OPTIONAL_LOCKS": "0",
}

#: Flags before the subcommand of every git run inside a nested repository.
NESTED_GIT_FLAGS: Final[tuple[str, ...]] = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "protocol.allow=never",
    # D-EXEC 1: never recurse into an inner repository, whose config was not checked.
    "-c",
    "submodule.recurse=false",
    "-c",
    "diff.ignoreSubmodules=all",
)

_CORE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "repositoryformatversion",
        "filemode",
        "bare",
        "logallrefupdates",
        "ignorecase",
        "precomposeunicode",
        "symlinks",
        "autocrlf",
        "eol",
        "safecrlf",
        "quotepath",
        "checkstat",
        "trustctime",
        "sharedrepository",
        "compression",
        "abbrev",
        "longpaths",
    }
)

#: ``(section, subsection present, allowed names)`` a nested config may hold.
_ALLOWED_CONFIG: Final[tuple[tuple[str, bool, frozenset[str]], ...]] = (
    ("core", False, _CORE_KEYS),
    (
        "remote",
        True,
        frozenset({"url", "pushurl", "fetch", "push", "mirror", "tagopt", "prune"}),
    ),
    (
        "branch",
        True,
        frozenset(
            {"remote", "merge", "rebase", "pushremote", "description"}
            # The daemon's own inert branch records; git lists names lowercased.
            | {key.lower() for key in (CREATOR_KEY, CREATED_KEY, ROUTE_KEY, TOUCHED_KEY)}
        ),
    ),
    ("user", False, frozenset({"name", "email"})),
    ("extensions", False, frozenset({"objectformat"})),
    ("init", False, frozenset({"defaultbranch"})),
    ("pull", False, frozenset({"rebase", "ff"})),
)

_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REMOTE_URL: Final[re.Pattern[str]] = re.compile(r"remote\..+\.url")
_IN_PROGRESS_NAMES: Final[frozenset[str]] = frozenset(
    {"MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply"}
)
_GIT_TRUE: Final[frozenset[str]] = frozenset({"true", "yes", "on", "1"})
_GIT_MARKER: Final[str] = ".git"
_GITDIR_PREFIX: Final[str] = "gitdir:"
_MAX_GIT_FILE_BYTES: Final[int] = 4096
_STASH_REF: Final[str] = "refs/stash"
_REMOTES: Final[str] = "refs/remotes/"
#: More distinct ref tips than this are not proved one by one: the entry is protected.
MAX_TIPS: Final[int] = 200
#: More dirty paths than this are not hashed: the entry is protected.
MAX_DIRTY_PATHS: Final[int] = 200


class RepoKind(enum.Enum):
    """What one repository inside an entry is."""

    STANDALONE = "standalone"
    RELATED = "related"
    REGISTERED_WORKTREE = "registered worktree"
    OUTSIDE_POINTING = "points outside the entry"
    BROKEN = "not judged"


@dataclass(frozen=True)
class ProjectGit:
    """What the project's own repository says, read once per sweep."""

    root: Path
    remote: str
    runner: GitRunner
    #: Real paths of the project's registered worktrees; None when git could not list them.
    worktrees: frozenset[Path] | None
    #: ``refs/remotes/<remote>/<name>`` -> sha, only where the live remote has that sha.
    verified: Mapping[str, str]
    #: Why ``verified`` is empty or partial; "" when every tracking ref was confirmed.
    verified_note: str
    #: Blob shas of the verified default tip's tree; None when there is no verified default.
    remote_blobs: frozenset[str] | None
    #: The default branch's name (the reference set searches its local tip), if known.
    default_branch: str | None = None


@dataclass(frozen=True)
class RepoFindings:
    """Every repository in one entry, and what they decide for it."""

    kinds: Mapping[str, RepoKind] = field(default_factory=dict)
    stuck: tuple[str, ...] = ()
    protected: tuple[str, ...] = ()
    #: Paths (from the scratch root) covered by P4: git directories and tracked files.
    p4_covered: tuple[str, ...] = ()
    #: The git directories among ``p4_covered``: they alone cover everything beneath them.
    p4_git_dirs: tuple[str, ...] = ()
    #: Roots (work tree and git directory) of each STANDALONE repository: P7 covers them.
    standalone_roots: tuple[str, ...] = ()
    #: Roots of every other repository: P7 stops at the deepest root holding a path.
    other_roots: tuple[str, ...] = ()


def _shas(text: str) -> list[str] | None:
    """Every whitespace-separated word as a sha, or None if one is not a sha."""
    words = text.split()
    return words if all(_SHA.fullmatch(word) for word in words) else None


def _git_live_tips(runner: GitRunner) -> LiveTips:
    def live(directory: Path, remote: str, names: list[str]) -> dict[str, str]:
        if not names:
            return {}
        result = runner(
            directory,
            "ls-remote",
            remote,
            *(f"refs/heads/{name}" for name in names),
            timeout=Timeout.GIT_FETCH_BACKGROUND,
            env=remote_git_env(),
        )
        if result.returncode != 0:
            return {}
        tips = {ref.removeprefix("refs/heads/"): sha for ref, sha in parse_listing(result.stdout)}
        return {name: sha for name, sha in tips.items() if _SHA.fullmatch(sha)}

    return live


def build_project_git(
    project_root: Path,
    *,
    remote: str,
    default_branch: str | None,
    runner: GitRunner = run_git,
    live_tips: LiveTips | None = None,
) -> ProjectGit:
    """Read the project's worktrees, live-verified remote tips and remote-held blobs."""
    listing = runner(project_root, "worktree", "list", "--porcelain")
    worktrees: frozenset[Path] | None = None
    if listing.returncode == 0 and listing.stdout.startswith("worktree "):
        worktrees = frozenset(
            Path(os.path.realpath(record.path))
            for record in parse_worktree_porcelain(listing.stdout)
        )
    prefix = f"{_REMOTES}{remote}/"
    tracking: dict[str, str] = {}
    refs = runner(project_root, "for-each-ref", "--format=%(objectname) %(refname)", prefix)
    note = ""
    if refs.returncode != 0:
        note = f"the project's remote-tracking refs could not be listed: {refs.stderr.strip()}"
    else:
        for line in refs.stdout.splitlines():
            sha, _, ref = line.partition(" ")
            if not _SHA.fullmatch(sha) or not ref.startswith(prefix):
                note = "the project's remote-tracking refs could not be parsed"
                tracking = {}
                break
            if ref != f"{prefix}HEAD":
                tracking[ref] = sha
    names = sorted(ref.removeprefix(prefix) for ref in tracking)
    live = (live_tips or _git_live_tips(runner))(project_root, remote, names)
    verified = {
        ref: sha for ref, sha in tracking.items() if live.get(ref.removeprefix(prefix)) == sha
    }
    if not note and len(verified) < len(tracking):
        note = f"{len(tracking) - len(verified)} remote-tracking ref(s) not confirmed by the live remote"
    blobs: frozenset[str] | None = None
    default_tip = verified.get(f"{prefix}{default_branch}") if default_branch else None
    if default_tip:
        tree = runner(project_root, "ls-tree", "-r", "-z", default_tip)
        if tree.returncode == 0:
            blobs = _tree_blobs(tree.stdout)
    return ProjectGit(
        project_root, remote, runner, worktrees, verified, note, blobs, default_branch
    )


_HASHES: Final[Mapping[int, Callable[[bytes], hashlib._Hash]]] = {
    40: hashlib.sha1,
    64: hashlib.sha256,
}
_READ_CHUNK: Final[int] = 1 << 20


def blob_length(blobs: frozenset[str] | None) -> int | None:
    """The sha length of a blob set, or None when it is empty, absent or mixed."""
    lengths = {len(sha) for sha in blobs or ()}
    return lengths.pop() if len(lengths) == 1 else None


def blob_id(path: Path, *, sha_length: int) -> str | None:
    """Git's ``hash-object --no-filters`` id of a regular file, never through a link.

    The last component is opened ``O_NOFOLLOW | O_NONBLOCK``, so a link swapped
    in after the walk's ``lstat`` fails to open and a FIFO never blocks; the
    descriptor must be a regular file. A parent directory swapped for a link is
    NOT caught here: this is a dry-run proof only, and ``--apply`` re-classifies
    the claimed tree through directory descriptors (DESIGN.md section 5.2).
    A short or long read, an unknown sha length, or any error proves nothing.
    """
    factory = _HASHES.get(sha_length)
    if factory is None:
        return None
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            return None
        digest = factory(f"blob {info.st_size}\0".encode())
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(_READ_CHUNK, remaining))
            if not chunk:
                return None
            digest.update(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            return None
        return digest.hexdigest()
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _tree_blobs(output: str) -> frozenset[str] | None:
    found: set[str] = set()
    for record in filter(None, output.split("\0")):
        meta, _, _path = record.partition("\t")
        parts = meta.split()
        if len(parts) != 3 or not _SHA.fullmatch(parts[2]):
            return None
        if parts[1] == "blob":
            found.add(parts[2])
    return frozenset(found)


@dataclass(frozen=True)
class _Repo:
    """One repository found in the entry, located but not yet judged."""

    marker: str  # from the scratch root: ``e/x/.git`` or a bare ``e/b.git``
    gitdir: Path
    common: Path
    work_tree: Path | None  # None for a bare repository


class _Broken(Exception):
    """This repository cannot be judged; the message says why."""


class _Decided(Exception):
    """This repository's kind is settled without running git in it."""

    def __init__(self, kind: RepoKind, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind


def _regular_file(path: Path) -> bool:
    """Whether ``path`` itself (never a link's target) is a regular file."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _inside(path: Path, entry: Path) -> bool:
    return path == entry or path_is_relative_to(path, entry)


def read_small_regular_file(path: Path, limit: int = _MAX_GIT_FILE_BYTES) -> bytes | None:
    """``path``'s bytes if it is itself a regular file of at most ``limit`` bytes, else None.

    Opened ``O_NOFOLLOW | O_NONBLOCK`` after an ``lstat``, so a link is never
    followed and a FIFO never blocks; the descriptor must be a regular file.
    """
    if not _regular_file(path):
        return None
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        raw = os.read(descriptor, limit + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    return raw if len(raw) <= limit else None


def _read_pointer(path: Path, prefix: str) -> str:
    raw = read_small_regular_file(path, _MAX_GIT_FILE_BYTES)
    if raw is None:
        raise _Broken(f"{path.name} is not a small regular file: not read")
    if len(raw) > _MAX_GIT_FILE_BYTES:
        raise _Broken(f"{path.name} is too large to be a git pointer")
    text = raw.decode("utf-8", errors="replace").strip()
    if prefix:
        if not text.startswith(prefix):
            raise _Broken(f"{path.name} names no {prefix}")
        text = text[len(prefix) :].strip()
    if not text or "\n" in text:
        raise _Broken(f"{path.name} is not a single path")
    return text


def _target(base: Path, pointer: str, entry: Path, what: str) -> Path:
    """``pointer`` relative to ``base``; refused (protected) when it leaves the entry."""
    lexical = Path(os.path.normpath(base / pointer))
    real = Path(os.path.realpath(lexical))
    if not (_inside(lexical, entry) and _inside(real, Path(os.path.realpath(entry)))):
        # The pointer is file content, so it is never echoed: the marker names the place.
        raise _Decided(RepoKind.OUTSIDE_POINTING, f"{what} points outside the entry")
    return lexical


def _locate(root: Path, entry: Path, marker: str, project: ProjectGit) -> _Repo:
    path = root / marker
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise _Broken(f"{marker} could not be read: {type(exc).__name__}") from exc
    work_tree: Path | None = path.parent if path.name == _GIT_MARKER else None
    if stat.S_ISLNK(info.st_mode):
        raise _Broken(f"{marker} is a link: not followed")
    if stat.S_ISREG(info.st_mode) and path.name == _GIT_MARKER:
        real_dir = Path(os.path.realpath(path.parent))
        if project.worktrees is not None and real_dir in project.worktrees:
            raise _Decided(
                RepoKind.REGISTERED_WORKTREE,
                f"{marker} is a registered worktree of the project: remove it with "
                f"`git worktree remove {shlex.quote(str(path.parent))}`, never a tree delete",
            )
        gitdir = _target(path.parent, _read_pointer(path, _GITDIR_PREFIX), entry, marker)
    elif stat.S_ISDIR(info.st_mode):
        gitdir = path
    else:
        raise _Broken(f"{marker} is neither a directory nor a git file")
    if not _regular_file(gitdir / "HEAD"):
        raise _Broken(f"{marker} is not a git repository (no HEAD)")
    common = gitdir
    if os.path.lexists(gitdir / "commondir"):  # read by _read_pointer: never followed
        common = _target(
            gitdir, _read_pointer(gitdir / "commondir", ""), entry, f"{marker} commondir"
        )
    return _Repo(marker, gitdir, common, work_tree)


def _in_progress(repo: _Repo, root: Path, nodes: frozenset[str]) -> str:
    for directory in {repo.gitdir, repo.common}:
        try:
            rel = directory.relative_to(root).as_posix()
        except ValueError:
            continue
        for node in nodes:
            if not node.startswith(f"{rel}/"):
                continue
            name = node.rsplit("/", 1)[-1]
            parent = node.rsplit("/", 1)[0]
            if name.endswith(".lock") or (parent == rel and name in _IN_PROGRESS_NAMES):
                return f"{repo.marker}: a git operation is in progress ({node[len(rel) + 1 :]})"
    return ""


def _allowed(key: str) -> bool:
    section, _, rest = key.partition(".")
    subsection, _, name = rest.rpartition(".")
    for allowed_section, has_subsection, names in _ALLOWED_CONFIG:
        if section == allowed_section and bool(subsection) == has_subsection:
            return name in names
    return False


def _config(repo: _Repo, project: ProjectGit) -> list[tuple[str, str]]:
    """``(key, value)`` of every entry of the repository's config; any unknown key is BROKEN."""
    config = repo.common / "config"
    if not _regular_file(config):
        raise _Broken(f"{repo.marker}: no readable config file")
    result = project.runner(
        project.root,
        "config",
        "--file",
        str(config),
        "--no-includes",
        "-z",
        "--list",
        env=NESTED_GIT_ENV,
    )
    if result.returncode != 0:
        raise _Broken(f"{repo.marker}: its config could not be read ({result.returncode})")
    entries = [
        (key, value)
        for key, _, value in (record.partition("\n") for record in result.stdout.split("\0"))
        if key
    ]
    for key, _value in entries:
        if not _allowed(key):
            raise _Broken(f"{repo.marker}: its config sets {key!r}, so git is not run in it")
    return entries


def _require_bare(repo: _Repo, config: Sequence[tuple[str, str]]) -> None:
    """N2: a git directory with no work tree in the entry must prove it is bare.

    ``git init --separate-git-dir`` leaves a git directory whose work tree is
    elsewhere: its config does not say ``bare = true`` and, once anything is
    staged, it holds an ``index``. Either sign, or a value-less ``core.bare``,
    means work lives outside the entry, so a human decides.
    """
    elsewhere = "so its work tree may be outside the entry (git init --separate-git-dir)"
    if os.path.lexists(repo.gitdir / "index"):
        raise _Decided(
            RepoKind.OUTSIDE_POINTING,
            f"{repo.marker}: a git directory holding an index, {elsewhere}",
        )
    bare = [value for key, value in config if key == "core.bare"]
    if not bare or bare[-1].strip().lower() not in _GIT_TRUE:
        raise _Decided(
            RepoKind.OUTSIDE_POINTING,
            f"{repo.marker}: a git directory whose config does not set bare = true, {elsewhere}",
        )


def _nested(repo: _Repo, project: ProjectGit, *args: str) -> GitResult:
    location = [f"--git-dir={repo.gitdir}"]
    if repo.work_tree is not None:
        location.append(f"--work-tree={repo.work_tree}")
    return project.runner(project.root, *NESTED_GIT_FLAGS, *location, *args, env=NESTED_GIT_ENV)


def _checked(result: GitResult, what: str) -> str:
    if result.returncode != 0:
        raise _Broken(f"{what} failed ({result.returncode}): {result.stderr.strip()[:200]}")
    return result.stdout


def _refs(repo: _Repo, project: ProjectGit) -> dict[str, str]:
    output = _checked(
        _nested(repo, project, "for-each-ref", "--format=%(objectname) %(refname)"),
        f"{repo.marker}: listing refs",
    )
    refs: dict[str, str] = {}
    for line in output.splitlines():
        sha, _, ref = line.partition(" ")
        if not _SHA.fullmatch(sha) or not ref.startswith("refs/"):
            raise _Broken(f"{repo.marker}: unparseable ref listing")
        refs[ref] = sha
    return refs


def _confirm_gitdir(repo: _Repo, project: ProjectGit) -> None:
    output = _checked(
        _nested(repo, project, "rev-parse", "--absolute-git-dir"), f"{repo.marker}: rev-parse"
    ).strip()
    if "\0" in output or not output.startswith("/"):
        raise _Broken(f"{repo.marker}: unparseable git directory")
    if os.path.realpath(output) != os.path.realpath(repo.gitdir):
        raise _Broken(f"{repo.marker}: git answered for another repository")


def _is_related(
    repo: _Repo, project: ProjectGit, config: Sequence[tuple[str, str]], refs: Mapping[str, str]
) -> str:
    """Why the repository is related to the project, or "" when it is standalone."""
    if any(_REMOTE_URL.fullmatch(key) for key, _value in config):
        return "it has a remote"
    if os.path.lexists(repo.common / "shallow"):
        return "it is a shallow clone"
    if os.path.lexists(repo.common / "objects" / "info" / "alternates"):
        return "it borrows objects from another repository"
    roots = _shas(
        _checked(
            _nested(repo, project, "rev-list", "--max-parents=0", "--all"),
            f"{repo.marker}: listing root commits",
        )
    )
    if roots is None:
        raise _Broken(f"{repo.marker}: unparseable root-commit listing")
    candidates = sorted({*roots, *refs.values()})
    if not candidates:
        return ""
    held = project.runner(project.root, "rev-list", "--no-walk", "--ignore-missing", *candidates)
    present = _shas(_checked(held, "the project's object lookup"))
    if present is None:
        raise _Broken("the project's object lookup was unparseable")
    return "it shares history with the project" if present else ""


def _held_by_verified(sha: str, project: ProjectGit) -> bool:
    result = project.runner(
        project.root,
        "for-each-ref",
        "--contains",
        sha,
        "--format=%(objectname) %(refname)",
        f"{_REMOTES}{project.remote}/",
    )
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        tip, _, ref = line.partition(" ")
        if project.verified.get(ref) == tip:
            return True
    return False


def _dirty_problems(repo: _Repo, project: ProjectGit, root: Path) -> list[str]:
    if repo.work_tree is None:
        return []
    # Status ignores gitlinks (it would run git with the inner repository's config),
    # so a gitlink's state is unproved: its presence protects the clone.
    staged = _checked(
        _nested(repo, project, "ls-files", "--stage", "-z"), f"{repo.marker}: ls-files --stage"
    )
    gitlinks = [
        record.partition("\t")[2]
        for record in filter(None, staged.split("\0"))
        if record.startswith("160000 ")
    ]
    if gitlinks:
        return [f"{len(gitlinks)} gitlink(s) whose state is not proved, first {gitlinks[0]}"]
    output = _checked(
        _nested(
            repo,
            project,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=no",
            "--ignore-submodules=all",
        ),
        f"{repo.marker}: status",
    )
    records = output.split("\0")
    to_hash: list[Path] = []
    problems: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2] != " ":
            raise _Broken(f"{repo.marker}: unparseable status")
        staged, worktree, rel = record[0], record[1], record[3:]
        if staged in "RC":
            index += 1
        if staged != " ":
            problems.append(f"a staged change ({rel})")
        elif worktree == "M":
            to_hash.append(repo.work_tree / rel)
        elif worktree != "D":
            problems.append(f"a {worktree!r} change ({rel})")
    if problems or not to_hash:
        return problems
    if project.remote_blobs is None or len(to_hash) > MAX_DIRTY_PATHS:
        return [f"{len(to_hash)} edited tracked file(s) not proved held by the remote"]
    length = blob_length(project.remote_blobs)
    return [
        f"an edited tracked file the remote does not hold ({path.relative_to(root).as_posix()})"
        for path in to_hash
        if length is None or blob_id(path, sha_length=length) not in project.remote_blobs
    ]


def _points_back(marker: Path, admin: Path) -> bool:
    """Whether ``marker`` is a ``.git`` file whose pointer resolves to ``admin``."""
    try:
        pointer = _read_pointer(marker, _GITDIR_PREFIX)
    except _Broken:
        return False
    back = os.path.normpath(marker.parent / pointer)
    return os.path.realpath(back) == os.path.realpath(admin)


def _admin_head(admin: Path, admin_rel: str, refs: Mapping[str, str]) -> tuple[str, str]:
    """``(tip sha or "", problem or "")`` from a linked worktree's own ``HEAD``.

    Read as a file, never through git: git would follow the admin dir's own
    ``commondir``, which is unchecked.
    """
    raw = read_small_regular_file(admin / "HEAD")
    if raw is None:
        raise _Broken(f"{admin_rel}: HEAD is not a small regular file")
    text = raw.decode("utf-8", errors="replace").strip()
    if _SHA.fullmatch(text):
        return text, ""
    if not text.startswith("ref:"):
        raise _Broken(f"{admin_rel}: unparseable HEAD")
    name = text[len("ref:") :].strip()
    if name in refs:
        return refs[name], ""
    if name.startswith("refs/heads/"):
        return "", ""  # an unborn branch: no commit to prove
    return "", f"{admin_rel}: its HEAD names a ref that is not proved"


def _linked_worktrees(
    repo: _Repo, root: Path, entry: Path, nodes: frozenset[str], refs: Mapping[str, str]
) -> tuple[list[str], list[str]]:
    """F-BYPS 1 and 2: ``(problems, HEAD tips)`` of every linked worktree of ``repo``.

    Each admin dir ``<common>/worktrees/<id>`` the walk saw is read. Its worktree
    must be in the entry and its ``.git`` file must point back at the admin dir;
    otherwise the worktree is elsewhere or gone and the repository is protected.
    An unreadable admin dir is BROKEN. Each admin ``HEAD`` joins the tip set.
    """
    common_rel = repo.common.relative_to(root).as_posix()
    prefix = f"{common_rel}/worktrees/"
    ids = sorted({node[len(prefix) :].split("/")[0] for node in nodes if node.startswith(prefix)})
    problems: list[str] = []
    heads: list[str] = []
    real_entry = Path(os.path.realpath(entry))
    for ident in ids:
        admin = repo.common / "worktrees" / ident
        admin_rel = f"{prefix}{ident}"
        try:
            pointer = _read_pointer(admin / "gitdir", "")
        except _Broken as exc:
            raise _Broken(f"{admin_rel}: {exc}") from exc
        target = Path(os.path.normpath(admin / pointer))
        if not (_inside(target, entry) and _inside(Path(os.path.realpath(target)), real_entry)):
            problems.append(f"{admin_rel}: its linked worktree lies outside the entry")
        elif (
            target.name != _GIT_MARKER
            or target.relative_to(root).as_posix() not in nodes
            or not _points_back(target, admin)
        ):
            problems.append(
                f"{admin_rel}: its linked worktree is missing (restore it, or run "
                "`git worktree prune` in the repository)"
            )
        if any(node.startswith(f"{admin_rel}/refs/") for node in nodes):
            problems.append(f"{admin_rel}: it holds per-worktree refs that are not proved")
        tip, problem = _admin_head(admin, admin_rel, refs)
        if tip:
            heads.append(tip)
        if problem:
            problems.append(problem)
    return problems, heads


def _standalone_roots(repo: _Repo, root: Path) -> list[str]:
    """A standalone repository's work tree and git directory, from the scratch root."""
    places = [repo.gitdir]
    if repo.work_tree is not None:
        places = [repo.work_tree]
        if not _inside(repo.gitdir, repo.work_tree):
            places.append(repo.gitdir)
    return [place.relative_to(root).as_posix() for place in places]


def _related_problems(
    repo: _Repo,
    project: ProjectGit,
    refs: Mapping[str, str],
    root: Path,
    worktree_heads: Sequence[str] = (),
) -> list[str]:
    """R6: why a related repository holds work that exists nowhere else."""
    problems = _dirty_problems(repo, project, root)
    if _STASH_REF in refs:
        problems.append("a stash")
    head = _nested(repo, project, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    tips = set(refs.values()) - ({refs[_STASH_REF]} if _STASH_REF in refs else set())
    tips.update(worktree_heads)
    if head.returncode == 0:
        head_sha = _shas(head.stdout)
        if head_sha is None or len(head_sha) != 1:
            raise _Broken(f"{repo.marker}: unparseable HEAD")
        tips.add(head_sha[0])
    elif head.returncode != 1 or head.stdout.strip():
        raise _Broken(f"{repo.marker}: HEAD could not be read ({head.returncode})")
    if not project.verified:
        problems.append(f"no live-verified remote tip ({project.verified_note or 'none'})")
    elif len(tips) > MAX_TIPS:
        problems.append(f"{len(tips)} ref tips, more than {MAX_TIPS} are proved")
    else:
        unheld = [sha for sha in sorted(tips) if not _held_by_verified(sha, project)]
        if unheld:
            problems.append(f"{len(unheld)} commit tip(s) no live-verified remote tip contains")
    return problems


#: ``ls-files -v`` tags of an index entry whose worktree changes ``status`` does not see.
_HIDING_TAGS: Final[frozenset[str]] = frozenset("hmrcks" + "S")


def _tracked(
    repo: _Repo, project: ProjectGit, root: Path, nodes: frozenset[str]
) -> tuple[list[str], list[str]]:
    """The tracked files the walk saw, and the tracked paths flagged so ``status`` hides edits.

    A listed path the walk did not see covers nothing. An ``assume-unchanged`` or
    ``skip-worktree`` entry can hold an edit no ``status`` reports, so it is flagged.
    """
    if repo.work_tree is None:
        return [], []
    output = _checked(_nested(repo, project, "ls-files", "-z", "-v"), f"{repo.marker}: ls-files")
    base = repo.work_tree.relative_to(root).as_posix()
    paths: list[str] = []
    flagged: list[str] = []
    for record in filter(None, output.split("\0")):
        tag, separator, rel = record.partition(" ")
        if not separator or len(tag) != 1:
            raise _Broken(f"{repo.marker}: unparseable ls-files listing")
        if tag in _HIDING_TAGS:
            flagged.append(rel)
        path = f"{base}/{rel}"
        if path in nodes:
            paths.append(path)
    return paths, flagged


def _bare_candidates(root: Path, nodes: frozenset[str], markers: Iterable[str]) -> list[str]:
    """Git directories no ``.git`` marker accounts for.

    One a ``.git`` file in the entry points back at (``--separate-git-dir`` with
    the work tree in the entry) is judged with that marker, which covers it.
    """
    gitdirs = tuple(markers)
    git_files = [root / marker for marker in gitdirs if _regular_file(root / marker)]
    found = []
    for node in sorted(nodes):
        if node.rsplit("/", 1)[-1] == _GIT_MARKER or any(
            node == marker or node.startswith(f"{marker}/") for marker in gitdirs
        ):
            continue
        if not {f"{node}/HEAD", f"{node}/objects", f"{node}/refs"} <= nodes:
            continue
        if not any(_points_back(git_file, root / node) for git_file in git_files):
            found.append(node)
    return found


def classify_entry(
    root: Path,
    name: str,
    *,
    nodes: Sequence[str],
    markers: Sequence[str],
    project: ProjectGit,
    runner: GitRunner | None = None,
) -> RepoFindings:
    """Classify every repository in entry ``name`` of scratch root ``root``.

    ``nodes`` and ``markers`` are the walk's paths, from the scratch root.
    ``runner`` replaces ``project.runner`` for the nested calls (tests).
    """
    if runner is not None and runner is not project.runner:
        project = dataclasses.replace(project, runner=runner)
    entry = root / name
    node_set = frozenset(nodes)
    kinds: dict[str, RepoKind] = {}
    stuck: list[str] = []
    protected: list[str] = []
    covered: list[str] = []
    standalone: set[str] = set()
    others: set[str] = set()
    for marker in [*markers, *_bare_candidates(root, node_set, markers)]:
        kind, reasons, cover = _classify_one(root, entry, marker, node_set, project)
        kinds[marker] = kind
        if kind is RepoKind.STANDALONE:
            standalone.update(cover)
            continue
        others.add(marker.removesuffix(f"/{_GIT_MARKER}"))
        if kind is RepoKind.BROKEN:
            stuck.extend(reasons)
        elif reasons:
            protected.extend(reasons)
        covered.extend(cover)
    if stuck or protected:
        # Markers sharing one git directory report its linked worktrees alike: once each.
        return RepoFindings(kinds, tuple(dict.fromkeys(stuck)), tuple(dict.fromkeys(protected)))
    git_dirs = tuple(sorted({path[:-1] for path in covered if path.endswith("/")}))
    files = {path for path in covered if not path.endswith("/")}
    return RepoFindings(
        kinds,
        (),
        (),
        tuple(sorted({*files, *git_dirs})),
        git_dirs,
        tuple(sorted(standalone)),
        tuple(sorted(others - standalone)),
    )


def _classify_one(
    root: Path, entry: Path, marker: str, nodes: frozenset[str], project: ProjectGit
) -> tuple[RepoKind, list[str], list[str]]:
    try:
        repo = _locate(root, entry, marker, project)
        progress = _in_progress(repo, root, nodes)
        if progress:
            raise _Broken(progress)
        config = _config(repo, project)
        if repo.work_tree is None:
            _require_bare(repo, config)
        _confirm_gitdir(repo, project)
        refs = _refs(repo, project)
        worktree_problems, worktree_heads = _linked_worktrees(repo, root, entry, nodes, refs)
        related = _is_related(repo, project, config, refs)
        if not related:
            if worktree_problems:
                # Another tree depends on this git directory: a human decides.
                raise _Decided(RepoKind.OUTSIDE_POINTING, "; ".join(worktree_problems))
            return RepoKind.STANDALONE, [], _standalone_roots(repo, root)
        problems = [
            *worktree_problems,
            *_related_problems(repo, project, refs, root, worktree_heads),
        ]
        if problems:
            return (
                RepoKind.RELATED,
                [f"{marker}: related ({related}) and holds {'; '.join(problems)}"],
                [],
            )
        tracked, flagged = _tracked(repo, project, root, nodes)
        if flagged:
            return (
                RepoKind.RELATED,
                [
                    f"{marker}: related ({related}) and {len(flagged)} tracked path(s) are "
                    f"flagged so status hides their edits, first {flagged[0]}"
                ],
                [],
            )
        return RepoKind.RELATED, [], [f"{repo.gitdir.relative_to(root).as_posix()}/", *tracked]
    except _Decided as decided:
        return (
            decided.kind,
            [str(decided) if marker in str(decided) else f"{marker}: {decided}"],
            [],
        )
    except _Broken as broken:
        return RepoKind.BROKEN, [str(broken)], []


__all__ = [
    "MAX_DIRTY_PATHS",
    "MAX_TIPS",
    "NESTED_GIT_ENV",
    "NESTED_GIT_FLAGS",
    "GitRunner",
    "LiveTips",
    "ProjectGit",
    "RepoFindings",
    "RepoKind",
    "blob_id",
    "blob_length",
    "build_project_git",
    "classify_entry",
]
