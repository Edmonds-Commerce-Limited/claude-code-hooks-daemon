"""Tests for skill_scan.pipeline (Plan 00274).

The pipeline is the CLI's engine: extraction → clustering → digest → model →
report, fail-open at every external boundary, model behind an injected
``ModelInvoker``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.skill_scan.models import SkillScanOptions
from claude_code_hooks_daemon.skill_scan.pipeline import run_scan

_TODAY = date(2026, 8, 26)


class FakeInvoker:
    def __init__(self, output: str | None, error: str | None = None) -> None:
        self.output = output
        self.error = error
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> tuple[str | None, str | None]:
        self.prompts.append(prompt)
        return self.output, self.error


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
    def test_happy_path_writes_report_and_calls_model(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        _seed_transcripts(transcripts)
        invoker = FakeInvoker('{"workloads": [], "corrections": []}')
        result = run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            invoker=invoker,
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
        )
        assert result.report_path is not None
        assert result.report_path.is_file()
        assert result.model_error is None
        assert result.stats.genuine == 3
        assert len(invoker.prompts) == 1

    def test_dry_run_skips_model_and_report(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        _seed_transcripts(transcripts)
        invoker = FakeInvoker("should never be called")
        result = run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            invoker=invoker,
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
            dry_run=True,
        )
        assert result.report_path is None
        assert invoker.prompts == []
        assert "regenerate the docs" in result.digest

    def test_model_failure_still_writes_partial_report(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        _seed_transcripts(transcripts)
        invoker = FakeInvoker(None, error="claude CLI not found on PATH")
        result = run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            invoker=invoker,
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
        )
        assert result.report_path is not None
        assert result.model_error == "claude CLI not found on PATH"
        assert "skipped" in result.report_path.read_text()

    def test_secret_terms_never_reach_model_prompt(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        transcripts.mkdir(parents=True)
        lines = [
            _record("rotate the hunter2 credential", "s1"),
            _record("rotate the hunter2 credential now", "s2"),
        ]
        (transcripts / "a.jsonl").write_text("\n".join(lines) + "\n")
        invoker = FakeInvoker('{"workloads": [], "corrections": []}')
        result = run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            invoker=invoker,
            report_dir=tmp_path / "reports",
            secret_terms=("hunter2",),
            today=_TODAY,
        )
        assert "hunter2" not in invoker.prompts[0]
        assert result.report_path is not None
        assert "hunter2" not in result.report_path.read_text()

    def test_missing_transcript_dir_is_successful_noop_scan(self, tmp_path: Path) -> None:
        invoker = FakeInvoker('{"workloads": [], "corrections": []}')
        result = run_scan(
            project_root=tmp_path,
            options=_options(tmp_path / "absent"),
            invoker=invoker,
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
        )
        # Nothing to scan: no model call, but a report noting the empty window.
        assert invoker.prompts == []
        assert result.report_path is not None
        assert result.stats.genuine == 0

    def test_existing_skill_inventory_reaches_model_prompt(self, tmp_path: Path) -> None:
        transcripts = tmp_path / "transcripts"
        _seed_transcripts(transcripts)
        (tmp_path / ".claude" / "skills" / "release").mkdir(parents=True)
        invoker = FakeInvoker('{"workloads": [], "corrections": []}')
        run_scan(
            project_root=tmp_path,
            options=_options(transcripts),
            invoker=invoker,
            report_dir=tmp_path / "reports",
            secret_terms=(),
            today=_TODAY,
        )
        assert "release" in invoker.prompts[0]
