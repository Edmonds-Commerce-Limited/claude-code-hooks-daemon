"""Tests for `daemon.install_layout` (Plan 00457).

The ONE definition of "is this a self-install checkout, and where does its
untracked/ live" -- deliberately a TINY, standard-library-only module with
no `claude_code_hooks_daemon` imports of its own, so the venv-free `signal`
entry point (`daemon/signal_standalone.py`) can load it by file path without
dragging in anything heavier (unlike `daemon/paths.py`, which is 1,800+
lines and sets a higher Python floor through unrelated code). `daemon/paths.py`
and `core/project_context.py` both call this instead of keeping their own
copy -- see `tests/unit/daemon/test_paths_untracked_dir_resolution.py` for
the coverage confirming `paths.py`'s re-export still behaves identically.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir, is_self_install_mode


class TestIsSelfInstallMode:
    def test_true_when_daemon_source_is_at_the_project_root(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)

        assert is_self_install_mode(tmp_path) is True

    def test_false_when_no_daemon_source_is_present(self, tmp_path: Path) -> None:
        assert is_self_install_mode(tmp_path) is False

    def test_false_when_the_path_is_a_file_not_a_directory(self, tmp_path: Path) -> None:
        marker = tmp_path / "src" / "claude_code_hooks_daemon"
        marker.parent.mkdir(parents=True)
        marker.write_text("not a directory", encoding="utf-8")

        assert is_self_install_mode(tmp_path) is False


class TestGetUntrackedDir:
    def test_self_install_mode_is_project_root_slash_untracked(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)

        assert get_untracked_dir(tmp_path) == tmp_path / "untracked"

    def test_normal_mode_nests_under_dot_claude_hooks_daemon(self, tmp_path: Path) -> None:
        assert get_untracked_dir(tmp_path) == tmp_path / ".claude" / "hooks-daemon" / "untracked"
