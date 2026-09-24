"""Tests for the ``format-markdown`` CLI subcommand."""

import argparse
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_format_markdown

_UNALIGNED_TABLE = (
    "# Test\n"
    "\n"
    "| Field | Key | Type |\n"
    "|-------|-----|------|\n"
    "| A | `x` | int |\n"
    "| Long Name | `y_long` | string |\n"
)

_ALIGNED_MARKER = "| A         |"  # Unaligned source has `| A |`; aligned pads to 9


def _git_init_with_commit(repo_root: Path, tracked_file: Path, content: str) -> None:
    """Create a real nested git repo at ``repo_root`` with one committed file.

    Mirrors the triage reproduction for Plan 00429: a plain ``git init`` plus
    a commit is enough to make ``git status --short`` a trustworthy oracle for
    "did format-markdown touch a file it does not own".
    """
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(repo_root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    tracked_file.parent.mkdir(parents=True, exist_ok=True)
    tracked_file.write_text(content)
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )


class TestCmdFormatMarkdownSingleFile:
    def test_formats_single_file_in_place(self, tmp_path: Path) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        args = argparse.Namespace(path=test_file, check=False)

        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in test_file.read_text()

    def test_returns_zero_when_already_formatted(self, tmp_path: Path) -> None:
        test_file = tmp_path / "already.md"
        test_file.write_text("# Heading\n\nJust prose, no tables.\n")
        args = argparse.Namespace(path=test_file, check=False)

        result = cmd_format_markdown(args)

        assert result == 0

    def test_rejects_non_markdown_extension(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        test_file = tmp_path / "notmarkdown.txt"
        test_file.write_text("some text\n")
        args = argparse.Namespace(path=test_file, check=False)

        result = cmd_format_markdown(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not a markdown file" in captured.err.lower()

    def test_rejects_missing_path(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        missing = tmp_path / "nope.md"
        args = argparse.Namespace(path=missing, check=False)

        result = cmd_format_markdown(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err.lower()


class TestCmdFormatMarkdownDirectory:
    def test_formats_all_markdown_files_in_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text(_UNALIGNED_TABLE)
        (tmp_path / "b.md").write_text(_UNALIGNED_TABLE)
        (tmp_path / "skip.txt").write_text("not markdown\n")
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "c.markdown").write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)

        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in (tmp_path / "a.md").read_text()
        assert _ALIGNED_MARKER in (tmp_path / "b.md").read_text()
        assert _ALIGNED_MARKER in (nested / "c.markdown").read_text()
        assert (tmp_path / "skip.txt").read_text() == "not markdown\n"

    def test_empty_directory_returns_zero(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        args = argparse.Namespace(path=empty, check=False)

        result = cmd_format_markdown(args)

        assert result == 0


class TestCmdFormatMarkdownCheckMode:
    def test_check_mode_returns_one_when_formatting_needed(self, tmp_path: Path) -> None:
        test_file = tmp_path / "doc.md"
        original = _UNALIGNED_TABLE
        test_file.write_text(original)
        args = argparse.Namespace(path=test_file, check=True)

        result = cmd_format_markdown(args)

        assert result == 1
        # Check mode must NOT modify the file
        assert test_file.read_text() == original

    def test_check_mode_returns_zero_when_already_formatted(self, tmp_path: Path) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text("# Heading\n\nNothing to format.\n")
        args = argparse.Namespace(path=test_file, check=True)

        result = cmd_format_markdown(args)

        assert result == 0

    def test_check_mode_directory_flags_any_unformatted_file(self, tmp_path: Path) -> None:
        (tmp_path / "clean.md").write_text("# Clean\n\nProse only.\n")
        (tmp_path / "dirty.md").write_text(_UNALIGNED_TABLE)
        args = argparse.Namespace(path=tmp_path, check=True)

        result = cmd_format_markdown(args)

        assert result == 1
        # Neither file should have been modified
        assert _ALIGNED_MARKER not in (tmp_path / "dirty.md").read_text()


class TestCmdFormatMarkdownMdformatErrors:
    def test_single_file_mdformat_exception_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        test_file = tmp_path / "doc.md"
        test_file.write_text(_UNALIGNED_TABLE)
        args = argparse.Namespace(path=test_file, check=False)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.format_markdown_text",
            side_effect=RuntimeError("boom"),
        ):
            result = cmd_format_markdown(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "boom" in captured.err

    def test_directory_mdformat_exception_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.md").write_text(_UNALIGNED_TABLE)
        args = argparse.Namespace(path=tmp_path, check=False)

        with patch(
            "claude_code_hooks_daemon.daemon.cli.format_markdown_text",
            side_effect=RuntimeError("kaboom"),
        ):
            result = cmd_format_markdown(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "kaboom" in captured.err


class TestCmdFormatMarkdownRepositoryBoundary:
    """Plan 00429: a nested git repository below the walk root is untouched."""

    def test_write_mode_does_not_modify_nested_repo(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Vacuity guard: the project's own file IS still formatted, so a walk
        # that (wrongly) found nothing at all cannot pass this test silently.
        own_file = tmp_path / "own.md"
        own_file.write_text(_UNALIGNED_TABLE)

        vendor_repo = tmp_path / "vendor" / "dep"
        vendored_doc = vendor_repo / "docs" / "b.md"
        _git_init_with_commit(vendor_repo, vendored_doc, _UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in own_file.read_text()

        status = subprocess.run(
            ["git", "-C", str(vendor_repo), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert status.stdout.strip() == ""
        assert _ALIGNED_MARKER not in vendored_doc.read_text()

        captured = capsys.readouterr()
        assert "b.md" not in captured.out

    def test_check_mode_does_not_report_nested_repo(self, tmp_path: Path) -> None:
        own_file = tmp_path / "own.md"
        own_file.write_text(_UNALIGNED_TABLE)

        vendor_repo = tmp_path / "vendor" / "dep"
        vendored_doc = vendor_repo / "docs" / "b.md"
        _git_init_with_commit(vendor_repo, vendored_doc, _UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=True)
        result = cmd_format_markdown(args)

        # Non-zero because own.md (which the caller DOES own) would change.
        assert result == 1

        status = subprocess.run(
            ["git", "-C", str(vendor_repo), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert status.stdout.strip() == ""

    def test_walk_roots_own_repository_is_not_a_boundary(self, tmp_path: Path) -> None:
        # The walk root's OWN repo must not be treated as a nested boundary --
        # only a checkout BELOW the root is skipped.
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        own_file = tmp_path / "own.md"
        own_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in own_file.read_text()

    def test_worktree_git_file_marks_a_boundary_too(self, tmp_path: Path) -> None:
        # A worktree's .git is a FILE, not a directory -- must be recognised
        # as a repository boundary too.
        nested = tmp_path / "worktree-dep"
        docs = nested / "docs"
        docs.mkdir(parents=True)
        (nested / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/x\n")
        vendored_doc = docs / "b.md"
        vendored_doc.write_text(_UNALIGNED_TABLE)

        own_file = tmp_path / "own.md"
        own_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in own_file.read_text()
        assert _ALIGNED_MARKER not in vendored_doc.read_text()


def _git_init_project(project_root: Path) -> None:
    """Init ``project_root`` itself as a git repo, no commit yet.

    Distinct from :func:`_git_init_with_commit`, which inits a NESTED repo
    below the walk root (the repository-BOUNDARY tests above). Here the walk
    ROOT itself is the repository, which is what ``git_visible_paths`` reads.
    """
    subprocess.run(["git", "init", str(project_root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(project_root), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(project_root), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )


def _git_commit_all(project_root: Path) -> None:
    subprocess.run(["git", "-C", str(project_root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(project_root), "commit", "-m", "initial"],
        check=True,
        capture_output=True,
    )


class TestCmdFormatMarkdownGitIgnore:
    """Plan 00468 P3 / Plan 00466 N9's class: a gitignored, non-git directory
    (a Claude Code plugin's cache -- ``.claude/ccy/plugins/cache/...`` has no
    ``.git`` of its own, so the nested-repo boundary above never protects it)
    must not be walked, rewritten, or even reported as needing a reformat.
    """

    def test_gitignored_directory_is_not_walked_or_rewritten(self, tmp_path: Path) -> None:
        _git_init_project(tmp_path)
        own_file = tmp_path / "own.md"
        own_file.write_text(_UNALIGNED_TABLE)
        _git_commit_all(tmp_path)

        (tmp_path / ".gitignore").write_text("plugins/\n")
        plugin_doc = tmp_path / "plugins" / "cache" / "some-plugin" / "SPEC.md"
        plugin_doc.parent.mkdir(parents=True)
        plugin_doc.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in own_file.read_text()
        assert _ALIGNED_MARKER not in plugin_doc.read_text()

    def test_gitignored_directory_is_not_reported_in_check_mode(self, tmp_path: Path) -> None:
        _git_init_project(tmp_path)
        own_file = tmp_path / "own.md"
        own_file.write_text("# Own\n\nAlready clean.\n")
        _git_commit_all(tmp_path)

        (tmp_path / ".gitignore").write_text("plugins/\n")
        plugin_doc = tmp_path / "plugins" / "cache" / "some-plugin" / "SPEC.md"
        plugin_doc.parent.mkdir(parents=True)
        plugin_doc.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=True)
        result = cmd_format_markdown(args)

        assert (
            result == 0
        ), "the gitignored plugin file must not surface as a would-reformat finding"
        assert plugin_doc.read_text() == _UNALIGNED_TABLE

    def test_untracked_but_not_ignored_file_is_still_formatted(self, tmp_path: Path) -> None:
        _git_init_project(tmp_path)
        (tmp_path / ".gitkeep").write_text("")
        _git_commit_all(tmp_path)

        new_file = tmp_path / "new.md"
        new_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in new_file.read_text()

    def test_naming_a_gitignored_directory_directly_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Task 3.1: ``format-markdown .claude/ccy/plugins`` must not rewrite
        anything, even when the plugin tree is named directly rather than
        reached by walking a wider root."""
        _git_init_project(tmp_path)
        (tmp_path / "own.md").write_text("# Own\n")
        _git_commit_all(tmp_path)

        (tmp_path / ".gitignore").write_text("plugins/\n")
        plugins_dir = tmp_path / "plugins"
        plugin_doc = plugins_dir / "cache" / "some-plugin" / "SPEC.md"
        plugin_doc.parent.mkdir(parents=True)
        plugin_doc.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=plugins_dir, check=False)
        result = cmd_format_markdown(args)

        assert result == 1
        assert plugin_doc.read_text() == _UNALIGNED_TABLE
        captured = capsys.readouterr()
        assert "gitignored" in captured.err.lower()

    def test_naming_a_gitignored_file_directly_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _git_init_project(tmp_path)
        (tmp_path / "own.md").write_text("# Own\n")
        _git_commit_all(tmp_path)

        (tmp_path / ".gitignore").write_text("ignored.md\n")
        ignored_file = tmp_path / "ignored.md"
        ignored_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=ignored_file, check=False)
        result = cmd_format_markdown(args)

        assert result == 1
        assert ignored_file.read_text() == _UNALIGNED_TABLE
        captured = capsys.readouterr()
        assert "gitignored" in captured.err.lower()

    def test_outside_a_git_repo_falls_back_to_the_unfiltered_walk(self, tmp_path: Path) -> None:
        own_file = tmp_path / "own.md"
        own_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in own_file.read_text()


class TestCmdFormatMarkdownExcludePaths:
    """Plan 00429: the directory walk honours ``daemon.exclude_paths``."""

    def _write_config(self, project_root: Path, exclude_paths: list[str]) -> None:
        claude_dir = project_root / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        patterns = "\n".join(f"      - '{p}'" for p in exclude_paths)
        (claude_dir / "hooks-daemon.yaml").write_text(f"daemon:\n  exclude_paths:\n{patterns}\n")

    def test_excluded_directory_is_skipped_in_write_mode(self, tmp_path: Path) -> None:
        self._write_config(tmp_path, ["excluded/**"])

        # Vacuity guard: a reachable file IS still formatted.
        reachable = tmp_path / "reachable.md"
        reachable.write_text(_UNALIGNED_TABLE)

        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        excluded_file = excluded_dir / "e.md"
        excluded_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in reachable.read_text()
        assert _ALIGNED_MARKER not in excluded_file.read_text()

    def test_excluded_directory_is_skipped_in_check_mode(self, tmp_path: Path) -> None:
        self._write_config(tmp_path, ["excluded/**"])

        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        excluded_file = excluded_dir / "e.md"
        excluded_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=tmp_path, check=True)
        result = cmd_format_markdown(args)

        # Nothing else in the tree is dirty, and the excluded file must not
        # be reported as needing a reformat.
        assert result == 0
        assert _ALIGNED_MARKER not in excluded_file.read_text()

    def test_exclusions_apply_when_the_walk_root_is_below_the_project_root(
        self, tmp_path: Path
    ) -> None:
        """The config is the PROJECT's, not whatever sits at the walk root.

        `format-markdown <subdir>` is an ordinary invocation, and the project's
        declared exclusions still govern its own tree. Looking for the config
        AT the walk root finds nothing there and silently applies no exclusions
        at all — a filter that quietly matches nothing, which is the exact
        shape of the defect this plan exists to fix.

        The sibling CLIs (docs-qa, plan-qa) resolve a project root first and
        load the config from there; this pins that this one agrees with them.
        """
        self._write_config(tmp_path, ["sub/skipme/**"])

        sub = tmp_path / "sub"
        skipme = sub / "skipme"
        skipme.mkdir(parents=True)

        # Vacuity guard: a reachable file under the SAME walk root is still
        # formatted, so this cannot pass by the walk finding nothing.
        reachable = sub / "keep.md"
        reachable.write_text(_UNALIGNED_TABLE)
        excluded_file = skipme / "x.md"
        excluded_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=sub, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in reachable.read_text()
        assert _ALIGNED_MARKER not in excluded_file.read_text()

    def test_file_argument_named_directly_is_formatted_even_if_excluded(
        self, tmp_path: Path
    ) -> None:
        # Task 1.4: only the DIRECTORY walk filters. A file the caller names
        # directly is formatted regardless of daemon.exclude_paths, because
        # naming it is explicit consent.
        self._write_config(tmp_path, ["excluded/**"])

        excluded_dir = tmp_path / "excluded"
        excluded_dir.mkdir()
        excluded_file = excluded_dir / "e.md"
        excluded_file.write_text(_UNALIGNED_TABLE)

        args = argparse.Namespace(path=excluded_file, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in excluded_file.read_text()


class TestCmdFormatMarkdownDanglingSymlink:
    """A dangling `.md` symlink in the walk must be skipped, not errored.

    Regression guard: the `os.walk` rewrite (Plan 00429) dropped the
    `is_file()` guard that `path.rglob` + `candidate.is_file()` used to
    provide. `os.walk` lists a broken symlink among `filenames`, so it
    reached `_format_single_markdown_file`, whose `read_text` raised
    `FileNotFoundError` -- reported as an error and failing the whole run.
    """

    def test_dangling_symlink_is_skipped_in_check_mode(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "good.md").write_text("# Title\n")
        (tmp_path / "dangling.md").symlink_to(tmp_path / "nowhere.md")

        args = argparse.Namespace(path=tmp_path, check=True)
        result = cmd_format_markdown(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "dangling.md" not in captured.err

    def test_dangling_symlink_is_skipped_in_write_mode(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "good.md").write_text(_UNALIGNED_TABLE)
        (tmp_path / "dangling.md").symlink_to(tmp_path / "nowhere.md")

        args = argparse.Namespace(path=tmp_path, check=False)
        result = cmd_format_markdown(args)

        assert result == 0
        assert _ALIGNED_MARKER in (tmp_path / "good.md").read_text()
        captured = capsys.readouterr()
        assert "dangling.md" not in captured.err
