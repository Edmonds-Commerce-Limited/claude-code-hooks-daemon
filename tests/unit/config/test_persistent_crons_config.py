"""Unit tests for declared persistent crons (Plan 00384).

Claude Code's ``CronCreate`` is session-only — its ``durable`` parameter is
documented as having no effect, and recurring jobs auto-expire after 7 days.
So a cron a project wants to ALWAYS have cannot be created once and relied on;
it has to be re-established each session. This config is the declaration half
of that: the project states which crons it wants, and a SessionStart advisory
asserts them.

Ships inert. A client project that never declares a job must gain nothing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    Config,
    PersistentCronConfig,
    PersistentCronsConfig,
)


class TestDefaultsAreInert:
    def test_a_project_that_says_nothing_declares_no_crons(self) -> None:
        config = Config()
        assert config.persistent_crons.enabled is False
        assert config.persistent_crons.jobs == []

    def test_the_section_is_off_even_if_jobs_are_declared(self) -> None:
        """Declaring a job is not the same as switching the mechanism on, so a
        half-finished config cannot start asserting crons by accident."""
        section = PersistentCronsConfig(
            jobs=[PersistentCronConfig(id="a", schedule="7 * * * *", prompt="do a thing")]
        )
        assert section.enabled is False


class TestScheduleValidation:
    def test_a_five_field_schedule_is_accepted(self) -> None:
        job = PersistentCronConfig(id="a", schedule="23 * * * *", prompt="p")
        assert job.schedule == "23 * * * *"

    @pytest.mark.parametrize(
        "schedule",
        ["* * * *", "* * * * * *", "hourly", "", "   "],
        ids=["four-fields", "six-fields", "words", "empty", "blank"],
    )
    def test_a_schedule_that_is_not_five_fields_is_rejected(self, schedule: str) -> None:
        """A malformed schedule must fail at config load, not at 3am when the
        cron silently never fires."""
        with pytest.raises(ValidationError):
            PersistentCronConfig(id="a", schedule=schedule, prompt="p")


class TestJobIdentity:
    def test_an_empty_prompt_is_rejected(self) -> None:
        """A cron with nothing to say would fire hourly and cost a turn to
        read, which is the failure mode the failsafe cron already taught us."""
        with pytest.raises(ValidationError):
            PersistentCronConfig(id="a", schedule="7 * * * *", prompt="   ")

    def test_an_empty_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PersistentCronConfig(id="", schedule="7 * * * *", prompt="p")

    def test_duplicate_ids_are_rejected(self) -> None:
        """Two jobs sharing an id cannot both be asserted — the agent could not
        tell which one was already present."""
        with pytest.raises(ValidationError):
            PersistentCronsConfig(
                jobs=[
                    PersistentCronConfig(id="same", schedule="7 * * * *", prompt="p"),
                    PersistentCronConfig(id="same", schedule="9 * * * *", prompt="q"),
                ]
            )


class TestActiveJobs:
    def test_only_enabled_jobs_are_active(self) -> None:
        section = PersistentCronsConfig(
            enabled=True,
            jobs=[
                PersistentCronConfig(id="on", schedule="7 * * * *", prompt="p"),
                PersistentCronConfig(id="off", schedule="9 * * * *", prompt="q", enabled=False),
            ],
        )
        assert [job.id for job in section.active_jobs()] == ["on"]

    def test_nothing_is_active_while_the_section_is_off(self) -> None:
        """The section switch wins over an individual job's own enabled flag,
        so turning the mechanism off is a single, reliable action."""
        section = PersistentCronsConfig(
            jobs=[PersistentCronConfig(id="on", schedule="7 * * * *", prompt="p")]
        )
        assert section.active_jobs() == []


class TestUnknownKeysAreRejected:
    def test_a_typo_in_a_job_key_is_not_silently_ignored(self) -> None:
        """Built through ``model_validate`` rather than the constructor: the
        misspelling is the POINT of the test, and a static checker would
        rightly reject it as a call-site error otherwise."""
        with pytest.raises(ValidationError):
            PersistentCronConfig.model_validate({"id": "a", "schedual": "7 * * * *", "prompt": "p"})
