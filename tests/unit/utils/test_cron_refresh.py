"""Refreshing a declared cron before the 7-day expiry kills it (Plan 00470 Task 2.2).

The Stop enforcers cannot read a job's age from ``session_crons``; they read it
from ``cron_records``. A job past ``refresh_after`` is denied a stop with the
exact ``CronDelete`` + ``CronCreate`` to run; a job with no record is stamped,
never denied.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import PersistentCronConfig
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.utils.cron_pause import CronPause, record_pause
from claude_code_hooks_daemon.utils.cron_records import (
    CRON_EXPIRY_SECONDS,
    DEFAULT_REFRESH_AFTER_DAYS,
    SECONDS_PER_DAY,
    CronRecord,
    prompt_fingerprint,
    read_records,
    record_cron,
)
from claude_code_hooks_daemon.utils.cron_refresh import judge_declared_crons

_NOW = 5_000_000.0
_REFRESH = 6 * SECONDS_PER_DAY
_JOB = PersistentCronConfig(
    id="issue-sdlc",
    schedule="23 * * * *",
    prompt="Invoke the issue-sdlc skill and follow it exactly.",
    description="One GitHub issue through the SDLC",
)
_OTHER_JOB = PersistentCronConfig(id="watchdog", schedule="47 * * * *", prompt="Watch the daemon.")


def _session_cron(job: PersistentCronConfig, cron_id: str) -> dict[str, Any]:
    return {"id": cron_id, "schedule": job.schedule, "recurring": True, "prompt": job.prompt}


def _stop(*crons: dict[str, Any], session_id: str = "s1", **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "Stop",
        "session_id": session_id,
        "session_crons": list(crons),
        **extra,
    }


def _born(
    job: PersistentCronConfig, cron_id: str, age: float, session_id: str = "s1"
) -> CronRecord:
    return CronRecord(
        session_id=session_id,
        cron_id=cron_id,
        schedule=job.schedule,
        prompt_hash=prompt_fingerprint(job.prompt),
        created_at=_NOW - age,
    )


def _judge(
    jobs: list[PersistentCronConfig],
    hook_input: dict[str, Any],
    records_path: Path | None,
    *,
    refresh_after: float = _REFRESH,
    pauses_path: Path | None = None,
    now: float = _NOW,
) -> Any:
    return judge_declared_crons(
        jobs,
        hook_input,
        pauses_path=pauses_path,
        records_path=records_path,
        should_advise=lambda _key: True,
        refresh_after_seconds=refresh_after,
        now=now,
    )


@pytest.fixture
def records(tmp_path: Path) -> Path:
    return tmp_path / "cron-records.json"


class TestTheAgeBoundary:
    def test_a_job_just_inside_refresh_after_is_allowed(self, records: Path) -> None:
        record_cron(records, _born(_JOB, "c1", _REFRESH - 1), now=_NOW)
        assert _judge([_JOB], _stop(_session_cron(_JOB, "c1")), records).decision is Decision.ALLOW

    def test_a_job_exactly_refresh_after_old_is_denied(self, records: Path) -> None:
        record_cron(records, _born(_JOB, "c1", _REFRESH), now=_NOW)
        assert _judge([_JOB], _stop(_session_cron(_JOB, "c1")), records).decision is Decision.DENY

    def test_a_job_well_past_refresh_after_is_denied(self, records: Path) -> None:
        record_cron(records, _born(_JOB, "c1", _REFRESH + SECONDS_PER_DAY / 2), now=_NOW)
        assert _judge([_JOB], _stop(_session_cron(_JOB, "c1")), records).decision is Decision.DENY

    def test_the_default_is_below_the_expiry_with_a_day_to_act_in(self) -> None:
        assert DEFAULT_REFRESH_AFTER_DAYS * SECONDS_PER_DAY <= CRON_EXPIRY_SECONDS - SECONDS_PER_DAY

    def test_a_shorter_refresh_after_catches_a_younger_job(self, records: Path) -> None:
        record_cron(records, _born(_JOB, "c1", 2 * SECONDS_PER_DAY), now=_NOW)
        verdict = _judge(
            [_JOB], _stop(_session_cron(_JOB, "c1")), records, refresh_after=SECONDS_PER_DAY
        )
        assert verdict.decision is Decision.DENY


class TestTheDenyNamesTheRefresh:
    @pytest.fixture
    def reason(self, records: Path) -> str:
        record_cron(records, _born(_JOB, "cron-abc", _REFRESH + 3600), now=_NOW)
        verdict = _judge([_JOB], _stop(_session_cron(_JOB, "cron-abc")), records)
        assert verdict.reason is not None
        return verdict.reason

    def test_it_names_the_cron_delete_with_the_id(self, reason: str) -> None:
        assert "CronDelete" in reason
        assert "cron-abc" in reason

    def test_it_names_the_cron_create_with_the_schedule_and_prompt(self, reason: str) -> None:
        assert "CronCreate" in reason
        assert _JOB.schedule in reason
        assert "Invoke the issue-sdlc skill" in reason

    def test_it_says_why(self, reason: str) -> None:
        assert "expire" in reason.lower()

    def test_it_says_how_old_the_job_is(self, reason: str) -> None:
        assert "6" in reason

    def test_every_stale_job_is_named_and_a_fresh_one_is_not(self, records: Path) -> None:
        record_cron(records, _born(_JOB, "old-1", _REFRESH + 1), now=_NOW)
        record_cron(records, _born(_OTHER_JOB, "fresh-2", 60), now=_NOW)
        verdict = _judge(
            [_JOB, _OTHER_JOB],
            _stop(_session_cron(_JOB, "old-1"), _session_cron(_OTHER_JOB, "fresh-2")),
            records,
        )
        assert verdict.reason is not None
        assert "old-1" in verdict.reason
        assert "fresh-2" not in verdict.reason


class TestAnUnknownAgeIsStampedNeverBlocked:
    def test_a_job_with_no_record_is_allowed(self, records: Path) -> None:
        assert _judge([_JOB], _stop(_session_cron(_JOB, "c1")), records).decision is Decision.ALLOW

    def test_and_a_record_is_created_now(self, records: Path) -> None:
        _judge([_JOB], _stop(_session_cron(_JOB, "c1")), records)
        assert [(r.session_id, r.cron_id, r.created_at) for r in read_records(records)] == [
            ("s1", "c1", _NOW)
        ]

    def test_the_stamp_starts_the_clock(self, records: Path) -> None:
        stop = _stop(_session_cron(_JOB, "c1"))
        _judge([_JOB], stop, records)
        assert _judge([_JOB], stop, records, now=_NOW + _REFRESH - 1).decision is Decision.ALLOW
        assert _judge([_JOB], stop, records, now=_NOW + _REFRESH).decision is Decision.DENY

    def test_another_sessions_record_does_not_age_this_session(self, records: Path) -> None:
        record_cron(records, _born(_JOB, "c1", _REFRESH + 100, session_id="other"), now=_NOW)
        assert _judge([_JOB], _stop(_session_cron(_JOB, "c1")), records).decision is Decision.ALLOW

    def test_a_lost_record_file_is_restamped_not_blocked(self, records: Path) -> None:
        records.write_text("{garbage", encoding="utf-8")
        assert _judge([_JOB], _stop(_session_cron(_JOB, "c1")), records).decision is Decision.ALLOW


class TestOnlyLiveCronsAreAged:
    def test_a_record_for_a_cron_the_session_no_longer_lists_is_forgotten(
        self, records: Path
    ) -> None:
        record_cron(records, _born(_JOB, "deleted", _REFRESH + 100), now=_NOW)
        verdict = _judge([_JOB], _stop(_session_cron(_JOB, "replacement")), records)

        assert verdict.decision is Decision.ALLOW
        assert [r.cron_id for r in read_records(records)] == ["replacement"]

    def test_a_refreshed_job_is_allowed(self, records: Path) -> None:
        """After CronDelete + CronCreate the old record is gone and the new one is young."""
        record_cron(records, _born(_JOB, "new", 30), now=_NOW)
        assert _judge([_JOB], _stop(_session_cron(_JOB, "new")), records).decision is Decision.ALLOW

    def test_a_duplicate_older_than_a_fresh_copy_does_not_deny(self, records: Path) -> None:
        record_cron(records, _born(_JOB, "old", _REFRESH + 100), now=_NOW)
        record_cron(records, _born(_JOB, "new", 30), now=_NOW)
        stop = _stop(_session_cron(_JOB, "old"), _session_cron(_JOB, "new"))
        assert _judge([_JOB], stop, records).decision is Decision.ALLOW


class TestWhatIsNeverJudged:
    def test_an_absent_session_crons_allows(self, records: Path) -> None:
        assert _judge([_JOB], {"session_id": "s1"}, records).decision is Decision.ALLOW

    def test_no_session_id_allows_and_writes_nothing(self, records: Path) -> None:
        stop = _stop(_session_cron(_JOB, "c1"), session_id="")
        assert _judge([_JOB], stop, records).decision is Decision.ALLOW
        assert not records.exists()

    def test_no_record_location_allows(self) -> None:
        assert _judge([_JOB], _stop(_session_cron(_JOB, "c1")), None).decision is Decision.ALLOW

    def test_a_missing_job_still_denies_as_before(self, records: Path) -> None:
        verdict = _judge([_JOB], _stop(), records)
        assert verdict.decision is Decision.DENY
        assert verdict.reason is not None and "MISSING" in verdict.reason

    def test_a_re_entered_stop_is_allowed_and_logged(
        self, records: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        record_cron(records, _born(_JOB, "c1", _REFRESH + 1), now=_NOW)
        stop = _stop(_session_cron(_JOB, "c1"), stop_hook_active=True)
        with caplog.at_level(logging.WARNING):
            verdict = _judge([_JOB], stop, records)
        assert verdict.decision is Decision.ALLOW
        assert "issue-sdlc" in caplog.text


class TestACronPausedForThisSessionIsNotRefreshed:
    def test_a_stale_paused_job_is_allowed(self, records: Path, tmp_path: Path) -> None:
        pauses = tmp_path / "cron-pauses.json"
        record_pause(pauses, CronPause("issue-sdlc", "s1", "owner said stop", _NOW - 60), now=_NOW)
        record_cron(records, _born(_JOB, "c1", _REFRESH + 100), now=_NOW)

        verdict = _judge([_JOB], _stop(_session_cron(_JOB, "c1")), records, pauses_path=pauses)

        assert verdict.decision is Decision.ALLOW

    def test_another_job_stale_beside_a_paused_one_still_denies(
        self, records: Path, tmp_path: Path
    ) -> None:
        pauses = tmp_path / "cron-pauses.json"
        record_pause(pauses, CronPause("issue-sdlc", "s1", "owner said stop", _NOW - 60), now=_NOW)
        record_cron(records, _born(_JOB, "c1", _REFRESH + 100), now=_NOW)
        record_cron(records, _born(_OTHER_JOB, "c2", _REFRESH + 100), now=_NOW)

        verdict = _judge(
            [_JOB, _OTHER_JOB],
            _stop(_session_cron(_JOB, "c1"), _session_cron(_OTHER_JOB, "c2")),
            records,
            pauses_path=pauses,
        )

        assert verdict.decision is Decision.DENY
        assert verdict.reason is not None
        assert "c2" in verdict.reason and "c1" not in verdict.reason
