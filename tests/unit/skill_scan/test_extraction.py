"""Tests for skill_scan.extraction (Plan 00274).

Freezes the verified transcript field/marker contract from BRAINSTORM.md
section 2 into synthetic fixtures. No real transcript content appears here.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.skill_scan.extraction import (
    derive_transcript_dir,
    extract_prompts,
)
from claude_code_hooks_daemon.skill_scan.models import ScanStats


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


class TestDeriveTranscriptDir:
    def test_slug_replaces_separators(self, tmp_path: Path) -> None:
        result = derive_transcript_dir(Path("/workspace"), home=tmp_path)
        assert result == tmp_path / ".claude" / "projects" / "-workspace"

    def test_nested_path_slug(self, tmp_path: Path) -> None:
        result = derive_transcript_dir(Path("/home/user/my-project"), home=tmp_path)
        assert result.name == "-home-user-my-project"


class TestExtractPrompts:
    def test_genuine_string_prompt_survives(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "a.jsonl", [_record()])
        stats = ScanStats()
        prompts = extract_prompts(tmp_path, window_days=None, stats=stats)
        assert len(prompts) == 1
        assert prompts[0].text == "please fix the failing test"
        assert prompts[0].session_id == "sess-1"
        assert stats.genuine == 1
        assert stats.files == 1

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        stats = ScanStats()
        assert extract_prompts(tmp_path / "absent", window_days=None, stats=stats) == []
        assert stats.files == 0

    def test_non_user_records_excluded(self, tmp_path: Path) -> None:
        lines = [
            json.dumps({"type": "assistant", "message": {"content": "hi"}}),
            json.dumps({"type": "last-prompt", "prompt": "x"}),
            json.dumps({"type": "system"}),
            json.dumps(["not", "a", "dict"]),
            _record(),
        ]
        _write_jsonl(tmp_path / "a.jsonl", lines)
        assert len(extract_prompts(tmp_path, window_days=None, stats=ScanStats())) == 1

    @pytest.mark.parametrize(
        "flag", ["isMeta", "isSidechain", "isCompactSummary", "isVisibleInTranscriptOnly"]
    )
    def test_field_flags_excluded(self, tmp_path: Path, flag: str) -> None:
        _write_jsonl(tmp_path / "a.jsonl", [_record(**{flag: True})])
        stats = ScanStats()
        assert extract_prompts(tmp_path, window_days=None, stats=stats) == []
        assert stats.excluded_flags == 1

    def test_tool_result_block_content_excluded(self, tmp_path: Path) -> None:
        content = [{"type": "tool_result", "content": "output"}]
        _write_jsonl(
            tmp_path / "a.jsonl",
            [_record(message={"role": "user", "content": content})],
        )
        stats = ScanStats()
        assert extract_prompts(tmp_path, window_days=None, stats=stats) == []
        assert stats.excluded_blocks == 1

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
            "🤖 [ccy-supervisor] continue",
            "<command-name>/release</command-name>",
            "<local-command-stdout>ok</local-command-stdout>",
            "<system-reminder>context stuff</system-reminder>",
            "<command-message>msg</command-message>",
        ],
    )
    def test_content_markers_excluded(self, tmp_path: Path, text: str) -> None:
        _write_jsonl(
            tmp_path / "a.jsonl",
            [_record(message={"role": "user", "content": text})],
        )
        stats = ScanStats()
        assert extract_prompts(tmp_path, window_days=None, stats=stats) == []
        assert stats.excluded_markers == 1

    def test_extra_exclude_patterns_applied(self, tmp_path: Path) -> None:
        _write_jsonl(
            tmp_path / "a.jsonl",
            [_record(message={"role": "user", "content": "wrapped by <acme-bot>"})],
        )
        stats = ScanStats()
        prompts = extract_prompts(
            tmp_path,
            window_days=None,
            stats=stats,
            extra_exclude_patterns=("<acme-bot>",),
        )
        assert prompts == []
        assert stats.excluded_markers == 1

    def test_malformed_lines_skipped_and_counted(self, tmp_path: Path) -> None:
        _write_jsonl(tmp_path / "a.jsonl", ["not json at all", "{}", _record()])
        stats = ScanStats()
        prompts = extract_prompts(tmp_path, window_days=None, stats=stats)
        assert len(prompts) == 1
        assert stats.unparseable == 1

    def test_empty_and_whitespace_prompts_excluded(self, tmp_path: Path) -> None:
        _write_jsonl(
            tmp_path / "a.jsonl",
            [_record(message={"role": "user", "content": "   "})],
        )
        assert extract_prompts(tmp_path, window_days=None, stats=ScanStats()) == []

    def test_window_excludes_old_files(self, tmp_path: Path) -> None:
        old = tmp_path / "old.jsonl"
        _write_jsonl(old, [_record()])
        thirty_days_ago = time.time() - 30 * 86_400
        os.utime(old, (thirty_days_ago, thirty_days_ago))
        fresh = tmp_path / "fresh.jsonl"
        _write_jsonl(fresh, [_record(sessionId="sess-2")])
        stats = ScanStats()
        prompts = extract_prompts(tmp_path, window_days=14, stats=stats)
        assert len(prompts) == 1
        assert prompts[0].session_id == "sess-2"
        assert stats.files == 1

    def test_session_id_falls_back_to_file_stem(self, tmp_path: Path) -> None:
        record = json.loads(_record())
        del record["sessionId"]
        _write_jsonl(tmp_path / "mystem.jsonl", [json.dumps(record)])
        prompts = extract_prompts(tmp_path, window_days=None, stats=ScanStats())
        assert prompts[0].session_id == "mystem"
