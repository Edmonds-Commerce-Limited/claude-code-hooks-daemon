"""Tests for skill_scan.report (Plan 00274)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.skill_scan.models import Cluster, Prompt, ScanStats
from claude_code_hooks_daemon.skill_scan.report import write_report

_TODAY = date(2026, 8, 26)
_STATS = ScanStats(files=2, lines=10, user_records=5, genuine=2, unparseable=1)
_PROMPT = "You are analysing clustered human prompts. CLUSTERS:\n[1] ..."


def _cluster(text: str, sessions: int = 2) -> Cluster:
    prompts = [Prompt(text, f"s{i}", float(i)) for i in range(sessions)]
    return Cluster(key_tokens=frozenset(text.split()), prompts=prompts)


def _write(
    tmp_path: Path,
    clusters: list[Cluster] | None = None,
    terms: tuple[str, ...] = (),
    judging_prompt: str = _PROMPT,
) -> Path:
    return write_report(
        report_dir=tmp_path,
        clusters=clusters if clusters is not None else [_cluster("regenerate docs then restart")],
        stats=_STATS,
        terms=terms,
        existing=["release"],
        judging_prompt=judging_prompt,
        today=_TODAY,
    )


class TestWriteReport:
    def test_dated_filename_convention(self, tmp_path: Path) -> None:
        path = _write(tmp_path)
        assert path.name == "2026-08-26-skill-opportunities.md"
        assert path.is_file()

    def test_privacy_header_present(self, tmp_path: Path) -> None:
        text = _write(tmp_path).read_text()
        assert "PRIVACY" in text
        assert "review before" in text

    def test_schema_drift_canary_present(self, tmp_path: Path) -> None:
        text = _write(tmp_path).read_text()
        assert "- Unparseable lines (schema-drift canary): 1" in text

    def test_paths_in_prompts_never_reach_report(self, tmp_path: Path) -> None:
        text = _write(
            tmp_path,
            clusters=[_cluster("fix the test in /workspace/tests/unit/secret_area/x.py now")],
        ).read_text()
        assert "/workspace/tests" not in text
        assert "secret_area" not in text

    def test_existing_skills_noted(self, tmp_path: Path) -> None:
        text = _write(tmp_path).read_text()
        assert "release" in text

    def test_judging_section_embeds_prompt_and_findings_placeholder(self, tmp_path: Path) -> None:
        text = _write(tmp_path).read_text()
        assert "## Judging (subagent task)" in text
        assert "You are analysing clustered human prompts" in text
        assert "## Findings" in text
        assert "Pending subagent judging" in text

    def test_secret_terms_never_reach_report(self, tmp_path: Path) -> None:
        text = _write(
            tmp_path,
            clusters=[_cluster("rotate hunter2 for me please")],
            judging_prompt="rubric mentioning hunter2 again",
            terms=("hunter2",),
        ).read_text()
        assert "hunter2" not in text
        assert "[REDACTED]" in text

    def test_single_occurrence_clusters_not_listed(self, tmp_path: Path) -> None:
        text = _write(
            tmp_path,
            clusters=[_cluster("a one off request qwertyuiop", sessions=1)],
        ).read_text()
        assert "qwertyuiop" not in text
