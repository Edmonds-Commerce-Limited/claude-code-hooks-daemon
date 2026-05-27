"""First-class git repository access (Plan 00113).

A single, bounded home for the git subprocess calls the daemon needs: resolve
the enclosing repo of a path, and read/write ``git config --local`` values.

SOLID:

- **Single Responsibility**: this module's only job is talking to git. Callers
  express intent (resolve / read_config / write_config) and never own argv,
  timeouts, or the None-on-failure convention.
- **Open/Closed**: new git operations are added as methods on :class:`GitRepo`,
  not by re-implementing ``subprocess.run(["git", ...])`` in each caller.
- **Dependency Inversion**: handlers and utilities depend on this typed
  surface, not on subprocess internals. Typed facades (e.g. a plan-number
  counter that returns ``int``) layer on top of ``read_config`` → ``str | None``.
"""

from __future__ import annotations

import subprocess  # nosec B404 — only ever runs the trusted system ``git`` binary
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout


def _git_output(cwd: Path, *args: str) -> str | None:
    """Run ``git -C <cwd> <args>`` and return stripped stdout, else ``None``.

    ``None`` means git was unavailable (OSError/SubprocessError), the command
    exited non-zero (e.g. not a git repo, config key absent), or stdout was
    empty. This is feature-detection — 'not a repo' / 'key absent' IS the
    answer — not error-hiding. Bounded by ``Timeout.GIT_CONTEXT`` so a wedged
    git cannot stall hook dispatch.
    """
    try:
        result = subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=Timeout.GIT_CONTEXT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


@dataclass(frozen=True)
class GitRepo:
    """A resolved git repository root, with local-config read/write."""

    root: Path

    @classmethod
    def resolve_for(cls, path: Path) -> GitRepo | None:
        """Return the nearest enclosing git repo of ``path``, or ``None``.

        ``path`` is often a file/dir about to be created, so it may not exist
        yet — walk up to the first existing ancestor before asking git. Returns
        ``None`` when no enclosing git repo is found.
        """
        start = path if path.is_dir() else path.parent
        while not start.exists() and start != start.parent:
            start = start.parent
        top = _git_output(start, "rev-parse", "--show-toplevel")
        return cls(Path(top)) if top else None

    def read_config(self, key: str) -> str | None:
        """Read a ``--local`` config value, or ``None`` when unset/unavailable.

        Type-agnostic: returns the raw string. Typed parsing (int, bool, …) is
        the caller's responsibility.
        """
        return _git_output(self.root, "config", "--local", "--get", key)

    def write_config(self, key: str, value: str) -> None:
        """Set a ``--local`` config value.

        FAIL FAST: raises ``CalledProcessError`` if git rejects the write, so
        callers that need resilience wrap the call explicitly rather than the
        failure being silently lost.
        """
        subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
            ["git", "-C", str(self.root), "config", "--local", key, value],
            capture_output=True,
            text=True,
            timeout=Timeout.GIT_CONTEXT,
            check=True,
        )
