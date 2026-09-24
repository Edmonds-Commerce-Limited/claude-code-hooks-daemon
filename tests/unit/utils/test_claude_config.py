"""Tests for the one Claude Code config-directory resolver (Plan 00468 G13).

Claude Code keeps its user settings, user agents, transcripts and installed
plugins under ``$CLAUDE_CONFIG_DIR``, else ``~/.claude``. Every daemon
component that looks there asks this module rather than hard-coding the
default, so they can never disagree about where the directory is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.claude_config import (
    CLAUDE_CONFIG_DIR_ENV,
    claude_config_dir,
    config_dir_within,
)


class TestClaudeConfigDir:
    def test_the_environment_variable_wins(self, tmp_path: Path) -> None:
        configured = tmp_path / "elsewhere"
        env = {CLAUDE_CONFIG_DIR_ENV: str(configured)}
        assert claude_config_dir(environ=env, home=tmp_path / "home") == configured

    def test_the_default_is_dot_claude_under_home(self, tmp_path: Path) -> None:
        assert claude_config_dir(environ={}, home=tmp_path) == tmp_path / ".claude"

    def test_an_empty_variable_counts_as_unset(self, tmp_path: Path) -> None:
        env = {CLAUDE_CONFIG_DIR_ENV: ""}
        assert claude_config_dir(environ=env, home=tmp_path) == tmp_path / ".claude"

    def test_a_tilde_in_the_variable_is_expanded(self, tmp_path: Path) -> None:
        resolved = claude_config_dir(environ={CLAUDE_CONFIG_DIR_ENV: "~/cfg"}, home=tmp_path)
        assert "~" not in str(resolved)

    def test_the_process_environment_is_the_default_source(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(CLAUDE_CONFIG_DIR_ENV, str(tmp_path / "from-env"))
        assert claude_config_dir() == tmp_path / "from-env"


class TestConfigDirWithin:
    """Whether the config dir lies inside a project, as a project-relative path.

    Under ccy the Claude home is a symlink into the project tree, so both
    sides are resolved before comparing: a literal comparison would miss it.
    """

    def test_an_in_project_config_dir_is_returned_relative(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        config = root / ".claude" / "ccy"
        config.mkdir(parents=True)
        assert config_dir_within(root, config_dir=config) == ".claude/ccy"

    def test_a_symlinked_home_into_the_project_is_found(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        target = root / ".claude" / "ccy"
        target.mkdir(parents=True)
        link = tmp_path / "home" / ".claude"
        link.parent.mkdir()
        link.symlink_to(target)
        assert config_dir_within(root, config_dir=link) == ".claude/ccy"

    def test_a_config_dir_outside_the_project_is_none(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        root.mkdir()
        assert config_dir_within(root, config_dir=tmp_path / "home" / ".claude") is None

    def test_the_project_root_itself_is_not_inside(self, tmp_path: Path) -> None:
        """A config dir equal to the root would make every project file
        'config' — never a sensible answer, so it is refused."""
        assert config_dir_within(tmp_path, config_dir=tmp_path) is None
