"""The git-backed :class:`~routines.intervals.Ancestry` oracle (Plan 00412).

:mod:`routines.intervals` keeps git out of the arithmetic deliberately, so the
composition stays pure and the healthy case — a consecutive pair that meets —
short-circuits on string equality and never pays for a subprocess. This module
is the edge where git comes back in, and the whole of it is about the answers
that are neither "yes" nor "no".

``git merge-base --is-ancestor`` signals through its EXIT CODE: 0 for yes, 1
for no, and something else when it could not answer — an unknown ref, a
rebased-away sha, a path that is not a repository at all. The protocol's
contract is that an unknown or unreachable ref **is not an ancestor of
anything**, so every one of those becomes False.

Spawned through :func:`utils.git_repo.run_git` rather than directly, which is
the project's single git entry point (Plan 00246): it declines git's optional
index lock and carries a timeout by construction. Declining the lock matters
even for a read like this one, because the sweep runs in the working tree an
agent is actively using. ``run_git`` also never raises — a missing binary or a
timeout arrives as a non-zero return code — which folds neatly into the
exit-code reading below instead of needing a second failure path.

That is a deliberate choice about WHERE a problem surfaces, not a swallowed
error. Returning False sends the pair to :data:`Continuity.UNRELATED`, which
is a finding a QA sweep reports and a human can act on. Raising instead would
abort the sweep, and a sweep that reports nothing looks exactly like a sweep
that found nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.git_repo import run_git

logger = logging.getLogger(__name__)

#: Exit code meaning "yes, an ancestor".
_IS_ANCESTOR: Final[int] = 0
#: Exit code meaning "no, not an ancestor". A real answer, not a failure.
_NOT_ANCESTOR: Final[int] = 1

#: Ceiling for one `merge-base` call. It is a local object-database lookup, so
#: this is a wedged-git guard rather than a budget.
_TIMEOUT_SECONDS: Final[int] = 30


class GitAncestry:
    """Answers ancestry questions for one repository.

    Not cached: :func:`routines.intervals.discontinuities` consults the oracle
    only for pairs that do NOT meet, so a healthy routine asks nothing and an
    unhealthy one asks about as many times as it has breaks. Adding a cache
    would optimise the case that is already a finding.
    """

    def __init__(self, repo_root: Path) -> None:
        """Bind the oracle to a repository.

        Args:
            repo_root: Directory to run git in. It need not exist — a path
                that is not a repository answers False to everything, which
                is the honest reading of "no history says otherwise".
        """
        self._repo_root = repo_root

    def is_ancestor(self, earlier: str, later: str) -> bool:
        """Whether ``earlier`` is an ancestor of ``later``.

        Args:
            earlier: Candidate ancestor — a commit or a tag (D12 anchors runs
                to release tags, so both must resolve).
            later: Candidate descendant.

        Returns:
            True only when git says so. Every other outcome — not an ancestor,
            an unresolvable ref, not a repository — is False.
        """
        completed = run_git(
            self._repo_root,
            "merge-base",
            "--is-ancestor",
            earlier,
            later,
            timeout=_TIMEOUT_SECONDS,
        )

        if completed.returncode == _IS_ANCESTOR:
            return True
        if completed.returncode == _NOT_ANCESTOR:
            return False

        # Git could not answer: an unknown ref, a rebased-away sha, or not a
        # repository. Logged rather than raised -- see the module docstring on
        # why a reportable UNRELATED beats an aborted sweep.
        logger.info(
            "routines: git could not resolve ancestry for %s..%s in %s "
            "(exit %d: %s); treating as not-an-ancestor",
            earlier,
            later,
            self._repo_root,
            completed.returncode,
            completed.stderr.strip(),
        )
        return False
