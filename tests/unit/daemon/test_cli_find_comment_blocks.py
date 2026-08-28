"""Tests for the ``find-comment-blocks`` CLI subcommand (Plan 00284 Task 3.1g).

Thin deterministic finder wrapping ``docs_qa.comment_finder`` — lists
candidate long comment blocks for the ``hooks-daemon-docs-qa`` agent's
worklist (Decision 7). Never judges content, never gates anything.
"""

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_find_comment_blocks


def _args(paths: list[Path], min_lines: int = 15, json_output: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        paths=[str(p) for p in paths], min_lines=min_lines, json_output=json_output
    )


class TestCmdFindCommentBlocks:
    def test_no_findings_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "module.py"
        target.write_text("code = 1\n")

        assert cmd_find_comment_blocks(_args([target])) == 0
        assert "0 finding" in capsys.readouterr().out

    def test_findings_exit_one_and_print_locations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = "\n".join(f"# line {i}" for i in range(20))
        target = tmp_path / "module.py"
        target.write_text(f"{body}\ncode = 1\n")

        assert cmd_find_comment_blocks(_args([target])) == 1
        out = capsys.readouterr().out
        assert str(target) in out
        assert "20" in out

    def test_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        body = "\n".join(f"# line {i}" for i in range(20))
        target = tmp_path / "module.py"
        target.write_text(f"{body}\ncode = 1\n")

        assert cmd_find_comment_blocks(_args([target], json_output=True)) == 1
        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 1
        assert payload[0]["path"] == str(target)
        assert payload[0]["line_count"] == 20

    def test_respects_min_lines_override(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        body = "\n".join(f"# line {i}" for i in range(5))
        target = tmp_path / "module.py"
        target.write_text(f"{body}\ncode = 1\n")

        assert cmd_find_comment_blocks(_args([target], min_lines=3)) == 1
