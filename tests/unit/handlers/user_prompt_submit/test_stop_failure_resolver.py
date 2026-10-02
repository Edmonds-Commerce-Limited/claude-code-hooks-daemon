"""StopFailureResolverHandler: a later prompt resolves the session's failure (Plan 00470 Task 3.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.user_prompt_submit.stop_failure_resolver import (
    StopFailureResolverHandler,
)
from claude_code_hooks_daemon.utils.stop_failure_records import (
    StopFailureRecord,
    latest_unresolved,
    read_records,
    record_failure,
)

_NOW = 4_000_000.0


class _Handler(StopFailureResolverHandler):
    """The handler with a fixed clock and a record file under ``tmp_path``."""

    def __init__(self, path: Path | None) -> None:
        super().__init__()
        self.path = path

    def _records_path(self) -> Path | None:
        return self.path

    def _now(self) -> float:
        return _NOW


def _prompt(session_id: str = "s1") -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "session_id": session_id, "prompt": "go on"}


def _failure(session_id: str = "s1") -> StopFailureRecord:
    return StopFailureRecord(session_id=session_id, error="rate_limit", recorded_at=_NOW - 100)


class TestIdentity:
    def test_it_is_wired_to_the_constants(self) -> None:
        handler = StopFailureResolverHandler()
        assert handler.name == HandlerID.STOP_FAILURE_RESOLVER.display_name
        assert handler.priority == Priority.STOP_FAILURE_RESOLVER
        assert handler.config_key == "stop_failure_resolver"

    def test_it_is_not_terminal(self) -> None:
        assert StopFailureResolverHandler().terminal is False


class TestHandling:
    def test_a_prompt_resolves_the_sessions_failure(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _failure())
        _Handler(path).handle(_prompt())
        assert latest_unresolved(path, "s1") is None
        assert read_records(path)[0].resolved_at == _NOW

    def test_another_sessions_prompt_leaves_it_alone(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _failure())
        _Handler(path).handle(_prompt("other"))
        assert latest_unresolved(path, "s1") is not None

    def test_the_prompt_is_always_allowed_and_silent(self, tmp_path: Path) -> None:
        result = _Handler(tmp_path / "stop-failures.json").handle(_prompt())
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_no_file_means_nothing_is_written(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        _Handler(path).handle(_prompt())
        assert not path.exists()

    def test_no_session_id_does_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "stop-failures.json"
        record_failure(path, _failure())
        _Handler(path).handle(_prompt(""))
        assert latest_unresolved(path, "s1") is not None

    def test_no_project_context_does_not_raise(self) -> None:
        assert _Handler(None).handle(_prompt()).decision == Decision.ALLOW


class TestDocumentation:
    def test_it_is_silent_so_it_ships_no_resident_guidance(self) -> None:
        assert StopFailureResolverHandler().get_claude_md() is None

    def test_it_declares_an_acceptance_test(self) -> None:
        assert StopFailureResolverHandler().get_acceptance_tests()
