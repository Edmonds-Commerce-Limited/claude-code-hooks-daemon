"""Tests for CommentChangelogHandler - blocks changelog narrative in comments.

NOTE for future editors: this file's fixtures deliberately contain
changelog-shaped example text (the exact thing the handler under test
detects). Once ``comment_changelog`` is registered in the live daemon
config, a future full-file ``Write`` of THIS file (not a normal ``Edit``,
which only scans ``new_string``) could in principle be denied by the very
handler it tests -- the same self-reference issue ``qa_suppression``'s own
test file works around via runtime string concatenation. This file has not
needed that treatment yet (no fixture has tripped it while editing this
file with ``Edit``); if a future edit does, follow qa_suppression's
pattern rather than disabling the handler.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.comment_changelog import (
    CommentChangelogHandler,
)

# Build the version-transition arrow dynamically so this test file's own
# source never contains a literal '->' immediately next to two dotted
# version numbers inside a real comment context.
_ARROW = "-" + ">"


def _make_write_input(file_path: str, content: str) -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def _make_edit_input(file_path: str, new_string: str, old_string: str = "x") -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": old_string,
            "new_string": new_string,
        },
    }


class TestCommentChangelogHandlerInit:
    def test_handler_id(self) -> None:
        handler = CommentChangelogHandler()
        assert handler.handler_id == HandlerID.COMMENT_CHANGELOG

    def test_priority(self) -> None:
        handler = CommentChangelogHandler()
        assert handler.priority == Priority.COMMENT_CHANGELOG

    def test_tags(self) -> None:
        handler = CommentChangelogHandler()
        assert HandlerTag.MULTI_LANGUAGE in handler.tags
        assert HandlerTag.CONTENT_QUALITY in handler.tags
        assert HandlerTag.BLOCKING in handler.tags
        assert HandlerTag.TERMINAL not in handler.tags

    def test_is_not_terminal(self) -> None:
        """A terminal ALLOW here would silently disable the rest of the chain.

        This handler has an advisory path: softer signals return ALLOW with
        context rather than a deny. The chain breaks on ANY terminal match
        whatever it decided, so while this was terminal an ordinary English
        phrase such as "no longer" in a comment ended dispatch at priority 31
        and switched off every higher-numbered handler for that write --
        tdd_enforcement (35) included. Nothing reported it, because a
        shadowed handler and one that never matched look identical.

        Denying is unaffected: core/chain.py keeps the most restrictive
        decision seen, so a non-terminal deny survives a later advisory ALLOW.
        """
        handler = CommentChangelogHandler()
        assert handler.terminal is False


class TestMatchesGating:
    def test_ignores_non_write_edit_tools(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        assert handler.matches(hook_input) is False

    def test_ignores_files_with_unknown_extension(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = _make_write_input("/workspace/data.xyz", "# Prior 1.0.0: x")
        assert handler.matches(hook_input) is False

    def test_ignores_markdown_files(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = _make_write_input("/workspace/README.md", "Prior 1.0.0: x")
        assert handler.matches(hook_input) is False

    def test_ignores_clean_content(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = _make_write_input("/workspace/src/mod.py", "# a normal comment\nx = 1\n")
        assert handler.matches(hook_input) is False

    def test_ignores_skip_directories(self) -> None:
        handler = CommentChangelogHandler()
        content = "# Prior 1.0.0: fixed. Prior 0.9.0: original.\n"
        hook_input = _make_write_input("/workspace/vendor/lib.py", content)
        assert handler.matches(hook_input) is False

    def test_ignores_third_party_dir_with_no_exclude_paths_configured(self) -> None:
        """third_party/ is part of the canonical vendored core (Task 3.2) but
        was NOT already covered by the per-language strategy's own
        skip_directories -- this specifically exercises the new
        handler_excludes_path(defaults=...) wiring (Plan 00288 Task 4.6)."""
        handler = CommentChangelogHandler()
        # Built from parts so this test file's OWN source text never contains
        # a literal changelog-narrative comment (comment_changelog would
        # otherwise deny writing this very test).
        content = "# " + "Prior" + " 2.0.0: fixed. " + "Prior" + " 1.5.0: original.\n"
        hook_input = _make_write_input("/workspace/third_party/lib.py", content)
        assert handler.matches(hook_input) is False

    def test_matches_write_with_prior_pattern(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # Prior 1.2.0: fixed the timing bug\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is True

    def test_matches_edit_scans_new_string_only(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = _make_edit_input(
            "/workspace/src/mod.py",
            new_string="x = 1  # Prior 1.2.0: fixed the timing bug\n",
            old_string="x = 0\n",
        )
        assert handler.matches(hook_input) is True

    def test_edit_old_string_content_alone_does_not_trigger(self) -> None:
        """Only new_string is scanned - removing changelog text is never blocked."""
        handler = CommentChangelogHandler()
        hook_input = _make_edit_input(
            "/workspace/src/mod.py",
            new_string="x = 1  # a clean comment now\n",
            old_string="x = 1  # Prior 1.2.0: fixed the timing bug\n",
        )
        assert handler.matches(hook_input) is False


class TestHighPrecisionBlockSignals:
    """Only these two survived Plan 00208's whole-repo self-scan with zero
    measured false positives (see JOURNAL). The other three signals the
    proposal originally specified as blocking (arrow, verb+version, 2+
    distinct entries) are demoted to advisory below -- the scan found them
    firing on legitimate version-processing code and rationale comments
    across this project's own ~1,080 files."""

    def test_prior_semver_colon(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # Prior 3.26.2: whitelisted the supervisor\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "changelog" in (result.reason or "").lower()

    def test_previously_semver_colon(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # Previously 2.0.0: used a different algorithm\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_dated_entry(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # 2026-08-12: switched to pasta for consistency\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_deny_reason_names_the_destination(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # Prior 3.26.2: whitelisted the supervisor\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        reason = result.reason or ""
        assert "git" in reason.lower()
        assert "journal" in reason.lower() or "changelog" in reason.lower()

    def test_task_number_is_not_mistaken_for_semver(self) -> None:
        """'Task 3.5.2' collides with the 3-part semver shape - must be excluded."""
        handler = CommentChangelogHandler()
        content = (
            "# Plan 00100 Phase 3.5: inline-safe bootstrap precondition.\n"
            "# Before attempting it, consults `can_inline_bootstrap` (Task 3.5.2);\n"
            "# any failure routes to the fallback (Task 3.5.3).\n"
        )
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False


class TestDemotedSignalsAreNowAdvisoryOnly:
    """These three were originally specified as high-precision/blocking;
    measurement against this repo's own source found each firing on
    legitimate code (see module docstring + JOURNAL 00208)."""

    def test_two_or_more_distinct_semver_tokens_advises_not_blocks(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # bumped from 1.2.3 to 1.2.4 for the fix\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_version_transition_arrow_advises_not_blocks(self) -> None:
        handler = CommentChangelogHandler()
        content = f"x = 1  # migrated 1.2.0 {_ARROW} 1.3.0 for the new API\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_version_transition_arrow_unicode_advises_not_blocks(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # migrated v1.2 → v1.3 for the new API\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_arrow_describing_a_value_transformation_is_a_real_repo_example(self) -> None:
        """Measured false positive this demotion fixes: version_check.py's own
        `# refs/tags/v2.7.0 -> v2.7.0` describes a string transform, not history."""
        handler = CommentChangelogHandler()
        content = f'tag = parts[1].split("/")[-1]  # refs/tags/v2.7.0 {_ARROW} v2.7.0\n'
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_changelog_verb_naming_version_advises_not_blocks(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # Removed in v2.1.224 after the audit\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_verb_version_rationale_with_wide_gap_is_a_real_repo_example(self) -> None:
        """Measured false positive: project_loader.py's own rationale comment
        ('was added to the Handler base in v3.24.0 (Plan 00133) ...')."""
        handler = CommentChangelogHandler()
        content = (
            "# NOTE: get_default_enabled() was added to the Handler base in "
            "v3.24.0 (Plan 00133) as a concrete method, deliberately not "
            "abstract, so it does not appear above.\n"
        )
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


class TestMustNotFlag:
    """The proposal's own must-not-flag pin: history as RATIONALE, not changelog."""

    def test_plan_00047_rationale_example_is_allowed(self) -> None:
        handler = CommentChangelogHandler()
        content = (
            "# History (Plan 00047 -- do NOT re-add DISABLE_MOUSE without "
            "reading this):\n"
            "# fullscreen draws on the terminal alt-screen, and with mouse "
            "capture OFF Wayland\n"
            '# terminals fall back to DECSET-1007 "alternate scroll" and '
            "remap the wheel to arrow keys\n"
        )
        hook_input = _make_write_input("/workspace/entrypoint.sh", content)
        assert handler.matches(hook_input) is False
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_own_source_rationale_referencing_plan_number_is_allowed(self) -> None:
        """A plan-number-keyed rationale (this repo's own style) must not trigger."""
        handler = CommentChangelogHandler()
        content = (
            "# Plan 00181: this append-only JSONL had no bound and grew "
            "without limit,\n"
            "# so entries older than the retention window are pruned here.\n"
        )
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False

    def test_single_version_mention_is_allowed(self) -> None:
        """One bare version reference is not 'two or more distinct' tokens."""
        handler = CommentChangelogHandler()
        content = "x = 1  # requires at least version 1.2.3 of the driver\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False

    def test_python_version_pair_without_v_prefix_is_allowed(self) -> None:
        """Bare two-part decimals (e.g. Python versions) are not semver tokens."""
        handler = CommentChangelogHandler()
        content = "x = 1  # supported on both 3.11 and 3.12\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False

    def test_docstring_rationale_without_history_shape_is_allowed(self) -> None:
        handler = CommentChangelogHandler()
        content = (
            '"""Compute the retry backoff.\n'
            "\n"
            "Uses exponential backoff because the naive fixed-delay retry "
            "caused a thundering herd against the upstream API.\n"
            '"""\n'
        )
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False

    def test_version_processing_docstring_with_two_example_versions_is_allowed(self) -> None:
        """Measured false positive this scope decision avoids: a version-range
        parser's own docstring citing two EXAMPLE versions is not a changelog."""
        handler = CommentChangelogHandler()
        content = (
            '"""Get breaking changes within a version range.\n'
            "\n"
            "Args:\n"
            '    from_version: Starting version (e.g., "2.12.0")\n'
            '    to_version: Ending version (e.g., "2.13.0")\n'
            '"""\n'
        )
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_utility_sense_used_to_is_allowed(self) -> None:
        """'X used to Y' (utility sense, 'used [in order] to') is NOT the
        retrospective 'we used to Y' sense -- must not be flagged even as
        advisory, or the noise rate on ordinary docstrings is unusable."""
        handler = CommentChangelogHandler()
        content = "# Flag used to validate the input before parsing.\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False


class TestLowerPrecisionAdvisorySignals:
    def test_multiple_fixed_added_bullets_advise_not_block(self) -> None:
        handler = CommentChangelogHandler()
        content = "# Fixed: the race. Added: a lock. Changed: the timeout.\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_retrospective_phrase_advises_not_block(self) -> None:
        handler = CommentChangelogHandler()
        content = "# We used to retry synchronously here.\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_single_fixed_bullet_alone_is_not_flagged(self) -> None:
        """One bullet-style entry is not a RUN of them."""
        handler = CommentChangelogHandler()
        content = "# Fixed: handles the empty-list case now.\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False


class TestWarnMode:
    def test_warn_mode_downgrades_block_to_advisory(self) -> None:
        handler = CommentChangelogHandler()
        handler._mode = "warn"
        content = "x = 1  # Prior 3.26.2: whitelisted the supervisor\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context


class TestMaxHistoryEntriesConfig:
    """max_history_entries now gates the ADVISORY entries-count signal
    (demoted from blocking - see TestDemotedSignalsAreNowAdvisoryOnly)."""

    def test_custom_max_history_entries_raises_the_advisory_bar(self) -> None:
        handler = CommentChangelogHandler()
        handler._max_history_entries = 3
        content = "x = 1  # bumped from 1.2.3 to 1.2.4 for the fix\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        # Only 2 distinct semver tokens, below the raised threshold of 3, and
        # no other signal (block or advisory) present in this text.
        assert handler.matches(hook_input) is False


class TestNoEscapeHatch:
    """comment_changelog deliberately has NO escape hatch (PLAN 00208 Non-Goals):
    changelog content must be MOVED, never exempted in place."""

    def test_must_exceed_marker_does_not_suppress_the_block(self) -> None:
        handler = CommentChangelogHandler()
        content = (
            "x = 1  # Prior 3.26.2: whitelisted the supervisor "
            "MUST_EXCEED_COMMENT_SIZE_BECAUSE: legacy\n"
        )
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


class TestGetClaudeMd:
    def test_returns_non_empty_guidance(self) -> None:
        handler = CommentChangelogHandler()
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "comment_changelog" in guidance


class TestGetAcceptanceTests:
    def test_aggregates_from_all_language_strategies(self) -> None:
        handler = CommentChangelogHandler()
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 12


class TestGuardClauses:
    """handle()/matches() are independently robust to malformed hook_input."""

    def test_matches_false_when_file_path_missing(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = {"tool_name": "Write", "tool_input": {"content": "# Prior 1.0.0: x"}}
        assert handler.matches(hook_input) is False

    def test_handle_allows_when_file_path_missing(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = {"tool_name": "Write", "tool_input": {"content": "# Prior 1.0.0: x"}}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_allows_when_extension_unknown(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = _make_write_input("/workspace/data.xyz", "# Prior 1.0.0: x")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_allows_when_content_empty(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = _make_write_input("/workspace/src/mod.py", "")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_apply_language_filter_is_idempotent(self) -> None:
        handler = CommentChangelogHandler()
        handler._languages = ["Python"]
        handler._apply_language_filter()
        handler._apply_language_filter()
        assert handler._registry.registered_languages == ["Python"]

    def test_matches_false_when_content_empty(self) -> None:
        handler = CommentChangelogHandler()
        hook_input = _make_write_input("/workspace/src/mod.py", "")
        assert handler.matches(hook_input) is False

    def test_matches_false_when_path_matches_exclude_glob(self) -> None:
        handler = CommentChangelogHandler()
        handler._exclude_paths = ["src/generated/**"]
        content = "# Prior 1.0.0: fixed. Prior 0.9.0: original.\n"
        hook_input = _make_write_input("/workspace/src/generated/mod.py", content)
        assert handler.matches(hook_input) is False


class TestLongSpanTruncation:
    def test_deny_reason_truncates_a_very_long_span_preview(self) -> None:
        handler = CommentChangelogHandler()
        long_tail = "x" * 200
        content = f"x = 1  # Prior 1.0.0: {long_tail}\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "..." in (result.reason or "")

    def test_advisory_context_truncates_a_very_long_span_preview(self) -> None:
        handler = CommentChangelogHandler()
        long_tail = "z" * 200
        content = f"# We used to do it differently: {long_tail}\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "..." in result.context[0]


class TestCommentChangelogGetRules:
    """get_rules() (Plan 00116): one rule for both high-precision block signals."""

    def test_get_rules_returns_one_rule(self) -> None:
        assert len(CommentChangelogHandler().get_rules()) == 1

    def test_get_rules_rule_id_is_constant(self) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        rule = CommentChangelogHandler().get_rules()[0]
        assert rule.rule_id == RuleID.COMMENT_CHANGELOG

    def test_get_rules_verbose_is_non_empty(self) -> None:
        assert CommentChangelogHandler().get_rules()[0].verbose


class TestCommentChangelogDisclosureLadder:
    """Verbose-first/terse-after per (transcript_path, rule_id) (Plan 00116)."""

    @pytest.fixture(autouse=True)
    def _reset_disclosure_tracker(self):
        from claude_code_hooks_daemon.core import reset_data_layer

        reset_data_layer()
        yield
        reset_data_layer()

    @staticmethod
    def _hook_input(transcript_path: str | None) -> dict[str, Any]:
        # Split across concatenation so this test module's own source text
        # never contains the contiguous 'Prior <version>:' phrase its OWN
        # pattern matches (avoids a live self-trip on this file's own edit).
        content = "x = 1  # " + "Prior" + " 3.26.2: whitelisted the supervisor\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_deny_reason_starts_with_rule_id_prefix(self) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        handler = CommentChangelogHandler()
        result = handler.handle(self._hook_input("/tmp/transcript-cl-a.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.COMMENT_CHANGELOG}]")

    def test_first_fire_is_verbose(self) -> None:
        handler = CommentChangelogHandler()
        result = handler.handle(self._hook_input("/tmp/transcript-cl-b.jsonl"))
        assert "RATIONALE" in result.reason

    def test_second_fire_same_agent_is_terse(self) -> None:
        handler = CommentChangelogHandler()
        transcript = "/tmp/transcript-cl-c.jsonl"
        handler.handle(self._hook_input(transcript))
        second = handler.handle(self._hook_input(transcript))
        assert "RATIONALE" not in second.reason
        assert "comment(s) carry changelog narrative" in second.reason

    def test_different_agent_is_independently_verbose(self) -> None:
        handler = CommentChangelogHandler()
        handler.handle(self._hook_input("/tmp/transcript-cl-d.jsonl"))
        other = handler.handle(self._hook_input("/tmp/transcript-cl-e.jsonl"))
        assert "RATIONALE" in other.reason

    def test_missing_transcript_path_always_verbose(self) -> None:
        handler = CommentChangelogHandler()
        first = handler.handle(self._hook_input(None))
        second = handler.handle(self._hook_input(None))
        assert "RATIONALE" in first.reason
        assert "RATIONALE" in second.reason
