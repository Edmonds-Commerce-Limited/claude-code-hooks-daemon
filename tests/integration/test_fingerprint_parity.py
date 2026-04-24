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


def _bash_fingerprint(
    python_bin: str,
    root: str | None = None,
    *,
    via_env: bool = False,
) -> str:
    """Invoke the bash helper against a specific Python interpreter.

    Args:
        python_bin: path to the Python interpreter to fingerprint
        root: optional project root; if given, prepends slug
        via_env: when True, pass ``root`` through ``HOOKS_DAEMON_ROOT_DIR``
            env var instead of the positional argument
    """
    if root is None:
        command = f'source "{BASH_HELPER}" && python_venv_fingerprint "{python_bin}"'
        env = None
    elif via_env:
        command = f'source "{BASH_HELPER}" && python_venv_fingerprint "{python_bin}"'
        import os

        env = {**os.environ, "HOOKS_DAEMON_ROOT_DIR": root}
    else:
        command = (
            f'source "{BASH_HELPER}" && python_venv_fingerprint "{python_bin}" "{root}"'
        )
        env = None

    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _python_fingerprint(python_bin: str, root: str | None = None) -> str:
    """Invoke python_venv_fingerprint() via the Python import under the given interpreter."""
    if root is None:
        snippet = (
            "from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint; "
            "print(python_venv_fingerprint())"
        )
    else:
        snippet = (
            "from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint; "
            f"print(python_venv_fingerprint({root!r}))"
        )
    result = subprocess.run(
        [python_bin, "-c", snippet],
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
        assert bash_fp == py_fp, f"Parity violation!\n  bash: {bash_fp}\n  python: {py_fp}"

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


class TestBashPythonSlugParity:
    """Plan 00100 Task 3.0.5: slug-prefixed fingerprints must also match.

    When a project root is supplied, both helpers must emit
    ``{slug}-py{MM}-{hash}`` with byte-identical slug and hash components so
    that the bash-installed venv and the Python-resolved venv land at the
    same directory.
    """

    def test_slug_parity_via_positional_arg(self, tmp_path: Path) -> None:
        """Bash (positional) and Python produce matching slug-prefixed fingerprints."""
        bash_fp = _bash_fingerprint(sys.executable, root=str(tmp_path))
        py_fp = _python_fingerprint(sys.executable, root=str(tmp_path))
        assert bash_fp == py_fp, (
            f"Slug parity violation!\n  bash: {bash_fp}\n  python: {py_fp}"
        )

    def test_slug_parity_via_env_var(self, tmp_path: Path) -> None:
        """Bash (via HOOKS_DAEMON_ROOT_DIR env) matches Python with the same root."""
        bash_fp = _bash_fingerprint(sys.executable, root=str(tmp_path), via_env=True)
        py_fp = _python_fingerprint(sys.executable, root=str(tmp_path))
        assert bash_fp == py_fp, (
            f"Slug-via-env parity violation!\n  bash: {bash_fp}\n  python: {py_fp}"
        )

    def test_slug_positional_and_env_equivalent(self, tmp_path: Path) -> None:
        """Passing root positionally or via env var yields the same output."""
        fp_positional = _bash_fingerprint(sys.executable, root=str(tmp_path))
        fp_env = _bash_fingerprint(sys.executable, root=str(tmp_path), via_env=True)
        assert fp_positional == fp_env

    def test_slug_fingerprint_format(self, tmp_path: Path) -> None:
        """Format is ``{slug}-py{MM}-{8-hex}`` when root is supplied."""
        import re

        fp = _bash_fingerprint(sys.executable, root=str(tmp_path))
        assert re.match(r"^[A-Za-z0-9_-]+-py\d{2,3}-[0-9a-f]{8}$", fp), f"Bad format: {fp}"

    def test_distinct_roots_produce_distinct_fingerprints(
        self, tmp_path: Path
    ) -> None:
        """Host-vs-container case: different roots -> different venvs."""
        root_a = tmp_path / "view_a"
        root_b = tmp_path / "view_b"
        root_a.mkdir()
        root_b.mkdir()

        fp_a = _bash_fingerprint(sys.executable, root=str(root_a))
        fp_b = _bash_fingerprint(sys.executable, root=str(root_b))
        assert fp_a != fp_b, (
            f"Distinct roots must produce distinct fingerprints!\n"
            f"  root_a ({root_a}): {fp_a}\n  root_b ({root_b}): {fp_b}"
        )

    def test_bare_fingerprint_still_unchanged(self) -> None:
        """Without root: bash still emits legacy ``py{MM}-{hash}`` (no slug)."""
        import re

        fp = _bash_fingerprint(sys.executable)
        assert re.match(r"^py\d{2,3}-[0-9a-f]{8}$", fp), (
            f"No-root invocation must preserve legacy format, got: {fp}"
        )
