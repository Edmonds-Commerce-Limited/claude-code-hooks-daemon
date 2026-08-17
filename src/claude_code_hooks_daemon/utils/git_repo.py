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

import os
import subprocess  # nosec B404 — only ever runs the trusted system ``git`` binary
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.timeout import Timeout

#: ``git status`` is not a read. It refreshes the index and writes it back,
#: which acquires ``.git/index.lock`` — so a daemon merely ASKING whether a file
#: is dirty contends for the lock with the agent working in the same tree, and a
#: holder killed mid-flight leaves the lock orphaned. This variable tells git to
#: skip operations needing an OPTIONAL lock; locks a command genuinely requires
#: are still taken, so it is safe on writes as well as reads (Plan 00246).
_OPTIONAL_LOCKS_VAR: Final[str] = "GIT_OPTIONAL_LOCKS"
_OPTIONAL_LOCKS_DECLINED: Final[str] = "0"

#: Reported when git could not be run at all (absent binary, timeout). Mirrors
#: the shell's "command not found" so callers branching on ``returncode`` need
#: no special case for it.
_GIT_UNAVAILABLE: Final[int] = 127


def run_git(
    cwd: Path, *args: str, timeout: float = Timeout.GIT_CONTEXT
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C <cwd> <args>`` without taking git's optional index lock.

    THE single place the daemon spawns git. Centralised so that the two
    properties every invocation needs — declining the optional index lock, and a
    timeout — hold by construction rather than per call site. Fifteen files once
    re-implemented this inline, which is how a one-line fix became a thirty-site
    sweep (Plan 00246).

    Never raises: an absent git binary or a timeout is reported as a non-zero
    ``returncode`` with the reason in ``stderr``. That is the same
    feature-detection convention :func:`_git_output` documents — 'not a repo' IS
    the answer — and it keeps a wedged git from stalling hook dispatch or
    aborting daemon startup.
    """
    argv = ["git", "-C", str(cwd), *args]
    try:
        return subprocess.run(  # nosec B603 B607 — fixed argv, no shell, trusted binary
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, _OPTIONAL_LOCKS_VAR: _OPTIONAL_LOCKS_DECLINED},
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, _GIT_UNAVAILABLE, "", str(exc))


def _git_output(cwd: Path, *args: str) -> str | None:
    """Run git and return stripped stdout, else ``None``.

    ``None`` means git was unavailable, the command exited non-zero (e.g. not a
    git repo, config key absent), or stdout was empty. This is feature-detection
    — 'not a repo' / 'key absent' IS the answer — not error-hiding.
    """
    result = run_git(cwd, *args)
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
        failure being silently lost. Goes through :func:`run_git` like every
        other invocation and re-raises here, rather than keeping its own
        ``check=True`` spawn outside the one bounded home.
        """
        result = run_git(self.root, "config", "--local", key, value)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr
            )
