"""Unit tests for the Stop-time cron enforcer (Plan 00416 Task 1.1).

``persistent_cron_assertor`` (SessionStart) can only DECLARE and instruct a
``CronList`` reconcile -- ``session_crons`` is not delivered that early. It IS
delivered to ``Stop`` (``contracts/claude-code-hooks/Stop.json``), so THIS
handler is where declared state gets VERIFIED, and the stop is blocked, naming
the exact ``CronCreate`` to run, when a declared job never got created.

Three contract constraints drive the required cases below, all pinned rather
than guessed (see the plan's DESIGN-cron-enforcement.md):

1. An ABSENT ``session_crons`` means "no information" and must never be read
   as "no crons exist" -- ALLOW, not a block.
2. ``prompt`` is delivered capped at 1000 characters with a truncation
   marker, so a declared prompt longer than that (this project's own
   ``issue-sdlc`` job) must still match its truncated delivered form.
3. A PRESENT ``session_crons`` is real information, even when empty.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.stop.cron_stop_enforcer import (
    CronStopEnforcerHandler,
)
from claude_code_hooks_daemon.utils.cron_enforcement import PROMPT_DELIVERY_CAP
from claude_code_hooks_daemon.utils.cron_pause import (
    CRON_PAUSES_FILENAME,
    PAUSE_ADVISE_INTERVAL,
    PAUSE_TTL_SECONDS,
    CronPause,
    record_pause,
    remove_pause,
)


class _RootedCronStopEnforcerHandler(CronStopEnforcerHandler):
    """Test double declaring `_workspace_root`, mirroring the SessionStart
    sibling's test double (`_RootedPersistentCronAssertorHandler`)."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._workspace_root = root


def _handler(monkeypatch: pytest.MonkeyPatch, config: Config) -> CronStopEnforcerHandler:
    handler = CronStopEnforcerHandler()
    monkeypatch.setattr(handler, "_load_config", lambda: config)
    return handler


def _config(*jobs: PersistentCronConfig, enabled: bool = True) -> Config:
    return Config(persistent_crons=PersistentCronsConfig(enabled=enabled, jobs=list(jobs)))


def _session_cron(schedule: str, prompt: str, cron_id: str = "c1") -> dict[str, Any]:
    return {"id": cron_id, "schedule": schedule, "recurring": True, "prompt": prompt}


_JOB = PersistentCronConfig(
    id="gh-issue-sdlc",
    schedule="23 * * * *",
    prompt="Invoke the issue-sdlc skill and follow it exactly.",
    description="One GitHub issue through the full SDLC",
)


def _long_prompt(length: int) -> str:
    body = "the issue-sdlc skill handles exactly one issue per tick. "
    return (body * (length // len(body) + 1))[:length]


class TestItStaysSilentWithNothingDeclared:
    def test_a_project_with_no_config_does_not_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, Config())
        assert handler.matches({}) is False

    def test_declared_jobs_with_the_section_off_do_not_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _handler(monkeypatch, _config(_JOB, enabled=False))
        assert handler.matches({}) is False

    def test_an_unreadable_config_degrades_to_silence(self, tmp_path: Path) -> None:
        handler = _RootedCronStopEnforcerHandler(tmp_path)
        assert handler.matches({}) is False


class TestAbsentSessionCronsNeverBlocks:
    """The single most important case: no information must never be read as
    'nothing exists' and used to block."""

    def test_a_missing_session_crons_field_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({})
        assert result.decision is Decision.ALLOW

    def test_an_explicit_null_session_crons_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({"session_crons": None})
        assert result.decision is Decision.ALLOW


class TestADeclaredCronPresentInSessionCronsAllows:
    def test_matching_schedule_and_prompt_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        payload = {"session_crons": [_session_cron(_JOB.schedule, _JOB.prompt)]}

        result = handler.handle(payload)

        assert result.decision is Decision.ALLOW


class TestADeclaredCronAbsentFromSessionCronsBlocks:
    def test_no_matching_entry_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        payload = {"session_crons": [_session_cron("0 9 * * 1-5", "unrelated job")]}

        result = handler.handle(payload)

        assert result.decision is Decision.DENY

    def test_the_deny_reason_names_the_schedule_and_the_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The agent must be able to act on the message alone."""
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({"session_crons": []})

        assert result.reason is not None
        assert _JOB.schedule in result.reason
        assert _JOB.prompt in result.reason
        assert _JOB.id in result.reason
        assert "CronCreate" in result.reason


class TestAPresentButEmptySessionCronsIsRealInformation:
    """A present empty list is a genuine report of 'nothing running', not the
    same fact as an absent field -- it must block exactly like any other
    verified-absent case, or the whole verification mechanism would treat its
    own explicit answer as noise."""

    def test_an_empty_list_with_a_declared_job_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        result = handler.handle({"session_crons": []})
        assert result.decision is Decision.DENY

    def test_an_empty_list_with_nothing_declared_allows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _handler(monkeypatch, Config())
        result = handler.handle({"session_crons": []})
        assert result.decision is Decision.ALLOW


class TestALongDeclaredPromptStillMatchesItsTruncatedForm:
    """The trap this handler exists to avoid: exact-equality against a
    declared prompt longer than the 1000-char delivery cap would nag on
    every single stop of every session, forever."""

    def test_a_prompt_over_the_cap_matches_its_capped_delivered_form(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        long_prompt = _long_prompt(2200)
        job = PersistentCronConfig(id="issue-sdlc", schedule="23 * * * *", prompt=long_prompt)
        handler = _handler(monkeypatch, _config(job))
        delivered = long_prompt[:PROMPT_DELIVERY_CAP] + "... [+1200 chars]"
        payload = {"session_crons": [_session_cron(job.schedule, delivered)]}

        result = handler.handle(payload)

        assert result.decision is Decision.ALLOW


class TestMultipleDeclaredJobs:
    def test_one_present_one_missing_blocks_naming_only_the_missing_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        present = _JOB
        missing = PersistentCronConfig(id="missing-job", schedule="41 * * * *", prompt="q")
        handler = _handler(monkeypatch, _config(present, missing))
        payload = {"session_crons": [_session_cron(present.schedule, present.prompt)]}

        result = handler.handle(payload)

        assert result.decision is Decision.DENY
        assert result.reason is not None
        assert "missing-job" in result.reason
        assert "gh-issue-sdlc" not in result.reason


class TestASessionPausedJobIsAcceptedVisibly:
    """Ledger 00422 N4, decision 2: a job paused for THIS session through
    ``hooks-daemon cron-pause`` may be missing, and the output says so."""

    _SESSION = "paused-session"

    def _paused_handler(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *jobs: PersistentCronConfig
    ) -> CronStopEnforcerHandler:
        handler = _handler(monkeypatch, _config(*jobs))
        monkeypatch.setattr(handler, "_pauses_path", lambda: tmp_path / CRON_PAUSES_FILENAME)
        return handler

    def _pause(self, tmp_path: Path, job_id: str, *, session_id: str = _SESSION) -> None:
        record_pause(
            tmp_path / CRON_PAUSES_FILENAME,
            CronPause(
                job_id=job_id,
                session_id=session_id,
                reason="owner asked to stop issue-sdlc for today",
                recorded_at=time.time(),
            ),
            now=time.time(),
        )

    def test_a_paused_missing_job_allows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB)
        self._pause(tmp_path, _JOB.id)

        result = handler.handle({"session_id": self._SESSION, "session_crons": []})

        assert result.decision is Decision.ALLOW

    def test_the_allow_names_the_job_the_reason_and_the_expiry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB)
        self._pause(tmp_path, _JOB.id)

        result = handler.handle({"session_id": self._SESSION, "session_crons": []})

        text = "\n".join(result.context)
        assert _JOB.id in text
        assert "owner asked to stop issue-sdlc for today" in text
        assert "expires" in text

    def test_the_pause_note_is_rate_limited_but_speaks_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Every ALLOW-with-context on Stop costs a turn, so the note speaks on
        the first stop and then periodically -- never on none of them."""
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB)
        self._pause(tmp_path, _JOB.id)
        payload = {"session_id": self._SESSION, "session_crons": []}

        results = [handler.handle(payload) for _ in range(PAUSE_ADVISE_INTERVAL + 1)]

        spoke = [bool(r.context) for r in results]
        assert spoke[0] is True
        assert spoke[1] is False
        assert spoke[PAUSE_ADVISE_INTERVAL] is True

    def test_another_sessions_pause_does_not_apply(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB)
        self._pause(tmp_path, _JOB.id, session_id="some-other-session")

        result = handler.handle({"session_id": self._SESSION, "session_crons": []})

        assert result.decision is Decision.DENY

    def test_an_expired_pause_blocks_again(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB)
        stale_at = time.time() - PAUSE_TTL_SECONDS - 60
        record_pause(
            tmp_path / CRON_PAUSES_FILENAME,
            CronPause(job_id=_JOB.id, session_id=self._SESSION, reason="r", recorded_at=stale_at),
            now=stale_at,
        )

        result = handler.handle({"session_id": self._SESSION, "session_crons": []})

        assert result.decision is Decision.DENY

    def test_a_resumed_job_blocks_again(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB)
        self._pause(tmp_path, _JOB.id)
        remove_pause(
            tmp_path / CRON_PAUSES_FILENAME,
            job_id=_JOB.id,
            session_id=self._SESSION,
            now=time.time(),
        )

        result = handler.handle({"session_id": self._SESSION, "session_crons": []})

        assert result.decision is Decision.DENY

    def test_an_unpaused_missing_job_still_blocks_and_the_pause_is_named(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        other = PersistentCronConfig(id="other-job", schedule="41 * * * *", prompt="q")
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB, other)
        self._pause(tmp_path, _JOB.id)

        result = handler.handle({"session_id": self._SESSION, "session_crons": []})

        assert result.decision is Decision.DENY
        assert result.reason is not None
        assert "other-job" in result.reason
        assert "PAUSED" in result.reason
        assert "owner asked to stop issue-sdlc for today" in result.reason

    def test_the_deny_hands_over_the_unpaused_jobs_sentinel_only(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The pause (ledger 00422 N4) and the tick sentinel (Plan 00388) came
        from separate branches: the job to re-create is given with its
        sentinel, and the paused one is named but not given to re-create."""
        other = PersistentCronConfig(id="other-job", schedule="41 * * * *", prompt="q")
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB, other)
        self._pause(tmp_path, _JOB.id)

        result = handler.handle({"session_id": self._SESSION, "session_crons": []})

        assert result.reason is not None
        assert "[tick:job:other-job]" in result.reason
        assert f"[tick:job:{_JOB.id}]" not in result.reason

    def test_a_paused_job_that_is_running_anyway_says_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        handler = self._paused_handler(monkeypatch, tmp_path, _JOB)
        self._pause(tmp_path, _JOB.id)
        payload = {
            "session_id": self._SESSION,
            "session_crons": [_session_cron(_JOB.schedule, _JOB.prompt)],
        }

        result = handler.handle(payload)

        assert result.decision is Decision.ALLOW
        assert result.context == []

    def test_no_untracked_dir_means_no_pause(self, monkeypatch: pytest.MonkeyPatch) -> None:
        handler = _handler(monkeypatch, _config(_JOB))
        monkeypatch.setattr(handler, "_pauses_path", lambda: None)

        result = handler.handle({"session_id": self._SESSION, "session_crons": []})

        assert result.decision is Decision.DENY


class TestHandlerWiring:
    def test_it_is_enabled_by_default(self) -> None:
        assert CronStopEnforcerHandler().get_default_enabled() is True

    def test_it_is_registered_below_auto_continue_stop(self) -> None:
        """Runs first (lower priority number) so it is never shadowed by
        auto_continue_stop, which is terminal and matches nearly every
        ordinary stop -- see test_stop_chain_terminal_shadowing.py."""
        assert CronStopEnforcerHandler().priority < Priority.AUTO_CONTINUE_STOP

    def test_it_is_non_terminal(self) -> None:
        """Deliberately non-terminal: this handler also matches nearly every
        ordinary stop (whenever a job is declared), so being terminal would
        make IT shadow auto_continue_stop and everything else registered
        after it. A DENY still wins the final response via
        most-restrictive-wins; dispatch simply always continues."""
        assert CronStopEnforcerHandler().terminal is False
