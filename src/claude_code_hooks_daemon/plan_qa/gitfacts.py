"""GitFacts — read-only git facts for plan QA (Plan 00144, Task 1.4).

The generic half lives in :mod:`claude_code_hooks_daemon.utils.git_facts`:
staged changes with rename detection, staged/HEAD file contents, last-commit
dates. Docs QA needs exactly those and nothing else, and importing them from
here made docs QA depend on plan QA for plumbing that has nothing to do with
plans (Plan 00444, from ledger 00422 N14).

What remains here is the one thing that genuinely IS plan-specific: the
authoritative plan counter (``hooksdaemon.latestPlanNumber``), read via the
shared :mod:`handlers.utils.plan_numbering` reader.

``StagedChange`` is re-exported so every existing plan-QA caller and test
imports it from the same place as before.

Strictly read-only: neither half ever mutates the repository.
"""

from claude_code_hooks_daemon.handlers.utils.plan_numbering import read_plan_counter
from claude_code_hooks_daemon.utils.git_facts import GitFactsBase, StagedChange

__all__ = ["GitFacts", "StagedChange"]


class GitFacts(GitFactsBase):
    """Read-only git facts for one repository root, plus the plan counter."""

    def plan_counter(self) -> int | None:
        """The repo's ``hooksdaemon.latestPlanNumber`` counter (None = unset)."""
        return read_plan_counter(self._repo_root)
