"""Tests for resolve_existing_venv_python() in paths.py.

Python-side SSOT for resolving an already-installed venv's bin/python.
Mirrors the 4-step precedence in
src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh:

  1. $HOOKS_DAEMON_VENV_PATH                      — explicit override
  2. {daemon_dir}/untracked/venv-{current-fingerprint}/bin/python
  3. First {daemon_dir}/untracked/venv-*/bin/python   (scan fallback)
  4. {daemon_dir}/untracked/venv/bin/python           (legacy)

The scan fallback exists because the interpreter that BUILT the venv
may differ from the interpreter that RESOLVES it. The venv's bin/python
is a symlink to the interpreter that built it, so any existing
venv-*/bin/python is usable regardless of the resolver's current Python.

Step 4 (legacy) is returned without existence check so callers can produce
useful "venv missing" error messages that still mention the legacy path.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    python_venv_fingerprint,
    resolve_existing_venv_python,
)


def _make_fake_venv(venv_dir: Path, executable: bool = True) -> Path:
    """Create a minimal venv layout with an executable (or non-executable) bin/python."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = bin_dir / "python"
    python.write_text("#!/bin/sh\nexec true\n")
    if executable:
        python.chmod(python.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    else:
        python.chmod(0o644)
    return python


class TestEnvOverride:
    """Step 1: $HOOKS_DAEMON_VENV_PATH overrides all other resolution."""

    def test_env_override_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When HOOKS_DAEMON_VENV_PATH is set, return {override}/bin/python regardless of disk state."""
        override_dir = tmp_path / "custom-venv"
        monkeypatch.setenv("HOOKS_DAEMON_VENV_PATH", str(override_dir))
        # Even if a matching fingerprint venv exists, the env override still wins.
        _make_fake_venv(tmp_path / "untracked" / f"venv-{python_venv_fingerprint()}")

        result = resolve_existing_venv_python(tmp_path)
        assert result == override_dir / "bin" / "python"

    def test_env_override_not_checked_for_existence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Override path is returned even if it does not exist — caller handles missing."""
        override_dir = tmp_path / "does-not-exist"
        monkeypatch.setenv("HOOKS_DAEMON_VENV_PATH", str(override_dir))

        result = resolve_existing_venv_python(tmp_path)
        assert result == override_dir / "bin" / "python"


class TestFingerprintMatch:
    """Step 2: venv-{current-fingerprint} is preferred when present and executable."""

    def test_matching_fingerprint_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When venv-{current-fingerprint} exists, return its python."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        venv_dir = tmp_path / "untracked" / f"venv-{python_venv_fingerprint()}"
        expected = _make_fake_venv(venv_dir)

        result = resolve_existing_venv_python(tmp_path)
        assert result == expected

    def test_matching_fingerprint_preferred_over_foreign_venv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If both current-fingerprint and foreign-fingerprint venvs exist, current wins."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        current = _make_fake_venv(tmp_path / "untracked" / f"venv-{python_venv_fingerprint()}")
        _make_fake_venv(tmp_path / "untracked" / "venv-py999-deadbeef")

        result = resolve_existing_venv_python(tmp_path)
        assert result == current

    def test_non_executable_fingerprint_match_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-executable bin/python at the matching path is not used; scan fallback runs."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        _make_fake_venv(
            tmp_path / "untracked" / f"venv-{python_venv_fingerprint()}", executable=False
        )
        scan_target = _make_fake_venv(tmp_path / "untracked" / "venv-py999-aaaaaaaa")

        result = resolve_existing_venv_python(tmp_path)
        assert result == scan_target


class TestScanFallback:
    """Step 3: when fingerprint match fails, scan for any venv-*/bin/python.

    This is the v3.8.1 fingerprint-mismatch fix: installer built venv with
    python3.13 but resolver's python3 is 3.9. Fingerprints differ but the
    venv is still usable because its bin/python symlinks the installer's
    interpreter.
    """

    def test_scan_fallback_when_no_fingerprint_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No matching-fingerprint venv; scan finds a foreign venv-*."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        expected = _make_fake_venv(tmp_path / "untracked" / "venv-py313-956ed987")

        result = resolve_existing_venv_python(tmp_path)
        assert result == expected

    def test_scan_skips_broken_venvs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scan skips venv-* directories whose bin/python is missing or non-executable."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        # Create one broken venv (non-exec) and one good venv.
        _make_fake_venv(tmp_path / "untracked" / "venv-py311-11111111", executable=False)
        good = _make_fake_venv(tmp_path / "untracked" / "venv-py313-22222222")

        result = resolve_existing_venv_python(tmp_path)
        assert result == good


class TestLegacyFallback:
    """Step 4: legacy untracked/venv/bin/python. Returned without existence check."""

    def test_legacy_fallback_when_no_venv_dash_star(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing on disk at all — returns legacy path (not checked for existence)."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)

        result = resolve_existing_venv_python(tmp_path)
        assert result == tmp_path / "untracked" / "venv" / "bin" / "python"

    def test_legacy_fallback_survives_missing_untracked_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even if untracked/ doesn't exist, the legacy path is still returned."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        # tmp_path has no untracked/ subdir.
        result = resolve_existing_venv_python(tmp_path)
        assert result == tmp_path / "untracked" / "venv" / "bin" / "python"


class TestPrecedenceInteraction:
    """Full precedence: env > fingerprint > scan > legacy."""

    def test_env_override_beats_everything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Set up all 4 options on disk; env override still wins."""
        override = tmp_path / "env-override"
        monkeypatch.setenv("HOOKS_DAEMON_VENV_PATH", str(override))
        _make_fake_venv(tmp_path / "untracked" / f"venv-{python_venv_fingerprint()}")
        _make_fake_venv(tmp_path / "untracked" / "venv-py999-aaaaaaaa")
        _make_fake_venv(tmp_path / "untracked" / "venv")

        result = resolve_existing_venv_python(tmp_path)
        assert result == override / "bin" / "python"

    def test_fingerprint_beats_scan_and_legacy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no env override, fingerprint match beats scan fallback and legacy."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        current = _make_fake_venv(tmp_path / "untracked" / f"venv-{python_venv_fingerprint()}")
        _make_fake_venv(tmp_path / "untracked" / "venv-py999-aaaaaaaa")
        _make_fake_venv(tmp_path / "untracked" / "venv")

        result = resolve_existing_venv_python(tmp_path)
        assert result == current

    def test_scan_beats_legacy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no env override and no fingerprint match, scan beats legacy."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        scan_target = _make_fake_venv(tmp_path / "untracked" / "venv-py999-aaaaaaaa")
        _make_fake_venv(tmp_path / "untracked" / "venv")

        result = resolve_existing_venv_python(tmp_path)
        assert result == scan_target


class TestStringArgumentAccepted:
    """resolve_existing_venv_python accepts both Path and str for daemon_dir."""

    def test_accepts_string_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        expected = _make_fake_venv(tmp_path / "untracked" / f"venv-{python_venv_fingerprint()}")

        result = resolve_existing_venv_python(str(tmp_path))
        assert result == expected
