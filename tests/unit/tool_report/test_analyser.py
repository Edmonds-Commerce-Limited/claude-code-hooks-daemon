"""Tests for the transcript tool-usage analyser (Plan 00293 Task 2.1).

The analyser scans a project's Claude Code session transcripts
(``~/.claude/projects/<slug>/**/*.jsonl``) and produces per-tool call counts.
Privacy is a hard requirement: only tool NAMES and COUNTS ever leave the scan
— transcript content (prompts, file contents, command text) is never copied
into any output structure.
"""

import dataclasses
import json
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.tool_report.analyser import (
    ToolUsage,
    analyse_transcripts,
    transcripts_root_for,
)


def _tool_use_record(tool_name: str, *, record_type: str = "assistant") -> str:
    """One transcript JSONL line containing a single tool_use block."""
    record: dict[str, Any] = {
        "type": record_type,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "working"},
                {"type": "tool_use", "id": "toolu_00000000", "name": tool_name, "input": {}},
            ],
        },
    }
    return json.dumps(record)


def _text_record() -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})


class TestTranscriptsRootFor:
    """Project root → transcripts directory slug mapping."""

    def test_workspace_maps_to_dash_slug(self, tmp_path: Path) -> None:
        """/workspace → <claude_home>/projects/-workspace (observed layout)."""
        root = transcripts_root_for(Path("/workspace"), claude_home=tmp_path)
        assert root == tmp_path / "projects" / "-workspace"

    def test_non_alphanumerics_become_dashes(self, tmp_path: Path) -> None:
        """Dots and underscores are flattened like slashes (observed: nested
        scratchpad paths slug every separator to `-`)."""
        root = transcripts_root_for(Path("/srv/my_app.v2"), claude_home=tmp_path)
        assert root == tmp_path / "projects" / "-srv-my-app-v2"


class TestAnalyseTranscripts:
    """Streaming per-tool counting over a transcripts tree."""

    def test_counts_calls_per_tool(self, tmp_path: Path) -> None:
        session = tmp_path / "11111111-1111-1111-1111-111111111111.jsonl"
        session.write_text(
            "\n".join(
                [
                    _tool_use_record("Bash"),
                    _tool_use_record("Bash"),
                    _tool_use_record("Read"),
                    _text_record(),
                ]
            )
        )
        summary = analyse_transcripts(tmp_path)
        assert summary.usages["Bash"].calls == 2
        assert summary.usages["Read"].calls == 1

    def test_counts_sessions_not_just_calls(self, tmp_path: Path) -> None:
        """A tool used in two sessions is distinguishable from one used twice
        in a single session — the rarity signal the report tiers need."""
        (tmp_path / "11111111-1111-1111-1111-111111111111.jsonl").write_text(
            _tool_use_record("Bash")
        )
        (tmp_path / "22222222-2222-2222-2222-222222222222.jsonl").write_text(
            _tool_use_record("Bash")
        )
        summary = analyse_transcripts(tmp_path)
        assert summary.usages["Bash"].calls == 2
        assert summary.usages["Bash"].sessions == 2

    def test_subagent_transcripts_attribute_to_their_session(self, tmp_path: Path) -> None:
        """A subagent transcript under <session>/subagents/ counts its calls,
        and its session attribution is the enclosing session, not a new one."""
        session_id = "33333333-3333-3333-3333-333333333333"
        (tmp_path / f"{session_id}.jsonl").write_text(_tool_use_record("Bash"))
        sub_dir = tmp_path / session_id / "subagents"
        sub_dir.mkdir(parents=True)
        (sub_dir / "agent-00000000.jsonl").write_text(_tool_use_record("Bash"))
        summary = analyse_transcripts(tmp_path)
        assert summary.usages["Bash"].calls == 2
        assert summary.usages["Bash"].sessions == 1

    def test_malformed_lines_are_skipped_and_counted(self, tmp_path: Path) -> None:
        session = tmp_path / "44444444-4444-4444-4444-444444444444.jsonl"
        session.write_text("{not json\n" + _tool_use_record("Edit") + "\n")
        summary = analyse_transcripts(tmp_path)
        assert summary.usages["Edit"].calls == 1
        assert summary.malformed_lines == 1

    def test_oversized_lines_are_skipped(self, tmp_path: Path) -> None:
        """A pathological multi-megabyte line must not be parsed — bounded
        memory is part of the analyser's contract."""
        big = '{"type": "assistant", "pad": "' + ("x" * 20_000_000) + '"}'
        session = tmp_path / "55555555-5555-5555-5555-555555555555.jsonl"
        session.write_text(big + "\n" + _tool_use_record("Write") + "\n")
        summary = analyse_transcripts(tmp_path)
        assert summary.usages["Write"].calls == 1
        assert "pad" not in str(summary)

    def test_missing_directory_yields_empty_summary(self, tmp_path: Path) -> None:
        summary = analyse_transcripts(tmp_path / "does-not-exist")
        assert summary.usages == {}
        assert summary.transcripts_scanned == 0

    def test_usage_rows_carry_names_and_counts_only(self, tmp_path: Path) -> None:
        """Privacy contract: the output dataclass has no field that could
        carry transcript content."""
        assert {f.name for f in dataclasses.fields(ToolUsage)} == {
            "name",
            "calls",
            "sessions",
        }
