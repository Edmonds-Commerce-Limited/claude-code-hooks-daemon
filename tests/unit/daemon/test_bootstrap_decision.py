"""Tests for ``can_inline_bootstrap`` — the inline-safe precondition predicate.

Plan 00100 Phase 3.5 Task 3.5.1: before the daemon attempts to self-bootstrap a
missing venv, it consults this predicate. Five preconditions must all hold:

1. ``uv`` resolvable on PATH
2. ``{daemon_dir}/pyproject.toml`` exists and parses
3. ``{daemon_dir}/uv.lock`` exists
4. a Python satisfying the project's ``requires-python`` is resolvable on PATH
5. ``{daemon_dir}/untracked/`` parent is writable (or createable)

If any fail, the returned :class:`BootstrapDecision` carries an actionable
breakdown so the LLM-guided fallback (Task 3.5.3) can surface exact remediation.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    BootstrapDecision,
    can_inline_bootstrap,
)

_VALID_PYPROJECT = """\
[project]
name = "fake-daemon"
version = "0.0.0"
requires-python = ">=3.11"
"""

_UNSATISFIABLE_PYPROJECT = """\
[project]
name = "fake-daemon"
version = "0.0.0"
requires-python = ">=99.0"
"""

_MALFORMED_PYPROJECT = """\
[project
name = not-closed
"""


@pytest.fixture
def daemon_dir(tmp_path: Path) -> Path:
    """Set up a tmp daemon_dir with the three files a healthy install requires."""
    (tmp_path / "pyproject.toml").write_text(_VALID_PYPROJECT)
    (tmp_path / "uv.lock").write_text("# minimal uv lock marker\n")
    (tmp_path / "untracked").mkdir()
    return tmp_path


class TestAllGreen:
    """When every precondition holds, ``allowed=True`` and ``missing=[]``."""

    def test_all_preconditions_met(self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force uv to appear on PATH; the real uv may or may not be installed.
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths.shutil.which",
            lambda name: "/usr/bin/uv" if name == "uv" else None,
        )
        # The current test interpreter is >=3.11, so use it as the compatible-python.
        import sys

        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths._find_compatible_python_on_path",
            lambda: Path(sys.executable),
        )

        decision = can_inline_bootstrap(daemon_dir)

        assert isinstance(decision, BootstrapDecision)
        assert decision.allowed is True
        assert decision.missing == []


class TestMissingPreconditions:
    """Each precondition failure surfaces in ``missing`` with a stable identifier."""

    def _patch_all_good(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths.shutil.which",
            lambda name: "/usr/bin/uv" if name == "uv" else None,
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths._find_compatible_python_on_path",
            lambda: Path(sys.executable),
        )

    def test_uv_not_on_path(self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_all_good(monkeypatch)
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths.shutil.which",
            lambda name: None,
        )

        decision = can_inline_bootstrap(daemon_dir)

        assert decision.allowed is False
        assert "uv" in decision.missing
        assert "uv" in decision.reason

    def test_pyproject_missing(self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_all_good(monkeypatch)
        (daemon_dir / "pyproject.toml").unlink()

        decision = can_inline_bootstrap(daemon_dir)

        assert decision.allowed is False
        assert "pyproject.toml" in decision.missing

    def test_pyproject_malformed(self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_all_good(monkeypatch)
        (daemon_dir / "pyproject.toml").write_text(_MALFORMED_PYPROJECT)

        decision = can_inline_bootstrap(daemon_dir)

        assert decision.allowed is False
        assert "pyproject.toml" in decision.missing
        assert "parse" in decision.reason.lower()

    def test_uv_lock_missing(self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_all_good(monkeypatch)
        (daemon_dir / "uv.lock").unlink()

        decision = can_inline_bootstrap(daemon_dir)

        assert decision.allowed is False
        assert "uv.lock" in decision.missing

    def test_no_compatible_python(self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_all_good(monkeypatch)
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths._find_compatible_python_on_path",
            lambda: None,
        )

        decision = can_inline_bootstrap(daemon_dir)

        assert decision.allowed is False
        assert "compatible-python" in decision.missing

    def test_python_version_does_not_satisfy_requires_python(
        self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # requires-python = ">=99.0" is impossible to satisfy.
        (daemon_dir / "pyproject.toml").write_text(_UNSATISFIABLE_PYPROJECT)
        self._patch_all_good(monkeypatch)

        decision = can_inline_bootstrap(daemon_dir)

        assert decision.allowed is False
        assert "compatible-python" in decision.missing
        assert "99" in decision.reason or "requires-python" in decision.reason

    def test_python_probe_failure_treated_as_incompatible(
        self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the version probe raises, the candidate is rejected.

        Covers the exception branch in :func:`can_inline_bootstrap` that
        catches ``OSError``/``SubprocessError``/``ValueError`` from
        :func:`_probe_python_major_minor`. A probe that can't return a
        version means we can't confirm compatibility — so we must NOT
        proceed with bootstrap.
        """
        self._patch_all_good(monkeypatch)

        def _explode(_python: Path) -> tuple[int, int]:
            raise OSError("simulated: candidate python disappeared between which() and probe")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths._probe_python_major_minor",
            _explode,
        )

        decision = can_inline_bootstrap(daemon_dir)

        assert decision.allowed is False
        assert "compatible-python" in decision.missing
        assert "probe failed" in decision.reason

    def test_untracked_not_writable(
        self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_all_good(monkeypatch)
        untracked = daemon_dir / "untracked"
        untracked.chmod(0o500)  # read+execute, no write
        try:
            # Running as root (inside YOLO container) ignores chmod. Skip in that case —
            # the precondition's writability guard is exercised by the non-root CI job.
            if os.geteuid() == 0:
                pytest.skip("chmod write-guard ineffective as root; covered by non-root CI")
            decision = can_inline_bootstrap(daemon_dir)
            assert decision.allowed is False
            assert "untracked-writable" in decision.missing
        finally:
            untracked.chmod(0o700)

    def test_untracked_parent_absent_is_createable(
        self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If untracked/ doesn't exist yet but daemon_dir IS writable, precondition holds."""
        self._patch_all_good(monkeypatch)
        import shutil as _shutil

        _shutil.rmtree(daemon_dir / "untracked")

        decision = can_inline_bootstrap(daemon_dir)

        # daemon_dir itself is writable (owned by tmp_path), so we can create untracked/.
        assert decision.allowed is True


class TestMultipleMissing:
    """Several failures surface together — the reason string enumerates them all."""

    def test_all_missing(self, daemon_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths.shutil.which",
            lambda name: None,
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.daemon.paths._find_compatible_python_on_path",
            lambda: None,
        )
        (daemon_dir / "pyproject.toml").unlink()
        (daemon_dir / "uv.lock").unlink()

        decision = can_inline_bootstrap(daemon_dir)

        assert decision.allowed is False
        assert "uv" in decision.missing
        assert "pyproject.toml" in decision.missing
        assert "uv.lock" in decision.missing
        assert "compatible-python" in decision.missing


class TestBootstrapDecisionDataclass:
    """The return type exposes the three fields the LLM-fallback relies on."""

    def test_dataclass_fields(self) -> None:
        decision = BootstrapDecision(allowed=True, missing=[], reason="ok")
        assert decision.allowed is True
        assert decision.missing == []
        assert decision.reason == "ok"
