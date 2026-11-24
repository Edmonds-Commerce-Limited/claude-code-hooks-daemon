"""Plan 00636 Task 2.4 (s8): the wind-down note for a stop around running background agents."""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import _declares_human_blocked
from claude_code_hooks_daemon.handlers.stop.owner_wait_stop_guard import _waiting_re
from claude_code_hooks_daemon.utils.wind_down import (
    MAX_ID_CHARS,
    MAX_LISTED_IDS,
    running_background_ids,
    suggested_stop_line,
    wind_down_note,
)


def _task(task_id: Any, status: Any = "running") -> dict[str, Any]:
    return {"id": task_id, "type": "subagent", "status": status}


class TestRunningBackgroundIds:
    def test_absent_field_is_no_information(self) -> None:
        assert running_background_ids({}) is None

    def test_malformed_field_is_no_information(self) -> None:
        assert running_background_ids({"background_tasks": "two"}) is None

    def test_empty_list_is_no_information(self) -> None:
        assert running_background_ids({"background_tasks": []}) is None

    def test_no_running_entry_is_none(self) -> None:
        tasks = [_task("a1", "completed"), _task("a2", "failed")]
        assert running_background_ids({"background_tasks": tasks}) is None

    def test_running_entries_are_counted_and_named(self) -> None:
        tasks = [_task("a1"), _task("a2", "completed"), _task("a3")]
        result = running_background_ids({"background_tasks": tasks})
        assert result is not None
        assert result.count == 2
        assert result.ids == ("a1", "a3")

    def test_non_dict_entries_are_skipped(self) -> None:
        tasks: list[Any] = ["running", 7, None, _task("a1")]
        result = running_background_ids({"background_tasks": tasks})
        assert result is not None
        assert result.count == 1

    def test_non_string_id_is_counted_but_not_named(self) -> None:
        tasks = [_task({"a": 1}), _task(12), _task(None)]
        result = running_background_ids({"background_tasks": tasks})
        assert result is not None
        assert result.count == 3
        assert result.ids == ()

    def test_id_with_markup_is_counted_but_not_named(self) -> None:
        tasks = [_task("a`b"), _task("x\ny"), _task("ok-1")]
        result = running_background_ids({"background_tasks": tasks})
        assert result is not None
        assert result.count == 3
        assert result.ids == ("ok-1",)

    def test_long_id_is_truncated(self) -> None:
        result = running_background_ids({"background_tasks": [_task("a" * 500)]})
        assert result is not None
        assert len(result.ids[0]) <= MAX_ID_CHARS

    def test_listed_ids_are_capped(self) -> None:
        tasks = [_task(f"t{n}") for n in range(MAX_LISTED_IDS + 4)]
        result = running_background_ids({"background_tasks": tasks})
        assert result is not None
        assert result.count == MAX_LISTED_IDS + 4
        assert len(result.ids) == MAX_LISTED_IDS


class TestWindDownNote:
    def test_note_names_count_ids_and_the_remedy(self) -> None:
        result = running_background_ids({"background_tasks": [_task("a1"), _task("a2")]})
        assert result is not None
        note = wind_down_note(result)
        assert "2 background tasks" in note
        assert "`a1`" in note and "`a2`" in note
        assert "STOPPING BECAUSE:" in note
        assert "ListAgents" in note
        assert "TaskStop" in note

    def test_note_says_how_many_more_were_not_listed(self) -> None:
        tasks = [_task(f"t{n}") for n in range(MAX_LISTED_IDS + 2)]
        result = running_background_ids({"background_tasks": tasks})
        assert result is not None
        assert "and 2 more" in wind_down_note(result)

    def test_note_carries_no_rule_id(self) -> None:
        result = running_background_ids({"background_tasks": [_task("a1")]})
        assert result is not None
        assert "R-" not in wind_down_note(result)
        assert "BLOCKED [" not in wind_down_note(result)

    @pytest.mark.parametrize("count", [1, 3])
    def test_suggested_line_is_not_a_human_wait(self, count: int) -> None:
        """The suggested stop must not arm awaiting-human nor the owner-wait guard."""
        line = suggested_stop_line(count)
        assert line.startswith("STOPPING BECAUSE:")
        assert not _declares_human_blocked(line)
        assert _waiting_re(()).search(line) is None
        assert "[awaiting-human]" not in line

    def test_whole_note_is_not_a_human_wait(self) -> None:
        result = running_background_ids({"background_tasks": [_task("a1")]})
        assert result is not None
        note = wind_down_note(result)
        assert not _declares_human_blocked(note)
        assert _waiting_re(()).search(note) is None


def _note(count: int) -> str:
    tasks = [_task(f"t{n}") for n in range(count)]
    result = running_background_ids({"background_tasks": tasks})
    assert result is not None
    return wind_down_note(result)


class TestWording:
    def test_note_does_not_promise_the_stop_passes(self) -> None:
        note = _note(2)
        assert "the stop passes" not in note
        assert "this refusal clears" in note
        assert "branch_stop_guard" in note
        assert "cron_stop_enforcer" in note

    @pytest.mark.parametrize("count", [1, 2, 5, 9999, 10000])
    def test_stop_line_number_agrees_with_count(self, count: int) -> None:
        line = suggested_stop_line(count)
        if count == 1:
            assert "1 background task is still running" in line
            assert "its completion notice resumes" in line
            assert "tasks" not in line
        else:
            assert f"{count} background tasks are still running" in line
            assert "their completion notices resume" in line

    @pytest.mark.parametrize("count", [1, 2, 5, 9999, 10000])
    def test_note_agrees_with_count(self, count: int) -> None:
        note = _note(count)
        assert suggested_stop_line(count) in note
        if count == 1:
            assert "letting it finish" in note
            assert "letting them finish" not in note
        else:
            assert "letting them finish" in note
            assert "letting it finish" not in note
