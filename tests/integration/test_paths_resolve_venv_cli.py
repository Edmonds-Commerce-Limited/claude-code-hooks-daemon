"""Plan 00100 Task 2.2: Python SSOT resolve-venv CLI contract.

The CLI is invoked as::

    python -m claude_code_hooks_daemon.daemon.paths resolve-venv [--daemon-dir DIR]

Output contract:
  - stdout: single line — the resolved absolute path to the venv's bin/python
  - stderr: empty on success
  - exit 0 on success

Failure contract:
  - stdout: empty
  - stderr: multi-line report citing every precedence step tried and why each
            failed (e.g. ``step 1: HOOKS_DAEMON_VENV_PATH unset``, ``step 2:
            {path} not found``, etc.)
  - exit 1

Precedence (matches resolve_existing_venv_python):
  1. ``$HOOKS_DAEMON_VENV_PATH/bin/python`` (explicit override)
  2. ``{daemon_dir}/untracked/venv-{fingerprint}/bin/python``
  3. First existing ``{daemon_dir}/untracked/venv-*/bin/python`` (scan)
  4. ``{daemon_dir}/untracked/venv/bin/python`` (legacy)

These tests drive Task 2.3 implementation. They must fail first, pass after
the CLI is implemented in paths.py.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_fake_venv(venv_dir: Path) -> Path:
    """Create a fake venv layout with an executable bin/python."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/bash\necho fake\n")
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return py


def _run_cli(
    daemon_dir: Path | None = None,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m claude_code_hooks_daemon.daemon.paths resolve-venv``."""
    env = os.environ.copy()
    # Strip any pre-existing override so tests can control it explicitly.
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    if env_overrides:
        env.update(env_overrides)

    args = [sys.executable, "-m", "claude_code_hooks_daemon.daemon.paths", "resolve-venv"]
    if daemon_dir is not None:
        args += ["--daemon-dir", str(daemon_dir)]

    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
        env=env,
        cwd=str(REPO_ROOT),
    )


def test_resolve_venv_module_is_invocable() -> None:
    """The CLI entry point must be invocable as ``python -m ... paths --help``."""
    result = subprocess.run(
        [sys.executable, "-m", "claude_code_hooks_daemon.daemon.paths", "--help"],
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"`python -m claude_code_hooks_daemon.daemon.paths --help` failed. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # Expect the help output to mention resolve-venv.
    assert "resolve-venv" in result.stdout


def test_resolve_venv_override_via_env(tmp_path: Path) -> None:
    """HOOKS_DAEMON_VENV_PATH takes absolute precedence (step 1)."""
    override_venv = tmp_path / "override-venv"
    py = _make_fake_venv(override_venv)

    result = _run_cli(
        daemon_dir=tmp_path / "daemon",
        env_overrides={"HOOKS_DAEMON_VENV_PATH": str(override_venv)},
    )
    assert result.returncode == 0, f"Expected 0; stderr={result.stderr!r}"
    assert result.stdout.strip() == str(py)


def test_resolve_venv_fingerprint_keyed(tmp_path: Path) -> None:
    """Fingerprint-keyed venv is picked when present (step 2)."""
    daemon_dir = tmp_path / "daemon"
    fp = python_venv_fingerprint()
    keyed_venv = daemon_dir / "untracked" / f"venv-{fp}"
    py = _make_fake_venv(keyed_venv)

    result = _run_cli(daemon_dir=daemon_dir)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert result.stdout.strip() == str(py)


def test_resolve_venv_scan_fallback(tmp_path: Path) -> None:
    """Any existing venv-*/bin/python is picked via scan (step 3)."""
    daemon_dir = tmp_path / "daemon"
    # Use a fingerprint that will NOT match the current interpreter.
    foreign_venv = daemon_dir / "untracked" / "venv-py999-deadbeef"
    py = _make_fake_venv(foreign_venv)

    result = _run_cli(daemon_dir=daemon_dir)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert result.stdout.strip() == str(py)


def test_resolve_venv_legacy_fallback(tmp_path: Path) -> None:
    """Legacy untracked/venv/bin/python is picked when nothing else (step 4)."""
    daemon_dir = tmp_path / "daemon"
    legacy = daemon_dir / "untracked" / "venv"
    py = _make_fake_venv(legacy)

    result = _run_cli(daemon_dir=daemon_dir)
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert result.stdout.strip() == str(py)


def test_resolve_venv_fails_when_nothing_exists(tmp_path: Path) -> None:
    """When no venv can be found, CLI exits 1 with detailed stderr.

    Stderr must cite all four precedence steps, showing what was tried
    and why each failed. This is the key improvement over the legacy
    behaviour (which returned the legacy path even when it didn't exist
    — silent failure).
    """
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()

    result = _run_cli(daemon_dir=daemon_dir)
    assert result.returncode == 1, (
        f"Expected exit 1 when no venv exists; got {result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (
        result.stdout.strip() == ""
    ), "stdout must be empty on failure (single-line success contract)"
    # Stderr must mention every step tried.
    err = result.stderr.lower()
    for keyword in ("step 1", "step 2", "step 3", "step 4"):
        assert keyword in err, (
            f"Failure stderr must cite each precedence step. "
            f"Missing '{keyword}' in: {result.stderr!r}"
        )


def test_resolve_venv_default_daemon_dir_is_cwd(tmp_path: Path) -> None:
    """When --daemon-dir is not given, CLI uses the current working directory."""
    daemon_dir = tmp_path / "project"
    fp = python_venv_fingerprint()
    keyed_venv = daemon_dir / "untracked" / f"venv-{fp}"
    py = _make_fake_venv(keyed_venv)

    # Invoke without --daemon-dir; cwd set to the project.
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "claude_code_hooks_daemon.daemon.paths", "resolve-venv"],
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
        env=env,
        cwd=str(daemon_dir),
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert result.stdout.strip() == str(py)


def test_resolve_venv_output_is_exactly_one_line(tmp_path: Path) -> None:
    """Success stdout is strictly one line (no trailing chatter)."""
    daemon_dir = tmp_path / "daemon"
    fp = python_venv_fingerprint()
    _make_fake_venv(daemon_dir / "untracked" / f"venv-{fp}")

    result = _run_cli(daemon_dir=daemon_dir)
    assert result.returncode == 0
    # Exactly one line (plus trailing newline from print).
    lines = [line for line in result.stdout.split("\n") if line]
    assert (
        len(lines) == 1
    ), f"Expected single-line stdout; got {len(lines)} lines: {result.stdout!r}"
