"""Tests for the Plan 00274 prototype skill-scan pipeline.

Prototype-level coverage: the deterministic prompt-extraction filter is the
crux (BRAINSTORM.md section 2), so it gets real tests against small synthetic
jsonl fixtures. Clustering and normalisation get sanity tests. No real
transcript content appears here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import skill_scan


def _record(**overrides: object) -> str:
    base: dict[str, object] = {
        "type": "user",
        "timestamp": "2026-08-20T10:00:00.000Z",
        "sessionId": "sess-1",
        "isSidechain": False,
        "message": {"role": "user", "content": "please fix the failing test"},
    }
    base.update(overrides)
    return json.dumps(base)


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestExtractPrompts:
    def test_genuine_string_prompt_survives(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "a.jsonl", [_record()])
        prompts = skill_scan.extract_prompts(tmp_path, window_days=None)
        assert len(prompts) == 1
        assert prompts[0].text == "please fix the failing test"
        assert prompts[0].session_id == "sess-1"

    def test_non_user_records_excluded(self, tmp_path: Path) -> None:
        lines = [
            json.dumps({"type": "assistant", "message": {"content": "hi"}}),
            json.dumps({"type": "last-prompt", "prompt": "x"}),
            json.dumps({"type": "system"}),
            _record(),
        ]
        _write_jsonl(tmp_path / "a.jsonl", lines)
        assert len(skill_scan.extract_prompts(tmp_path, window_days=None)) == 1

    @pytest.mark.parametrize(
        "flag", ["isMeta", "isSidechain", "isCompactSummary", "isVisibleInTranscriptOnly"]
    )
    def test_field_flags_excluded(self, tmp_path: Path, flag: str) -> None:
        _write_jsonl(tmp_path / "a.jsonl", [_record(**{flag: True})])
        assert skill_scan.extract_prompts(tmp_path, window_days=None) == []

    def test_tool_result_block_content_excluded(self, tmp_path: Path) -> None:
        content = [{"type": "tool_result", "content": "output"}]
        _write_jsonl(
            tmp_path / "a.jsonl",
            [_record(message={"role": "user", "content": content})],
        )
        assert skill_scan.extract_prompts(tmp_path, window_days=None) == []

    @pytest.mark.parametrize(
        "text",
        [
            '<teammate-message teammate_id="lead">do a thing</teammate-message>',
            "Another Claude session sent a message: hello",
            "<task-notification>agent finished</task-notification>",
            "[Request interrupted by user]",
            "[Request interrupted by user for tool use]",
            "**FAILSAFE RECOVERY CHECK (automated hourly safety net)** resume",
            "/goal 🤖 [ccy-supervisor] work on the plan",
            "/compact 🤖 [ccy-supervisor] After compacting, resume the work.",
            "🤖 [ccy-supervisor] continue",
            "<command-name>/release</command-name>",
            "<local-command-stdout>ok</local-command-stdout>",
            "<system-reminder>context stuff</system-reminder>",
        ],
    )
    def test_content_markers_excluded(self, tmp_path: Path, text: str) -> None:
        _write_jsonl(
            tmp_path / "a.jsonl",
            [_record(message={"role": "user", "content": text})],
        )
        assert skill_scan.extract_prompts(tmp_path, window_days=None) == []

    def test_malformed_lines_skipped_and_counted(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "a.jsonl", ["not json at all", "{}", _record()])
        prompts = skill_scan.extract_prompts(tmp_path, window_days=None)
        assert len(prompts) == 1

    def test_empty_and_whitespace_prompts_excluded(self, tmp_path: Path) -> None:
        _write_jsonl(
            tmp_path / "a.jsonl",
            [_record(message={"role": "user", "content": "   "})],
        )
        assert skill_scan.extract_prompts(tmp_path, window_days=None) == []


class TestNormalise:
    def test_paths_and_numbers_become_placeholders(self) -> None:
        out = skill_scan.normalise("Fix test in /workspace/tests/unit/x.py line 42")
        assert "/workspace" not in out
        assert "42" not in out
        assert skill_scan.PATH_PLACEHOLDER in out
        assert skill_scan.NUM_PLACEHOLDER in out

    def test_two_variants_normalise_identically(self) -> None:
        a = skill_scan.normalise("fix the test in tests/unit/a.py")
        b = skill_scan.normalise("Fix the test in tests/unit/b.py")
        assert a == b


class TestClustering:
    def test_near_identical_prompts_cluster(self) -> None:
        prompts = [
            skill_scan.Prompt("run qa then restart the daemon and verify", "s1", 1.0),
            skill_scan.Prompt("run qa then restart the daemon and verify it", "s2", 2.0),
            skill_scan.Prompt("write a haiku about penguins", "s3", 3.0),
        ]
        clusters = skill_scan.cluster_prompts(prompts)
        sizes = sorted(len(c.prompts) for c in clusters)
        assert sizes == [1, 2]

    def test_cluster_counts_distinct_sessions(self) -> None:
        prompts = [
            skill_scan.Prompt("same prompt again", "s1", 1.0),
            skill_scan.Prompt("same prompt again", "s1", 2.0),
            skill_scan.Prompt("same prompt again", "s2", 3.0),
        ]
        clusters = skill_scan.cluster_prompts(prompts)
        assert len(clusters) == 1
        assert clusters[0].distinct_sessions == 2
        assert len(clusters[0].prompts) == 3
