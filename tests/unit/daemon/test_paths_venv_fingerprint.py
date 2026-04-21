"""Tests for python_venv_fingerprint() and get_venv_path() in paths.py.

Plan 00099: keys venvs by a Python-environment fingerprint so concurrent
containers from the same image share one venv while distinct Pythons
(pyenv vs distro, different minor versions, different arches) are kept
apart.

Fingerprint components (all included):
- sys.version (catches version changes including patch / build tag)
- sys.base_prefix (catches pyenv vs distro vs other installs; stable across
  system-python and venv-python invocations so bash-side and Python-side
  both agree)
- platform.machine() (catches cross-arch x86 vs ARM)
"""

import hashlib
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    get_venv_path,
    python_venv_fingerprint,
)


class TestPythonVenvFingerprintFormat:
    """Tests for the output format of python_venv_fingerprint()."""

    def test_returns_string(self) -> None:
        """Fingerprint is a string."""
        assert isinstance(python_venv_fingerprint(), str)

    def test_format_is_py_major_minor_dash_hash(self) -> None:
        """Fingerprint matches pattern pyMM-XXXXXXXX.

        Human-readable Python version prefix + 8-char md5 digest.
        """
        result = python_venv_fingerprint()
        assert re.match(r"^py\d{2,3}-[0-9a-f]{8}$", result), f"Bad format: {result}"

    def test_includes_current_python_major_minor(self) -> None:
        """Prefix reflects the running interpreter's major.minor."""
        result = python_venv_fingerprint()
        expected_prefix = f"py{sys.version_info.major}{sys.version_info.minor}-"
        assert result.startswith(expected_prefix)

    def test_hash_is_exactly_8_chars(self) -> None:
        """Hash portion is 8 hex chars (md5 truncated)."""
        result = python_venv_fingerprint()
        _, _, hash_part = result.partition("-")
        assert len(hash_part) == 8
        assert all(c in "0123456789abcdef" for c in hash_part)


class TestPythonVenvFingerprintStability:
    """Tests that fingerprint is stable for identical Python environments."""

    def test_is_stable_across_calls(self) -> None:
        """Repeated calls return the same value."""
        assert python_venv_fingerprint() == python_venv_fingerprint()

    def test_is_stable_across_many_calls(self) -> None:
        """Stability over many invocations (catches any timestamp/randomness)."""
        first = python_venv_fingerprint()
        for _ in range(50):
            assert python_venv_fingerprint() == first


class TestPythonVenvFingerprintDifferentiation:
    """Tests that fingerprint differs when Python env components differ."""

    def test_differs_when_python_version_differs(self) -> None:
        """Different sys.version produces different fingerprint."""
        with patch.object(sys, "version", "3.11.5 (main, Jan 1 2025, 00:00:00)"):
            fp1 = python_venv_fingerprint()
        with patch.object(sys, "version", "3.13.0 (main, Jan 1 2025, 00:00:00)"):
            fp2 = python_venv_fingerprint()
        assert fp1 != fp2

    def test_differs_when_base_prefix_differs(self) -> None:
        """Different sys.base_prefix (pyenv vs distro install) produces different fingerprint."""
        with patch.object(sys, "base_prefix", "/usr"):
            fp1 = python_venv_fingerprint()
        with patch.object(sys, "base_prefix", "/home/user/.pyenv/versions/3.11.5"):
            fp2 = python_venv_fingerprint()
        assert fp1 != fp2

    def test_stable_across_system_and_venv_invocations(self) -> None:
        """sys.base_prefix is stable when the same Python is invoked via venv symlink.

        Bash-side computes fingerprint before the venv exists (using system python3);
        Python-side computes fingerprint from within the venv. Both must agree.
        Simulate by swapping sys.executable while keeping base_prefix constant.
        """
        with (
            patch.object(sys, "base_prefix", "/usr"),
            patch.object(sys, "executable", "/usr/bin/python3.11"),
        ):
            system_fp = python_venv_fingerprint()
        with (
            patch.object(sys, "base_prefix", "/usr"),
            patch.object(sys, "executable", "/workspace/untracked/venv/bin/python"),
        ):
            venv_fp = python_venv_fingerprint()
        assert system_fp == venv_fp

    def test_differs_when_platform_machine_differs(self) -> None:
        """Different architecture produces different fingerprint."""
        with patch("claude_code_hooks_daemon.daemon.paths.platform.machine", return_value="x86_64"):
            fp1 = python_venv_fingerprint()
        with patch(
            "claude_code_hooks_daemon.daemon.paths.platform.machine", return_value="aarch64"
        ):
            fp2 = python_venv_fingerprint()
        assert fp1 != fp2

    def test_same_inputs_produce_same_fingerprint(self) -> None:
        """All three components equal -> identical fingerprint (concurrent container case)."""
        with (
            patch.object(sys, "version", "3.11.5 (fixed)"),
            patch.object(sys, "base_prefix", "/usr"),
            patch(
                "claude_code_hooks_daemon.daemon.paths.platform.machine",
                return_value="x86_64",
            ),
        ):
            fp1 = python_venv_fingerprint()
            fp2 = python_venv_fingerprint()
        assert fp1 == fp2


class TestPythonVenvFingerprintHashLogic:
    """Verify the exact hashing formula matches the documented spec."""

    def test_hash_matches_explicit_md5_formula(self) -> None:
        """Verify hash = md5(sys.version|sys.base_prefix|platform.machine())[:8]."""
        import platform as _platform

        parts = f"{sys.version}|{sys.base_prefix}|{_platform.machine()}"
        expected_hash = hashlib.md5(
            parts.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:8]
        expected = f"py{sys.version_info.major}{sys.version_info.minor}-{expected_hash}"
        assert python_venv_fingerprint() == expected


class TestGetVenvPath:
    """Tests for get_venv_path() helper."""

    def test_returns_path_object(self, tmp_path: Path) -> None:
        """Returns a pathlib.Path."""
        result = get_venv_path(tmp_path)
        assert isinstance(result, Path)

    def test_path_contains_fingerprint(self, tmp_path: Path) -> None:
        """Returned path embeds the current fingerprint as directory name."""
        fingerprint = python_venv_fingerprint()
        result = get_venv_path(tmp_path)
        assert result.name == f"venv-{fingerprint}"

    def test_path_is_under_untracked_dir_self_install(self, tmp_path: Path) -> None:
        """In self-install mode, venv lives under {project}/untracked/."""
        # Mark project as self-install (has src/claude_code_hooks_daemon/)
        (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
        result = get_venv_path(tmp_path)
        assert result.parent == tmp_path / "untracked"

    def test_path_is_under_untracked_dir_normal_install(self, tmp_path: Path) -> None:
        """In normal install, venv lives under {project}/.claude/hooks-daemon/untracked/."""
        # Normal mode: no src/claude_code_hooks_daemon/
        result = get_venv_path(tmp_path)
        assert result.parent == tmp_path / ".claude" / "hooks-daemon" / "untracked"

    def test_different_fingerprints_produce_different_paths(self, tmp_path: Path) -> None:
        """Simulating different Pythons yields distinct venv directories."""
        with (
            patch.object(sys, "base_prefix", "/usr"),
            patch.object(sys, "version", "3.11.5 distro"),
        ):
            path1 = get_venv_path(tmp_path)
        with (
            patch.object(sys, "base_prefix", "/home/u/.pyenv/versions/3.13"),
            patch.object(sys, "version", "3.13.0 pyenv"),
        ):
            path2 = get_venv_path(tmp_path)
        assert path1 != path2
        assert path1.name != path2.name


class TestFingerprintSafeForFilesystem:
    """Ensure fingerprint only uses characters safe for any filesystem."""

    @pytest.mark.parametrize(
        "fake_executable",
        [
            "/usr/bin/python3.11",
            "/home/user with spaces/.pyenv/versions/3.11.5/bin/python",
            "C:\\Program Files\\Python311\\python.exe",
            "/path/with/unicode/日本語/python",
        ],
    )
    def test_filesystem_safe_characters(self, fake_executable: str) -> None:
        """Fingerprint output is always `pyMM-{8 hex chars}` regardless of input oddities."""
        with patch.object(sys, "executable", fake_executable):
            result = python_venv_fingerprint()
        assert re.match(r"^py\d{2,3}-[0-9a-f]{8}$", result)
