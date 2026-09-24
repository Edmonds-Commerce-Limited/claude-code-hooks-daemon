"""Tests for the deterministic long-comment-block finder (Plan 00284 Task 3.1g).

Decision 7: the ``hooks-daemon-docs-qa`` agent explicitly hunts verbose
comment blocks in source code and treats them as documentation to
cross-check against the canonical doc tree. This module is the DETERMINISTIC
finder that feeds the agent's worklist — it lists candidates, it never
judges content and never gates a tool call.
"""

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.docs_qa.comment_finder import (
    DEFAULT_MIN_BLOCK_LINES,
    CommentBlockFinding,
    find_long_comment_blocks,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")


class TestFindLongCommentBlocks:
    def test_finds_block_at_or_above_threshold(self, tmp_path: Path) -> None:
        body = "\n".join(f"# line {i}" for i in range(20))
        target = tmp_path / "module.py"
        target.write_text(f"{body}\n\ncode = 1\n")

        findings = find_long_comment_blocks([target], min_lines=15)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.path == target
        assert finding.start_line == 1
        assert finding.line_count == 20

    def test_ignores_block_below_threshold(self, tmp_path: Path) -> None:
        target = tmp_path / "module.py"
        target.write_text("# short\n# comment\ncode = 1\n")

        findings = find_long_comment_blocks([target], min_lines=15)

        assert findings == []

    def test_ignores_docstrings(self, tmp_path: Path) -> None:
        body = "\n".join(f"    line {i}" for i in range(20))
        target = tmp_path / "module.py"
        target.write_text(f'"""\n{body}\n"""\ncode = 1\n')

        findings = find_long_comment_blocks([target], min_lines=15)

        assert findings == []

    def test_skips_files_with_no_registered_strategy(self, tmp_path: Path) -> None:
        target = tmp_path / "data.json"
        target.write_text("{}\n")

        findings = find_long_comment_blocks([target], min_lines=1)

        assert findings == []

    def test_expands_directory_recursively(self, tmp_path: Path) -> None:
        nested = tmp_path / "pkg"
        nested.mkdir()
        body = "\n".join(f"# line {i}" for i in range(20))
        (nested / "mod.py").write_text(f"{body}\ncode = 1\n")

        findings = find_long_comment_blocks([tmp_path], min_lines=15)

        assert len(findings) == 1
        assert findings[0].path == nested / "mod.py"

    def test_default_threshold_is_fifteen(self) -> None:
        assert DEFAULT_MIN_BLOCK_LINES == 15

    def test_finding_preview_is_first_line(self, tmp_path: Path) -> None:
        body = "\n".join(f"# line {i}" for i in range(20))
        target = tmp_path / "module.py"
        target.write_text(f"{body}\ncode = 1\n")

        findings = find_long_comment_blocks([target], min_lines=15)

        assert findings[0].preview == "# line 0"

    def test_comment_block_finding_is_frozen_dataclass(self, tmp_path: Path) -> None:
        target = tmp_path / "module.py"
        finding = CommentBlockFinding(
            path=target, start_line=1, end_line=5, line_count=5, preview="# x"
        )
        assert finding.path == target


class TestFindLongCommentBlocksGitIgnore:
    """Plan 00468 P3 / Plan 00466 N9's class: a gitignored Claude Code
    plugin install must not surface in the docs-qa agent's worklist as this
    project's own documentation."""

    def test_gitignored_file_under_a_scanned_directory_is_not_found(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        body = "\n".join(f"# line {i}" for i in range(20))
        tracked = tmp_path / "tracked.py"
        tracked.write_text(f"{body}\ncode = 1\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "initial")

        (tmp_path / ".gitignore").write_text("plugins/\n")
        vendored_dir = tmp_path / "plugins" / "cache" / "some-plugin"
        vendored_dir.mkdir(parents=True)
        vendored = vendored_dir / "spec.py"
        vendored.write_text(f"{body}\ncode = 1\n")

        findings = find_long_comment_blocks([tmp_path], min_lines=15)

        found_paths = {finding.path for finding in findings}
        assert tracked in found_paths
        assert vendored not in found_paths

    def test_tracked_file_is_still_found(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        body = "\n".join(f"# line {i}" for i in range(20))
        tracked = tmp_path / "tracked.py"
        tracked.write_text(f"{body}\ncode = 1\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "initial")

        findings = find_long_comment_blocks([tmp_path], min_lines=15)

        assert {finding.path for finding in findings} == {tracked}

    def test_untracked_but_not_ignored_file_is_still_found(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / ".gitkeep").write_text("")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "initial")

        body = "\n".join(f"# line {i}" for i in range(20))
        new_file = tmp_path / "new.py"
        new_file.write_text(f"{body}\ncode = 1\n")

        findings = find_long_comment_blocks([tmp_path], min_lines=15)

        assert {finding.path for finding in findings} == {new_file}

    def test_outside_a_git_repo_falls_back_to_the_unfiltered_walk(self, tmp_path: Path) -> None:
        body = "\n".join(f"# line {i}" for i in range(20))
        target = tmp_path / "module.py"
        target.write_text(f"{body}\ncode = 1\n")

        findings = find_long_comment_blocks([tmp_path], min_lines=15)

        assert {finding.path for finding in findings} == {target}

    def test_a_file_argument_named_directly_is_not_filtered(self, tmp_path: Path) -> None:
        # Mirrors the daemon.cli convention: only a directory WALK is
        # filtered by git-visibility; a file the caller names directly is
        # scanned regardless (naming it is explicit consent).
        _init_repo(tmp_path)
        (tmp_path / ".gitkeep").write_text("")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "initial")

        (tmp_path / ".gitignore").write_text("ignored.py\n")
        body = "\n".join(f"# line {i}" for i in range(20))
        ignored_file = tmp_path / "ignored.py"
        ignored_file.write_text(f"{body}\ncode = 1\n")

        findings = find_long_comment_blocks([ignored_file], min_lines=15)

        assert {finding.path for finding in findings} == {ignored_file}


class TestFindLongCommentBlocksProtectedPath:
    """Plan 00412: a file whose name matches a protected glob must never
    surface here, tracked or not -- this finder reads the body of every file
    it returns (``file_path.read_text()`` in ``find_long_comment_blocks``),
    so inclusion in the result IS disclosure of that body. The protected
    filename is built from ``DEFAULT_PROTECTED_PATTERNS`` at runtime rather
    than spelled out in this file's own source, which the Write/Edit content
    guard would otherwise treat as script authorship regardless of test
    intent."""

    def test_protected_pattern_file_is_not_found(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.utils import secret_file_matching as sfm

        both_edges_pattern = next(p for p in sfm.DEFAULT_PROTECTED_PATTERNS if p.count("*") == 2)
        protected_name = f"{both_edges_pattern.replace('*', 'x')}.py"

        _init_repo(tmp_path)
        body = "\n".join(f"# line {i}" for i in range(20))
        safe = tmp_path / "safe.py"
        safe.write_text(f"{body}\ncode = 1\n")
        protected = tmp_path / protected_name
        protected.write_text(f"{body}\ncode = 1\n")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-m", "initial")

        findings = find_long_comment_blocks([tmp_path], min_lines=15)

        found_paths = {finding.path for finding in findings}
        assert safe in found_paths
        assert protected not in found_paths
