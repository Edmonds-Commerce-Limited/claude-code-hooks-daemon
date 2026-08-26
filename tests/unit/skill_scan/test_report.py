"""Tests for skill_scan.report (Plan 00274)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from claude_code_hooks_daemon.skill_scan.invoker import ModelSuggestions, Suggestion
from claude_code_hooks_daemon.skill_scan.models import Cluster, Prompt, ScanStats
from claude_code_hooks_daemon.skill_scan.report import write_report

_TODAY = date(2026, 8, 26)
_STATS = ScanStats(files=2, lines=10, user_records=5, genuine=2, unparseable=1)


def _cluster(text: str, sessions: int = 2) -> Cluster:
    prompts = [Prompt(text, f"s{i}", float(i)) for i in range(sessions)]
    return Cluster(key_tokens=frozenset(text.split()), prompts=prompts)


def _write(
    tmp_path: Path,
    clusters: list[Cluster] | None = None,
    terms: tuple[str, ...] = (),
    suggestions: ModelSuggestions | None = None,
    raw_model_output: str | None = None,
    model_error: str | None = None,
) -> Path:
    return write_report(
        report_dir=tmp_path,
        clusters=clusters if clusters is not None else [_cluster("regenerate docs then restart")],
        stats=_STATS,
        terms=terms,
        suggestions=suggestions,
        raw_model_output=raw_model_output,
        model_error=model_error,
        existing=["release"],
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
        assert "canary" in text
        assert "1" in text

    def test_existing_skills_noted(self, tmp_path: Path) -> None:
        text = _write(tmp_path).read_text()
        assert "release" in text

    def test_suggestions_rendered_in_two_sections(self, tmp_path: Path) -> None:
        suggestions = ModelSuggestions(
            workloads=(
                Suggestion(name="docs-regen", purpose="regenerate docs", evidence_cluster_ids=(1,)),
            ),
            corrections=(
                Suggestion(name="qa-note", purpose="doc not skill", evidence_cluster_ids=(2,)),
            ),
        )
        text = _write(tmp_path, suggestions=suggestions).read_text()
        assert "Repeated workloads" in text
        assert "docs-regen" in text
        assert "corrections" in text.lower()
        assert "qa-note" in text

    def test_model_error_renders_skip_note(self, tmp_path: Path) -> None:
        text = _write(tmp_path, model_error="claude CLI exited 1: Not logged in").read_text()
        assert "skipped" in text
        assert "Not logged in" in text

    def test_unparseable_output_rendered_as_raw_notes(self, tmp_path: Path) -> None:
        text = _write(tmp_path, raw_model_output="freeform model musings").read_text()
        assert "freeform model musings" in text
        assert "unparsed" in text.lower()

    def test_secret_terms_never_reach_report(self, tmp_path: Path) -> None:
        text = _write(
            tmp_path,
            clusters=[_cluster("rotate hunter2 for me please")],
            raw_model_output="mentioning hunter2 again",
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
