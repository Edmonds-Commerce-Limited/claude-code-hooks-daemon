"""Freshness governance for reference repositories (Plan 00401).

A convention this project and its siblings share: read-only clones of upstream
repositories are kept under ``untracked/repos/`` so an agent can consult real
source rather than recalling it. The failure this package exists to prevent is
an agent reading such a clone WITHOUT pulling, reasoning from a weeks-old
checkout, and producing conclusions indistinguishable from correct ones.

One checker, three surfaces — a SessionStart sweep that does the network work, a
PreToolUse backstop that reads cached state only, and a CLI report — so the
three can never disagree about what "stale" means.

What actually enforces that is :mod:`sweep` and :mod:`report`: one pipeline the
sweep and the CLI both spend, and one renderer all three describe a repository
through. The re-exports below are the package's public surface, not the
mechanism — a consumer reaching into a submodule still gets the shared
behaviour, because the shared behaviour lives in the modules rather than in how
they are addressed.
"""

from __future__ import annotations

from claude_code_hooks_daemon.reference_repos.cache import (
    DEFAULT_TTL_SECONDS,
    cache_path,
    cached_states,
    write_cache,
)
from claude_code_hooks_daemon.reference_repos.discovery import (
    DEFAULT_MAX_DEPTH,
    discover_reference_repos,
)
from claude_code_hooks_daemon.reference_repos.inspection import inspect_repo
from claude_code_hooks_daemon.reference_repos.model import Checkability, RepoState
from claude_code_hooks_daemon.reference_repos.refresh import RefreshOutcome, refresh_repo
from claude_code_hooks_daemon.reference_repos.report import (
    NOT_VERIFIED_HEADLINE,
    UNCONFIRMED_HEADLINE,
    remediation_command,
    repo_line,
    report_lines,
    unconfirmed_note,
)
from claude_code_hooks_daemon.reference_repos.sweep import (
    governed_roots,
    sweep_reference_repos,
)

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_TTL_SECONDS",
    "NOT_VERIFIED_HEADLINE",
    "UNCONFIRMED_HEADLINE",
    "Checkability",
    "RefreshOutcome",
    "RepoState",
    "cache_path",
    "cached_states",
    "discover_reference_repos",
    "governed_roots",
    "inspect_repo",
    "refresh_repo",
    "remediation_command",
    "repo_line",
    "report_lines",
    "sweep_reference_repos",
    "unconfirmed_note",
    "write_cache",
]
