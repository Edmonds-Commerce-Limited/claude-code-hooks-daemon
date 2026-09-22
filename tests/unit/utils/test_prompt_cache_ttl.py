"""Tests for prompt-cache TTL resolution (Plan 00452 Task 5.1).

Claude Code decides a TTL per request and every request falls into one of two
fixed buckets: the MAIN conversation, and EVERYTHING ELSE (sub-agents,
workflows, forks, compaction). The two get different defaults, and the
sub-agent bucket gets five minutes even on a subscription — which is exactly
the expensive half a project cannot see.

The resolution order is documented upstream and is NOT obvious, so it is
implemented once here and pinned by these tests rather than being re-derived
at each call site. The vendored source is
`remote-docs/code.claude.com/docs/en/prompt-caching.md`.

The `TestInvalidValuesAreIgnored` class matters more than it looks. Claude
Code ignores a value that is not `5m` or `1h`, so a project that sets `3600`
or `1hr` believes it has chosen a TTL and has not. Reporting that as an
explicit choice would be worse than reporting nothing.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.prompt_cache_ttl import (
    BUCKET_MAIN,
    BUCKET_SUBAGENT,
    resolve_ttl,
)


class TestTheDefaults:
    def test_the_subagent_bucket_defaults_to_five_minutes(self):
        """Determinate under BOTH billing modes, which is why it is stated."""
        result = resolve_ttl(BUCKET_SUBAGENT, settings={}, env={})
        assert result.ttl == "5m"
        assert result.explicit is False

    def test_the_main_bucket_default_is_billing_dependent_and_says_so(self):
        """One hour on a subscription within plan usage, five minutes on credits.

        Nothing inside a hook can see which applies, and guessing would produce
        a confident wrong answer about the more expensive half of the bill.
        """
        result = resolve_ttl(BUCKET_MAIN, settings={}, env={})
        assert result.ttl is None
        assert result.explicit is False

    def test_an_unknown_bucket_is_rejected_rather_than_guessed(self):
        with pytest.raises(ValueError):
            resolve_ttl("something-else", settings={}, env={})


class TestThePrecedenceOrder:
    def test_force_five_minutes_beats_everything(self):
        result = resolve_ttl(
            BUCKET_MAIN,
            settings={"promptCacheTtl": "1h"},
            env={"FORCE_PROMPT_CACHING_5M": "1", "CLAUDE_CODE_PROMPT_CACHE_TTL": "1h"},
        )
        assert result.ttl == "5m"
        assert result.source == "FORCE_PROMPT_CACHING_5M"

    def test_force_five_minutes_applies_to_the_subagent_bucket_too(self):
        result = resolve_ttl(
            BUCKET_SUBAGENT,
            settings={"subagentPromptCacheTtl": "1h"},
            env={"FORCE_PROMPT_CACHING_5M": "1"},
        )
        assert result.ttl == "5m"

    def test_the_bucket_env_var_beats_the_setting(self):
        result = resolve_ttl(
            BUCKET_MAIN,
            settings={"promptCacheTtl": "5m"},
            env={"CLAUDE_CODE_PROMPT_CACHE_TTL": "1h"},
        )
        assert result.ttl == "1h"
        assert result.source == "CLAUDE_CODE_PROMPT_CACHE_TTL"

    def test_the_setting_beats_enable_one_hour(self):
        result = resolve_ttl(
            BUCKET_MAIN,
            settings={"promptCacheTtl": "5m"},
            env={"ENABLE_PROMPT_CACHING_1H": "1"},
        )
        assert result.ttl == "5m"
        assert result.source == "promptCacheTtl"

    def test_enable_one_hour_beats_the_default(self):
        result = resolve_ttl(BUCKET_SUBAGENT, settings={}, env={"ENABLE_PROMPT_CACHING_1H": "1"})
        assert result.ttl == "1h"
        assert result.source == "ENABLE_PROMPT_CACHING_1H"

    def test_each_bucket_reads_its_OWN_env_var(self):
        """The main var must not silently set the sub-agent bucket, or vice versa."""
        env = {"CLAUDE_CODE_PROMPT_CACHE_TTL": "1h"}
        assert resolve_ttl(BUCKET_MAIN, settings={}, env=env).ttl == "1h"
        assert resolve_ttl(BUCKET_SUBAGENT, settings={}, env=env).ttl == "5m"

    def test_each_bucket_reads_its_OWN_setting(self):
        settings = {"subagentPromptCacheTtl": "1h"}
        assert resolve_ttl(BUCKET_SUBAGENT, settings=settings, env={}).ttl == "1h"
        assert resolve_ttl(BUCKET_MAIN, settings=settings, env={}).ttl is None


class TestInvalidValuesAreIgnored:
    """Claude Code accepts only `5m` and `1h`; anything else it ignores."""

    @pytest.mark.parametrize("bad", ["3600", "1hr", "60m", "", "1H", "5M", None, 3600, True])
    def test_an_invalid_setting_falls_through_to_the_default(self, bad):
        result = resolve_ttl(BUCKET_SUBAGENT, settings={"subagentPromptCacheTtl": bad}, env={})
        assert result.ttl == "5m"
        assert result.explicit is False

    @pytest.mark.parametrize("bad", ["3600", "1hr", "forever"])
    def test_an_invalid_env_var_falls_through_to_the_setting(self, bad):
        result = resolve_ttl(
            BUCKET_SUBAGENT,
            settings={"subagentPromptCacheTtl": "1h"},
            env={"CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": bad},
        )
        assert result.ttl == "1h"
        assert result.source == "subagentPromptCacheTtl"

    def test_an_invalid_value_is_reported_so_it_can_be_corrected(self):
        """A project that set `3600` believes it chose a TTL and did not."""
        result = resolve_ttl(BUCKET_SUBAGENT, settings={"subagentPromptCacheTtl": "3600"}, env={})
        assert result.ignored == [("subagentPromptCacheTtl", "3600")]

    def test_nothing_is_reported_as_ignored_when_everything_is_valid(self):
        result = resolve_ttl(BUCKET_SUBAGENT, settings={"subagentPromptCacheTtl": "1h"}, env={})
        assert result.ignored == []


class TestTheFlagsAreOnlyHonouredWhenTruthy:
    @pytest.mark.parametrize("value", ["0", "", "false", "no"])
    def test_a_falsy_force_flag_does_not_force(self, value):
        """`FORCE_PROMPT_CACHING_5M=0` must not behave like `=1`."""
        result = resolve_ttl(
            BUCKET_SUBAGENT,
            settings={"subagentPromptCacheTtl": "1h"},
            env={"FORCE_PROMPT_CACHING_5M": value},
        )
        assert result.ttl == "1h"

    @pytest.mark.parametrize("value", ["0", "", "false"])
    def test_a_falsy_enable_one_hour_flag_does_not_enable(self, value):
        result = resolve_ttl(BUCKET_SUBAGENT, settings={}, env={"ENABLE_PROMPT_CACHING_1H": value})
        assert result.ttl == "5m"


class TestExplicitness:
    """`explicit` is the whole point: 'have we CHOSEN, or are we drifting?'"""

    @pytest.mark.parametrize(
        ("settings", "env"),
        [
            ({"subagentPromptCacheTtl": "1h"}, {}),
            ({}, {"CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL": "5m"}),
            ({}, {"FORCE_PROMPT_CACHING_5M": "1"}),
            ({}, {"ENABLE_PROMPT_CACHING_1H": "1"}),
        ],
    )
    def test_any_deliberate_control_counts_as_explicit(self, settings, env):
        assert resolve_ttl(BUCKET_SUBAGENT, settings=settings, env=env).explicit is True

    def test_the_bare_default_is_not_explicit(self):
        assert resolve_ttl(BUCKET_SUBAGENT, settings={}, env={}).explicit is False

    def test_a_non_dict_settings_blob_does_not_raise(self):
        """Settings come from a file on disk that anything could have written."""
        assert resolve_ttl(BUCKET_SUBAGENT, settings=None, env={}).ttl == "5m"
