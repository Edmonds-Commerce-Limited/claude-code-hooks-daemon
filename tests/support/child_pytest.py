"""The one way the suite starts a child pytest (Plan 00474 N531).

A child pytest started with ``subprocess.run`` and the caller's environment
shares the caller's ``/tmp/pytest-of-<user>`` tree, inherits whatever the
outer run exported, and, when it hangs, reports nothing but
``TimeoutExpired``. ``run_child_pytest`` gives every child:

- its own ``--basetemp`` under the caller's ``tmp_path``, so the child's exit
  cleanup never sweeps the shared tree;
- an environment built explicitly from a short allowlist plus what the caller
  names, so nothing incidental leaks in;
- a ``faulthandler`` watchdog set at ``WATCHDOG_FRACTION`` of the timeout, so a
  hang prints the child's stacks before the caller kills it.

It raises ``ChildPytestError`` carrying the child's stdout and stderr on a
timeout or an unexpected exit code. It never retries.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants import Timeout
from tests.support.child_pytest_plugin.child_pytest_watchdog import DEADLINE_ENV

#: Share of the caller's timeout after which the child dumps its stacks.
WATCHDOG_FRACTION: Final[float] = 0.75

#: Keys the helper sets itself; ``extra_env`` may not name them.
HELPER_OWNED_ENV_KEYS: Final[frozenset[str]] = frozenset(
    {"PYTEST_ADDOPTS", "PYTHONPATH", "PYTHONUNBUFFERED", DEADLINE_ENV}
)

#: The only ambient variables a child inherits.
_INHERITED_ENV_KEYS: Final[tuple[str, ...]] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
)

_PLUGIN_DIR: Final[Path] = Path(__file__).resolve().parent / "child_pytest_plugin"
_PLUGIN_MODULE: Final[str] = "child_pytest_watchdog"


class ChildPytestError(AssertionError):
    """A child pytest timed out or exited with an unexpected code."""


def _child_env(
    basetemp: Path,
    deadline: float,
    extra_env: Mapping[str, str],
    pythonpath: Sequence[Path],
) -> dict[str, str]:
    env = {key: os.environ[key] for key in _INHERITED_ENV_KEYS if key in os.environ}
    env.update(extra_env)
    env["PYTEST_ADDOPTS"] = shlex.join(["-p", _PLUGIN_MODULE, f"--basetemp={basetemp}"])
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in (_PLUGIN_DIR, *pythonpath))
    env["PYTHONUNBUFFERED"] = "1"
    env[DEADLINE_ENV] = repr(deadline)
    return env


def _text(stream: str | bytes | None) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return stream


def _failure(explain: str, headline: str, stdout: str, stderr: str) -> ChildPytestError:
    prefix = f"{explain}: " if explain else ""
    return ChildPytestError(
        f"{prefix}{headline}\n--- child stdout ---\n{stdout}\n--- child stderr ---\n{stderr}"
    )


def run_child_pytest(
    args: Sequence[str],
    *,
    cwd: Path,
    tmp_path: Path,
    timeout: float = Timeout.REQUEST_LONG,
    expected_returncode: int = 0,
    explain: str = "",
    extra_env: Mapping[str, str] | None = None,
    pythonpath: Sequence[Path] = (),
    launcher: Sequence[str] | None = None,
    pass_fds: Sequence[int] = (),
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m pytest *args`` (or ``launcher``) as an isolated child.

    Args:
        args: Arguments after ``python -m pytest``; empty when ``launcher`` is given.
        cwd: Directory the child runs in.
        tmp_path: The caller's ``tmp_path``; the child's ``--basetemp`` is made under it.
        timeout: Seconds before the child is killed; must be positive.
        expected_returncode: The exit code that counts as success.
        explain: What the caller was checking, put first in any failure message.
        extra_env: Variables added to the explicit environment.
        pythonpath: Directories put on the child's ``PYTHONPATH`` after the plugin's.
        launcher: A full argv that itself starts pytest (a wrapper script);
            the basetemp and watchdog still reach that pytest through the
            environment.
        pass_fds: Descriptors the child inherits.

    Returns:
        The completed child, its exit code equal to ``expected_returncode``.

    Raises:
        ValueError: If ``timeout`` is not positive, ``extra_env`` names a key the
            helper owns, or ``args`` is given beside ``launcher``.
        ChildPytestError: If the child times out or exits with another code.
    """
    if timeout <= 0:
        raise ValueError(f"timeout must be positive, got {timeout}")
    extra = dict(extra_env or {})
    owned = sorted(HELPER_OWNED_ENV_KEYS.intersection(extra))
    if owned:
        raise ValueError(f"extra_env may not set helper-owned keys: {', '.join(owned)}")
    if launcher is not None and args:
        raise ValueError("pass pytest arguments inside the launcher, not beside it")

    argv = list(launcher) if launcher is not None else [sys.executable, "-m", "pytest", *args]
    basetemp = Path(tempfile.mkdtemp(prefix=".child-", dir=tmp_path))
    deadline = time.time() + timeout * WATCHDOG_FRACTION
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=_child_env(basetemp, deadline, extra, pythonpath),
            capture_output=True,
            text=True,
            pass_fds=tuple(pass_fds),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        raise _failure(
            explain,
            f"child pytest {argv} timed out after {timeout:.0f}s",
            _text(expired.stdout),
            _text(expired.stderr),
        ) from expired
    if completed.returncode != expected_returncode:
        raise _failure(
            explain,
            f"child pytest {argv} exited {completed.returncode}, expected {expected_returncode}",
            completed.stdout,
            completed.stderr,
        )
    return completed
