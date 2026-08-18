"""GitFacts — read-only git facts for plan QA (Plan 00144, Task 1.4).

Everything the cross-file checks need from git, behind one small class:

- staged changes (``git diff --cached``) with rename detection, so the
  commit gate can see terminal-status flips, ``git mv`` moves, and README
  diffs in the STAGED tree — not the working tree
- staged/HEAD file contents (``git show``) for parsing PLAN.md / README.md
  exactly as they will be committed
- the authoritative plan counter (``hooksdaemon.latestPlanNumber``), via the
  shared :mod:`handlers.utils.plan_numbering` reader (single source of truth)
- last-commit dates per path for the staleness sweep

Strictly read-only: this module never mutates the repository.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.handlers.utils.plan_numbering import read_plan_counter
from claude_code_hooks_daemon.utils.git_repo import run_git

# name-status codes that carry TWO paths (old NUL new) in -z output.
_TWO_PATH_STATUS_PREFIXES: Final[tuple[str, ...]] = ("R", "C")

_NUL: Final[str] = "\0"


@dataclass(frozen=True)
class StagedChange:
    """One entry from ``git diff --cached --name-status``."""

    status: str
    path: str
    old_path: str | None


class GitFacts:
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

    def staged_changes(self) -> tuple[StagedChange, ...]:
        """Changes THIS commit will actually contain.

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
        if output is None:
            return ()
        return _parse_name_status_z(output)

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

    def head_file_text(self, path: str) -> str | None:
        """Content of ``path`` at HEAD, or ``None`` when not present."""
        return self._git_output("show", f"HEAD:{path}")

    def plan_counter(self) -> int | None:
        """The repo's ``hooksdaemon.latestPlanNumber`` counter (None = unset)."""
        return read_plan_counter(self._repo_root)

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
        declined optional index lock applies. This module ran
        ``git diff --cached`` with its own inline spawn, which refreshes and
        REWRITES ``.git/index`` — from the commit gate, at the exact moment the
        agent needs ``.git/index.lock`` for the commit being gated. Plan 00246
        centralised every other spawn for this reason and missed this one
        because the guard could not see an argv whose head was a module
        constant.

        ``run_git`` also never raises, so a wedged git now yields ``None``
        (the "fact not available" answer this method already documents) instead
        of a ``TimeoutExpired`` escaping into hook dispatch.
        """
        result = run_git(self._repo_root, *args, timeout=Timeout.GIT_CONTEXT)
        if result.returncode != 0:
            return None
        return result.stdout


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
