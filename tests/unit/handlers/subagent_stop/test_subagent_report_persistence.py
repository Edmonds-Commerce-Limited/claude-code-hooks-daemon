"""SubagentReportPersistenceHandler - persist every reply to a gitignored file.

Plan 00460 Task 1.6. The owner asked directly whether there is a hook that
ensures sub-agent reports are persisted to file. This handler answers it at
the daemon level: EVERY SubagentStop's ``last_assistant_message`` is saved to
a gitignored location, regardless of agent type or Write access, so nothing
depends on the agent's own cooperation (or tool set) to survive.

Design constraints pinned:

- **Never blocks** -- a sensor on a blocking event; persistence failing must
  never strand a stopping agent.
- **Never overwrites** -- each stop gets its own file (agent_id makes the
  name unique; a same-second collision still gets a numeric suffix).
- **Bounded from day one** -- pruned to a configured cap after every write
  (issue #52 was a feature with no pruner).
- **Nothing written for a missing/empty reply** -- logged at debug, not an
  error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.subagent_stop.subagent_report_persistence import (
    SubagentReportPersistenceHandler,
)


def _subagent_stop_input(message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "SubagentStop",
        "agent_id": "agent-1",
        "agent_type": "Explore",
        "last_assistant_message": message,
        "stop_hook_active": False,
    }
    payload.update(extra)
    return payload


@pytest.fixture
def handler(tmp_path: Path) -> SubagentReportPersistenceHandler:
    instance = SubagentReportPersistenceHandler()
    instance._project_root = tmp_path
    return instance


class TestIdentity:
    def test_is_non_terminal(self, handler: SubagentReportPersistenceHandler) -> None:
        assert handler.terminal is False

    def test_exposes_claude_md_guidance(self, handler: SubagentReportPersistenceHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "agent-reports" in guidance


class TestMatching:
    def test_matches_normal_subagent_stop(self, handler: SubagentReportPersistenceHandler) -> None:
        assert handler.matches(_subagent_stop_input("short")) is True

    def test_does_not_match_re_entry(self, handler: SubagentReportPersistenceHandler) -> None:
        hook_input = _subagent_stop_input("short", stop_hook_active=True)
        assert handler.matches(hook_input) is False


class TestPersistence:
    def test_persists_a_short_reply_to_a_new_file(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_subagent_stop_input("a short reply", agent_id="agent-42"))

        assert result.decision == Decision.ALLOW
        report_dir = tmp_path / "untracked" / "agent-reports"
        saved = list(report_dir.glob("*agent-42*.md"))
        assert len(saved) == 1
        assert saved[0].read_text() == "a short reply"

    def test_persists_regardless_of_agent_type(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(
            _subagent_stop_input(
                "writable agent's reply", agent_type="general-purpose", agent_id="agent-7"
            )
        )

        assert result.decision == Decision.ALLOW
        report_dir = tmp_path / "untracked" / "agent-reports"
        assert list(report_dir.glob("*agent-7*.md"))

    def test_persists_regardless_of_size_threshold(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        """Task 1.6 is unconditional -- unlike the size blocker, this handler
        saves a SHORT reply too, not only an over-threshold one."""
        result = handler.handle(_subagent_stop_input("tiny", agent_id="agent-tiny"))

        assert result.decision == Decision.ALLOW
        report_dir = tmp_path / "untracked" / "agent-reports"
        assert list(report_dir.glob("*agent-tiny*.md"))

    def test_never_overwrites_a_prior_report(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler.handle(_subagent_stop_input("first", agent_id="agent-dup"))
        handler.handle(_subagent_stop_input("second", agent_id="agent-dup"))

        report_dir = tmp_path / "untracked" / "agent-reports"
        saved = sorted(report_dir.glob("*agent-dup*.md"))
        assert len(saved) == 2
        contents = {path.read_text() for path in saved}
        assert contents == {"first", "second"}

    def test_report_dir_is_configurable(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler._report_dir = "untracked/custom-agent-reports/"

        handler.handle(_subagent_stop_input("x", agent_id="agent-custom"))

        assert list((tmp_path / "untracked" / "custom-agent-reports").glob("*.md"))


class TestFailSafe:
    def test_allows_when_last_assistant_message_missing(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        hook_input = {"hook_event_name": "SubagentStop", "stop_hook_active": False}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert not (tmp_path / "untracked" / "agent-reports").exists()

    def test_allows_when_last_assistant_message_is_empty(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_subagent_stop_input("   "))

        assert result.decision == Decision.ALLOW
        assert not (tmp_path / "untracked" / "agent-reports").exists()

    def test_allows_when_last_assistant_message_is_not_a_string(
        self, handler: SubagentReportPersistenceHandler
    ) -> None:
        hook_input = _subagent_stop_input("placeholder")
        hook_input["last_assistant_message"] = {"not": "a string"}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW

    def test_never_denies_even_when_write_target_is_unwritable(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        # A FILE where the report directory should be: mkdir raises inside
        # write_new_file_never_overwrite, which must degrade to None, not raise.
        blocker = tmp_path / "untracked"
        blocker.mkdir()
        (blocker / "agent-reports").write_text("not a directory")

        result = handler.handle(_subagent_stop_input("x"))

        assert result.decision == Decision.ALLOW


class TestRetention:
    def test_prunes_to_the_configured_max_count(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler._max_kept_reports = 2
        handler._max_report_age_days = 365

        for index in range(4):
            handler.handle(_subagent_stop_input(f"reply {index}", agent_id=f"agent-{index}"))

        report_dir = tmp_path / "untracked" / "agent-reports"
        remaining = list(report_dir.glob("*.md"))
        assert len(remaining) == 2

    def test_the_just_written_report_is_never_pruned_out_by_its_own_write(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler._max_kept_reports = 1

        result = handler.handle(_subagent_stop_input("last one standing", agent_id="agent-last"))

        assert result.decision == Decision.ALLOW
        report_dir = tmp_path / "untracked" / "agent-reports"
        remaining = list(report_dir.glob("*.md"))
        assert len(remaining) == 1
        assert remaining[0].read_text() == "last one standing"


class TestDeclaredAcceptanceTestsAreProducible:
    def test_every_blocking_test_hook_input_produces_its_declared_decision_and_patterns(
        self, handler: SubagentReportPersistenceHandler
    ) -> None:
        import re

        from claude_code_hooks_daemon.core import TestType

        tests = [t for t in handler.get_acceptance_tests() if t.test_type == TestType.BLOCKING]
        for test in tests:
            assert test.hook_input is not None
            result = handler.handle(test.hook_input)
            assert result.decision == test.expected_decision
            for pattern in test.expected_message_patterns:
                assert re.search(pattern, result.reason or "")
