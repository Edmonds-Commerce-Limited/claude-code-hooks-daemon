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
    claude_project_dir,
    config_dir_within,
    is_in_claude_config_dir,
    project_dir_name,
    session_config_dir,
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


class TestIsInClaudeConfigDir:
    """Whether a path in a project lies in Claude Code's config dir (Plan 00468 P3).

    Both spellings count: the config dir named inside the project, and a
    home that is a symlink into it (ccy). A config dir that contains the
    project would claim every project file, so it claims none.
    """

    def test_a_file_in_an_in_project_config_dir_is_in_it(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        config = root / ".claude" / "ccy"
        (config / "plugins").mkdir(parents=True)
        assert is_in_claude_config_dir(config / "plugins" / "a.md", root, config_dir=config)

    def test_a_project_file_is_not(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        config = root / ".claude" / "ccy"
        config.mkdir(parents=True)
        assert not is_in_claude_config_dir(root / "README.md", root, config_dir=config)

    def test_a_home_symlinked_into_the_project_is_recognised(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        target = root / ".claude" / "ccy"
        target.mkdir(parents=True)
        link = tmp_path / "home" / ".claude"
        link.parent.mkdir()
        link.symlink_to(target)
        assert is_in_claude_config_dir(target / "a.md", root, config_dir=link)

    def test_a_project_symlink_to_an_outside_home_is_recognised(self, tmp_path: Path) -> None:
        home = tmp_path / "home" / ".claude"
        (home / "plugins").mkdir(parents=True)
        root = tmp_path / "project"
        (root / ".claude").mkdir(parents=True)
        (root / ".claude" / "ccy").symlink_to(home)
        path = root / ".claude" / "ccy" / "plugins"
        assert is_in_claude_config_dir(path, root, config_dir=home)

    def test_a_config_dir_containing_the_project_claims_nothing(self, tmp_path: Path) -> None:
        root = tmp_path / "config" / "projects" / "p"
        root.mkdir(parents=True)
        assert not is_in_claude_config_dir(root / "a.md", root, config_dir=tmp_path / "config")


class TestSessionConfigDir:
    """The calling session's config dir, read from the transcript path Claude
    Code names in every payload (Plan 00468 G10): the daemon's own
    environment is fixed at start and may belong to a different home."""

    def test_the_transcript_names_its_config_dir(self, tmp_path: Path) -> None:
        transcript = tmp_path / "home" / ".claude" / "projects" / "-repo" / "abc.jsonl"
        assert session_config_dir(str(transcript)) == tmp_path / "home" / ".claude"

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            42,
            "relative/projects/-repo/abc.jsonl",
            "/home/.claude/logs/-repo/abc.jsonl",
            "/home/.claude/projects/-repo/abc.txt",
            "/home/.claude/projects/-repo/session/subagents/agent-1.jsonl",
        ],
    )
    def test_any_other_shape_names_nothing(self, value: object) -> None:
        assert session_config_dir(value) is None


class TestProjectDirName:
    """Claude Code's name for a project's transcripts directory (00466 N27).

    Pinned to Claude Code's own rule, read from its shipped bundle: every
    UTF-16 code unit outside ``[a-zA-Z0-9]`` becomes ``-``; a name longer than
    200 characters is cut to 200 and suffixed with ``-`` and the base-36
    absolute value of the path's 32-bit Java-style string hash. The expected
    values below were computed by running that JavaScript under node.
    """

    def test_dots_underscores_and_hyphens_all_become_hyphens(self) -> None:
        assert project_dir_name("/home/me/my_app.v2/sub-dir") == "-home-me-my-app-v2-sub-dir"

    def test_the_workspace_root_matches_the_real_directory(self) -> None:
        assert project_dir_name("/workspace") == "-workspace"

    def test_a_long_path_is_truncated_and_hashed(self) -> None:
        long_path = "/srv/" + "deep_dir.v2/" * 20 + "proj-x"
        expected = "-srv" + "-deep-dir-v2" * 16 + "-dee-2zml51"
        assert project_dir_name(long_path) == expected

    def test_non_ascii_is_replaced_per_utf16_code_unit(self) -> None:
        path = "/tmp/café \U0001f600" + "x" * 200
        name = project_dir_name(path)
        assert name.startswith("-tmp-caf----xxx")
        assert name.endswith("-irosb")


class TestClaudeProjectDir:
    def test_it_is_under_projects_in_the_config_dir(self, tmp_path: Path) -> None:
        root = tmp_path / "my_app.v2"
        root.mkdir()
        config = tmp_path / "cfg"
        expected = config / "projects" / project_dir_name(str(root.resolve()))
        assert claude_project_dir(root, config_dir=config) == expected

    def test_a_symlinked_project_uses_its_real_path(self, tmp_path: Path) -> None:
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        config = tmp_path / "cfg"
        assert claude_project_dir(link, config_dir=config) == claude_project_dir(
            real, config_dir=config
        )

    def test_the_default_config_dir_honours_the_variable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(CLAUDE_CONFIG_DIR_ENV, str(tmp_path / "cfg"))
        assert claude_project_dir(tmp_path).parent == tmp_path / "cfg" / "projects"

    def test_a_missing_directory_raises_when_required(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="projects"):
            claude_project_dir(tmp_path, config_dir=tmp_path / "cfg", must_exist=True)

    def test_an_existing_directory_is_returned_when_required(self, tmp_path: Path) -> None:
        config = tmp_path / "cfg"
        expected = claude_project_dir(tmp_path, config_dir=config)
        expected.mkdir(parents=True)
        assert claude_project_dir(tmp_path, config_dir=config, must_exist=True) == expected
