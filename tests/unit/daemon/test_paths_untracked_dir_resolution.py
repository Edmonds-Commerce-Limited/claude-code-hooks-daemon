"""Tests for `daemon.paths` self-install/untracked-dir resolution (Plan 00457).

`is_self_install_mode` and `get_untracked_dir` are the ONE definition of
"is this a self-install checkout, and where does its untracked/ live" --
`ProjectContext.initialize` (core/project_context.py) and the venv-free
`signal` entry point (`daemon/signal_standalone.py`, loaded by file path
rather than import) both call these instead of each keeping their own copy.
"""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import get_untracked_dir, is_self_install_mode


class TestIsSelfInstallMode:
    def test_true_when_daemon_source_is_at_the_project_root(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)

        assert is_self_install_mode(tmp_path) is True

    def test_false_when_no_daemon_source_is_present(self, tmp_path: Path) -> None:
        assert is_self_install_mode(tmp_path) is False

    def test_false_when_the_path_is_a_file_not_a_directory(self, tmp_path: Path) -> None:
        """A stray file at that path is not a checked-out daemon source tree."""
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

    def test_accepts_a_string_path(self, tmp_path: Path) -> None:
        assert (
            get_untracked_dir(str(tmp_path)) == tmp_path / ".claude" / "hooks-daemon" / "untracked"
        )

    def test_resolves_a_relative_path(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert get_untracked_dir(Path()) == tmp_path / ".claude" / "hooks-daemon" / "untracked"
