"""Scope of a ``git merge``/``pull``/``rebase``: did it run, and what did it touch?

Extracted from ``merge_qa_report`` (Plan 00373) when a second handler needed the
same two answers (Plan 00389). Both halves are shared deliberately rather than
copied:

- **Matching the operation** is evasion-resistant, tolerating global options
  (``git -C``), an ``env``/``VAR=`` prefix and line continuations. A
  command-evasion pattern maintained in two places eventually diverges, and the
  copy that quietly stops matching is the one nobody notices.
- **Attributing the change** uses ``git diff --name-only ORIG_HEAD HEAD``, which
  names only what THIS operation introduced. That bound is what keeps a post-merge
  advisory from re-reporting the whole tree's pre-existing drift on every single
  merge — the noise failure that gets an advisory ignored.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.command_evasion import (
    ENV_PREFIX,
    GIT_INVOCATION,
    normalise_line_continuations,
)
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

# A newline separates commands exactly as `;` does (the same lesson
# `staged_lint_gate`/`verification_result_gate` already encode), and
# `&&`/`||`/`|` each start a new command span within a statement.
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("||", "&&", "|", ";", "\n")

_GIT_MERGE_PULL_REBASE_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"^\s*{ENV_PREFIX}{GIT_INVOCATION}(?:merge|pull|rebase)(?=\s|$)"
)


def is_git_merge_pull_rebase_command(command: str) -> bool:
    """Whether any segment of ``command`` is a ``git merge``/``pull``/``rebase``.

    Evasion-resistant via the same fragments `staged_lint_gate` uses: global
    options (`git -C`), an `env`/`VAR=` prefix, and line continuations
    (normalised before segmenting).
    """
    normalised = normalise_line_continuations(command)
    for segment in split_unquoted(normalised, _SEGMENT_SEPARATORS):
        if _GIT_MERGE_PULL_REBASE_PATTERN.search(segment.strip()):
            return True
    return False


def changed_paths(project_root: Path) -> frozenset[str]:
    """Repo-relative paths ``ORIG_HEAD..HEAD`` touched; empty when unavailable.

    Empty covers every silent case in ONE return: ``ORIG_HEAD`` absent (git
    exits non-zero -- unknown revision), git failing outright (also non-zero),
    and ``ORIG_HEAD`` resolving to the same commit as ``HEAD`` (nothing to
    diff, empty stdout). A caller need only check truthiness.
    """
    result = run_git(project_root, "diff", "--name-only", "ORIG_HEAD", "HEAD")
    if result.returncode != 0:
        return frozenset()
    return frozenset(line.strip() for line in result.stdout.splitlines() if line.strip())


def changed_path_is_or_is_under(candidate: str, changed: frozenset[str]) -> bool:
    """Whether some changed path equals ``candidate`` or is nested under it."""
    normalised = candidate.rstrip("/")
    prefix = normalised + "/"
    return any(path == normalised or path.startswith(prefix) for path in changed)
