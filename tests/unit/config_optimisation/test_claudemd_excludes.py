"""Optimise recommends ``claudeMdExcludes`` for worktrees under the project root (Plan 00563)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config_optimisation.claudemd_excludes import (
    git_worktree_paths,
    glob_to_regex,
    suggest_claudemd_excludes,
)

UNTRACKED_GLOB = "**/untracked/worktrees/*/CLAUDE.md"
CLAUDE_GLOB = "**/.claude/worktrees/*/CLAUDE.md"


def _make_worktree_dir(project: Path, root: str, name: str = "wt-one") -> None:
    (project / root / name).mkdir(parents=True)


def _write_settings(project: Path, filename: str, excludes: list[str]) -> None:
    settings = project / ".claude" / filename
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"claudeMdExcludes": excludes}))


class TestSuggestClaudeMdExcludes:
    """The three detection cases the owner ruling requires, plus edges."""

    def test_uncovered_root_is_recommended(self, tmp_path: Path) -> None:
        _make_worktree_dir(tmp_path, "untracked/worktrees")

        lines = suggest_claudemd_excludes(tmp_path)

        text = "\n".join(lines)
        assert UNTRACKED_GLOB in text
        assert "claudeMdExcludes" in text
        assert ".claude/settings.local.json" in text
        assert "twice" in text
        assert CLAUDE_GLOB not in text

    def test_covered_root_is_silent(self, tmp_path: Path) -> None:
        _make_worktree_dir(tmp_path, "untracked/worktrees")
        _write_settings(tmp_path, "settings.local.json", [UNTRACKED_GLOB])

        assert suggest_claudemd_excludes(tmp_path) == []

    def test_no_worktrees_under_root_is_silent(self, tmp_path: Path) -> None:
        assert suggest_claudemd_excludes(tmp_path) == []

    def test_empty_worktree_root_is_silent(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "worktrees").mkdir(parents=True)

        assert suggest_claudemd_excludes(tmp_path) == []

    def test_coverage_may_come_from_shared_settings_file(self, tmp_path: Path) -> None:
        _make_worktree_dir(tmp_path, ".claude/worktrees")
        _write_settings(tmp_path, "settings.json", [CLAUDE_GLOB])

        assert suggest_claudemd_excludes(tmp_path) == []

    def test_only_the_uncovered_root_is_recommended(self, tmp_path: Path) -> None:
        _make_worktree_dir(tmp_path, "untracked/worktrees")
        _make_worktree_dir(tmp_path, ".claude/worktrees")
        _write_settings(tmp_path, "settings.local.json", [UNTRACKED_GLOB])

        text = "\n".join(suggest_claudemd_excludes(tmp_path))

        assert CLAUDE_GLOB in text
        assert UNTRACKED_GLOB not in text

    def test_git_reported_worktree_under_root_is_recommended(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "ws" / "feature-a"
        elsewhere.mkdir(parents=True)

        text = "\n".join(suggest_claudemd_excludes(tmp_path, git_worktrees=[elsewhere]))

        assert "**/ws/*/CLAUDE.md" in text

    def test_git_worktree_outside_root_is_ignored(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        outside = tmp_path / "other" / "wt"
        outside.mkdir(parents=True)

        assert suggest_claudemd_excludes(project, git_worktrees=[outside]) == []

    def test_project_root_itself_is_not_a_worktree_root(self, tmp_path: Path) -> None:
        assert suggest_claudemd_excludes(tmp_path, git_worktrees=[tmp_path]) == []

    def test_unreadable_settings_is_reported_not_swallowed(self, tmp_path: Path) -> None:
        _make_worktree_dir(tmp_path, "untracked/worktrees")
        settings = tmp_path / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("{not json")

        text = "\n".join(suggest_claudemd_excludes(tmp_path))

        assert "settings.local.json" in text
        assert "cannot" in text.lower()


class TestEdges:
    """A worktree directly under the root, and an unreadable worktree root."""

    def test_worktree_directly_under_the_root_is_excluded_by_its_own_name(
        self, tmp_path: Path
    ) -> None:
        direct = tmp_path / "feature-a"
        direct.mkdir()

        text = "\n".join(suggest_claudemd_excludes(tmp_path, git_worktrees=[direct]))

        assert '"**/feature-a/CLAUDE.md"' in text
        assert "**/feature-a/*/CLAUDE.md" not in text

    def test_worktree_directly_under_the_root_is_silent_once_covered(self, tmp_path: Path) -> None:
        direct = tmp_path / "feature-a"
        direct.mkdir()
        _write_settings(tmp_path, "settings.local.json", ["**/feature-a/CLAUDE.md"])

        assert suggest_claudemd_excludes(tmp_path, git_worktrees=[direct]) == []

    def test_unreadable_worktree_root_is_reported_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_worktree_dir(tmp_path, "untracked/worktrees")
        real_iterdir = Path.iterdir

        def deny(self: Path) -> Iterator[Path]:
            if self.name == "worktrees":
                raise PermissionError(13, "Permission denied", str(self))
            return real_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", deny)

        text = "\n".join(suggest_claudemd_excludes(tmp_path))

        assert "cannot" in text.lower()
        assert "Permission denied" in text


class TestGlobToRegex:
    """``**`` crosses directories, ``*`` does not (moved from the integration test)."""

    def test_double_star_crosses_directories(self) -> None:
        assert glob_to_regex(UNTRACKED_GLOB).match("/p/untracked/worktrees/w/CLAUDE.md")

    def test_single_star_stays_in_one_segment(self) -> None:
        assert not glob_to_regex(UNTRACKED_GLOB).match("/p/untracked/worktrees/w/src/CLAUDE.md")

    def test_question_mark_matches_one_character(self) -> None:
        assert glob_to_regex("/a/?.md").match("/a/b.md")
        assert not glob_to_regex("/a/?.md").match("/a/bc.md")

    def test_character_classes_and_braces_are_literal(self) -> None:
        """Only ``**``, ``*`` and ``?`` are wildcards; ``[...]`` and ``{a,b}`` are not."""
        assert glob_to_regex("/a/[bc].md").match("/a/[bc].md")
        assert not glob_to_regex("/a/[bc].md").match("/a/b.md")
        assert glob_to_regex("/a/{x,y}.md").match("/a/{x,y}.md")
        assert not glob_to_regex("/a/{x,y}.md").match("/a/x.md")


class TestGitWorktreePaths:
    """``git worktree list --porcelain`` parsing against a real repository."""

    def test_lists_linked_worktrees(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        env_args = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), *env_args, "commit", "-q", "--allow-empty", "-m", "init"],
            check=True,
        )
        linked = repo / "wts" / "one"
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "one", str(linked)],
            check=True,
        )

        paths = git_worktree_paths(repo)

        assert linked.resolve() in [p.resolve() for p in paths]

    def test_not_a_repository_yields_nothing(self, tmp_path: Path) -> None:
        assert git_worktree_paths(tmp_path) == []


@pytest.mark.parametrize("glob", [UNTRACKED_GLOB, CLAUDE_GLOB])
def test_repo_own_setting_shape_is_covered(glob: str) -> None:
    """The reference globs from Plan 00561 match a worktree-root CLAUDE.md."""
    target = "/example/project/" + glob.removeprefix("**/").replace("*", "wt", 1)
    assert glob_to_regex(glob).match(target)
