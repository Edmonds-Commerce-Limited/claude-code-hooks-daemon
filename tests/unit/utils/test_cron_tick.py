"""Tests for the daemon-authored cron tick sentinel (Plan 00388, option 2').

Claude Code gives ``UserPromptSubmit`` no automated-versus-human flag, so the
only way the daemon can tell a cron tick from its owner is text it wrote into
the tick's prompt itself. Every cron prompt the daemon supplies carries one
sentinel line; everything else reads as the human.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.cron_tick import (
    TICK_SENTINEL_PREFIX,
    DaemonTick,
    TickKind,
    classify_tick,
    is_daemon_tick,
    strip_tick_sentinels,
    tick_sentinel,
    with_tick_sentinel,
)


class TestTheSentinelSpelling:
    def test_the_failsafe_sentinel(self) -> None:
        assert tick_sentinel(TickKind.FAILSAFE) == "[tick:failsafe]"

    def test_the_watchdog_sentinel(self) -> None:
        assert tick_sentinel(TickKind.WATCHDOG) == "[tick:watchdog]"

    def test_a_declared_job_names_its_id(self) -> None:
        assert tick_sentinel(TickKind.DECLARED, "issue-sdlc") == "[tick:job:issue-sdlc]"

    def test_every_sentinel_starts_with_the_shared_prefix(self) -> None:
        for sentinel in (
            tick_sentinel(TickKind.FAILSAFE),
            tick_sentinel(TickKind.WATCHDOG),
            tick_sentinel(TickKind.DECLARED, "x"),
        ):
            assert sentinel.startswith(TICK_SENTINEL_PREFIX)

    def test_a_declared_sentinel_needs_an_id(self) -> None:
        with pytest.raises(ValueError, match="job id"):
            tick_sentinel(TickKind.DECLARED)

    def test_a_fixed_kind_takes_no_id(self) -> None:
        with pytest.raises(ValueError, match="job id"):
            tick_sentinel(TickKind.WATCHDOG, "issue-sdlc")


class TestClassification:
    def test_a_human_sentence_is_not_a_tick(self) -> None:
        assert classify_tick("please fix the failing test") is None

    def test_a_non_string_is_not_a_tick(self) -> None:
        assert classify_tick(None) is None
        assert classify_tick(123) is None

    def test_the_failsafe_sentinel_classifies_as_failsafe(self) -> None:
        assert classify_tick("[tick:failsafe]\nbody") == DaemonTick(TickKind.FAILSAFE)

    def test_the_watchdog_sentinel_classifies_as_watchdog(self) -> None:
        assert classify_tick("[tick:watchdog]\nbody") == DaemonTick(TickKind.WATCHDOG)

    def test_a_declared_sentinel_carries_the_job_id(self) -> None:
        assert classify_tick("[tick:job:issue-sdlc]\nbody") == DaemonTick(
            TickKind.DECLARED, "issue-sdlc"
        )

    def test_a_sentinel_survives_being_reflowed_onto_the_first_line(self) -> None:
        """An agent retyping the prompt may join the sentinel to the heading;
        a substring test keeps working where a first-line test would not."""
        assert is_daemon_tick("**HEADING** [tick:watchdog] then prose")

    def test_the_failsafe_wins_over_a_declared_sentinel(self) -> None:
        """A project may declare the failsafe cron under persistent_crons. Its
        prompt must keep the failsafe's own cadence rules, not a declared
        job's, whichever sentinel the agent kept."""
        prompt = "[tick:job:failsafe-recovery]\n[tick:failsafe]\nbody"
        assert classify_tick(prompt) == DaemonTick(TickKind.FAILSAFE)

    def test_an_unknown_kind_is_not_a_tick(self) -> None:
        """Unknown means human: recognition must be positive evidence."""
        assert classify_tick("[tick:heartbeat]\nbody") is None

    def test_an_empty_job_id_is_not_a_tick(self) -> None:
        assert classify_tick("[tick:job:]\nbody") is None


class TestAddingAndRemovingTheSentinel:
    def test_the_sentinel_is_prepended_as_its_own_line(self) -> None:
        assert with_tick_sentinel("body", "[tick:watchdog]") == "[tick:watchdog]\nbody"

    def test_a_prompt_that_already_carries_a_sentinel_is_unchanged(self) -> None:
        """A declared failsafe job already says [tick:failsafe]; adding
        [tick:job:<id>] on top would make one cron carry two identities."""
        prompt = "[tick:failsafe]\nbody"
        assert with_tick_sentinel(prompt, "[tick:job:failsafe-recovery]") == prompt

    def test_stripping_removes_every_sentinel_and_keeps_the_words(self) -> None:
        stripped = strip_tick_sentinels("[tick:job:a]\n**HEAD** [tick:watchdog] words")
        assert "[tick:" not in stripped
        assert "**HEAD**" in stripped
        assert "words" in stripped

    def test_stripping_a_prompt_without_a_sentinel_is_a_no_op(self) -> None:
        assert strip_tick_sentinels("plain prompt") == "plain prompt"
