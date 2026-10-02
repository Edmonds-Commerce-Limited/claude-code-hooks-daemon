"""Read-only git facts, shared by both QA commit gates and PostToolUse handlers.

Everything a cross-file check needs from git, behind one small class:

- staged changes (``git diff --cached``) with rename detection, so a commit
  gate can see terminal-status flips, ``git mv`` moves and README diffs in the
  STAGED tree — not the working tree
- staged/HEAD file contents (``git show``) for parsing a document exactly as it
  will be committed
- last-commit dates per path, for staleness sweeps

Strictly read-only: this module never mutates the repository.

It lives in ``utils`` because both QA packages need it. It began in
``plan_qa`` and grew a ``docs_qa`` caller, which made docs QA depend on plan QA
for git plumbing that has nothing to do with plans — one of the edges
``tests/integration/test_qa_package_dependency_direction.py`` declares.
:class:`plan_qa.gitfacts.GitFacts` subclasses this and adds the one genuinely
plan-specific accessor, the plan counter, so plan QA's callers are unaffected
and docs QA depends on this module alone.

:func:`project_relative_head_text` is a THIRD caller family (ledger 00466
N3): PostToolUse handlers reading "what did this file say a moment ago"
after a Write/Edit has already landed on disk. Membership is checked
against a caller-supplied project root (review nit n3 — this module stays
core-free, per the paragraph above; every caller already resolves
``ProjectContext.project_root()`` for its own other purposes), but HEAD is
read from the file's OWN enclosing repository (ledger 00466 review m5) — a
nested checkout under the project root is a separate repository the
project root's repo never tracks.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_commit_parsing import CommitReading, CommitRun
from claude_code_hooks_daemon.utils.git_repo import GitRepo, read_blobs, run_git
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to, path_relative_to
from claude_code_hooks_daemon.utils.path_predicates import read_text_or_reason

if TYPE_CHECKING:
    import subprocess  # nosec B404 — only the CompletedProcess type is named

# name-status codes that carry TWO paths (old NUL new) in -z output.
_TWO_PATH_STATUS_PREFIXES: Final[tuple[str, ...]] = ("R", "C")

_NUL: Final[str] = "\0"

# ``ls-files -s`` mode of a submodule entry: a commit pointer, not a file.
_GITLINK_MODE: Final[str] = "160000"

# ``ls-tree`` object type of a submodule entry.
_GITLINK_TYPE: Final[str] = "commit"

# A listing value that is not a blob sha: the commit takes this path's content
# from the WORKING TREE (``git commit <pathspec>``), where no blob exists yet.
WORKING_TREE: Final[str] = "working-tree"

# ``git diff --name-status`` letter of a path the commit removes.
_DELETED_STATUS: Final[str] = "D"

# Appended to every ``git diff`` whose paths are joined to the repository root:
# with ``diff.relative`` set, a diff run from a subdirectory otherwise names
# paths relative to THAT directory.
NO_RELATIVE: Final[str] = "--no-relative"

# Ends git's options, so a pathspec that starts with a dash is not read as one.
_END_OF_OPTIONS: Final[str] = "--"

# Prefixes that name the repository's whole tree, where git wants no pathspec.
_WHOLE_TREE_PREFIXES: Final[frozenset[str]] = frozenset({"", "."})


@dataclass(frozen=True)
class StagedChange:
    """One entry from ``git diff --cached --name-status``."""

    status: str
    path: str
    old_path: str | None


@dataclass(frozen=True)
class PathspecScope:
    """Pathspecs of one ``git commit``, and the directory they are read from."""

    directory: Path
    pathspecs: tuple[str, ...]


class GitFactsBase:
    """Read-only git facts for one repository root."""

    def __init__(
        self,
        repo_root: Path,
        pathspecs: Sequence[str] | None = None,
        include: bool = False,
        directory: Path | None = None,
        union: bool = False,
        scopes: Sequence[PathspecScope] = (),
        index_env: Mapping[str, str] | None = None,
    ) -> None:
        """Initialise.

        Args:
            repo_root: Repository root ``git -C`` targets.
            pathspecs: The commit's explicit pathspec arguments, when the
                inspected ``git commit`` invocation names paths directly
                (``git commit <pathspec>...``). ``None``/empty means a bare
                commit (or ``-a``), which commits the INDEX — the original,
                unscoped behaviour. See :meth:`staged_changes`.
            include: ``git commit --include <pathspec>...``: the commit records
                the INDEX with the named paths' working-tree content laid over
                it, rather than HEAD with the named paths replaced. Ignored
                without ``pathspecs``.
            directory: The directory the commit command runs in, which its
                pathspecs are relative to. Only a call that carries the
                pathspecs runs there; every other call, and every file read,
                is rooted at ``repo_root``. Defaults to ``repo_root``.
            union: The commit's reading is not certain (see
                :class:`~claude_code_hooks_daemon.utils.git_commit_parsing.CommitReading`),
                so judge the index PLUS the named paths' working-tree changes,
                never less than the index alone. Ignored without ``pathspecs``.
            scopes: The pathspecs of every commit of the command (ledger 00474
                N307), each with a directory it is read from; what any scope
                names is judged. When given, ``pathspecs`` and ``directory``
                are not used, and the first scope is the primary one.
            index_env: Git environment that points every read at a COPY of the
                index with a same-command ``git add`` already applied (ledger
                00474 N246), so the index read is the one the commit records.
        """
        self._repo_root = repo_root
        self._env = index_env
        primary = tuple(pathspecs) if pathspecs else ()
        self._directory = scopes[0].directory if scopes else directory or repo_root
        self._scopes: tuple[PathspecScope, ...] = tuple(scopes) or (
            (PathspecScope(self._directory, primary),) if primary else ()
        )
        self._pathspecs = tuple(
            dict.fromkeys(spec for scope in self._scopes for spec in scope.pathspecs)
        )
        self._union = union and bool(self._pathspecs)
        self._include = include and bool(self._pathspecs)
        self._staged: tuple[StagedChange, ...] | None = None
        self._index_listings: dict[str, dict[str, str] | None] = {}
        self._named_changes: dict[str, str] | None = None
        self._named: frozenset[str] | None = None

    @property
    def repo_root(self) -> Path:
        """The repository root this instance reads files from."""
        return self._repo_root

    @property
    def directory(self) -> Path:
        """The directory the commit's pathspecs are read from."""
        return self._directory

    @property
    def scopes(self) -> tuple[PathspecScope, ...]:
        """Every (directory, pathspecs) the commits' pathspecs are read from, the primary first."""
        return self._scopes

    @property
    def pathspecs(self) -> tuple[str, ...]:
        """The commits' explicit pathspecs; empty when none names a path."""
        return self._pathspecs

    @property
    def index_env(self) -> Mapping[str, str] | None:
        """The environment pointing git at the post-``git add`` index copy, if any."""
        return self._env

    @property
    def union(self) -> bool:
        """Whether the commit is judged as the index plus the named paths."""
        return self._union

    def staged_changes(self) -> tuple[StagedChange, ...]:
        """Changes THIS commit will actually contain.

        Read from git ONCE per instance and held. The commit gate asks this
        question once per plan folder in the tree (``commit_touches_plan``
        from ``row_folder_bijection`` and its siblings), so an unmemoised
        call spawns a subprocess per folder inside a PreToolUse budget --
        measured at 363 spawns against one on this repository's own plan
        tree. An instance is built per context and never outlives the
        decision it informs, so no invalidation is needed: a context that
        wants fresh facts constructs a new instance.

        A bare ``git commit`` (or ``git commit -a``) commits the INDEX, so
        this compares the index to HEAD (``git diff --cached``).

        A ``git commit <pathspec>...`` form instead commits the CURRENT
        WORKING TREE content of exactly the named paths — regardless of
        whether they are staged — and ignores anything ELSE that happens to
        be staged; git does not commit "everything staged plus these
        paths", it commits only these paths' current content. When
        pathspecs were supplied at construction we mirror that exactly: a
        working-tree-vs-HEAD diff (not ``--cached``) scoped to those paths,
        so a modified-but-unstaged path named on the commit line is still
        seen, and a staged-but-unnamed path is correctly excluded.

        ``git commit --include <pathspec>...`` records the index with the named
        paths' working-tree content laid over it (ledger 00474 N245): the
        staged changes to every UNNAMED path, plus the named paths' own
        working-tree-vs-HEAD changes. A staged change to a named path that the
        working tree has since repaired is not among them, because the commit
        does not record it.
        """
        if self._staged is not None:
            return self._staged
        if self._pathspecs:
            outputs = self._pathspec_outputs(
                "diff",
                "HEAD",
                "--name-status",
                "-z",
                "--find-renames",
                NO_RELATIVE,
            )
            changes = None if outputs is None else self._resurrected(_merged_changes(outputs))
            if self._union:
                changes = self._with_all_staged(changes or ())
            elif changes is None:
                # HEAD cannot be diffed (a fresh repository has none): judge the
                # index rather than nothing.
                changes = self._index_changes()
            elif self._include:
                changes = self._with_unnamed_staged(changes)
        else:
            changes = self._index_changes()
        # An unavailable answer is cached too: a wedged or absent git will not
        # recover mid-decision, so re-asking it once per plan folder only
        # multiplies the timeout that made it unavailable.
        self._staged = () if changes is None else changes
        return self._staged

    def _index_changes(self) -> tuple[StagedChange, ...] | None:
        """The index against HEAD, or ``None`` when git could not say."""
        output = self._git_output(
            "diff", "--cached", "--name-status", "-z", "--find-renames", NO_RELATIVE
        )
        return None if output is None else _parse_name_status_z(output)

    def _with_all_staged(self, named_changes: tuple[StagedChange, ...]) -> tuple[StagedChange, ...]:
        """``named_changes`` plus every staged change not already among them.

        The union a commit whose reading is not certain is judged as: whatever
        the pathspecs resolve to, the index is covered.
        """
        seen = {change.path for change in named_changes}
        staged = self._index_changes() or ()
        return named_changes + tuple(change for change in staged if change.path not in seen)

    def _resurrected(self, changes: tuple[StagedChange, ...]) -> tuple[StagedChange, ...]:
        """``changes`` with a named deletion that is still on disk read as a modification.

        ``git rm --cached p`` then an edit: HEAD has ``p``, the index does not,
        and ``git commit p`` records the working tree's ``p``. Diffed against
        HEAD that reads as a deletion of a path the commit in fact keeps.
        """
        if not any(change.status == _DELETED_STATUS for change in changes):
            return changes
        revived = self.resurrected_paths() or frozenset()
        return tuple(
            (
                StagedChange(status="M", path=change.path, old_path=None)
                if change.path in revived and change.status == _DELETED_STATUS
                else change
            )
            for change in changes
        )

    def resurrected_paths(self) -> frozenset[str] | None:
        """Named paths HEAD has and the index lacks, whose file is on disk.

        The commit records each from the working tree, which is the one place
        a diff against HEAD shows them as deleted. ``None`` when git could not
        answer.
        """
        if not self._pathspecs:
            return frozenset()
        changes = self._pathspec_changes()
        if changes is None:
            return None
        return frozenset(
            path
            for path, status in changes.items()
            if status == _DELETED_STATUS and (self._repo_root / path).is_file()
        )

    def every_pathspec_matches(self) -> bool:
        """Whether each pathspec selects at least one path; ``False`` when git cannot say.

        A word that selects nothing is how a misread token shows itself (git
        itself refuses such a commit), so a reading containing one is not
        certain.

        One ``ls-files --error-unmatch`` answers for every pathspec at once. A
        pathspec it cannot find among the index's paths may still select a path
        only HEAD has (``git rm --cached``), so only that rarer shape is asked
        again, one pathspec at a time.
        """
        if not self._pathspecs:
            return True
        everywhere = self._git_output(
            "ls-files", "-z", "--error-unmatch", "--", *self._pathspecs, in_directory=True
        )
        if everywhere is not None:
            return True
        return all(self._pathspec_matches_head_or_index(spec) for spec in self._pathspecs)

    def _pathspec_matches_head_or_index(self, pathspec: str) -> bool:
        """Whether ``pathspec`` selects a path the index holds or HEAD has changed."""
        changed = self._git_output(
            "diff", "HEAD", "--name-only", "-z", NO_RELATIVE, "--", pathspec, in_directory=True
        )
        indexed = self._git_output(
            "ls-files", "-z", "--full-name", "--", pathspec, in_directory=True
        )
        return changed is not None and indexed is not None and bool(changed or indexed)

    def _with_unnamed_staged(
        self, named_changes: tuple[StagedChange, ...]
    ) -> tuple[StagedChange, ...] | None:
        """``named_changes`` plus the staged changes to paths the commit does not name.

        ``None`` when git could not say which paths are named or what is staged.
        """
        named = self.named_paths()
        staged = self._index_changes()
        if named is None or staged is None:
            return None
        unnamed = tuple(
            change for change in staged if change.path not in named and change.old_path not in named
        )
        return named_changes + unnamed

    def named_paths(self) -> frozenset[str] | None:
        """Every path the commit's pathspecs select, repository-relative.

        The paths whose recorded content is the WORKING TREE's: those the index
        holds and those that differ from HEAD there (a staged change the working
        tree has put back is still named). Empty when the pathspecs match
        nothing, which is how a word misread as a pathspec shows itself.
        ``None`` when git could not answer.
        """
        if self._named is not None:
            return self._named
        changes = self._pathspec_changes()
        indexed = self._pathspec_outputs("ls-files", "-z", "--full-name")
        if changes is None or indexed is None:
            return None
        self._named = frozenset(changes) | {
            path for output in indexed for path in output.split(_NUL) if path
        }
        return self._named

    def _pathspec_changes(self) -> dict[str, str] | None:
        """Path -> status letter of what the working tree changes against HEAD, within the pathspecs."""
        if self._named_changes is not None:
            return self._named_changes
        outputs = self._pathspec_outputs(
            "diff",
            "HEAD",
            "--name-status",
            "-z",
            "--no-renames",
            NO_RELATIVE,
        )
        if outputs is None:
            return None
        self._named_changes = {
            change.path: change.status[:1] for change in _merged_changes(outputs)
        }
        return self._named_changes

    def recorded_text(self, path: str) -> str | None:
        """Content of ``path`` as the commit will record it, or ``None`` if unreadable.

        A bare commit records the index. A pathspec commit records the WORKING
        TREE for a named path (``git show :path`` would read the index, which
        can disagree), and under ``--include`` still the index for the rest.
        """
        if self._pathspecs and (not self._include or path in (self.named_paths() or ())):
            return self._working_tree_text(path)
        return self.staged_file_text(path)

    def staged_paths_under(self, prefix: str) -> tuple[str, ...]:
        """New-side staged paths under ``prefix`` (repo-relative, sorted)."""
        normalised = prefix.rstrip("/") + "/"
        return tuple(
            sorted(
                change.path
                for change in self.staged_changes()
                if change.path.startswith(normalised)
            )
        )

    def staged_file_text(self, path: str) -> str | None:
        """Content of ``path`` in the index, or ``None`` when not present."""
        return self._git_output("show", f":{path}")

    def index_listing(self, prefix: str) -> dict[str, str] | None:
        """Every path the commit will record under ``prefix``, mapped to its blob sha.

        Ledger 00474 N244: a commit gate judges the tree the commit WILL
        record, and that is the index, never the disk. ``git rm --cached``
        leaves a file on disk that the commit does not carry; a file deleted
        on disk but still indexed is still carried.

        ONE ``git ls-files -s`` per prefix, held for the instance's life (the
        same reason as :meth:`staged_changes`: the answer is asked once per
        decision, never once per plan folder). Paths are relative to the
        repository root this instance targets. Submodule entries (mode 160000)
        are not files and are left out.

        Ledger 00474 N245: for a ``git commit <pathspec>`` the commit records
        HEAD's tree with the named paths' WORKING-TREE content, and for
        ``--include`` the index with the same overlay. A path whose content
        the commit takes from the working tree is mapped to
        :data:`WORKING_TREE` instead of a sha, because no blob holds it yet;
        :meth:`index_texts` reads it from the disk.

        ``None`` means git could not answer, so the caller can fall back to
        what it did before rather than treat an unreadable index as an empty
        tree.
        """
        if prefix in self._index_listings:
            return self._index_listings[prefix]
        listing = self._recorded_listing(prefix) if self._pathspecs else self._indexed(prefix)
        self._index_listings[prefix] = listing
        return listing

    def _indexed(self, prefix: str) -> dict[str, str] | None:
        """The index under ``prefix``: path -> blob sha."""
        output = self._git_output("ls-files", "-s", "-z", "--", prefix)
        return None if output is None else _parse_index_listing(output)

    def _head_listing(self, prefix: str) -> dict[str, str] | None:
        """HEAD's tree under ``prefix``: path -> blob sha."""
        scope = () if prefix in _WHOLE_TREE_PREFIXES else ("--", prefix)
        output = self._git_output("ls-tree", "-r", "-z", "HEAD", *scope)
        return None if output is None else _parse_tree_listing(output)

    def _recorded_listing(self, prefix: str) -> dict[str, str] | None:
        """The tree a pathspec commit records under ``prefix``.

        Starts from what the commit does NOT take from the working tree (HEAD's
        tree, or the index under ``--include``), then lays each named path's
        working-tree state over it: removed when the working tree deletes it,
        read from the disk when it differs from HEAD, and HEAD's own content
        when the working tree has put it back.
        """
        changes = self._pathspec_changes()
        named = self.named_paths()
        revived = self.resurrected_paths()
        head = self._head_listing(prefix)
        base = self._indexed(prefix) if self._include else head
        if changes is None or named is None or revived is None or head is None or base is None:
            return None
        listing = dict(base)
        for path in named:
            if not _is_under(path, prefix):
                continue
            status = changes.get(path)
            if status is None:
                restored = head.get(path)
                if restored is None:
                    listing.pop(path, None)
                else:
                    listing[path] = restored
            elif status == _DELETED_STATUS and path not in revived:
                listing.pop(path, None)
            else:
                listing[path] = WORKING_TREE
        return listing

    def index_texts(
        self, listing: Mapping[str, str], paths: Sequence[str]
    ) -> dict[str, str] | None:
        """Recorded text of each of ``paths`` found in ``listing``, from one batch.

        A path absent from ``listing`` is absent from the result. Decoding is
        lossy (a mangled character is visible; a gate that cannot read a file
        is not). A path the listing marks :data:`WORKING_TREE` is read from the
        disk. ``None`` when git could not answer or such a file cannot be read.
        """
        wanted = {path: listing[path] for path in paths if path in listing}
        shas = sorted({sha for sha in wanted.values() if sha != WORKING_TREE})
        blobs = read_blobs(self._repo_root, shas, env=self._env)
        if blobs is None:
            return None
        texts: dict[str, str] = {}
        for path, sha in wanted.items():
            if sha == WORKING_TREE:
                text = self._working_tree_text(path)
                if text is None:
                    return None
                texts[path] = text
            elif sha in blobs:
                texts[path] = blobs[sha].decode("utf-8", errors="replace")
        return texts

    def _working_tree_text(self, path: str) -> str | None:
        """Content of ``path`` on disk, or ``None`` when it cannot be read."""
        return read_text_or_reason(self._repo_root / path, errors="replace").text

    def head_file_text(self, path: str) -> str | None:
        """Content of ``path`` at HEAD, or ``None`` when not present."""
        return self._git_output("show", f"HEAD:{path}")

    def last_commit_date(self, path: str) -> date | None:
        """Committer date of the last commit touching ``path`` (None = never)."""
        output = self._git_output("log", "-1", "--format=%cs", "--", path)
        if not output:
            return None
        return date.fromisoformat(output.strip())

    def _pathspec_outputs(self, *args: str) -> list[str] | None:
        """stdout of ``git <args> -- <pathspecs>``, once per scope it may run in.

        With one scope this is :meth:`_git_output` in a list. With several (a
        ``cd`` that may not have taken effect, a second commit) a directory git
        cannot run in (one that does not exist) is skipped, because the commit
        might never have been there; ``None`` only when no scope could answer.
        """
        outputs: list[str] = []
        for scope in self._scopes:
            result = self._run(scope.directory, *args, _END_OF_OPTIONS, *scope.pathspecs)
            if result.returncode == 0:
                outputs.append(result.stdout)
        return outputs or None

    def _run(self, directory: Path, *args: str) -> "subprocess.CompletedProcess[str]":
        """``git <args>`` in ``directory``, reading the post-``git add`` index when there is one."""
        return run_git(directory, *args, timeout=Timeout.GIT_CONTEXT, env=self._env)

    def _git_output(self, *args: str, in_directory: bool = False) -> str | None:
        """Run a read-only git command; stdout on success, ``None`` on non-zero.

        A non-zero exit here is a documented "fact not available" signal
        (unknown path, empty repo), not a hidden error: the caller branches
        on ``None`` and surfaces the absence as a finding where relevant.

        Routed through :func:`run_git` rather than spawning git here, so the
        declined optional index lock applies. This code ran
        ``git diff --cached`` with its own inline spawn, which refreshes and
        REWRITES ``.git/index`` — from the commit gate, at the exact moment the
        agent needs ``.git/index.lock`` for the commit being gated. Plan 00246
        centralised every other spawn for this reason and missed this one
        because the guard could not see an argv whose head was a module
        constant.

        ``run_git`` also never raises, so a wedged git yields ``None``
        (the "fact not available" answer this method already documents) instead
        of a ``TimeoutExpired`` escaping into hook dispatch.

        ``in_directory`` runs it where the commit command runs, which is the
        only place its pathspecs mean what the commit takes them to mean.
        """
        root = self._directory if in_directory else self._repo_root
        result = self._run(root, *args)
        if result.returncode != 0:
            return None
        return result.stdout


def _merged_changes(outputs: Sequence[str]) -> tuple[StagedChange, ...]:
    """The changes of every ``--name-status -z`` output, each path once, first seen first."""
    merged: dict[str, StagedChange] = {}
    for output in outputs:
        for change in _parse_name_status_z(output):
            merged.setdefault(change.path, change)
    return tuple(merged.values())


def commit_facts(
    reading: CommitReading,
    repo_root: Path,
    cwd: str | Path | None = None,
    index_env: Mapping[str, str] | None = None,
) -> GitFactsBase:
    """The facts a commit gate should judge ``reading`` by.

    The pathspec view (only the named paths' working tree) is used ONLY when the
    reading is certain and every pathspec selects something. Any other shape is
    the union: the index with the named paths' working-tree changes laid over
    it, so no gate ever reads less of the recorded tree than the index.

    ``cwd`` is where the command runs; each commit's pathspecs are read from
    every directory it may run in (see :func:`commit_scopes`). ``index_env``
    points every read at the index a same-command ``git add`` leaves (see
    :func:`~claude_code_hooks_daemon.utils.staging_simulation.simulated_staging`).
    """
    scopes = commit_scopes(reading, cwd, repo_root)
    if not scopes:
        return GitFactsBase(repo_root, index_env=index_env)
    primary, *others = scopes
    if reading.certain and not others:
        facts = GitFactsBase(
            repo_root,
            pathspecs=primary.pathspecs,
            include=reading.form.include,
            directory=primary.directory,
            index_env=index_env,
        )
        if facts.every_pathspec_matches():
            return facts
    return GitFactsBase(repo_root, union=True, scopes=scopes, index_env=index_env)


def commit_scopes(
    reading: CommitReading, cwd: str | Path | None, repo_root: Path
) -> tuple[PathspecScope, ...]:
    """Every (directory, pathspecs) the pathspecs of ``reading``'s commits are read from.

    Ledger 00474 N307: each ``git commit`` of the command is judged, not only the
    first, and each reads its pathspecs where IT runs. A commit with no pathspec
    adds no scope; the index it records is judged as always. The directories of
    one commit are those of :func:`run_directories`, the one it moves to first.
    """
    scopes: dict[PathspecScope, None] = {}
    for run in _commit_runs(reading):
        if not run.form.pathspecs:
            continue
        for directory in run_directories(run.moves, run.optional_moves, cwd, repo_root):
            scopes[PathspecScope(directory, run.form.pathspecs)] = None
    return tuple(scopes)


def _commit_runs(reading: CommitReading) -> tuple[CommitRun, ...]:
    """The commits of ``reading``; one built from its own fields when it carries none."""
    if reading.runs:
        return reading.runs
    return (
        CommitRun(
            form=reading.form,
            moves=reading.moves,
            optional_moves=0 if reading.moves_certain else len(reading.moves),
        ),
    )


#: Past this many ``cd`` moves that may not have taken effect, only the whole
#: chain, each move alone and none of them are tried, not every subset.
_MAX_SUBSET_MOVES: Final[int] = 5


def run_directories(
    moves: Sequence[str | None], optional: int, cwd: str | Path | None, repo_root: Path
) -> tuple[Path, ...]:
    """Every directory inside ``repo_root`` a command with ``moves`` may run git in.

    The :func:`landing_directories` that lie inside the repository; ``cwd`` (or
    ``repo_root`` without one) stands in when none does, so there is always a
    directory to read from.
    """
    if not cwd:
        return (repo_root,)
    inside = [
        found
        for landed in landing_directories(moves, optional, Path(cwd))
        if (found := _directory_inside(landed, repo_root)) is not None
    ]
    return tuple(dict.fromkeys(inside)) or (_directory_inside(cwd, repo_root) or repo_root,)


def landing_directories(
    moves: Sequence[str | None], optional: int, start: Path
) -> tuple[Path, ...]:
    """Every directory a command that starts in ``start`` and makes ``moves`` may run git in.

    ``moves`` is the ``cd``/``pushd`` chain followed by the ``-C`` operands, and
    ``optional`` is how many leading ones may not have taken effect (ledger 00474
    N306: ``cd sub || cd x`` runs ONE of them, ``cd nosuch; git ...`` none). Every
    way those can combine is a place git may run, so each is returned; the
    ``-C`` operands always apply. The directory every move takes the command to
    comes first. A move this reading cannot state drops the combinations that
    contain it.
    """
    optional_moves, fixed_moves = tuple(moves[:optional]), tuple(moves[optional:])
    if len(optional_moves) > _MAX_SUBSET_MOVES:
        chains: list[tuple[str | None, ...]] = [
            optional_moves,
            *((move,) for move in optional_moves),
            (),
        ]
    else:
        chains = [
            chain
            for size in range(len(optional_moves), -1, -1)
            for chain in combinations(optional_moves, size)
        ]
    landed = (_moved(start, (*chain, *fixed_moves)) for chain in chains)
    return tuple(dict.fromkeys(found for found in landed if found is not None))


def _moved(start: Path, moves: Sequence[str | None]) -> Path | None:
    """``start`` after ``moves``, or ``None`` when one of them cannot be stated."""
    here = start
    for move in moves:
        if move is None:
            return None
        here = here / move
    return here.resolve()


def commit_directory(reading: CommitReading, start: str | Path) -> Path | None:
    """The directory the commit runs in, after the ``cd``/``pushd``/``-C`` moves before it.

    ``start`` is where the command begins (the hook's ``cwd``). ``None`` when a
    move cannot be stated (``cd -``, a variable, ``--git-dir``): the caller then
    reads the command as it would have without the move.
    """
    return _moved(Path(start), reading.moves)


def commit_runs_in_foreign_repo(
    reading: CommitReading, cwd: str | Path | None, project_root: Path
) -> bool:
    """True when the commit runs in a repository other than the project's.

    Ledger 00474 N300/N305: a nested worktree or another checkout owns its own
    index. Where the commit runs is the hook's ``cwd`` after any ``cd``/``-C``
    move before it; a move this reading cannot state is judged against this
    project. A ``cd`` that may not have taken effect leaves two places the
    commit could run, and it stands down only when BOTH are another repository.
    """
    if not cwd:
        return False
    moved = commit_directory(reading, cwd)
    places = [moved if moved is not None else Path(cwd)]
    if not reading.moves_certain:
        places.append(Path(cwd))
    for place in places:
        repo = GitRepo.resolve_for(place)
        if repo is None or repo.root == project_root:
            return False
    return True


def _directory_inside(cwd: str | Path | None, repo_root: Path) -> Path | None:
    """``cwd`` as a path when it lies inside ``repo_root``, else ``None``."""
    if not cwd:
        return None
    candidate = Path(cwd).resolve()
    return candidate if path_is_relative_to(candidate, repo_root.resolve()) else None


def project_relative_head_text(file_path: Path, project_root: Path) -> str | None:
    """``file_path``'s content at git HEAD, resolved against ``project_root``.

    Shared by every PostToolUse handler that needs "what did this file say a
    moment ago" once a Write/Edit has already landed on disk (ledger 00466
    N3): ``goal_injection`` and ``recovery_cron_advisor`` both compare a
    just-written PLAN.md against this to tell a real status TRANSITION from
    a write that merely lands on a file already in that state.

    Returns ``None`` for every "nothing to compare against" case alike — no
    repository, ``file_path`` outside ``project_root``, or a path HEAD has
    never seen (new file, never committed) — so a caller with nothing to
    diff against can only read the write as a genuine transition, never as
    an error. Membership is a plain comparison (``Path.is_relative_to``),
    never a caught ``ValueError``.

    ``project_root`` is a parameter, not ``ProjectContext.project_root()``
    called here, so this module stays core-free (review nit n3 — its own
    docstring above claims exactly that, and every caller already resolves
    ``ProjectContext.project_root()`` unguarded for its own other purposes,
    so nothing is lost by asking it to pass the value through rather than
    this module importing ``core`` to fetch it a second time).

    HEAD is read from ``file_path``'s OWN enclosing repository (ledger
    00466 review m5), not from ``project_root``'s — a nested checkout
    under the project root (a linked worktree under ``untracked/worktrees/``,
    or any other nested clone) is a SEPARATE repository whose HEAD the
    project root's repo never tracks. Reading against the project root
    there would run ``git show HEAD:<path-project-root-never-committed>``,
    which always answers "absent" — silently misreading every write in a
    nested checkout as a genuine transition. :func:`GitRepo.resolve_for`
    (the same ``git -C <dir> rev-parse --show-toplevel`` this project
    already centralises) finds the file's real containing repo; a project
    root that is itself a plain git checkout (the common case) resolves to
    itself, so nothing changes there.
    """
    root = project_root.resolve()
    resolved = file_path.resolve()
    if not path_is_relative_to(resolved, root):
        return None
    repo = GitRepo.resolve_for(resolved)
    if repo is None or not path_is_relative_to(resolved, repo.root):
        return None
    return GitFactsBase(repo.root).head_file_text(path_relative_to(resolved, repo.root).as_posix())


def _parse_index_listing(output: str) -> dict[str, str]:
    """Parse ``ls-files -s -z`` (``<mode> <sha> <stage>\\t<path>``) into path -> sha."""
    listing: dict[str, str] = {}
    for record in output.split(_NUL):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        mode, sha, _stage = meta.split(" ")
        if mode == _GITLINK_MODE:
            continue
        listing[path] = sha
    return listing


def _parse_tree_listing(output: str) -> dict[str, str]:
    """Parse ``ls-tree -r -z`` (``<mode> <type> <sha>\\t<path>``) into path -> sha."""
    listing: dict[str, str] = {}
    for record in output.split(_NUL):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        _mode, kind, sha = meta.split(" ")
        if kind == _GITLINK_TYPE:
            continue
        listing[path] = sha
    return listing


def _is_under(path: str, prefix: str) -> bool:
    """Whether the repository-relative ``path`` is ``prefix`` or lies beneath it."""
    if prefix in _WHOLE_TREE_PREFIXES:
        return True
    directory = prefix.rstrip("/")
    return path == directory or path.startswith(f"{directory}/")


def _parse_name_status_z(output: str) -> tuple[StagedChange, ...]:
    """Parse NUL-separated ``--name-status -z`` output into changes."""
    tokens = [token for token in output.split(_NUL) if token]
    changes: list[StagedChange] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        if status.startswith(_TWO_PATH_STATUS_PREFIXES):
            changes.append(
                StagedChange(status=status, path=tokens[index + 2], old_path=tokens[index + 1])
            )
            index += 3
        else:
            changes.append(StagedChange(status=status, path=tokens[index + 1], old_path=None))
            index += 2
    return tuple(changes)
