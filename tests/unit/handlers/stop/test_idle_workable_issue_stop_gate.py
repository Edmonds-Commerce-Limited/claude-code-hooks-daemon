"""Tests for the idle-stop gate (Plan 00470 Phase 7 Task 7.1).

Incident: having closed an issue, the issue-sdlc coordinator stopped with "the
next issue is for the hourly tick" while workable issues existed and nothing was
in flight. The Stop hook accepted it on the ``STOPPING BECAUSE:`` prefix alone.
This gate refuses that stop on FACTS: the declared job, the work queue and the
workable-issues cache. It never calls GitHub.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler_scope import HandlerScope
from claude_code_hooks_daemon.handlers.stop.idle_workable_issue_stop_gate import (
    IdleWorkableIssueStopGateHandler,
)
from claude_code_hooks_daemon.utils.blockage_marker import MARKER_FILENAME, write_marker
from claude_code_hooks_daemon.utils.session_thread_group import OtherHolder
from claude_code_hooks_daemon.utils.work_queue import (
    WORK_QUEUE_FILENAME,
    add_record,
    update_record,
)
from claude_code_hooks_daemon.utils.workable_issues import (
    WORKABLE_ISSUES_FILENAME,
    write_workable,
)

NOW = 1_000_000.0
SESSION = "sess-1"
_JOB = PersistentCronConfig(
    id="issue-sdlc", schedule="23 * * * *", prompt="Invoke the issue-sdlc skill."
)


def _config(*jobs: PersistentCronConfig, enabled: bool = True) -> Config:
    return Config(persistent_crons=PersistentCronsConfig(enabled=enabled, jobs=list(jobs)))


class _Rooted(IdleWorkableIssueStopGateHandler):
    """The real handler rooted at a directory, as the cron enforcers' tests do."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._workspace_root = root


class _Handler(IdleWorkableIssueStopGateHandler):
    """The real handler with its four environment seams fixed."""

    def __init__(
        self,
        state: Path | None,
        config: Config,
        holder: OtherHolder | None = None,
    ) -> None:
        super().__init__()
        self._state = state
        self._config = config
        self._holder = holder
        self._clock = lambda: NOW

    def _load_config(self) -> Config:
        return self._config

    def _untracked_dir(self) -> Path | None:
        return self._state

    def _exempt_holder(self, *_args: Any, **_kwargs: Any) -> OtherHolder | None:
        return self._holder


def _handler(
    state: Path | None,
    config: Config | None = None,
    *,
    holder: OtherHolder | None = None,
    **options: Any,
) -> _Handler:
    handler = _Handler(state, config if config is not None else _config(_JOB), holder)
    for name, value in options.items():
        setattr(handler, f"_{name}", value)
    return handler


def _stop(**extra: Any) -> dict[str, Any]:
    return {"hook_event_name": "Stop", "session_id": SESSION, "stop_hook_active": False, **extra}


def _transcript(tmp_path: Path, text: str) -> str:
    path = tmp_path / "transcript.jsonl"
    message = {
        "type": "message",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    path.write_text(json.dumps(message) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def state(tmp_path: Path) -> Path:
    directory = tmp_path / "state"
    directory.mkdir()
    return directory


def _cache(state: Path, numbers: list[int], *, age: float = 60.0) -> None:
    write_workable(state / WORKABLE_ISSUES_FILENAME, numbers, now=NOW - age)


def _queue_entry(state: Path, name: str = "p470") -> None:
    add_record(
        state / WORK_QUEUE_FILENAME,
        name,
        worktree="/w",
        branch="b",
        brief="x",
        brief_file=None,
        last_sha="s",
        now=1.0,
    )


def _judge(handler: IdleWorkableIssueStopGateHandler, hook_input: dict[str, Any]) -> Decision:
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestItDeniesAnIdleStopWithWorkableIssues:
    def test_it_denies_naming_the_first_issue_and_the_rule(self, state: Path) -> None:
        _cache(state, [118, 120])
        handler = _handler(state)
        assert handler.matches(_stop()) is True
        result = handler.handle(_stop())
        assert result.decision is Decision.DENY
        assert result.rule == RuleID.STOP_IDLE_WITH_WORKABLE_ISSUE
        reason = result.reason or ""
        assert "#118" in reason
        assert "safety net" in reason
        assert "not a scheduler" in reason

    def test_the_deny_offers_a_way_out_so_nothing_is_a_trap(self, state: Path) -> None:
        _cache(state, [5])
        reason = _handler(state).handle(_stop()).reason or ""
        assert "blocker" in reason

    def test_a_queue_with_only_finished_entries_does_not_count_as_in_flight(
        self, state: Path
    ) -> None:
        _cache(state, [5])
        _queue_entry(state, "a")
        update_record(state / WORK_QUEUE_FILENAME, "a", now=2.0, last_sha=None, status="done")
        assert _judge(_handler(state), _stop()) is Decision.DENY

    def test_it_is_non_terminal_main_scoped_and_runs_before_auto_continue(self) -> None:
        handler = IdleWorkableIssueStopGateHandler()
        assert handler.terminal is False
        assert handler.scope is HandlerScope.MAIN
        assert handler.priority == Priority.IDLE_WORKABLE_ISSUE_STOP_GATE < 10
        assert handler.handler_id is HandlerID.IDLE_WORKABLE_ISSUE_STOP_GATE
        assert handler.get_default_enabled() is True


class TestItStandsAside:
    def test_when_nothing_is_declared(self, state: Path) -> None:
        _cache(state, [5])
        assert _judge(_handler(state, _config()), _stop()) is Decision.ALLOW

    def test_when_the_cron_section_is_off(self, state: Path) -> None:
        _cache(state, [5])
        assert _judge(_handler(state, _config(_JOB, enabled=False)), _stop()) is Decision.ALLOW

    def test_when_only_other_jobs_are_declared(self, state: Path) -> None:
        _cache(state, [5])
        other = PersistentCronConfig(id="watchdog", schedule="5 * * * *", prompt="p")
        assert _judge(_handler(state, _config(other)), _stop()) is Decision.ALLOW

    def test_the_job_id_is_an_option(self, state: Path) -> None:
        _cache(state, [5])
        other = PersistentCronConfig(id="my-loop", schedule="5 * * * *", prompt="p")
        handler = _handler(state, _config(other), job_id="my-loop")
        assert _judge(handler, _stop()) is Decision.DENY

    def test_when_the_job_is_declared_for_another_host(
        self, state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _cache(state, [5])
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "somewhere-else")
        hosted = PersistentCronConfig(
            id="issue-sdlc", schedule="23 * * * *", prompt="p", hosts=["the-unattended-host"]
        )
        assert _judge(_handler(state, _config(hosted)), _stop()) is Decision.ALLOW

    def test_a_non_holder_thread_task_6_4(self, state: Path) -> None:
        _cache(state, [5])
        handler = _handler(state, holder=OtherHolder(session_id="holder"))
        assert _judge(handler, _stop()) is Decision.ALLOW

    def test_while_a_usage_pause_is_live(
        self, state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _cache(state, [5])
        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.stop.idle_workable_issue_stop_gate."
            "hook_is_usage_paused",
            lambda _hook_input: True,
        )
        assert _judge(_handler(state), _stop()) is Decision.ALLOW

    def test_when_work_is_in_flight(self, state: Path) -> None:
        _cache(state, [5])
        _queue_entry(state)
        assert _judge(_handler(state), _stop()) is Decision.ALLOW

    def test_when_the_work_queue_cannot_be_read(self, state: Path) -> None:
        _cache(state, [5])
        (state / WORK_QUEUE_FILENAME).write_text("{not json", encoding="utf-8")
        assert _judge(_handler(state), _stop()) is Decision.ALLOW

    def test_when_there_is_no_cache(self, state: Path) -> None:
        assert _judge(_handler(state), _stop()) is Decision.ALLOW

    def test_when_the_cache_is_stale(self, state: Path) -> None:
        _cache(state, [5], age=3 * 3600)
        assert _judge(_handler(state), _stop()) is Decision.ALLOW

    def test_the_cache_age_limit_is_an_option(self, state: Path) -> None:
        _cache(state, [5], age=3 * 3600)
        handler = _handler(state, max_cache_age_hours=4.0)
        assert _judge(handler, _stop()) is Decision.DENY

    def test_when_the_cache_lists_nothing(self, state: Path) -> None:
        _cache(state, [])
        assert _judge(_handler(state), _stop()) is Decision.ALLOW

    def test_when_the_stop_is_a_re_entry_so_the_session_is_never_trapped(self, state: Path) -> None:
        _cache(state, [5])
        assert _judge(_handler(state), _stop(stop_hook_active=True)) is Decision.ALLOW

    def test_when_the_camel_case_re_entry_flag_is_set(self, state: Path) -> None:
        _cache(state, [5])
        hook_input = {"hook_event_name": "Stop", "session_id": SESSION, "stopHookActive": True}
        assert _judge(_handler(state), hook_input) is Decision.ALLOW

    def test_when_there_is_no_project_state_directory(self) -> None:
        assert _judge(_handler(None), _stop()) is Decision.ALLOW


class TestTheAwaitingHumanDeclaration:
    def test_a_live_marker_for_this_session(self, state: Path) -> None:
        _cache(state, [5])
        write_marker(state / MARKER_FILENAME, SESSION, now=NOW - 60)
        assert _judge(_handler(state), _stop()) is Decision.ALLOW

    def test_a_marker_for_another_session_does_not_count(self, state: Path) -> None:
        _cache(state, [5])
        write_marker(state / MARKER_FILENAME, "other", now=NOW - 60)
        assert _judge(_handler(state), _stop()) is Decision.DENY

    def test_an_expired_marker_does_not_count(self, state: Path) -> None:
        _cache(state, [5])
        write_marker(state / MARKER_FILENAME, SESSION, now=NOW - 48 * 3600)
        assert _judge(_handler(state), _stop()) is Decision.DENY

    def test_this_very_stop_declaring_it_counts_before_the_marker_is_written(
        self, state: Path, tmp_path: Path
    ) -> None:
        """auto_continue_stop writes the marker AFTER this handler runs."""
        _cache(state, [5])
        path = _transcript(
            tmp_path, "STOPPING BECAUSE: [awaiting-human] the owner must choose A or B."
        )
        assert _judge(_handler(state), _stop(transcript_path=path)) is Decision.ALLOW

    def test_an_ordinary_stopping_because_does_not_count(self, state: Path, tmp_path: Path) -> None:
        _cache(state, [5])
        path = _transcript(tmp_path, "STOPPING BECAUSE: the next issue is for the hourly tick.")
        assert _judge(_handler(state), _stop(transcript_path=path)) is Decision.DENY

    def test_an_unreadable_transcript_does_not_count(self, state: Path) -> None:
        _cache(state, [5])
        hook_input = _stop(transcript_path="/nonexistent/transcript.jsonl")
        assert _judge(_handler(state), hook_input) is Decision.DENY


class TestNoNetwork:
    def test_the_handler_never_runs_a_subprocess(
        self, state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def forbidden(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("the Stop hook must not run a subprocess")

        monkeypatch.setattr(subprocess, "run", forbidden)
        monkeypatch.setattr(subprocess, "Popen", forbidden)
        _cache(state, [5])
        assert _judge(_handler(state), _stop()) is Decision.DENY


class TestRealSeams:
    """The production seams: config file, project context, wall clock."""

    def test_an_unloadable_config_degrades_to_silence(self, tmp_path: Path) -> None:
        assert _Rooted(tmp_path).matches(_stop()) is False  # no .claude/hooks-daemon.yaml here

    def test_no_project_context_means_no_state_directory(self) -> None:
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        ProjectContext.reset()
        assert IdleWorkableIssueStopGateHandler()._untracked_dir() is None

    def test_the_state_directory_comes_from_the_project_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.is_initialized",
            lambda: True,
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.daemon_untracked_dir",
            lambda: tmp_path,
        )
        assert IdleWorkableIssueStopGateHandler()._untracked_dir() == tmp_path


class TestDocumentation:
    def test_the_rule_is_filed_and_the_guidance_names_it(self) -> None:
        handler = IdleWorkableIssueStopGateHandler()
        (rule,) = handler.get_rules()
        assert rule.rule_id == RuleID.STOP_IDLE_WITH_WORKABLE_ISSUE
        guidance = handler.get_claude_md() or ""
        assert "safety net" in guidance
        assert "idle_workable_issue_stop_gate" in guidance

    def test_it_declares_acceptance_tests(self) -> None:
        assert IdleWorkableIssueStopGateHandler().get_acceptance_tests()
