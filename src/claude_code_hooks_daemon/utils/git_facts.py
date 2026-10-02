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
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils.git_repo import GitRepo, read_blobs, run_git
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to, path_relative_to

# name-status codes that carry TWO paths (old NUL new) in -z output.
_TWO_PATH_STATUS_PREFIXES: Final[tuple[str, ...]] = ("R", "C")

_NUL: Final[str] = "\0"

# ``ls-files -s`` mode of a submodule entry: a commit pointer, not a file.
_GITLINK_MODE: Final[str] = "160000"


@dataclass(frozen=True)
class StagedChange:
    """One entry from ``git diff --cached --name-status``."""

    status: str
    path: str
    old_path: str | None


class GitFactsBase:
    """Read-only git facts for one repository root."""

    def __init__(self, repo_root: Path, pathspecs: Sequence[str] | None = None) -> None:
        """Initialise.

        Args:
            repo_root: Repository root ``git -C`` targets.
            pathspecs: The commit's explicit pathspec arguments, when the
                inspected ``git commit`` invocation names paths directly
                (``git commit <pathspec>...``). ``None``/empty means a bare
                commit (or ``-a``), which commits the INDEX — the original,
                unscoped behaviour. See :meth:`staged_changes`.
        """
        self._repo_root = repo_root
        self._pathspecs = tuple(pathspecs) if pathspecs else ()
        self._staged: tuple[StagedChange, ...] | None = None
        self._index_listings: dict[str, dict[str, str] | None] = {}

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
        """
        if self._staged is not None:
            return self._staged
        if self._pathspecs:
            output = self._git_output(
                "diff",
                "HEAD",
                "--name-status",
                "-z",
                "--find-renames",
                "--",
                *self._pathspecs,
            )
        else:
            output = self._git_output("diff", "--cached", "--name-status", "-z", "--find-renames")
        # An unavailable answer is cached too: a wedged or absent git will not
        # recover mid-decision, so re-asking it once per plan folder only
        # multiplies the timeout that made it unavailable.
        self._staged = () if output is None else _parse_name_status_z(output)
        return self._staged

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

        ``None`` means git could not answer, so the caller can fall back to
        what it did before rather than treat an unreadable index as an empty
        tree.
        """
        if prefix in self._index_listings:
            return self._index_listings[prefix]
        output = self._git_output("ls-files", "-s", "-z", "--", prefix)
        listing = None if output is None else _parse_index_listing(output)
        self._index_listings[prefix] = listing
        return listing

    def index_texts(
        self, listing: Mapping[str, str], paths: Sequence[str]
    ) -> dict[str, str] | None:
        """Staged text of each of ``paths`` found in ``listing``, from one batch.

        A path absent from ``listing`` is absent from the result. Decoding is
        lossy (a mangled character is visible; a gate that cannot read a file
        is not). ``None`` when git could not answer.
        """
        wanted = {path: listing[path] for path in paths if path in listing}
        blobs = read_blobs(self._repo_root, sorted(set(wanted.values())))
        if blobs is None:
            return None
        return {
            path: blobs[sha].decode("utf-8", errors="replace")
            for path, sha in wanted.items()
            if sha in blobs
        }

    def head_file_text(self, path: str) -> str | None:
        """Content of ``path`` at HEAD, or ``None`` when not present."""
        return self._git_output("show", f"HEAD:{path}")

    def last_commit_date(self, path: str) -> date | None:
        """Committer date of the last commit touching ``path`` (None = never)."""
        output = self._git_output("log", "-1", "--format=%cs", "--", path)
        if not output:
            return None
        return date.fromisoformat(output.strip())

    def _git_output(self, *args: str) -> str | None:
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
        """
        result = run_git(self._repo_root, *args, timeout=Timeout.GIT_CONTEXT)
        if result.returncode != 0:
            return None
        return result.stdout


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
