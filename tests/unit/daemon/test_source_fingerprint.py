"""Tests for daemon/source_fingerprint.py (Plan 00371).

A running daemon never hot-reloads its own code: every handler module and
every project-level handler is imported once, at ``DaemonController.initialise()``
time, and stays in memory until the process is restarted. These tests cover
the content-fingerprint primitives that let a caller detect when a running
daemon's loaded code no longer matches what is on disk -- the general-purpose
version of the exact bug this plan fixes (Plan 00371: a stale daemon answered
an acceptance probe with pre-merge code and the harness could not tell).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.source_fingerprint import (
    compute_current_project_fingerprint,
    compute_daemon_identity_fingerprint,
    compute_source_fingerprint,
    daemon_package_root,
    describe_fingerprint_mismatch,
)


class TestDaemonPackageRoot:
    """Tests for daemon_package_root()."""

    def test_returns_a_directory(self) -> None:
        """The resolved root exists and is a directory."""
        root = daemon_package_root()
        assert root.is_dir()

    def test_contains_this_very_module(self) -> None:
        """The root is the package this test imports FROM, not some other path."""
        root = daemon_package_root()
        assert (root / "daemon" / "source_fingerprint.py").is_file()

    def test_is_absolute(self) -> None:
        """Callers hash byte content by path; a relative root would be ambiguous."""
        assert daemon_package_root().is_absolute()


class TestComputeSourceFingerprint:
    """Tests for compute_source_fingerprint()."""

    def test_deterministic_across_repeated_calls(self, tmp_path: Path) -> None:
        """Hashing the same tree twice gives the same digest."""
        root = tmp_path / "pkg"
        root.mkdir()
        (root / "a.py").write_text("print('a')\n", encoding="utf-8")
        (root / "b.py").write_text("print('b')\n", encoding="utf-8")

        first = compute_source_fingerprint(root)
        second = compute_source_fingerprint(root)

        assert first == second

    def test_changes_when_a_byte_changes(self, tmp_path: Path) -> None:
        """A single-character edit to a tracked file flips the digest.

        This is the property the whole plan depends on: the daemon and the
        working tree diverging by even one character must be detectable.
        """
        root = tmp_path / "pkg"
        root.mkdir()
        target = root / "a.py"
        target.write_text("print('a')\n", encoding="utf-8")
        before = compute_source_fingerprint(root)

        target.write_text("print('A')\n", encoding="utf-8")
        after = compute_source_fingerprint(root)

        assert before != after

    def test_sensitive_to_a_rename(self, tmp_path: Path) -> None:
        """Renaming a file (same bytes, different relative path) flips the digest.

        A path-blind hash (content only, no filename) would miss a handler
        module being renamed or moved to a different event-type directory.
        """
        root = tmp_path / "pkg"
        root.mkdir()
        original = root / "a.py"
        original.write_text("print('same bytes')\n", encoding="utf-8")
        before = compute_source_fingerprint(root)

        renamed = root / "renamed.py"
        original.rename(renamed)
        after = compute_source_fingerprint(root)

        assert before != after

    def test_stable_regardless_of_filesystem_iteration_order(self, tmp_path: Path) -> None:
        """Files are visited in sorted order, not directory-listing order."""
        root_a = tmp_path / "pkg_a"
        root_a.mkdir()
        (root_a / "zzz.py").write_text("1\n", encoding="utf-8")
        (root_a / "aaa.py").write_text("2\n", encoding="utf-8")

        root_b = tmp_path / "pkg_b"
        root_b.mkdir()
        # Same two files, created in the opposite order.
        (root_b / "aaa.py").write_text("2\n", encoding="utf-8")
        (root_b / "zzz.py").write_text("1\n", encoding="utf-8")

        assert compute_source_fingerprint(root_a) == compute_source_fingerprint(root_b)

    def test_missing_root_is_skipped_not_raised(self, tmp_path: Path) -> None:
        """A configured-but-absent extra root (e.g. no project-handlers yet) is inert.

        Matches the project convention elsewhere (e.g. metadata.py's
        read_daemon_metadata): absence of an optional directory is a normal
        state, not a fatal one.
        """
        present = tmp_path / "present"
        present.mkdir()
        (present / "a.py").write_text("print('a')\n", encoding="utf-8")
        missing = tmp_path / "does-not-exist"

        with_missing = compute_source_fingerprint(present, missing)
        without_missing = compute_source_fingerprint(present)

        assert with_missing == without_missing

    def test_only_python_files_are_hashed(self, tmp_path: Path) -> None:
        """A non-.py file changing must not affect the fingerprint.

        The fingerprint's whole premise is "the code a running Python
        process imported" -- a README or a .pyc byte-compiled cache is
        neither.
        """
        root = tmp_path / "pkg"
        root.mkdir()
        (root / "a.py").write_text("print('a')\n", encoding="utf-8")
        before = compute_source_fingerprint(root)

        (root / "README.md").write_text("unrelated docs\n", encoding="utf-8")
        after = compute_source_fingerprint(root)

        assert before == after

    def test_two_roots_combine_into_one_digest(self, tmp_path: Path) -> None:
        """Multiple roots are mixed into a single fingerprint, not compared separately."""
        root_a = tmp_path / "a"
        root_a.mkdir()
        (root_a / "x.py").write_text("1\n", encoding="utf-8")
        root_b = tmp_path / "b"
        root_b.mkdir()
        (root_b / "y.py").write_text("2\n", encoding="utf-8")

        combined = compute_source_fingerprint(root_a, root_b)

        assert combined != compute_source_fingerprint(root_a)
        assert combined != compute_source_fingerprint(root_b)


class TestComputeDaemonIdentityFingerprint:
    """Tests for compute_daemon_identity_fingerprint()."""

    def test_matches_manual_computation_with_no_extra_roots(self) -> None:
        """With no extra roots, it is exactly the package root's own fingerprint."""
        assert compute_daemon_identity_fingerprint() == compute_source_fingerprint(
            daemon_package_root()
        )

    def test_includes_an_extra_root_when_given(self, tmp_path: Path) -> None:
        """An extra root (e.g. a resolved project-handlers directory) changes the digest."""
        extra = tmp_path / "project-handlers"
        extra.mkdir()
        (extra / "custom_handler.py").write_text("# custom\n", encoding="utf-8")

        without_extra = compute_daemon_identity_fingerprint()
        with_extra = compute_daemon_identity_fingerprint(extra)

        assert without_extra != with_extra


class TestDescribeFingerprintMismatch:
    """Tests for describe_fingerprint_mismatch()."""

    def test_none_when_fingerprints_match(self) -> None:
        """A daemon whose reported fingerprint equals the current one is fresh."""
        assert describe_fingerprint_mismatch("abc123", "abc123") is None

    def test_message_when_running_fingerprint_is_missing(self) -> None:
        """No reported fingerprint at all (down, unreachable, or a daemon that
        predates this plan) is a staleness risk, not merely 'unknown'."""
        message = describe_fingerprint_mismatch(None, "abc123")

        assert message is not None
        assert "restart" in message.lower()

    def test_message_names_stale_daemon_on_mismatch(self) -> None:
        """A genuine mismatch is named clearly, not left to a generic assertion failure.

        This is the regression this plan fixes, reproduced directly: the
        exact reported incident was a stale daemon answering with the wrong
        reason and nothing naming *why* -- this message must name it.
        """
        message = describe_fingerprint_mismatch("running-fp-value", "current-fp-value")

        assert message is not None
        assert "stale" in message.lower()
        assert "restart" in message.lower()

    @pytest.mark.parametrize("running", ["deadbeef" * 8, None])
    def test_never_raises(self, running: str | None) -> None:
        """A pure comparison function: never raises regardless of input shape."""
        describe_fingerprint_mismatch(running, "current")


class TestComputeCurrentProjectFingerprint:
    """Tests for compute_current_project_fingerprint() -- Plan 00371.

    This is the config-aware convenience a caller with no live
    ``DaemonController`` uses (a CLI verb, an acceptance test): it loads the
    project's own ``hooks-daemon.yaml`` to resolve ``project_handlers`` the
    same way ``DaemonController.initialise()`` does, so it matches what a
    freshly-started daemon would report.
    """

    def test_no_config_file_matches_package_only_fingerprint(self, tmp_path: Path) -> None:
        """No hooks-daemon.yaml at all -> defaults (enabled, default path,
        which does not exist under an empty tmp_path) -> package root alone."""
        result = compute_current_project_fingerprint(tmp_path)

        assert result == compute_daemon_identity_fingerprint()

    def test_enabled_project_handlers_directory_is_included(self, tmp_path: Path) -> None:
        """A configured, enabled, populated project-handlers dir changes the digest."""
        claude_dir = tmp_path / ".claude"
        handlers_dir = claude_dir / "project-handlers"
        handlers_dir.mkdir(parents=True)
        (handlers_dir / "custom.py").write_text("# custom\n", encoding="utf-8")
        (claude_dir / "hooks-daemon.yaml").write_text(
            "version: '1.0'\n"
            "project_handlers:\n"
            "  enabled: true\n"
            "  path: .claude/project-handlers\n",
            encoding="utf-8",
        )

        result = compute_current_project_fingerprint(tmp_path)

        assert result != compute_daemon_identity_fingerprint()
        assert result == compute_daemon_identity_fingerprint(handlers_dir)

    def test_disabled_project_handlers_directory_is_excluded(self, tmp_path: Path) -> None:
        """enabled: false means that directory's edits must not look like staleness."""
        claude_dir = tmp_path / ".claude"
        handlers_dir = claude_dir / "project-handlers"
        handlers_dir.mkdir(parents=True)
        (handlers_dir / "custom.py").write_text("# custom\n", encoding="utf-8")
        (claude_dir / "hooks-daemon.yaml").write_text(
            "version: '1.0'\n"
            "project_handlers:\n"
            "  enabled: false\n"
            "  path: .claude/project-handlers\n",
            encoding="utf-8",
        )

        result = compute_current_project_fingerprint(tmp_path)

        assert result == compute_daemon_identity_fingerprint()

    def test_malformed_config_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """A config that fails schema validation degrades gracefully rather than raising.

        A freshness CHECK must not itself crash on an already-broken config --
        that is a separate, already-surfaced problem (the daemon's own
        degraded-mode path), not this helper's to raise.
        """
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / "hooks-daemon.yaml").write_text(
            "project_handlers:\n  enabled: not-a-boolean\n", encoding="utf-8"
        )

        result = compute_current_project_fingerprint(tmp_path)

        assert result == compute_daemon_identity_fingerprint()
