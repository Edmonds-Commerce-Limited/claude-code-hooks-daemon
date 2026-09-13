"""Tests for DaemonUpgradeDetectorHandler (Plan 00395).

A running daemon loads `claude_code_hooks_daemon.version.__version__` once, at
import time, and keeps serving it for the life of the process. This handler
notices when the INSTALLED daemon (the venv's `.daemon-metadata.json`) has
moved on without this process — another session or process upgraded the
installation on the same filesystem while this one kept running.

Two properties matter more than any of the mechanics:

- **Re-resolution, not memory.** The venv is fingerprint-keyed, so an upgrade
  that changes the fingerprint inputs creates a NEW venv directory rather than
  rewriting the old one. A check that reused a path captured once (at
  construction, or after the first successful resolution) would keep reading
  the OLD venv's untouched metadata and report "fresh" forever.
  `TestReReResolvesTheVenvEachCall` is the test that would fail against that
  bug -- it drives the SAME handler instance across two calls and only adds
  the new venv directory between them.
- **Silent when nothing changed, fail-open when anything is unreadable.** An
  advisory on every turn for a fact that changes at most once per upgrade
  would be worse than the defect it reports, and this handler must never
  block a prompt over its own inability to read installer state.
"""

from __future__ import annotations

import json
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

_RUNNING_VERSION = "1.0.0"


def _hook_input() -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "prompt": "hello"}


def _make_fake_venv(venv_dir: Path) -> Path:
    """Create a minimal venv layout with an executable `bin/python`."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = bin_dir / "python"
    python.write_text("#!/bin/sh\nexec true\n")
    python.chmod(python.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return python


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
    """Task 2.7: nothing changed -> nothing said."""

    def test_matching_version_produces_no_context(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        _write_metadata(venv_dir, daemon_version="v1.0.0")

        handler = _handler(daemon_dir)
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []


class TestReportsStaleWhenMetadataRewrittenInPlace:
    """Task 2.2: same venv directory, `.daemon-metadata.json` rewritten."""

    def test_second_call_reports_the_new_version(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        _write_metadata(venv_dir, daemon_version="v1.0.0")

        handler = _handler(daemon_dir)

        first = handler.handle(_hook_input())
        assert first.decision == Decision.ALLOW
        assert first.context == []

        # In-place upgrade: same venv directory, metadata rewritten.
        _write_metadata(venv_dir, daemon_version="v1.1.0")

        second = handler.handle(_hook_input())
        assert second.decision == Decision.ALLOW
        assert second.context
        joined = " ".join(second.context)
        assert "1.1.0" in joined
        assert "1.0.0" in joined


class TestReReResolvesTheVenvEachCall:
    """Task 2.1: the case a remembered-path check gets wrong.

    An upgrade that changes the venv's fingerprint inputs creates a NEW
    venv directory rather than rewriting the old one, so the old venv's own
    metadata stays untouched (the file the process was started against, or
    ``sys.prefix``, never moves). A correct check must re-resolve the venv on
    every call rather than reuse a value captured once; this test drives the
    SAME handler instance across two calls, adding the new venv directory
    only between them, and would fail against an implementation that cached
    the resolved venv path (or the installed version) after the first call.
    """

    def test_new_fingerprint_keyed_venv_is_noticed_without_reconstructing_the_handler(
        self, tmp_path: Path
    ) -> None:
        daemon_dir = tmp_path
        untracked = daemon_dir / "untracked"

        # The OLD venv: a foreign, non-current-fingerprint name -- exactly
        # what a stale venv from a prior interpreter/fingerprint looks like.
        # It is the only venv present before the "upgrade", so scan fallback
        # (step 3 of resolve_existing_venv_python) finds it.
        old_venv = untracked / "venv-py311-00000000"
        _make_fake_venv(old_venv)
        _write_metadata(old_venv, daemon_version="v1.0.0")

        handler = _handler(daemon_dir)

        first = handler.handle(_hook_input())
        assert first.decision == Decision.ALLOW
        assert first.context == []

        # "Another session upgrades": a NEW venv appears at the CURRENT
        # fingerprint-keyed path -- exactly what ensure_venv would name it --
        # with a newer daemon_version. The OLD venv is left in place
        # (upgrades do not always clean up), which is exactly the case a
        # remembered-path/sys.prefix check would get wrong.
        new_venv = untracked / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(new_venv)
        _write_metadata(new_venv, daemon_version="v2.0.0")

        second = handler.handle(_hook_input())
        assert second.decision == Decision.ALLOW
        assert second.context
        joined = " ".join(second.context)
        assert "2.0.0" in joined
        assert "1.0.0" in joined


class TestAdvisoryContent:
    """Task 2.4: the advisory names the restart command; nothing self-restarts."""

    def test_advisory_names_both_versions_and_the_restart_command(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        _write_metadata(venv_dir, daemon_version="v9.9.9")

        handler = _handler(daemon_dir, running_version="1.0.0")
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context
        message = " ".join(result.context)
        assert "9.9.9" in message
        assert "1.0.0" in message
        assert daemon_cli_command("restart") in message

    def test_decision_is_allow_even_when_stale(self, tmp_path: Path) -> None:
        """The handler is purely advisory: it never denies or blocks a prompt,
        and (by construction -- it only ever returns text) never restarts
        anything itself."""
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        _write_metadata(venv_dir, daemon_version="v42.0.0")

        handler = _handler(daemon_dir)
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW


class TestFailOpen:
    """Task 2.5: unreadable, missing or malformed metadata never blocks a prompt."""

    def test_no_untracked_dir_at_all_is_silent_allow(self, tmp_path: Path) -> None:
        handler = _handler(tmp_path)
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_venv_present_but_no_metadata_file_is_silent_allow(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        # No .daemon-metadata.json written at all.

        handler = _handler(daemon_dir)
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_malformed_metadata_is_silent_allow(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        (venv_dir / ".daemon-metadata.json").write_text("{not valid json")

        handler = _handler(daemon_dir)
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_empty_metadata_file_is_silent_allow(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        (venv_dir / ".daemon-metadata.json").write_text("")

        handler = _handler(daemon_dir)
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_daemon_root_reader_raising_is_silent_allow(self, tmp_path: Path) -> None:
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


class TestVersionMetadataShapesAreTolerated:
    """The plan requires tolerating the guarded-branch install stamp shape
    (`vX.Y.Z+<ref>.<sha>`) without crashing, comparing on the numeric part."""

    def test_guarded_branch_metadata_compares_on_the_numeric_version(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        _write_metadata(venv_dir, daemon_version="v1.0.0+main.abcdef1")

        # The running process's own __version__ never carries a ref/sha
        # suffix (it is a plain release literal), so a matching numeric
        # version must still be silent.
        handler = _handler(daemon_dir, running_version="1.0.0")
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_guarded_branch_metadata_with_different_numeric_version_is_reported(
        self, tmp_path: Path
    ) -> None:
        daemon_dir = tmp_path
        venv_dir = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        _make_fake_venv(venv_dir)
        _write_metadata(venv_dir, daemon_version="v2.0.0+main.abcdef1")

        handler = _handler(daemon_dir, running_version="1.0.0")
        result = handler.handle(_hook_input())

        assert result.decision == Decision.ALLOW
        assert result.context
        assert "2.0.0" in " ".join(result.context)


def test_metadata_json_round_trips_through_the_public_reader(tmp_path: Path) -> None:
    """Sanity check that this test module's fixtures write metadata the same
    way the real installer does, via the SAME public writer/reader pair the
    plan requires the handler to reuse (no second metadata reader)."""
    from claude_code_hooks_daemon.daemon.metadata import read_daemon_metadata

    venv_dir = tmp_path / "venv-example"
    _make_fake_venv(venv_dir)
    _write_metadata(venv_dir, daemon_version="v3.0.0")

    metadata = read_daemon_metadata(venv_dir)

    assert metadata is not None
    assert metadata.daemon_version == "v3.0.0"
    assert json.loads((venv_dir / ".daemon-metadata.json").read_text())["daemon_version"] == (
        "v3.0.0"
    )
