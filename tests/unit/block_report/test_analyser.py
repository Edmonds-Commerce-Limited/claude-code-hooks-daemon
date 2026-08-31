"""Tests for the block-report transcript analyser (Plan 00116 Task 2b.1).

Real transcript shape verified 2026-08-31 against this project's own
``~/.claude/projects/-workspace/*.jsonl`` (research for this plan, never
committed): a hook denial is a ``type: "user"`` record whose
``message.content`` is a list containing a ``tool_result`` block with
``is_error: true`` and a plain-string ``content`` field carrying the
handler's reason text, AND the record itself carries
``toolDenialKind: "permission-rule"`` (as opposed to ``"user-rejected"``,
which is a human declining a permission prompt, not a hook deny, and
carries no ``BLOCKED`` text at all). An ordinary failed command (e.g.
``Error: Exit code 2``) is ``is_error: true`` with no ``toolDenialKind``
key present at all, so keying on that field's presence-and-value is what
separates a genuine hook deny from any other tool failure.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.block_report.analyser import (
    analyse_transcripts,
    transcripts_root_for,
)


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def _deny_record(
    session_id: str,
    reason: str,
    *,
    denial_kind: str | None = "permission-rule",
    timestamp: str = "2026-08-30T12:00:00.000Z",
) -> dict[str, object]:
    record: dict[str, object] = {
        "type": "user",
        "sessionId": session_id,
        "timestamp": timestamp,
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
    if denial_kind is not None:
        record["toolDenialKind"] = denial_kind
    return record


class TestTranscriptsRootFor:
    def test_slugs_project_path(self, tmp_path: Path) -> None:
        root = transcripts_root_for(Path("/workspace"), claude_home=tmp_path)
        assert root == tmp_path / "projects" / "-workspace"


class TestAnalyseTranscripts:
    def test_missing_directory_yields_empty_summary(self, tmp_path: Path) -> None:
        summary = analyse_transcripts(tmp_path / "does-not-exist")
        assert summary.transcripts_scanned == 0
        assert summary.blocks == {}

    def test_counts_a_real_deny_shape(self, tmp_path: Path) -> None:
        root = tmp_path / "projects" / "-workspace"
        root.mkdir(parents=True)
        _write_jsonl(
            root / "session-a.jsonl",
            [
                _deny_record(
                    "session-a",
                    "BLOCKED: sed is forbidden. Use Edit tool (or parallel Haiku agents "
                    "for bulk).\n\nBLOCKED command: echo hi",
                ),
            ],
        )
        summary = analyse_transcripts(root)
        assert summary.transcripts_scanned == 1
        assert summary.blocks["sed_blocker"].total == 1
        assert summary.blocks["sed_blocker"].sessions == {"session-a"}
        assert summary.blocks["sed_blocker"].last_seen == "2026-08-30T12:00:00.000Z"

    def test_ordinary_tool_failure_without_denial_kind_is_not_counted(self, tmp_path: Path) -> None:
        root = tmp_path / "projects" / "-workspace"
        root.mkdir(parents=True)
        _write_jsonl(
            root / "session-a.jsonl",
            [_deny_record("session-a", "Error: Exit code 2", denial_kind=None)],
        )
        summary = analyse_transcripts(root)
        assert summary.blocks == {}

    def test_user_rejected_permission_prompt_is_not_counted(self, tmp_path: Path) -> None:
        root = tmp_path / "projects" / "-workspace"
        root.mkdir(parents=True)
        _write_jsonl(
            root / "session-a.jsonl",
            [_deny_record("session-a", "User rejected tool use", denial_kind="user-rejected")],
        )
        summary = analyse_transcripts(root)
        assert summary.blocks == {}

    def test_unattributable_deny_is_counted_as_unattributed(self, tmp_path: Path) -> None:
        root = tmp_path / "projects" / "-workspace"
        root.mkdir(parents=True)
        _write_jsonl(
            root / "session-a.jsonl",
            [_deny_record("session-a", "BLOCKED: something no fingerprint covers")],
        )
        summary = analyse_transcripts(root)
        assert summary.unattributed_denies == 1
        assert summary.blocks == {}

    def test_distinct_sessions_counted_separately(self, tmp_path: Path) -> None:
        root = tmp_path / "projects" / "-workspace"
        root.mkdir(parents=True)
        _write_jsonl(
            root / "session-a.jsonl",
            [_deny_record("session-a", "SECRET FILE PROTECTED: nope")],
        )
        _write_jsonl(
            root / "session-b.jsonl",
            [
                _deny_record("session-b", "SECRET FILE PROTECTED: nope"),
                _deny_record("session-b", "SECRET FILE PROTECTED: nope again"),
            ],
        )
        summary = analyse_transcripts(root)
        usage = summary.blocks["secret_file_guard"]
        assert usage.total == 3
        assert usage.sessions == {"session-a", "session-b"}

    def test_last_seen_is_the_most_recent_timestamp(self, tmp_path: Path) -> None:
        root = tmp_path / "projects" / "-workspace"
        root.mkdir(parents=True)
        _write_jsonl(
            root / "session-a.jsonl",
            [
                _deny_record(
                    "session-a", "SECRET FILE PROTECTED: nope", timestamp="2026-08-01T00:00:00Z"
                ),
                _deny_record(
                    "session-a", "SECRET FILE PROTECTED: nope", timestamp="2026-08-30T00:00:00Z"
                ),
            ],
        )
        summary = analyse_transcripts(root)
        assert summary.blocks["secret_file_guard"].last_seen == "2026-08-30T00:00:00Z"

    def test_malformed_line_is_skipped_not_raised(self, tmp_path: Path) -> None:
        root = tmp_path / "projects" / "-workspace"
        root.mkdir(parents=True)
        (root / "session-a.jsonl").write_text("not json at all\n", encoding="utf-8")
        summary = analyse_transcripts(root)
        assert summary.malformed_lines == 1
        assert summary.blocks == {}

    def test_privacy_no_command_text_leaks_into_summary_repr(self, tmp_path: Path) -> None:
        root = tmp_path / "projects" / "-workspace"
        root.mkdir(parents=True)
        secret = "rm -rf /some/secret/path/nobody/should/see"
        _write_jsonl(
            root / "session-a.jsonl",
            [_deny_record("session-a", f"BLOCKED: sed is forbidden.\n\nBLOCKED command: {secret}")],
        )
        summary = analyse_transcripts(root)
        assert secret not in repr(summary)
        assert secret not in repr(summary.blocks)
