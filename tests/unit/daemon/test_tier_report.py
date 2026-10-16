"""Tests for ``hooks-daemon tiers`` (Plan 00472 Task 3.4): golden output from fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.tier_report import (
    collect_tiers,
    render_tiers,
    tiers_as_dict,
)
from claude_code_hooks_daemon.utils.spend_ledger import (
    merge_dispatch_row,
    spend_cache,
    write_dispatch_row,
)


def _request(request_id: str, model: str, tokens: int) -> dict[str, Any]:
    return {
        "type": "assistant",
        "requestId": request_id,
        "message": {"model": model, "usage": {"input_tokens": tokens}},
    }


def _agent(
    directory: Path, agent_id: str, name: str, tool_use_id: str, records: list[dict]
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"agent-{agent_id}.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )
    (directory / f"agent-{agent_id}.meta.json").write_text(
        json.dumps({"name": name, "toolUseId": tool_use_id})
    )


def _dispatch(untracked: Path, tool_use_id: str, resolved: str, **fields: str) -> None:
    write_dispatch_row(untracked, "s1", tool_use_id, fields)
    merge_dispatch_row(untracked, "s1", tool_use_id, {"resolved_model": resolved})


@pytest.fixture
def session(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Three agents: an explicit Sonnet fixer, an inherited Opus implementer and an
    inherited Opus reviewer the safety fallback swapped mid-run."""
    untracked = tmp_path / "untracked"
    agents = tmp_path / "s1" / "subagents"
    _agent(agents, "afix", "fixer-1", "toolu_a", [_request("r1", "claude-sonnet-5-5", 1000)])
    _agent(agents, "aimpl", "impl-1", "toolu_b", [_request("r2", "claude-opus-5-5", 500)])
    _agent(
        agents,
        "arev",
        "review-guards-5",
        "toolu_c",
        [_request("r3", "claude-opus-5-5", 200), _request("r4", "claude-opus-4-8", 300)],
    )
    _dispatch(
        untracked,
        "toolu_a",
        "claude-sonnet-5-5",
        subagent_type="python-developer",
        source="explicit",
        role="fix",
        predicted_family="sonnet",
    )
    _dispatch(
        untracked,
        "toolu_b",
        "claude-opus-5-5",
        subagent_type="general-purpose",
        source="inherited",
        role="implement",
        predicted_family="opus",
    )
    _dispatch(
        untracked,
        "toolu_c",
        "claude-opus-5-5",
        subagent_type="general-purpose",
        source="inherited",
        role="review",
        predicted_family="opus",
    )
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    return agents, untracked, project


GOLDEN = """\
Subagent tiers, session s1 (3 agents, 0 unjoined dispatch rows)

source                 agents         ite   share  models
explicit                    1       1,000   50.0%  sonnet 1
inherited                   2       1,000   50.0%  opus 2
TOTAL                       3       2,000  100.0%

model                  agents         ite   share  models
opus                        2       1,000   50.0%  opus 2
sonnet                      1       1,000   50.0%  sonnet 1
TOTAL                       3       2,000  100.0%

role                   agents         ite   share  models
fix                         1       1,000   50.0%  sonnet 1
implement                   1         500   25.0%  opus 1
review                      1         500   25.0%  opus 1
TOTAL                       3       2,000  100.0%

CLAUDE_CODE_SUBAGENT_MODEL: not set in .claude/settings.json (recommended: sonnet, with floors for reviewers; see docs/guides/SUBAGENT_MODEL_TIERS.md)
Inherited at the spawner's tier: 2 of 3 agents, 50.0% of ite
Downgraded agents (model swapped mid-run):
  review-guards-5  claude-opus-5-5 1, claude-opus-4-8 1
"""


def _collect(session: tuple[Path, Path, Path]) -> Any:
    agents, untracked, project = session
    return collect_tiers(
        agents,
        session_id="s1",
        untracked=untracked,
        cache=spend_cache(None),
        project_root=project,
    )


class TestGolden:
    def test_all_tables(self, session: tuple[Path, Path, Path]) -> None:
        assert render_tiers(_collect(session), by=None) == GOLDEN

    def test_by_type_prints_only_that_grouping(self, session: tuple[Path, Path, Path]) -> None:
        text = render_tiers(_collect(session), by="type")
        assert "subagent_type" in text
        assert "general-purpose             2" in text
        assert "\nsource " not in text
        assert "CLAUDE_CODE_SUBAGENT_MODEL" in text

    def test_env_value_is_reported(self, session: tuple[Path, Path, Path]) -> None:
        _, _, project = session
        (project / ".claude" / "settings.json").write_text(
            json.dumps({"env": {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}})
        )
        text = render_tiers(_collect(session), by=None)
        assert "CLAUDE_CODE_SUBAGENT_MODEL: sonnet (.claude/settings.json env)" in text


class TestCli:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from claude_code_hooks_daemon.core.project_context import ProjectContext
        from claude_code_hooks_daemon.daemon import cli

        monkeypatch.setattr(cli, "get_project_path", lambda _override: tmp_path)
        monkeypatch.setattr(ProjectContext, "_initialized", False)

    def _args(self, tmp_path: Path, transcript: Path, **extra: Any) -> argparse.Namespace:
        values: dict[str, Any] = {
            "transcript": str(transcript),
            "session": None,
            "by": None,
            "json": False,
            "project_root": tmp_path,
        }
        values.update(extra)
        return argparse.Namespace(**values)

    def _main_transcript(self, tmp_path: Path) -> Path:
        agents = tmp_path / "s1" / "subagents"
        _agent(agents, "ax", "impl-1", "toolu_a", [_request("r1", "claude-opus-5-5", 10)])
        _dispatch(
            tmp_path / "untracked",
            "toolu_a",
            "claude-opus-5-5",
            subagent_type="general-purpose",
            source="inherited",
            role="implement",
        )
        transcript = tmp_path / "s1.jsonl"
        transcript.write_text("{}\n")
        return transcript

    def test_text_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from claude_code_hooks_daemon.daemon.cli import cmd_tiers

        assert cmd_tiers(self._args(tmp_path, self._main_transcript(tmp_path))) == 0
        out = capsys.readouterr().out
        assert "inherited                   1" in out
        assert "CLAUDE_CODE_SUBAGENT_MODEL" in out

    def test_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from claude_code_hooks_daemon.daemon.cli import cmd_tiers

        transcript = self._main_transcript(tmp_path)
        assert cmd_tiers(self._args(tmp_path, transcript, json=True)) == 0
        assert json.loads(capsys.readouterr().out)["agents"][0]["source"] == "inherited"

    def test_missing_transcript_is_an_error(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.cli import cmd_tiers

        assert cmd_tiers(self._args(tmp_path, tmp_path / "nope.jsonl")) == 2

    def test_parser_registers_the_command(self) -> None:
        from claude_code_hooks_daemon.daemon.cli import build_parser

        args = build_parser().parse_args(["tiers", "--by", "role", "--session", "s1"])
        assert (args.by, args.session) == ("role", "s1")


class TestJoin:
    def test_an_agent_with_no_dispatch_row_is_unrecorded(self, tmp_path: Path) -> None:
        agents = tmp_path / "s1" / "subagents"
        _agent(agents, "ax", "old", "toolu_z", [_request("r1", "claude-opus-5-5", 10)])
        report = collect_tiers(
            agents,
            session_id="s1",
            untracked=tmp_path / "u",
            cache=spend_cache(None),
            project_root=tmp_path,
        )
        (agent,) = report.agents
        assert agent.source == "unrecorded"
        assert agent.family == "opus"

    def test_a_post_only_row_counts_as_unjoined(self, session: tuple[Path, Path, Path]) -> None:
        _, untracked, _ = session
        merge_dispatch_row(untracked, "s1", "toolu_x", {"resolved_model": "claude-opus-5-5"})
        assert _collect(session).unjoined == 1

    def test_json(self, session: tuple[Path, Path, Path]) -> None:
        data = tiers_as_dict(_collect(session))
        assert data["session"] == "s1"
        assert data["unjoined"] == 0
        assert {row["source"] for row in data["agents"]} == {"explicit", "inherited"}
        (downgraded,) = data["downgraded"]
        assert downgraded["per_model_requests"] == {"claude-opus-5-5": 1, "claude-opus-4-8": 1}
