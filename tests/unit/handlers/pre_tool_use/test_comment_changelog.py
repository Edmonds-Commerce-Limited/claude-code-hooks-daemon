"""Tests for CommentChangelogHandler - blocks changelog narrative in comments."""

from typing import Any

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
        assert HandlerTag.TERMINAL in handler.tags


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

    def test_two_or_more_distinct_semver_tokens(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # bumped from 1.2.3 to 1.2.4 for the fix\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_version_transition_arrow(self) -> None:
        handler = CommentChangelogHandler()
        content = f"x = 1  # migrated 1.2.0 {_ARROW} 1.3.0 for the new API\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_version_transition_arrow_unicode(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # migrated v1.2 → v1.3 for the new API\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_dated_entry(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # 2026-08-12: switched to pasta for consistency\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_changelog_verb_naming_version(self) -> None:
        handler = CommentChangelogHandler()
        content = "x = 1  # Removed in v2.1.224 after the audit\n"
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
    def test_custom_max_history_entries_raises_the_bar(self) -> None:
        handler = CommentChangelogHandler()
        handler._max_history_entries = 3
        content = "x = 1  # bumped from 1.2.3 to 1.2.4 for the fix\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        # Only 2 distinct semver tokens, below the raised threshold of 3, and
        # no other high-precision signal present.
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
