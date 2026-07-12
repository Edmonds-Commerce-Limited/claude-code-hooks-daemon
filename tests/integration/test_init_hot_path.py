"""Characterization tests for the init.sh source-time hot path (Plan 00156, T3).

T3 slims per-event work that runs every time a wrapper sources init.sh, WITHOUT
changing behaviour. These tests lock the observable behaviour of the two
functions T3 touches so the refactor (fewer process spawns) cannot regress them:

- ``_get_hostname_suffix`` — sanitises the hostname to a filesystem-safe suffix
  (lowercase, spaces → hyphens, leading ``-``). The refactor replaces one of two
  ``tr`` pipeline spawns with bash parameter expansion; the OUTPUT must be
  byte-identical. Parameter expansion stays bash-3.2 safe (macOS ships no
  ``${var,,}``), so lowercase remains on ``tr``.
- the unconditional ``mkdir -p "$_untracked_dir"`` — guarded with ``[[ -d ]]``
  so the common (dir-exists) path skips the spawn; the directory must still be
  created when absent.

The tests source the REAL deployed init.sh in a subprocess with a controlled
HOSTNAME / HOOKS_DAEMON_ROOT_DIR and observe the result.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INIT_SH = _REPO_ROOT / ".claude" / "init.sh"

_SOURCE_TIMEOUT_SECONDS = 30


def _source_and_run(snippet: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Source the real init.sh, then run a snippet; return the completed proc."""
    env = os.environ.copy()
    env.update(extra_env)
    script = f'source "{_INIT_SH}" >/dev/null 2>&1\n{snippet}'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=_SOURCE_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize(
    "hostname,expected",
    [
        ("laptop", "-laptop"),
        ("My-Server", "-my-server"),
        ("506355bfbc76", "-506355bfbc76"),
        ("My Server", "-my-server"),
        ("UPPER lower MIX", "-upper-lower-mix"),
        ("prod-server-01", "-prod-server-01"),
    ],
)
def test_hostname_suffix_sanitization(hostname: str, expected: str) -> None:
    """Suffix is lowercased, spaces become hyphens, and it is '-'-prefixed."""
    result = _source_and_run("_get_hostname_suffix", {"HOSTNAME": hostname})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_hostname_suffix_fallback_is_sanitized() -> None:
    """With no HOSTNAME the suffix still starts with '-' and has no spaces/upper."""
    env = {k: v for k, v in os.environ.items() if k != "HOSTNAME"}
    env.pop("HOSTNAME", None)
    proc = subprocess.run(
        ["bash", "-c", f'source "{_INIT_SH}" >/dev/null 2>&1\n_get_hostname_suffix'],
        capture_output=True,
        text=True,
        env=env,
        timeout=_SOURCE_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, proc.stderr
    suffix = proc.stdout.strip()
    assert suffix.startswith("-")
    body = suffix[1:]
    assert body != ""
    assert " " not in body
    assert body == body.lower()


def test_untracked_dir_exists_after_source() -> None:
    """After sourcing, the resolved untracked dir exists.

    The mkdir is guarded with ``[[ -d ]] || mkdir -p`` so the common path skips
    the spawn; this invariant proves the guard still guarantees the directory is
    present (the daemon writes its socket/PID there). The real self-install
    ``hooks-daemon.env`` pins ``HOOKS_DAEMON_ROOT_DIR`` to the project, so we
    read the resolved ``_untracked_dir`` rather than overriding the root.
    """
    result = _source_and_run('printf "%s" "$_untracked_dir"', {})
    assert result.returncode == 0, result.stderr
    resolved = result.stdout.strip()
    assert resolved, "init.sh did not resolve _untracked_dir"
    assert Path(resolved).is_dir(), f"untracked dir missing after source: {resolved}"
