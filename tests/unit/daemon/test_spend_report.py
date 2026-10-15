"""Tests for ``hooks-daemon spend`` (Plan 00471 Task 2.1): ledger report from fixture transcripts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.spend_report import collect_session_spend, render_report
from claude_code_hooks_daemon.utils.transcript_spend import TranscriptSpendCache


def _assistant(request_id: str, ctx: int, output: int = 100) -> dict[str, Any]:
    return {
        "type": "assistant",
        "requestId": request_id,
        "gitBranch": "main",
        "message": {
            "model": "claude-opus-5-5",
            "usage": {"input_tokens": 0, "cache_read_input_tokens": ctx, "output_tokens": output},
        },
    }


def _write_agent(directory: Path, agent_id: str, name: str, records: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(record) + "\n" for record in records)
    (directory / f"agent-{agent_id}.jsonl").write_text(lines, encoding="utf-8")
    (directory / f"agent-{agent_id}.meta.json").write_text(json.dumps({"name": name}))


@pytest.fixture
def session(tmp_path: Path) -> Path:
    """A main transcript and two agents: one large with a compaction, one small."""
    projects = tmp_path / "projects"
    projects.mkdir()
    (projects / "s1.jsonl").write_text("", encoding="utf-8")
    subagents = projects / "s1" / "subagents"
    _write_agent(
        subagents,
        "ap471-impl-0123456789abcdef",
        "p471-impl",
        [
            {"type": "user", "message": {"content": "<teammate-message>go"}},
            _assistant("r1", 200_000),
            {
                "type": "system",
                "subtype": "compact_boundary",
                "compactMetadata": {"preTokens": 567_000},
            },
            _assistant("r2", 400_000),
            {"type": "user", "message": {"content": "<teammate-message>NEW TASK"}},
        ],
    )
    _write_agent(subagents, "a0123456789abcdef", "", [_assistant("r9", 30_000)])
    return projects / "s1.jsonl"


GOLDEN_BY_AGENT = """\
Subagent spend, session s1 (2 agents)

agent                   plan  requests  max_ctx  mean_ctx         ite  compactions  inbound
p471-impl                471         2  400,000   300,000      61,000            1        2
a0123456789abcdef          -         1   30,000    30,000       3,500            0        0
TOTAL                                3  400,000   210,000      64,500            1        2

Compactions (compact_boundary preTokens): 1, min 567,000, median 567,000, max 567,000
Unmeasured gate calls (agent, reason): 0
"""

GOLDEN_BY_PLAN = """\
Subagent spend, session s1 (2 agents)

plan                  agents  requests  max_ctx  mean_ctx         ite  compactions  inbound
471                        1         2  400,000   300,000      61,000            1        2
-                          1         1   30,000    30,000       3,500            0        0
TOTAL                                3  400,000   210,000      64,500            1        2

Compactions (compact_boundary preTokens): 1, min 567,000, median 567,000, max 567,000
Unmeasured gate calls (agent, reason): 0
"""


class TestReport:
    def test_golden_by_agent(self, session: Path) -> None:
        report = collect_session_spend(
            session.parent / "s1" / "subagents",
            session_id="s1",
            cache=TranscriptSpendCache(None),
            unmeasured=0,
        )
        assert render_report(report, by="agent") == GOLDEN_BY_AGENT

    def test_golden_by_plan(self, session: Path) -> None:
        report = collect_session_spend(
            session.parent / "s1" / "subagents",
            session_id="s1",
            cache=TranscriptSpendCache(None),
            unmeasured=0,
        )
        assert render_report(report, by="plan") == GOLDEN_BY_PLAN

    def test_no_agents_and_unmeasured_count(self, tmp_path: Path) -> None:
        report = collect_session_spend(
            tmp_path / "absent", session_id="s9", cache=TranscriptSpendCache(None), unmeasured=3
        )
        text = render_report(report, by="agent")
        assert "(0 agents)" in text
        assert "Compactions (compact_boundary preTokens): none" in text
        assert "Unmeasured gate calls (agent, reason): 3" in text


class TestCli:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pin the project to ``tmp_path`` so the ledger store lands there."""
        from claude_code_hooks_daemon.core.project_context import ProjectContext
        from claude_code_hooks_daemon.daemon import cli

        monkeypatch.setattr(cli, "get_project_path", lambda _override: tmp_path)
        monkeypatch.setattr(ProjectContext, "_initialized", False)

    def _args(self, tmp_path: Path, transcript: Path, **extra: Any) -> argparse.Namespace:
        values: dict[str, Any] = {
            "transcript": str(transcript),
            "session": None,
            "by": "agent",
            "json": False,
            "project_root": tmp_path,
        }
        values.update(extra)
        return argparse.Namespace(**values)

    def test_text_output(
        self, tmp_path: Path, session: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.daemon.cli import cmd_spend

        assert cmd_spend(self._args(tmp_path, session)) == 0
        assert "p471-impl" in capsys.readouterr().out

    def test_json_output(
        self, tmp_path: Path, session: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.daemon.cli import cmd_spend

        assert cmd_spend(self._args(tmp_path, session, json=True, by="plan")) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["session"] == "s1"
        assert data["agents"][0]["name"] == "p471-impl"
        assert data["agents"][0]["max_ctx"] == 400_000
        assert data["compactions"]["pre_tokens"] == [567_000]
        assert data["by_plan"][0]["plan"] == "471"
        assert data["unmeasured"] == 0

    def test_missing_transcript_is_an_error(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.cli import cmd_spend

        assert cmd_spend(self._args(tmp_path, tmp_path / "nope.jsonl")) == 2
