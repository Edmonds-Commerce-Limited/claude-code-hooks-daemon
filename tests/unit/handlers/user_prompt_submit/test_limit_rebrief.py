"""LimitRebriefHandler: re-brief after a usage-limit resume or a limit-killed agent (Plan 00470 Task 3.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.user_prompt_submit.limit_rebrief import (
    _REBRIEF_PLACES,
    LimitRebriefHandler,
)
from claude_code_hooks_daemon.utils.limit_events import (
    KIND_AGENT_KILLED,
    LimitEvent,
    pending_events,
    read_events,
    record_event,
)
from claude_code_hooks_daemon.utils.stop_failure_records import StopFailureRecord, record_failure
from claude_code_hooks_daemon.utils.work_queue import STATUS_DONE, add_record, update_record

_NOW = 6_000_000.0

# The harness's own wording for a usage-limit rejection, as the repository's
# transcript evidence quotes it (Plan 00315 transcript miner, Plan 00466 N46).
_LIMIT_TEXT = "You've hit your session limit · resets 9:50am (UTC)"
_WEEKLY_TEXT = "You've hit your weekly limit · resets Sep 27, 8am (UTC)"


class _Handler(LimitRebriefHandler):
    """The handler with a fixed clock and record files under ``tmp_path``."""

    def __init__(self, events: Path | None, failures: Path | None = None) -> None:
        super().__init__()
        self.events = events
        self.failures = failures

    def _events_path(self) -> Path | None:
        return self.events

    def _stop_failures_path(self) -> Path | None:
        return self.failures

    def _queue_path(self) -> Path | None:
        return None

    def _now(self) -> float:
        return _NOW


def _prompt(text: str = "go on", session_id: str = "s1") -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "session_id": session_id, "prompt": text}


def _task_notification(body: str) -> str:
    return f"<task-notification>\n{body}\n</task-notification>"


def _teammate_failure(teammate: str = "reviewer-1", reason: str = _LIMIT_TEXT) -> str:
    return (
        f'<teammate-message teammate_id="{teammate}" summary="idle">'
        f'{{"type":"idle_notification","from":"{teammate}","idleReason":"failed",'
        f'"failureReason":"{reason}"}}</teammate-message>'
    )


def _resume(kind: str = "quota_auto_resume_fired", session_id: str = "s1") -> LimitEvent:
    return LimitEvent(session_id=session_id, kind=kind, recorded_at=_NOW - 60)


def _context(result: Any) -> str:
    return "\n".join(result.context or [])


class _QueuedHandler(_Handler):
    """The handler with a work queue file under ``tmp_path``."""

    def __init__(self, events: Path, queue: Path | None) -> None:
        super().__init__(events)
        self.queue = queue

    def _queue_path(self) -> Path | None:
        return self.queue


def _queue_one(queue: Path, worktree: Path, *, name: str = "builder") -> None:
    add_record(
        queue,
        name,
        worktree=str(worktree),
        branch="worktree-builder",
        brief="Implement the thing.",
        brief_file=None,
        last_sha="abc1234",
        now=_NOW - 600,
    )


class TestWorkQueueRebrief:
    """Plan 00470 Task 3.3: the re-brief after a resume lists the durable work queue."""

    def test_the_queue_heads_the_places_to_look(self) -> None:
        assert "work-queue list" in _REBRIEF_PLACES[0]

    def test_running_agents_are_listed_with_their_respawn_facts(self, tmp_path: Path) -> None:
        events, queue = tmp_path / "e.json", tmp_path / "q.json"
        record_event(events, _resume())
        _queue_one(queue, tmp_path)
        text = _context(_QueuedHandler(events, queue).handle(_prompt()))
        assert "builder" in text
        assert "worktree-builder" in text
        assert "abc1234" in text
        assert "Implement the thing." in text

    def test_a_closed_agent_is_not_listed(self, tmp_path: Path) -> None:
        events, queue = tmp_path / "e.json", tmp_path / "q.json"
        record_event(events, _resume())
        _queue_one(queue, tmp_path)
        update_record(queue, "builder", now=_NOW, status=STATUS_DONE)
        assert "WORK QUEUE" not in _context(_QueuedHandler(events, queue).handle(_prompt()))

    def test_an_unreadable_queue_is_reported_not_called_empty(self, tmp_path: Path) -> None:
        events, queue = tmp_path / "e.json", tmp_path / "q.json"
        record_event(events, _resume())
        queue.write_text("{oops", encoding="utf-8")
        text = _context(_QueuedHandler(events, queue).handle(_prompt()))
        assert "WORK QUEUE UNREADABLE" in text

    def test_no_queue_file_leaves_the_rebrief_as_it_was(self, tmp_path: Path) -> None:
        events = tmp_path / "e.json"
        record_event(events, _resume())
        text = _context(_QueuedHandler(events, tmp_path / "none.json").handle(_prompt()))
        assert "WORK QUEUE" not in text
        assert "RE-BRIEF WHAT WAS IN FLIGHT" in text


class TestIdentity:
    def test_it_is_wired_to_the_constants(self) -> None:
        handler = LimitRebriefHandler()
        assert handler.name == HandlerID.LIMIT_REBRIEF.display_name
        assert handler.priority == Priority.LIMIT_REBRIEF
        assert handler.config_key == "limit_rebrief"

    def test_it_is_not_terminal(self) -> None:
        assert LimitRebriefHandler().terminal is False


class TestMatching:
    def test_an_ordinary_prompt_with_nothing_pending_does_not_match(self, tmp_path: Path) -> None:
        assert _Handler(tmp_path / "e.json").matches(_prompt()) is False

    def test_a_pending_resume_event_matches_any_prompt(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume())
        assert _Handler(path).matches(_prompt()) is True

    def test_a_resume_event_of_another_session_does_not_match(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume(session_id="other"))
        assert _Handler(path).matches(_prompt()) is False

    def test_a_killed_agent_alone_is_not_a_resume(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(
            path,
            LimitEvent(session_id="s1", kind=KIND_AGENT_KILLED, recorded_at=1.0, detail="x"),
        )
        assert _Handler(path).matches(_prompt()) is False

    def test_a_limit_task_notification_matches(self, tmp_path: Path) -> None:
        text = _task_notification(f'Agent "builder" failed: {_LIMIT_TEXT}')
        assert _Handler(tmp_path / "e.json").matches(_prompt(text)) is True

    def test_no_project_context_and_a_plain_prompt_does_not_match(self) -> None:
        assert _Handler(None).matches(_prompt()) is False


class TestResumeRebrief:
    @pytest.mark.parametrize(
        ("kind", "wording"),
        [
            ("quota_auto_resume_fired", "resumed"),
            ("quota_auto_resume_stale", "waiting"),
            ("quota_auto_resume_disabled", "did not continue"),
        ],
    )
    def test_each_kind_is_worded_for_what_happened(
        self, tmp_path: Path, kind: str, wording: str
    ) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume(kind))
        result = _Handler(path).handle(_prompt())
        assert result.decision == Decision.ALLOW
        assert wording in _context(result).lower()
        assert kind in _context(result)

    def test_it_points_at_what_exists_today(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume())
        text = _context(_Handler(path).handle(_prompt()))
        assert "git worktree list" in text
        assert "JOURNAL" in text
        assert "re-brief" in text.lower()

    def test_it_is_delivered_once(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume())
        handler = _Handler(path)
        assert handler.handle(_prompt()).context
        assert pending_events(path, "s1") == []
        assert handler.matches(_prompt()) is False

    def test_delivery_is_stamped_with_the_time(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume())
        _Handler(path).handle(_prompt())
        assert read_events(path)[0].delivered_at == _NOW

    def test_agents_recorded_as_killed_are_named(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(
            path,
            LimitEvent(
                session_id="s1", kind=KIND_AGENT_KILLED, recorded_at=1.0, detail="builder-7"
            ),
        )
        record_event(path, _resume())
        text = _context(_Handler(path).handle(_prompt()))
        assert "builder-7" in text

    def test_another_sessions_agents_are_not_named(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(
            path,
            LimitEvent(session_id="other", kind=KIND_AGENT_KILLED, recorded_at=1.0, detail="alien"),
        )
        record_event(path, _resume())
        assert "alien" not in _context(_Handler(path).handle(_prompt()))

    def test_agents_are_marked_delivered_with_the_resume(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(
            path,
            LimitEvent(session_id="s1", kind=KIND_AGENT_KILLED, recorded_at=1.0, detail="a"),
        )
        record_event(path, _resume())
        _Handler(path).handle(_prompt())
        assert pending_events(path, "s1") == []

    def test_with_no_agents_recorded_it_says_so_and_still_points_at_the_worktrees(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume())
        text = _context(_Handler(path).handle(_prompt()))
        assert "no agent was recorded" in text.lower()

    def test_the_last_recorded_limit_hit_is_cited_even_when_already_resolved(
        self, tmp_path: Path
    ) -> None:
        events = tmp_path / "e.json"
        failures = tmp_path / "f.json"
        record_event(events, _resume())
        record_failure(
            failures,
            StopFailureRecord(
                session_id="s1", error="rate_limit", recorded_at=_NOW - 3600, resolved_at=_NOW - 1
            ),
        )
        text = _context(_Handler(events, failures).handle(_prompt()))
        assert "rate_limit" in text

    def test_another_sessions_limit_hit_is_not_cited(self, tmp_path: Path) -> None:
        events = tmp_path / "e.json"
        failures = tmp_path / "f.json"
        record_event(events, _resume())
        record_failure(
            failures,
            StopFailureRecord(session_id="other", error="authentication_failed", recorded_at=1.0),
        )
        text = _context(_Handler(events, failures).handle(_prompt()))
        assert "authentication_failed" not in text

    def test_it_lists_no_queued_agent_when_there_is_no_queue(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume())
        assert "WORK QUEUE" not in _context(_Handler(path).handle(_prompt()))


class TestKilledAgentNotice:
    def test_a_background_task_notification_naming_a_limit_is_recorded_and_surfaced(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "e.json"
        body = f'Agent "builder-7" failed: {_WEEKLY_TEXT}'
        result = _Handler(path).handle(_prompt(_task_notification(body)))
        assert result.decision == Decision.ALLOW
        text = _context(result)
        assert "builder-7" in text
        assert "re-brief" in text.lower()
        events = read_events(path)
        assert [e.kind for e in events] == [KIND_AGENT_KILLED]
        assert "builder-7" in events[0].detail

    def test_a_teammate_idle_failure_names_the_teammate(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        result = _Handler(path).handle(_prompt(_teammate_failure("reviewer-1")))
        assert "reviewer-1" in _context(result)
        assert read_events(path)[0].detail.startswith("teammate reviewer-1")

    def test_a_teammate_message_without_the_failed_idle_shape_is_ignored(
        self, tmp_path: Path
    ) -> None:
        chatter = (
            '<teammate-message teammate_id="peer">I think reviewer-1 hit its session limit '
            "· resets 9:50am (UTC), could you cover?</teammate-message>"
        )
        assert _Handler(tmp_path / "e.json").matches(_prompt(chatter)) is False

    def test_a_task_notification_without_limit_wording_is_ignored(self, tmp_path: Path) -> None:
        text = _task_notification('Agent "builder" failed: tests did not pass')
        assert _Handler(tmp_path / "e.json").matches(_prompt(text)) is False

    def test_a_human_prompt_quoting_the_limit_text_is_ignored(self, tmp_path: Path) -> None:
        assert _Handler(tmp_path / "e.json").matches(_prompt(f"it said: {_LIMIT_TEXT}")) is False

    def test_the_marker_must_open_the_prompt(self, tmp_path: Path) -> None:
        text = f"please look at <task-notification>{_LIMIT_TEXT}</task-notification>"
        assert _Handler(tmp_path / "e.json").matches(_prompt(text)) is False

    def test_a_notification_prompt_with_surrounding_whitespace_still_matches(
        self, tmp_path: Path
    ) -> None:
        text = "\n  " + _task_notification(f"agent x: {_LIMIT_TEXT}")
        assert _Handler(tmp_path / "e.json").matches(_prompt(text)) is True

    def test_the_agent_is_named_by_the_notification_text_without_markup(
        self, tmp_path: Path
    ) -> None:
        text = _task_notification(f'<summary>Agent "x" died</summary> {_LIMIT_TEXT}')
        _Handler(tmp_path / "e.json").handle(_prompt(text))
        detail = read_events(tmp_path / "e.json")[0].detail
        assert "<" not in detail
        assert "x" in detail

    def test_the_observed_notification_shape_is_named_by_its_summary(self, tmp_path: Path) -> None:
        text = (
            "<task-notification>\n<task-id>a1b2c3</task-id>\n"
            "<tool-use-id>toolu_01Example</tool-use-id>\n"
            "<output-file>/tmp/claude-0/-workspace/tasks/a1b2c3.output</output-file>\n"
            "<status>failed</status>\n"
            f'<summary>Agent "builder-7" stopped: {_WEEKLY_TEXT}</summary>\n'
            "</task-notification>"
        )
        _Handler(tmp_path / "e.json").handle(_prompt(text))
        detail = read_events(tmp_path / "e.json")[0].detail
        assert detail.startswith('background task notification: Agent "builder-7"')
        assert "toolu_01Example" not in detail

    def test_a_long_notification_is_bounded(self, tmp_path: Path) -> None:
        text = _task_notification("y" * 5000 + _LIMIT_TEXT)
        _Handler(tmp_path / "e.json").handle(_prompt(text))
        assert len(read_events(tmp_path / "e.json")[0].detail) <= 300

    def test_a_repeated_notification_is_recorded_once(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        text = _task_notification(f'Agent "b" failed: {_LIMIT_TEXT}')
        handler = _Handler(path)
        handler.handle(_prompt(text))
        handler.handle(_prompt(text))
        assert len(read_events(path)) == 1

    def test_a_death_and_a_pending_resume_give_both_notices(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        record_event(path, _resume())
        text = _task_notification(f'Agent "b" failed: {_LIMIT_TEXT}')
        result = _Handler(path).handle(_prompt(text))
        assert len(result.context) == 2

    def test_no_session_id_records_nothing_but_still_warns(self, tmp_path: Path) -> None:
        path = tmp_path / "e.json"
        text = _task_notification(f"agent b: {_LIMIT_TEXT}")
        result = _Handler(path).handle(_prompt(text, session_id=""))
        assert not path.exists()
        assert result.context

    def test_no_project_context_still_warns_and_does_not_raise(self) -> None:
        text = _task_notification(f"agent b: {_LIMIT_TEXT}")
        assert _Handler(None).handle(_prompt(text)).context


class TestSilence:
    def test_an_ordinary_prompt_with_nothing_pending_adds_no_context(self, tmp_path: Path) -> None:
        result = _Handler(tmp_path / "e.json").handle(_prompt())
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_a_non_string_prompt_is_ignored(self, tmp_path: Path) -> None:
        payload = _prompt()
        payload["prompt"] = None
        assert _Handler(tmp_path / "e.json").matches(payload) is False


class TestDocumentation:
    def test_it_never_denies_and_delivers_in_full_at_fire_time_so_ships_no_guidance(
        self,
    ) -> None:
        assert LimitRebriefHandler().get_claude_md() is None

    def test_it_declares_acceptance_tests(self) -> None:
        assert LimitRebriefHandler().get_acceptance_tests()
