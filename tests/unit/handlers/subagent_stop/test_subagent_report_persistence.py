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

import logging
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.daemon.synthetic_traffic import (
    MANUAL_PROBE,
    PROBE_AGENT_ID,
    PROBE_AS_FIELD,
    SYNTHETIC_SOURCE_FIELD,
)
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

    def test_also_matches_a_re_entry_stop(self, handler: SubagentReportPersistenceHandler) -> None:
        """Review M2: `stop_hook_active` guards a BLOCKING sibling against
        looping on its own deny -- this handler never denies, so there is no
        loop to guard against, and dropping a re-entry stop means the
        agent's ACTUAL final reply (the one that survived a block from
        another handler and kept working) is never the one that gets
        saved. 'Every sub-agent's final reply' means every stop, including
        a re-entry one."""
        hook_input = _subagent_stop_input("short", stop_hook_active=True)
        assert handler.matches(hook_input) is True


class TestAProbeIsNotATeammate:
    """Plan 00466 N12: a `hooks-daemon probe SubagentStop --as sub` stop is
    fabricated, and persisting it would file a report no agent wrote."""

    def test_a_marked_probe_stop_is_not_matched(
        self, handler: SubagentReportPersistenceHandler
    ) -> None:
        hook_input = _subagent_stop_input(
            "probe",
            agent_id=PROBE_AGENT_ID,
            **{SYNTHETIC_SOURCE_FIELD: MANUAL_PROBE, PROBE_AS_FIELD: "sub"},
        )
        assert handler.matches(hook_input) is False

    def test_any_synthetic_stop_is_not_matched(
        self, handler: SubagentReportPersistenceHandler
    ) -> None:
        hook_input = _subagent_stop_input("probe", **{SYNTHETIC_SOURCE_FIELD: "playbook-probe"})
        assert handler.matches(hook_input) is False


class TestPersistence:
    def test_persists_a_short_reply_to_a_new_file(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_subagent_stop_input("a short reply", agent_id="agent-42"))

        assert result.decision == Decision.ALLOW
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
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
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        assert list(report_dir.glob("*agent-7*.md"))

    def test_persists_regardless_of_size_threshold(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        """Task 1.6 is unconditional -- unlike the size blocker, this handler
        saves a SHORT reply too, not only an over-threshold one."""
        result = handler.handle(_subagent_stop_input("tiny", agent_id="agent-tiny"))

        assert result.decision == Decision.ALLOW
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        assert list(report_dir.glob("*agent-tiny*.md"))

    def test_never_overwrites_a_prior_report(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler.handle(_subagent_stop_input("first", agent_id="agent-dup"))
        handler.handle(_subagent_stop_input("second", agent_id="agent-dup"))

        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        saved = sorted(report_dir.glob("*agent-dup*.md"))
        assert len(saved) == 2
        contents = {path.read_text() for path in saved}
        assert contents == {"first", "second"}

    def test_a_re_entry_stop_is_saved_as_a_second_file(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        """Review M2's failure scenario: a stop-hook block on the first stop,
        then a re-entry stop carrying the agent's real, corrected reply --
        both must be on disk, not just the first, superseded one."""
        handler.handle(_subagent_stop_input("superseded first attempt", agent_id="agent-resumed"))
        handler.handle(
            _subagent_stop_input(
                "the real final reply", agent_id="agent-resumed", stop_hook_active=True
            )
        )

        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        saved = sorted(report_dir.glob("*agent-resumed*.md"))
        assert len(saved) == 2
        contents = {path.read_text() for path in saved}
        assert contents == {"superseded first attempt", "the real final reply"}

    def test_report_dir_is_configurable(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler._report_dir = "untracked/custom-agent-reports/"

        handler.handle(_subagent_stop_input("x", agent_id="agent-custom"))

        assert list((tmp_path / "untracked" / "custom-agent-reports").glob("*.md"))

    def test_writes_only_under_its_own_auto_subdirectory_by_default(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        """Review B2: the default write target must be a subdirectory the
        daemon exclusively owns, never the shared `untracked/agent-reports/`
        a coordinator or agent is told to hand-author non-plan reports
        into -- otherwise retention prunes deliberate deliverables."""
        handler.handle(_subagent_stop_input("x", agent_id="agent-scoped"))

        shared_dir = tmp_path / "untracked" / "agent-reports"
        assert not list(shared_dir.glob("*agent-scoped*.md"))
        assert list((shared_dir / "auto").glob("*agent-scoped*.md"))

    def test_a_hand_authored_report_in_the_parent_dir_is_never_touched(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        """Review B2's exact failure scenario: an agent-authored report
        already sitting in the shared (non-`auto`) directory, dated well
        past the retention window, must survive every subsequent
        persist+prune -- this handler must never even list that directory,
        let alone write or prune inside it."""
        import os
        from datetime import UTC, datetime

        shared_dir = tmp_path / "untracked" / "agent-reports"
        shared_dir.mkdir(parents=True)
        old_report = shared_dir / "260915-claude-code-guide-haiku.md"
        old_report.write_text("a deliberately authored, old report")
        old_time = datetime(2026, 9, 15, tzinfo=UTC).timestamp()
        os.utime(old_report, (old_time, old_time))
        handler._max_kept_reports = 1
        handler._max_report_age_days = 1

        handler.handle(_subagent_stop_input("new auto-saved reply", agent_id="agent-new"))

        assert old_report.exists()
        assert old_report.read_text() == "a deliberately authored, old report"


class TestFailSafe:
    def test_allows_when_last_assistant_message_missing(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        hook_input = {"hook_event_name": "SubagentStop", "stop_hook_active": False}

        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert not (tmp_path / "untracked" / "agent-reports" / "auto").exists()

    def test_allows_when_last_assistant_message_is_empty(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_subagent_stop_input("   "))

        assert result.decision == Decision.ALLOW
        assert not (tmp_path / "untracked" / "agent-reports" / "auto").exists()

    def test_missing_field_matches_a_background_agents_stop_payload_shape(
        self,
        handler: SubagentReportPersistenceHandler,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Plan 00460 Task 1.6, explicitly requested coverage: a BACKGROUND
        agent's SubagentStop payload is the same shape as any other missing/
        empty ``last_assistant_message`` case above -- nothing written, and
        the reason is logged at debug (not silently dropped, not an error)."""
        hook_input = {
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-bg",
            "agent_type": "general-purpose",
            "stop_hook_active": False,
        }

        with caplog.at_level(logging.DEBUG):
            result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert not (tmp_path / "untracked" / "agent-reports" / "auto").exists()
        assert any(
            record.levelno == logging.DEBUG and "nothing to persist" in record.message.lower()
            for record in caplog.records
        )

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

    def test_allows_and_writes_nothing_when_report_dir_is_empty(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        """Review M1 (probe P2): an empty `report_dir` must never resolve to
        the project root, where retention would then prune README.md,
        CLAUDE.md and every other root-level markdown file by age."""
        handler._report_dir = ""

        result = handler.handle(_subagent_stop_input("x"))

        assert result.decision == Decision.ALLOW
        assert not list(tmp_path.glob("*.md"))

    def test_allows_and_writes_nothing_when_report_dir_is_dot(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler._report_dir = "."

        result = handler.handle(_subagent_stop_input("x"))

        assert result.decision == Decision.ALLOW
        assert not list(tmp_path.glob("*.md"))

    def test_allows_and_writes_nothing_when_report_dir_is_absolute(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        """Review M1 (probe P3): an absolute `report_dir` must never write
        outside the project root. Deliberately an absolute path UNDER
        `tmp_path` (rather than a fixed system path like `/tmp/x`, which a
        prior interrupted run could leave stale artefacts in): the
        rejection is keyed on the STRING being absolute, not on where it
        happens to point, and this way pytest cleans it up regardless."""
        absolute_target = tmp_path / "absolute-target"
        handler._report_dir = str(absolute_target)

        result = handler.handle(_subagent_stop_input("x"))

        assert result.decision == Decision.ALLOW
        assert not absolute_target.exists()

    def test_allows_and_writes_nothing_when_report_dir_escapes_the_root(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler._report_dir = "../escaped"

        result = handler.handle(_subagent_stop_input("x"))

        assert result.decision == Decision.ALLOW
        assert not list(tmp_path.parent.glob("escaped/*.md"))


class TestRetention:
    def test_prunes_to_the_configured_max_count(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler._max_kept_reports = 2
        handler._max_report_age_days = 365

        for index in range(4):
            handler.handle(_subagent_stop_input(f"reply {index}", agent_id=f"agent-{index}"))

        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        remaining = list(report_dir.glob("*.md"))
        assert len(remaining) == 2

    def test_the_just_written_report_is_never_pruned_out_by_its_own_write(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        handler._max_kept_reports = 1

        result = handler.handle(_subagent_stop_input("last one standing", agent_id="agent-last"))

        assert result.decision == Decision.ALLOW
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
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

    def test_the_advisory_test_actually_persists_a_file(
        self, handler: SubagentReportPersistenceHandler, tmp_path: Path
    ) -> None:
        """Review m9: the persister declares a single `TestType.ADVISORY`
        acceptance test, not a BLOCKING one -- the sibling test above
        filters for BLOCKING and therefore drives zero iterations, passing
        no matter what the handler does. This test actually runs the
        declared ADVISORY hook_input and asserts the file it is supposed to
        produce is really on disk."""
        from claude_code_hooks_daemon.core import TestType

        tests = [t for t in handler.get_acceptance_tests() if t.test_type == TestType.ADVISORY]
        assert tests, "expected at least one ADVISORY acceptance test"

        for test in tests:
            assert test.hook_input is not None
            result = handler.handle(test.hook_input)
            assert result.decision == test.expected_decision

        agent_id = tests[0].hook_input["agent_id"]
        report_dir = tmp_path / "untracked" / "agent-reports" / "auto"
        saved = list(report_dir.glob(f"*{agent_id}*.md"))
        assert len(saved) == 1
        assert saved[0].read_text() == tests[0].hook_input["last_assistant_message"]
