"""Tests for the `hooks-daemon block-report` CLI command (Plan 00116 Task 2b.1)."""

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_block_report


def _args(project_root: Path, transcripts_dir: Path, **overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "project_root": str(project_root),
        "transcripts_dir": str(transcripts_dir),
        "json_output": False,
        "no_write": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _deny_line(session_id: str, reason: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "sessionId": session_id,
            "timestamp": "2026-08-30T12:00:00.000Z",
            "toolDenialKind": "permission-rule",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": reason,
                        "is_error": True,
                        "tool_use_id": "toolu_1",
                    }
                ],
            },
        }
    )


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, Path]:
    """A minimal project root plus a transcripts dir with one session."""
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "11111111-1111-1111-1111-111111111111.jsonl").write_text(
        "\n".join(
            [
                _deny_line(
                    "s1",
                    "BLOCKED: sed is forbidden. Use Edit tool (or parallel Haiku agents "
                    "for bulk).\n\nBLOCKED command: echo hi",
                ),
                _deny_line(
                    "s1",
                    "BLOCKED: sed is forbidden. Use Edit tool (or parallel Haiku agents "
                    "for bulk).\n\nBLOCKED command: echo bye",
                ),
            ]
        )
    )
    return root, transcripts


class TestCmdBlockReport:
    def test_prints_markdown_and_writes_reports(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        exit_code = cmd_block_report(_args(root, transcripts))
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "| Handler" in out
        reports_dir = root / ".claude" / "hooks-daemon" / "untracked" / "reports"
        assert (reports_dir / "block-report.md").is_file()
        payload = json.loads((reports_dir / "block-report.json").read_text())
        handlers = {row["handler"]: row for row in payload["rows"]}
        assert handlers["sed_blocker"]["total_blocks"] == 2

    def test_reads_promotion_config_thresholds(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        (root / ".claude" / "hooks-daemon.yaml").write_text(
            "claude_md:\n  promotion:\n    min_blocks: 1\n    min_sessions: 1\n"
        )
        assert cmd_block_report(_args(root, transcripts)) == 0
        reports_dir = root / ".claude" / "hooks-daemon" / "untracked" / "reports"
        payload = json.loads((reports_dir / "block-report.json").read_text())
        assert payload["min_blocks"] == 1
        row = next(r for r in payload["rows"] if r["handler"] == "sed_blocker")
        assert row["recommended_promote"] is True

    def test_json_output_prints_machine_readable(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        assert cmd_block_report(_args(root, transcripts, json_output=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["sessions_scanned"] == 1

    def test_no_write_skips_report_files(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        assert cmd_block_report(_args(root, transcripts, no_write=True)) == 0
        assert not (root / ".claude" / "hooks-daemon" / "untracked" / "reports").exists()

    def test_missing_transcripts_dir_still_reports(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A fresh project has no transcripts yet — that is a report saying
        so, not an error."""
        root, _ = project
        exit_code = cmd_block_report(_args(root, root / "nope", no_write=True))
        assert exit_code == 0
        assert "0 transcript" in capsys.readouterr().out
