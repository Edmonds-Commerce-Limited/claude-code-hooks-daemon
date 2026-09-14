"""Freshness governance for reference repositories (Plan 00401).

A convention this project and its siblings share: read-only clones of upstream
repositories are kept under ``untracked/repos/`` so an agent can consult real
source rather than recalling it. The failure this package exists to prevent is
an agent reading such a clone WITHOUT pulling, reasoning from a weeks-old
checkout, and producing conclusions indistinguishable from correct ones.

One checker, three surfaces — a SessionStart sweep that does the network work, a
PreToolUse backstop that reads cached state only, and a CLI report — so the
three can never disagree about what "stale" means. Consumers import from this
package rather than reaching into its modules, which is what keeps that promise
enforceable.
"""

from __future__ import annotations

from claude_code_hooks_daemon.reference_repos.discovery import (
    DEFAULT_MAX_DEPTH,
    discover_reference_repos,
)

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "discover_reference_repos",
]
