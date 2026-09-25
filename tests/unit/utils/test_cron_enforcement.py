"""Tests for the Stop/SubagentStop cron-enforcement primitives (Plan 00416).

Pure logic, deliberately free of Handler/hook-dispatch machinery, so the three
contract constraints from
``CLAUDE/Plan/00416-session-start-action-tiers-and-teeth/DESIGN-cron-enforcement.md``
can be pinned without standing up a chain:

1. ``session_crons`` is CONDITIONAL -- an absent field means "no information",
   never "no crons exist", and the two must stay distinguishable through this
   module's API (``None`` vs ``[]``).
2. ``prompt`` is capped at 1000 characters with an in-string truncation
   marker, so a declared prompt longer than that (this project's own
   ``issue-sdlc`` job) can never equal the delivered value by exact string
   comparison -- matching must normalise both sides to the cap.
3. Matching is on ``schedule`` plus the normalised ``prompt``, not on ``id``:
   the daemon declares jobs by id, but nothing guarantees the session's
   ``CronCreate`` call echoed that id back into ``session_crons``.
"""

from __future__ import annotations

from claude_code_hooks_daemon.config.models import PersistentCronConfig
from claude_code_hooks_daemon.utils.cron_enforcement import (
    PROMPT_DELIVERY_CAP,
    SessionCron,
    cron_is_asserted,
    declared_tick_prompt,
    find_missing_crons,
    parse_session_crons,
    render_missing_crons_reason,
)

_SHORT_JOB = PersistentCronConfig(
    id="short-job",
    schedule="23 * * * *",
    prompt="check the build",
)


def _long_prompt(length: int) -> str:
    """A deterministic prompt of exactly ``length`` characters."""
    body = "the issue-sdlc skill handles exactly one issue per tick. "
    return (body * (length // len(body) + 1))[:length]


class TestParseSessionCrons:
    def test_an_absent_field_parses_as_none(self) -> None:
        """None means 'no information' -- never treated as 'no crons exist'."""
        assert parse_session_crons({}) is None

    def test_an_explicit_null_parses_as_none(self) -> None:
        assert parse_session_crons({"session_crons": None}) is None

    def test_an_empty_list_parses_as_an_empty_list_not_none(self) -> None:
        """A present empty list IS information -- it must not collapse to None."""
        result = parse_session_crons({"session_crons": []})
        assert result == []
        assert result is not None

    def test_a_well_formed_entry_round_trips(self) -> None:
        payload = {
            "session_crons": [
                {"id": "cron-1", "schedule": "23 * * * *", "prompt": "hello", "recurring": True}
            ]
        }
        assert parse_session_crons(payload) == [
            SessionCron(id="cron-1", schedule="23 * * * *", prompt="hello")
        ]

    def test_a_non_list_value_parses_as_none(self) -> None:
        """A malformed payload is exactly as uninformative as an absent one."""
        assert parse_session_crons({"session_crons": "not-a-list"}) is None

    def test_a_malformed_entry_is_skipped_not_fatal(self) -> None:
        payload = {
            "session_crons": [
                {"id": "cron-1", "schedule": "23 * * * *", "prompt": "hello"},
                {"id": "cron-2"},  # missing schedule/prompt
                "not-a-dict",
            ]
        }
        assert parse_session_crons(payload) == [
            SessionCron(id="cron-1", schedule="23 * * * *", prompt="hello")
        ]


class TestCronIsAsserted:
    def test_matching_schedule_and_prompt_asserts(self) -> None:
        actual = [SessionCron(id="x", schedule="23 * * * *", prompt="check the build")]
        assert cron_is_asserted(_SHORT_JOB, actual) is True

    def test_mismatched_schedule_does_not_assert(self) -> None:
        actual = [SessionCron(id="x", schedule="0 9 * * 1-5", prompt="check the build")]
        assert cron_is_asserted(_SHORT_JOB, actual) is False

    def test_mismatched_prompt_does_not_assert(self) -> None:
        actual = [SessionCron(id="x", schedule="23 * * * *", prompt="something else entirely")]
        assert cron_is_asserted(_SHORT_JOB, actual) is False

    def test_no_entries_at_all_does_not_assert(self) -> None:
        assert cron_is_asserted(_SHORT_JOB, []) is False

    def test_a_declared_prompt_longer_than_the_cap_still_matches_its_truncated_form(
        self,
    ) -> None:
        """The trap this whole module exists to avoid.

        A declared prompt of 2200 characters is delivered as its first 1000
        characters plus a truncation marker -- exact-equality would never
        match, and would nag on every stop of every session forever.
        """
        long_prompt = _long_prompt(2200)
        declared = PersistentCronConfig(id="issue-sdlc", schedule="23 * * * *", prompt=long_prompt)
        delivered_prompt = long_prompt[:PROMPT_DELIVERY_CAP] + "... [+1200 chars]"
        actual = [SessionCron(id="c1", schedule="23 * * * *", prompt=delivered_prompt)]

        assert cron_is_asserted(declared, actual) is True

    def test_a_declared_prompt_at_exactly_the_cap_matches_with_no_marker(self) -> None:
        prompt = _long_prompt(PROMPT_DELIVERY_CAP)
        declared = PersistentCronConfig(id="at-cap", schedule="1 * * * *", prompt=prompt)
        actual = [SessionCron(id="c1", schedule="1 * * * *", prompt=prompt)]

        assert cron_is_asserted(declared, actual) is True

    def test_a_short_prompt_truncated_form_does_not_falsely_match_a_different_job(self) -> None:
        """Truncation-marker stripping must not make two DIFFERENT long jobs
        look identical just because they share the same cap-length prefix."""
        shared_prefix = _long_prompt(PROMPT_DELIVERY_CAP)
        declared = PersistentCronConfig(
            id="job-a", schedule="23 * * * *", prompt=shared_prefix + " tail A " * 50
        )
        other_delivered = shared_prefix + "... [+999 chars]"
        # Different job's actual entry happens to share the identical schedule
        # and truncated prefix, but declared's prefix (recomputed) still must
        # match it -- this asserts the prefix-comparison itself is exercised
        # correctly, not that it rejects a same-prefix match.
        actual = [SessionCron(id="c1", schedule="23 * * * *", prompt=other_delivered)]
        assert cron_is_asserted(declared, actual) is True


class TestAnEmptyPrefixAssertsNothing:
    """Plan 00436, from ledger 00422 N5 row (g).

    Prefix matching is deliberately restricted to deliveries that were really
    truncated, because every prompt starts with every prefix of itself. The
    EMPTY prefix escapes that restriction: a delivered prompt of nothing but a
    marker is correctly identified as truncated, and then every declaration on
    the schedule starts with it.

    This fails in the ALLOW direction, which is the expensive one — a cron that
    was never created gets reported as live, and the session runs with no
    recovery net and nothing saying so.
    """

    def test_a_marker_only_prompt_does_not_assert_a_declared_job(self) -> None:
        actual = [SessionCron(id="c1", schedule="23 * * * *", prompt="... [+1200 chars]")]
        assert cron_is_asserted(_SHORT_JOB, actual) is False

    def test_a_unicode_marker_only_prompt_does_not_assert_either(self) -> None:
        actual = [SessionCron(id="c1", schedule="23 * * * *", prompt="… [+1200 chars]")]
        assert cron_is_asserted(_SHORT_JOB, actual) is False

    def test_whitespace_around_the_marker_does_not_rescue_it(self) -> None:
        actual = [SessionCron(id="c1", schedule="23 * * * *", prompt="  \n... [+9 chars]  \n")]
        assert cron_is_asserted(_SHORT_JOB, actual) is False

    def test_a_marker_only_prompt_does_not_assert_a_LONG_declared_job(self) -> None:
        """The over-cap job is the one this module exists for; it is not exempt."""
        declared = PersistentCronConfig(
            id="issue-sdlc", schedule="23 * * * *", prompt=_long_prompt(2200)
        )
        actual = [SessionCron(id="c1", schedule="23 * * * *", prompt="... [+2200 chars]")]
        assert cron_is_asserted(declared, actual) is False

    def test_a_real_truncated_delivery_still_asserts(self) -> None:
        """Control: the fix must not narrow the case the module was built for.

        Without this, returning False unconditionally would pass every test
        above.
        """
        long_prompt = _long_prompt(2200)
        declared = PersistentCronConfig(id="issue-sdlc", schedule="23 * * * *", prompt=long_prompt)
        delivered = long_prompt[:PROMPT_DELIVERY_CAP] + "... [+1200 chars]"
        actual = [SessionCron(id="c1", schedule="23 * * * *", prompt=delivered)]

        assert cron_is_asserted(declared, actual) is True


class TestFindMissingCrons:
    def test_no_declared_jobs_reports_nothing_missing(self) -> None:
        assert find_missing_crons([], []) == []

    def test_a_present_job_is_not_reported_missing(self) -> None:
        actual = [SessionCron(id="x", schedule="23 * * * *", prompt="check the build")]
        assert find_missing_crons([_SHORT_JOB], actual) == []

    def test_an_absent_job_is_reported_missing(self) -> None:
        assert find_missing_crons([_SHORT_JOB], []) == [_SHORT_JOB]

    def test_one_present_one_missing_reports_only_the_missing_one(self) -> None:
        present = _SHORT_JOB
        missing = PersistentCronConfig(id="missing-job", schedule="41 * * * *", prompt="q")
        actual = [SessionCron(id="x", schedule="23 * * * *", prompt="check the build")]

        assert find_missing_crons([present, missing], actual) == [missing]


class TestRenderMissingCronsReason:
    def test_it_names_the_schedule_and_the_prompt(self) -> None:
        reason = render_missing_crons_reason([_SHORT_JOB])
        assert "23 * * * *" in reason
        assert "check the build" in reason

    def test_it_names_the_job_id(self) -> None:
        reason = render_missing_crons_reason([_SHORT_JOB])
        assert "short-job" in reason

    def test_it_instructs_crun_create(self) -> None:
        reason = render_missing_crons_reason([_SHORT_JOB])
        assert "CronCreate" in reason

    def test_multiple_missing_jobs_are_all_named(self) -> None:
        second = PersistentCronConfig(id="second-job", schedule="41 * * * *", prompt="q")
        reason = render_missing_crons_reason([_SHORT_JOB, second])
        assert "short-job" in reason
        assert "second-job" in reason


class TestDeclaredJobsCarryTheTickSentinel:
    """Plan 00388 option 2'. A declared job's prompt is handed to the agent by
    the daemon, so the daemon adds the sentinel that lets the blockage
    suppressor tell the job's tick from the owner. Matching must accept the
    job with or without it, so a cron created before the sentinel existed is
    not reported missing -- which would block every stop in a live session."""

    def test_the_rendered_prompt_leads_with_the_job_sentinel(self) -> None:
        assert declared_tick_prompt(_SHORT_JOB) == "[tick:job:short-job]\ncheck the build"

    def test_a_prompt_already_carrying_a_sentinel_is_rendered_unchanged(self) -> None:
        """A declared failsafe job pastes the canonical prompt, which already
        says [tick:failsafe]; it must not gain a second identity."""
        job = PersistentCronConfig(
            id="failsafe-recovery", schedule="47 * * * *", prompt="[tick:failsafe]\nrecover"
        )
        assert declared_tick_prompt(job) == "[tick:failsafe]\nrecover"

    def test_a_cron_created_with_the_sentinel_is_asserted(self) -> None:
        actual = [SessionCron("c1", "23 * * * *", declared_tick_prompt(_SHORT_JOB))]
        assert cron_is_asserted(_SHORT_JOB, actual)

    def test_a_cron_created_before_the_sentinel_is_still_asserted(self) -> None:
        actual = [SessionCron("c1", "23 * * * *", "check the build")]
        assert cron_is_asserted(_SHORT_JOB, actual)

    def test_the_sentinel_alone_does_not_make_a_different_job_match(self) -> None:
        actual = [SessionCron("c1", "23 * * * *", "[tick:job:short-job]\nsomething else")]
        assert not cron_is_asserted(_SHORT_JOB, actual)

    def test_a_truncated_delivery_with_the_sentinel_still_matches(self) -> None:
        job = PersistentCronConfig(id="long", schedule="23 * * * *", prompt=_long_prompt(1200))
        delivered = declared_tick_prompt(job)[:PROMPT_DELIVERY_CAP] + "… [+217 chars]"
        assert cron_is_asserted(job, [SessionCron("c1", "23 * * * *", delivered)])

    def test_the_stop_block_names_the_prompt_with_its_sentinel(self) -> None:
        """The block message is the other place an agent copies the prompt
        from, so it must hand over the same text the SessionStart advisory
        does."""
        reason = render_missing_crons_reason([_SHORT_JOB])
        assert "[tick:job:short-job]" in reason
