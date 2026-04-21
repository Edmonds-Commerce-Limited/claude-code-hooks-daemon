"""Parity integration test: bash and Python helpers MUST produce identical fingerprints.

Plan 00099: the venv keying scheme requires that
`scripts/install/python_fingerprint.sh` and
`claude_code_hooks_daemon.daemon.paths.python_venv_fingerprint()` produce
byte-identical output when given the same Python interpreter. The bash side
runs during install (before the venv is created, using system python3); the
Python side runs inside the daemon (from within the venv). Any divergence
would cause the bash-installed venv to land at a different path than the one
the Python daemon tries to activate, bricking startup.

These tests invoke both helpers as real subprocesses and assert equality.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH_HELPER = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"


def _bash_fingerprint(python_bin: str) -> str:
    """Invoke the bash helper against a specific Python interpreter."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{BASH_HELPER}" && python_venv_fingerprint "{python_bin}"',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _python_fingerprint(python_bin: str) -> str:
    """Invoke python_venv_fingerprint() via the Python import under the given interpreter."""
    result = subprocess.run(
        [
            python_bin,
            "-c",
            "from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint; "
            "print(python_venv_fingerprint())",
        ],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(REPO_ROOT),
    )
    return result.stdout.strip()


class TestBashHelperExists:
    """Preflight: the bash helper must exist and be executable."""

    def test_bash_helper_exists(self) -> None:
        assert BASH_HELPER.exists(), f"Missing bash helper: {BASH_HELPER}"

    def test_bash_helper_is_executable(self) -> None:
        assert BASH_HELPER.stat().st_mode & 0o111, "Bash helper is not executable"


class TestBashPythonParity:
    """Bash and Python helpers MUST produce identical fingerprints."""

    def test_parity_for_current_interpreter(self) -> None:
        """Running interpreter: bash-side and Python-side match exactly."""
        bash_fp = _bash_fingerprint(sys.executable)
        py_fp = _python_fingerprint(sys.executable)
        assert bash_fp == py_fp, (
            f"Parity violation!\n  bash: {bash_fp}\n  python: {py_fp}"
        )

    def test_fingerprint_format(self) -> None:
        """Both helpers emit the documented `pyMM-XXXXXXXX` format."""
        import re

        fp = _bash_fingerprint(sys.executable)
        assert re.match(r"^py\d{2,3}-[0-9a-f]{8}$", fp), f"Bad format: {fp}"

    def test_system_python_matches_venv_python_same_base_prefix(self) -> None:
        """System python3 and the venv it created share one base_prefix, thus one fingerprint.

        This is the crucial property: bash-side runs during install using the
        system python BEFORE the venv exists; Python-side runs AFTER the venv
        is active. Both must agree.
        """
        system_python = "/usr/bin/python3"
        if not Path(system_python).exists():
            pytest.skip(f"{system_python} unavailable in this environment")

        system_fp = _bash_fingerprint(system_python)
        venv_fp = _bash_fingerprint(sys.executable)

        # When the running interpreter is a venv created from system_python,
        # both should produce the same fingerprint.
        import sysconfig

        if sysconfig.get_config_var("prefix") != sysconfig.get_config_var("base_prefix"):
            assert system_fp == venv_fp, (
                f"System/venv fingerprint mismatch!\n"
                f"  system ({system_python}): {system_fp}\n"
                f"  venv   ({sys.executable}): {venv_fp}"
            )
