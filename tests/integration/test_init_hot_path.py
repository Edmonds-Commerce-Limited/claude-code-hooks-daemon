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


def _sandbox_project(tmp_path: Path, root_subdir: str) -> Path:
    """Build a throwaway project that sources a copy of the real init.sh.

    Layout: ``<proj>/.claude/init.sh`` (copy) + ``<proj>/.claude/hooks-daemon.env``
    pinning ``HOOKS_DAEMON_ROOT_DIR`` to ``<proj>/<root_subdir>``. The project has
    no ``.git``, so the hooks-daemon-repo self-install guard is skipped and the
    source runs cleanly to the ``mkdir`` on the hot path. Returns the project dir.
    """
    proj = tmp_path / "proj"
    claude_dir = proj / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "init.sh").write_text(_INIT_SH.read_text())
    (claude_dir / "hooks-daemon.env").write_text(
        f'export HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/{root_subdir}"\n'
    )
    return proj


def test_untracked_dir_created_when_absent(tmp_path: Path) -> None:
    """Sourcing creates the untracked dir when it does not yet exist.

    Exercises the *creation* half of the ``[[ -d ]] || mkdir -p`` guard (Plan
    00156 T3) — the branch the previous smoke test never reached because the real
    repo's untracked dir always exists. The sandbox root exists but its
    ``untracked/`` subdir does not, so the guard must spawn the mkdir.
    """
    root_subdir = "fresh-root"
    proj = _sandbox_project(tmp_path, root_subdir)
    untracked = proj / root_subdir / "untracked"
    (proj / root_subdir).mkdir()  # root exists; untracked/ deliberately absent
    assert not untracked.exists(), "precondition: untracked dir must be absent"

    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_ROOT_DIR", None)  # let the sandbox .env set it
    result = subprocess.run(
        ["bash", "-c", f'source "{proj / ".claude" / "init.sh"}" >/dev/null 2>&1'],
        capture_output=True,
        text=True,
        env=env,
        timeout=_SOURCE_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, result.stderr
    assert untracked.is_dir(), f"guard did not create untracked dir: {untracked}"


@pytest.mark.parametrize("mode", ["default", "status"])
def test_passthrough_override_handles_status_mode(mode: str) -> None:
    """The CI passthrough override renders a status fallback, not a raw JSON blob.

    Review finding 2: ``send_request_stdin "Status" "status"`` under passthrough
    mode must degrade to ``⚠️ NO STATUS DATA`` (matching the old ``jq -r``
    fallback), while a normal event still gets the silent ``{}`` passthrough.
    """
    snippet = "_enter_passthrough_mode\n" + (
        'echo "{}" | send_request_stdin "Status" "status"'
        if mode == "status"
        else 'echo "{}" | send_request_stdin "PreToolUse"'
    )
    result = _source_and_run(snippet, {})
    assert result.returncode == 0, result.stderr
    out = result.stdout.strip()
    if mode == "status":
        assert out == "⚠️ NO STATUS DATA", out
    else:
        assert out == "{}", out
