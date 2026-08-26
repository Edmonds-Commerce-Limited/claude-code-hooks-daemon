"""Tests for skill_scan.pipeline (Plan 00274).

The pipeline is the CLI's engine: extraction → clustering → digest → report.
The judging stage is not run here — the report embeds the rubric prompt for
an in-session subagent (Decision 9).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.skill_scan.models import SkillScanOptions
from claude_code_hooks_daemon.skill_scan.pipeline import run_scan

_TODAY = date(2026, 8, 26)


def _record(text: str, session: str = "s1") -> str:
    return json.dumps(
        {
            "type": "user",
            "sessionId": session,
            "message": {"role": "user", "content": text},
        }
    )


def _seed_transcripts(transcript_dir: Path) -> None:
    transcript_dir.mkdir(parents=True)
    lines = [
        _record("regenerate the docs then restart the daemon", "s1"),
        _record("regenerate the docs then restart the daemon please", "s2"),
        _record("one off question about penguins", "s3"),
    ]
    (transcript_dir / "a.jsonl").write_text("\n".join(lines) + "\n")


def _options(transcript_dir: Path) -> SkillScanOptions:
    return SkillScanOptions.from_dict({"transcript_dir": str(transcript_dir)})


class TestRunScan:
    def test_happy_path_writes_report_with_judging_prompt(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        _seed_transcripts(transcripts)
        result = run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
        )
        assert result.report_path is not None
        assert result.report_path.is_file()
        assert result.stats.genuine == 3
        assert result.judging_prompt is not None
        assert "You are analysing clustered human prompts" in result.judging_prompt
        report_text = result.report_path.read_text()
        assert "## Judging (subagent task)" in report_text
        assert "You are analysing clustered human prompts" in report_text
        assert "## Findings" in report_text

    def test_dry_run_skips_report(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        _seed_transcripts(transcripts)
        result = run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
            dry_run=True,
        )
        assert result.report_path is None
        assert result.judging_prompt is None
        assert "regenerate the docs" in result.digest

    def test_secret_terms_never_reach_judging_prompt(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        transcripts.mkdir(parents=True)
        lines = [
            _record("rotate the hunter2 credential", "s1"),
            _record("rotate the hunter2 credential now", "s2"),
        ]
        (transcripts / "a.jsonl").write_text("\n".join(lines) + "\n")
        result = run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            report_dir=tmp_path / "reports",
            secret_terms=("hunter2",),
            today=_TODAY,
        )
        assert result.judging_prompt is not None
        assert "hunter2" not in result.judging_prompt
        assert result.report_path is not None
        assert "hunter2" not in result.report_path.read_text()

    def test_missing_transcript_dir_is_successful_noop_scan(self, tmp_path: Path) -> None:
        result = run_scan(
            project_root=tmp_path,
            options=_options(tmp_path / "absent"),
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
        )
        # Nothing to scan: a report is still written noting the empty window.
        assert result.report_path is not None
        assert result.stats.genuine == 0

    def test_existing_skill_inventory_reaches_judging_prompt(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        _seed_transcripts(transcripts)
        (tmp_path / ".claude" / "skills" / "release").mkdir(parents=True)
        result = run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
        )
        assert result.judging_prompt is not None
        assert "release" in result.judging_prompt
