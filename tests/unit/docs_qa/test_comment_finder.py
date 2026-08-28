"""Tests for the deterministic long-comment-block finder (Plan 00284 Task 3.1g).

Decision 7: the ``hooks-daemon-docs-qa`` agent explicitly hunts verbose
comment blocks in source code and treats them as documentation to
cross-check against the canonical doc tree. This module is the DETERMINISTIC
finder that feeds the agent's worklist — it lists candidates, it never
judges content and never gates a tool call.
"""

from pathlib import Path

from claude_code_hooks_daemon.docs_qa.comment_finder import (
    DEFAULT_MIN_BLOCK_LINES,
    CommentBlockFinding,
    find_long_comment_blocks,
)


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
