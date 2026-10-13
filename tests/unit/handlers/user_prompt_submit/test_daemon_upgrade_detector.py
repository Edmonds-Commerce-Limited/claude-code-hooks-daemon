"""Tests for DaemonUpgradeDetectorHandler (Plan 00395, Plan 00517).

A running daemon loads `claude_code_hooks_daemon.version.__version__` once, at
import time, and keeps serving it for the life of the process. This handler
notices when the INSTALLED daemon has moved on without this process -- another
session or process upgraded the installation on the same filesystem while this
one kept running.

The installed version is the installed source tree's `version.py` (Plan 00517):
a single source, read as text on every call. A venv's `.daemon-metadata.json`
records which daemon version BUILT the venv, which is not the version
installed, so it is never consulted.

Two properties matter more than any of the mechanics:

- **Re-reading, not memory.** A source upgraded underneath a running daemon
  changes `version.py` on disk; the handler must see that on the next call.
- **Silent when nothing changed, fail-open when anything is unreadable.** An
  advisory on every turn for a fact that changes at most once per upgrade
  would be worse than the defect it reports, and this handler must never
  block a prompt over its own inability to read installer state.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.daemon.metadata import DaemonVenvMetadata, write_daemon_metadata
from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint
from claude_code_hooks_daemon.handlers.user_prompt_submit.daemon_upgrade_detector import (
    DaemonUpgradeDetectorHandler,
)
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command
from claude_code_hooks_daemon.utils.deployed_version import INSTALLED_SOURCE_VERSION_REL_PATH

_RUNNING_VERSION = "1.0.0"


def _hook_input() -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "prompt": "hello"}


def _write_installed_version(daemon_dir: Path, version: str) -> None:
    """Write the installed source tree's version.py."""
    target = daemon_dir / INSTALLED_SOURCE_VERSION_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'"""Version."""\n\n__version__ = "{version}"\n', encoding="utf-8")


def _make_fake_venv(venv_dir: Path) -> None:
    """Create a minimal venv layout with an executable `bin/python`."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = bin_dir / "python"
    python.write_text("#!/bin/sh\nexec true\n")
    python.chmod(python.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_metadata(venv_dir: Path, *, daemon_version: str) -> None:
    write_daemon_metadata(
        venv_dir,
        DaemonVenvMetadata(
            python_path=str(venv_dir / "bin" / "python"),
            fingerprint="py311-deadbeef",
            lock_hash="sha256:" + "a" * 64,
            daemon_version=daemon_version,
            written_at="2026-01-01T00:00:00+00:00",
        ),
    )


def _handler(
    daemon_dir: Path, *, running_version: str = _RUNNING_VERSION
) -> DaemonUpgradeDetectorHandler:
    """A handler wired to a fake daemon root, with self-install mode OFF."""
    handler = DaemonUpgradeDetectorHandler()
    handler.self_install_reader = lambda: False
    handler.daemon_root_reader = lambda: daemon_dir
    handler.running_version_reader = lambda: running_version
    return handler


class TestInitialisation:
    def test_handler_identity_and_priority(self) -> None:
        handler = DaemonUpgradeDetectorHandler()
        assert handler.handler_id == HandlerID.DAEMON_UPGRADE_DETECTOR
        assert handler.priority == Priority.DAEMON_UPGRADE_DETECTOR

    def test_handler_is_never_terminal(self) -> None:
        """An advisory that can end dispatch would be a bug."""
        assert DaemonUpgradeDetectorHandler().terminal is False


class TestDormancyInSelfInstallMode:
    """Plan 00395: irrelevant, and must be silent, in self-install mode."""

    def test_matches_false_when_self_install_mode_true(self) -> None:
        handler = DaemonUpgradeDetectorHandler()
        handler.self_install_reader = lambda: True
        assert handler.matches(_hook_input()) is False

    def test_matches_true_when_self_install_mode_false(self) -> None:
        handler = DaemonUpgradeDetectorHandler()
        handler.self_install_reader = lambda: False
        assert handler.matches(_hook_input()) is True

    def test_is_dormant_reflects_self_install_reader(self) -> None:
        handler = DaemonUpgradeDetectorHandler()
        handler.self_install_reader = lambda: True
        assert handler.is_dormant() is True
        handler.self_install_reader = lambda: False
        assert handler.is_dormant() is False

    def test_is_dormant_fails_open_to_dormant_when_reader_raises(self) -> None:
        """An advisory that cannot even tell which install mode it is running
        under must not announce itself as active policy."""

        def _raise() -> bool:
            raise RuntimeError("ProjectContext not initialised")

        handler = DaemonUpgradeDetectorHandler()
        handler.self_install_reader = _raise
        assert handler.is_dormant() is True


class TestMatchingVersionIsSilent:
    def test_matching_version_produces_no_context(self, tmp_path: Path) -> None:
        _write_installed_version(tmp_path, "1.0.0")

        result = _handler(tmp_path).handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestReportsSourceUpgradedUnderneathTheDaemon:
    """Plan 00517 Task 2.1: version.py rewritten on disk while the daemon runs."""

    def test_second_call_reports_the_new_version(self, tmp_path: Path) -> None:
        _write_installed_version(tmp_path, "1.0.0")
        handler = _handler(tmp_path)

        first = handler.handle(_hook_input())
        assert first.decision == Decision.ALLOW
        assert first.context == []

        _write_installed_version(tmp_path, "1.1.0")

        second = handler.handle(_hook_input())
        assert second.decision == Decision.ALLOW
        assert second.context
        joined = " ".join(second.context)
        assert "1.1.0" in joined
        assert "1.0.0" in joined


class TestVenvMetadataIsNotTheInstalledVersion:
    """Plan 00517 Task 2.1: metadata names the build, not the installation."""

    def test_metadata_naming_another_version_than_the_source_is_silent(
        self, tmp_path: Path
    ) -> None:
        _write_installed_version(tmp_path, "1.0.0")
        venv_dir = tmp_path / "untracked" / f"venv-{python_venv_fingerprint(tmp_path)}"
        _make_fake_venv(venv_dir)
        _write_metadata(venv_dir, daemon_version="v9.9.9")

        result = _handler(tmp_path).handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_metadata_matching_the_running_version_does_not_hide_an_upgraded_source(
        self, tmp_path: Path
    ) -> None:
        _write_installed_version(tmp_path, "2.0.0")
        venv_dir = tmp_path / "untracked" / f"venv-{python_venv_fingerprint(tmp_path)}"
        _make_fake_venv(venv_dir)
        _write_metadata(venv_dir, daemon_version="v1.0.0")

        result = _handler(tmp_path).handle(_hook_input())

        assert result.context
        assert "2.0.0" in " ".join(result.context)


class TestAdvisoryContent:
    """The advisory names the restart command; nothing self-restarts."""

    def test_advisory_names_both_versions_and_the_restart_command(self, tmp_path: Path) -> None:
        _write_installed_version(tmp_path, "9.9.9")

        result = _handler(tmp_path, running_version="1.0.0").handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context
        message = " ".join(result.context)
        assert "9.9.9" in message
        assert "1.0.0" in message
        assert daemon_cli_command("restart") in message

    def test_decision_is_allow_even_when_stale(self, tmp_path: Path) -> None:
        """The handler is purely advisory: it never denies or blocks a prompt."""
        _write_installed_version(tmp_path, "42.0.0")

        result = _handler(tmp_path).handle(_hook_input())

        assert result.decision == Decision.ALLOW


class TestFailOpen:
    """An unreadable or missing version.py never blocks a prompt."""

    def test_no_version_file_at_all_is_silent_allow(self, tmp_path: Path) -> None:
        result = _handler(tmp_path).handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_version_file_without_a_version_literal_is_silent_allow(self, tmp_path: Path) -> None:
        target = tmp_path / INSTALLED_SOURCE_VERSION_REL_PATH
        target.parent.mkdir(parents=True)
        target.write_text('"""nothing here"""\n')

        result = _handler(tmp_path).handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_undecodable_version_file_is_silent_allow(self, tmp_path: Path) -> None:
        target = tmp_path / INSTALLED_SOURCE_VERSION_REL_PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(b"\xff\xfe\x00 not utf-8 \xff")

        result = _handler(tmp_path).handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_daemon_root_reader_raising_is_silent_allow(self) -> None:
        """No project context yet (e.g. mid-startup) must never block a prompt."""

        def _raise() -> Path:
            raise RuntimeError("ProjectContext not initialised")

        handler = DaemonUpgradeDetectorHandler()
        handler.self_install_reader = lambda: False
        handler.daemon_root_reader = _raise
        handler.running_version_reader = lambda: _RUNNING_VERSION

        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []
