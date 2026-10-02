"""CronRecordKeeperHandler: record every CronCreate, forget every CronDelete (Plan 00470 Task 2.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.cron_record_keeper import (
    CronRecordKeeperHandler,
)
from claude_code_hooks_daemon.utils.cron_records import (
    CRON_EXPIRY_SECONDS,
    CronRecord,
    prompt_fingerprint,
    read_records,
    record_cron,
)

_NOW = 2_000_000.0
_PROMPT = "[tick:job:issue-sdlc]\nInvoke the issue-sdlc skill."


class _Handler(CronRecordKeeperHandler):
    """The handler with a fixed clock and a record file under ``tmp_path``."""

    def __init__(self, path: Path | None, now: float = _NOW) -> None:
        super().__init__()
        self.path = path
        self.now = now

    def _records_path(self) -> Path | None:
        return self.path

    def _now(self) -> float:
        return self.now


def _create(response: Any = None, **overrides: Any) -> dict[str, Any]:
    tool_input = {"cron": "23 * * * *", "prompt": _PROMPT, "recurring": True}
    payload: dict[str, Any] = {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "tool_name": "CronCreate",
        "tool_input": tool_input,
        "tool_response": {"id": "job-1"} if response is None else response,
    }
    payload.update(overrides)
    return payload


def _delete(cron_id: str = "job-1", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "tool_name": "CronDelete",
        "tool_input": {"id": cron_id},
        "tool_response": {"success": True},
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "cron-records.json"


class TestMatching:
    @pytest.mark.parametrize("tool", ["CronCreate", "CronDelete"])
    def test_it_matches_the_two_cron_tools(self, path: Path, tool: str) -> None:
        assert _Handler(path).matches({"tool_name": tool}) is True

    @pytest.mark.parametrize("tool", ["CronList", "Bash", "Write", ""])
    def test_it_ignores_everything_else(self, path: Path, tool: str) -> None:
        assert _Handler(path).matches({"tool_name": tool}) is False


class TestRecordingACreate:
    def test_the_created_cron_is_recorded(self, path: Path) -> None:
        result = _Handler(path).handle(_create())

        assert result.decision is Decision.ALLOW
        assert read_records(path) == [
            CronRecord(
                session_id="s1",
                cron_id="job-1",
                schedule="23 * * * *",
                prompt_hash=prompt_fingerprint(_PROMPT),
                created_at=_NOW,
            )
        ]

    def test_the_prompt_text_is_never_stored(self, path: Path) -> None:
        _Handler(path).handle(_create())
        assert "issue-sdlc skill" not in path.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "response",
        [
            {"id": "job-1"},
            {"cronId": "job-1"},
            {"jobId": "job-1"},
            "Scheduled recurring job. id: job-1 (every hour)",
        ],
    )
    def test_the_id_is_read_from_the_shapes_the_result_may_take(
        self, path: Path, response: Any
    ) -> None:
        _Handler(path).handle(_create(response))
        assert [r.cron_id for r in read_records(path)] == ["job-1"]

    def test_a_result_with_no_readable_id_records_nothing(self, path: Path) -> None:
        """The next Stop stamps the job instead; an invented id would never match."""
        result = _Handler(path).handle(_create({"unexpected": "shape"}))

        assert result.decision is Decision.ALLOW
        assert read_records(path) == []

    def test_a_one_shot_cron_is_not_recorded(self, path: Path) -> None:
        """It does not auto-expire after 7 days, so it never needs a refresh."""
        payload = _create()
        payload["tool_input"]["recurring"] = False
        _Handler(path).handle(payload)
        assert read_records(path) == []

    def test_recurring_defaults_to_true_when_omitted(self, path: Path) -> None:
        payload = _create()
        del payload["tool_input"]["recurring"]
        _Handler(path).handle(payload)
        assert len(read_records(path)) == 1

    def test_a_create_without_a_session_is_not_recorded(self, path: Path) -> None:
        _Handler(path).handle(_create(session_id=""))
        assert read_records(path) == []

    def test_a_create_without_a_prompt_or_schedule_is_not_recorded(self, path: Path) -> None:
        payload = _create()
        payload["tool_input"] = {"recurring": True}
        _Handler(path).handle(payload)
        assert read_records(path) == []


class TestForgettingADelete:
    def test_a_deleted_cron_is_forgotten(self, path: Path) -> None:
        handler = _Handler(path)
        handler.handle(_create())
        handler.handle(_delete("job-1"))
        assert read_records(path) == []

    def test_only_the_deleted_cron_is_forgotten(self, path: Path) -> None:
        handler = _Handler(path)
        handler.handle(_create({"id": "job-1"}))
        handler.handle(_create({"id": "job-2"}))
        handler.handle(_delete("job-1"))
        assert [r.cron_id for r in read_records(path)] == ["job-2"]

    def test_a_delete_with_no_id_changes_nothing(self, path: Path) -> None:
        handler = _Handler(path)
        handler.handle(_create())
        payload = _delete()
        payload["tool_input"] = {}
        handler.handle(payload)
        assert len(read_records(path)) == 1


class TestPruningDeadSessions:
    def test_a_record_older_than_the_expiry_is_pruned_by_the_next_create(self, path: Path) -> None:
        record_cron(
            path,
            CronRecord("gone", "old", "* * * * *", "h", _NOW - CRON_EXPIRY_SECONDS - 1),
            now=_NOW - CRON_EXPIRY_SECONDS - 1,
        )
        _Handler(path).handle(_create())
        assert [r.cron_id for r in read_records(path)] == ["job-1"]

    def test_a_delete_prunes_too(self, path: Path) -> None:
        record_cron(path, CronRecord("gone", "old", "* * * * *", "h", _NOW - 10), now=_NOW - 10)
        late = _NOW + CRON_EXPIRY_SECONDS
        _Handler(path, now=late).handle(_delete("nothing"))
        assert read_records(path) == []


class TestFailingOpen:
    def test_no_project_context_means_no_recording_and_no_error(self) -> None:
        result = _Handler(None).handle(_create())
        assert result.decision is Decision.ALLOW

    def test_an_unwritable_location_never_raises(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        result = _Handler(blocker / "cron-records.json").handle(_create())
        assert result.decision is Decision.ALLOW

    def test_it_never_speaks(self, path: Path) -> None:
        assert not _Handler(path).handle(_create()).context


class TestWiring:
    def test_identity(self) -> None:
        handler = CronRecordKeeperHandler()
        assert handler.handler_id == HandlerID.CRON_RECORD_KEEPER
        assert handler.priority == Priority.CRON_RECORD_KEEPER

    def test_it_is_non_terminal(self) -> None:
        assert CronRecordKeeperHandler().terminal is False

    def test_it_runs_everywhere_by_default(self) -> None:
        """Silent bookkeeping that the stop enforcers' refresh depends on."""
        assert CronRecordKeeperHandler().get_default_enabled() is True

    def test_it_has_acceptance_tests_and_no_resident_guidance(self) -> None:
        handler = CronRecordKeeperHandler()
        assert handler.get_claude_md() is None
        assert handler.get_acceptance_tests()
