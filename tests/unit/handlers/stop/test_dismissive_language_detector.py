"""Tests for dismissive language detector handler.

Detects when the agent dismisses issues as "pre-existing", "out of scope",
or "someone else's problem" instead of offering to fix them.
"""

import json
import tempfile
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision


def _make_transcript(messages: list[dict[str, Any]]) -> str:
    """Create a temporary JSONL transcript file."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for msg in messages:
        tmp.write(json.dumps(msg) + "\n")
    tmp.flush()
    return tmp.name


def _assistant_message(text: str) -> dict[str, Any]:
    """Create an assistant message transcript entry."""
    return {
        "type": "message",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _human_message(text: str) -> dict[str, Any]:
    """Create a human message transcript entry."""
    return {
        "type": "message",
        "message": {
            "role": "human",
            "content": [{"type": "text", "text": text}],
        },
    }


class TestDismissiveLanguageDetectorInit:
    """Test handler initialization."""

    def test_handler_id(self) -> None:
        """Test handler has correct ID."""
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        handler = DismissiveLanguageDetectorHandler()
        assert handler.handler_id.config_key == "dismissive_language_detector"

    def test_non_terminal(self) -> None:
        """Test handler is non-terminal (advisory only)."""
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        handler = DismissiveLanguageDetectorHandler()
        assert handler.terminal is False

    def test_tags_include_advisory(self) -> None:
        """Test handler has advisory-related tags."""
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        handler = DismissiveLanguageDetectorHandler()
        assert HandlerTag.VALIDATION in handler.tags
        assert HandlerTag.ADVISORY in handler.tags
        assert HandlerTag.NON_TERMINAL in handler.tags

    def test_priority(self) -> None:
        """Test handler has correct priority (58 - advisory range)."""
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        handler = DismissiveLanguageDetectorHandler()
        assert handler.priority == 58


class TestDismissiveLanguageDetectorMatches:
    """Test matches() correctly identifies dismissive language in transcripts."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        return DismissiveLanguageDetectorHandler()

    # --- "Not our problem" patterns ---

    def test_matches_pre_existing_issue(self, handler: Any) -> None:
        """Detect 'pre-existing issue' - deflecting responsibility."""
        path = _make_transcript(
            [_assistant_message("This is a pre-existing issue unrelated to our changes")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_pre_existing_problem(self, handler: Any) -> None:
        """Detect 'pre-existing problem'."""
        path = _make_transcript(
            [_assistant_message("That's a pre-existing problem in the codebase")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_caused_by_our_changes(self, handler: Any) -> None:
        """Detect 'not caused by our changes'."""
        path = _make_transcript([_assistant_message("This error is not caused by our changes")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_caused_by_my_changes(self, handler: Any) -> None:
        """Detect 'not caused by my changes'."""
        path = _make_transcript([_assistant_message("This failure is not caused by my changes")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_unrelated_to_our(self, handler: Any) -> None:
        """Detect 'unrelated to our' work."""
        path = _make_transcript(
            [_assistant_message("This test failure is unrelated to our implementation")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_unrelated_to_what_were(self, handler: Any) -> None:
        """Detect 'unrelated to what we're doing'."""
        path = _make_transcript(
            [_assistant_message("That error is unrelated to what we're working on")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_existed_before_our_changes(self, handler: Any) -> None:
        """Detect 'existed before our changes'."""
        path = _make_transcript(
            [_assistant_message("This bug existed before our changes were made")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_was_already_there(self, handler: Any) -> None:
        """Detect 'was already there/present/broken/failing'."""
        path = _make_transcript(
            [_assistant_message("That warning was already there before we started")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_was_already_broken(self, handler: Any) -> None:
        """Detect 'was already broken'."""
        path = _make_transcript(
            [_assistant_message("The test was already broken, not something we did")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_our_problem(self, handler: Any) -> None:
        """Detect 'not our problem/issue/concern/fault/bug'."""
        path = _make_transcript([_assistant_message("That's not our problem to fix right now")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_something_we_introduced(self, handler: Any) -> None:
        """Detect 'not something we introduced/caused/broke'."""
        path = _make_transcript(
            [_assistant_message("This is not something we introduced in this PR")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- "Out of scope" patterns ---

    def test_matches_outside_the_scope_of(self, handler: Any) -> None:
        """Detect 'outside the scope of'."""
        path = _make_transcript(
            [_assistant_message("That refactoring is outside the scope of this task")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_beyond_scope_of(self, handler: Any) -> None:
        """Detect 'beyond the scope of'."""
        path = _make_transcript(
            [_assistant_message("Fixing that is beyond the scope of our current work")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_out_of_scope(self, handler: Any) -> None:
        """Detect 'out of scope'."""
        path = _make_transcript([_assistant_message("That feature request is out of scope")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_separate_concern(self, handler: Any) -> None:
        """Detect 'separate concern'."""
        path = _make_transcript([_assistant_message("Error handling there is a separate concern")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_separate_issue(self, handler: Any) -> None:
        """Detect 'separate issue'."""
        path = _make_transcript([_assistant_message("The styling bug is a separate issue")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_in_scope(self, handler: Any) -> None:
        """Detect 'not in scope'."""
        path = _make_transcript(
            [_assistant_message("That improvement is not in scope for this ticket")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_falls_outside(self, handler: Any) -> None:
        """Detect 'falls outside'."""
        path = _make_transcript(
            [_assistant_message("This requirement falls outside our current sprint")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- "Someone else's job" patterns ---

    def test_matches_not_our_responsibility(self, handler: Any) -> None:
        """Detect 'not our responsibility'."""
        path = _make_transcript(
            [_assistant_message("Database migrations are not our responsibility")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_my_area(self, handler: Any) -> None:
        """Detect 'not my/our area/domain'."""
        path = _make_transcript([_assistant_message("That's not my area of expertise to fix")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_different_task_entirely(self, handler: Any) -> None:
        """Detect 'different task entirely'."""
        path = _make_transcript(
            [_assistant_message("Fixing the CSS layout is a different task entirely")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_a_different_effort(self, handler: Any) -> None:
        """Detect 'a different effort/initiative/project'."""
        path = _make_transcript(
            [_assistant_message("That would be a different effort from what we're doing")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_what_were_here(self, handler: Any) -> None:
        """Detect 'not what we're here/working on'."""
        path = _make_transcript([_assistant_message("That's not what we're here to do")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- "Defer/ignore" patterns ---

    def test_matches_can_be_addressed_later(self, handler: Any) -> None:
        """Detect 'can be addressed/fixed/handled/resolved later/separately'."""
        path = _make_transcript(
            [_assistant_message("That issue can be addressed later in a follow-up")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_can_be_fixed_separately(self, handler: Any) -> None:
        """Detect 'can be fixed separately'."""
        path = _make_transcript([_assistant_message("The type error can be fixed separately")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_leave_that_for_now(self, handler: Any) -> None:
        """Detect 'leave that/this/it for now/later'."""
        path = _make_transcript(
            [_assistant_message("Let's leave that for now and focus on the main feature")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_tackle_that_separately(self, handler: Any) -> None:
        """Detect 'tackle that/this separately'."""
        path = _make_transcript(
            [_assistant_message("We should tackle that separately in another PR")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_defer_that(self, handler: Any) -> None:
        """Detect 'defer that/this to/for'."""
        path = _make_transcript(
            [_assistant_message("I'd suggest we defer that to a future sprint")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_worth_fixing(self, handler: Any) -> None:
        """Detect 'not worth fixing/addressing/worrying'."""
        path = _make_transcript(
            [_assistant_message("That edge case is not worth fixing right now")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_ignore_for_now(self, handler: Any) -> None:
        """Detect 'ignore that/this for now'."""
        path = _make_transcript([_assistant_message("We can ignore this for now")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_best_left_alone(self, handler: Any) -> None:
        """Detect 'best left alone/as-is'."""
        path = _make_transcript([_assistant_message("That legacy code is best left alone")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_lets_not_worry(self, handler: Any) -> None:
        """Detect 'let's not worry/concern ourselves about'."""
        path = _make_transcript(
            [_assistant_message("Let's not worry about that deprecation warning")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- Subtle dismissal patterns (dogfooding-discovered gaps) ---

    def test_matches_no_issues_with_my_code(self, handler: Any) -> None:
        """Detect 'no issues with my new code' - subtle self-exoneration."""
        path = _make_transcript(
            [_assistant_message("There are no issues with my new code, these warnings were there before")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_introduced_by_my_change(self, handler: Any) -> None:
        """Detect 'not introduced by my change' - deflecting blame."""
        path = _make_transcript(
            [_assistant_message("This error is not introduced by my change")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_related_to_my_changes(self, handler: Any) -> None:
        """Detect 'not related to my/our changes'."""
        path = _make_transcript(
            [_assistant_message("These shellcheck warnings are not related to my changes")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_nothing_to_do_with_our_changes(self, handler: Any) -> None:
        """Detect 'nothing to do with our/my changes'."""
        path = _make_transcript(
            [_assistant_message("That failure has nothing to do with our changes")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_not_a_result_of(self, handler: Any) -> None:
        """Detect 'not a result of our/my changes'."""
        path = _make_transcript(
            [_assistant_message("The lint warning is not a result of my changes")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_no_issues_with_my_implementation(self, handler: Any) -> None:
        """Detect 'no issues with my/our implementation'."""
        path = _make_transcript(
            [_assistant_message("There are no issues with my implementation")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_my_code_is_correct(self, handler: Any) -> None:
        """Detect 'my/our code is correct' - self-exoneration."""
        path = _make_transcript(
            [_assistant_message("My code is correct, the test must be wrong")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    def test_matches_these_are_not_from_my(self, handler: Any) -> None:
        """Detect 'these are not from my/our' changes."""
        path = _make_transcript(
            [_assistant_message("These warnings are not from my changes")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- Case insensitivity ---

    def test_matches_case_insensitive(self, handler: Any) -> None:
        """Patterns should match regardless of case."""
        path = _make_transcript(
            [_assistant_message("THIS IS A PRE-EXISTING ISSUE IN THE CODEBASE")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is True

    # --- Negative cases (should NOT match) ---

    def test_no_match_clean_response(self, handler: Any) -> None:
        """Clean response that fixes the issue should not trigger."""
        path = _make_transcript(
            [
                _assistant_message(
                    "I found a bug in the parser. Let me fix it now. " "Here's the corrected code:"
                )
            ]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_proactive_fix(self, handler: Any) -> None:
        """Response that proactively offers to fix should not trigger."""
        path = _make_transcript(
            [_assistant_message("I noticed a test failure. I'll investigate and fix it.")]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_acknowledging_issue(self, handler: Any) -> None:
        """Response that acknowledges and addresses issue should not trigger."""
        path = _make_transcript(
            [
                _assistant_message(
                    "There's a type error in the validation module. "
                    "I'll add the proper type annotations now."
                )
            ]
        )
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_no_transcript_path(self, handler: Any) -> None:
        """No transcript_path in input should not match."""
        assert handler.matches({}) is False

    def test_no_match_nonexistent_transcript(self, handler: Any) -> None:
        """Nonexistent transcript file should not match."""
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: "/nonexistent/path.jsonl"}) is False

    def test_no_match_empty_transcript(self, handler: Any) -> None:
        """Empty transcript should not match."""
        path = _make_transcript([])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_only_human_messages(self, handler: Any) -> None:
        """Transcript with only human messages should not match."""
        path = _make_transcript([_human_message("This is a pre-existing issue")])
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: path}) is False

    def test_no_match_stop_hook_active(self, handler: Any) -> None:
        """Should not match when stop_hook_active is set (re-entry prevention)."""
        path = _make_transcript([_assistant_message("This is a pre-existing issue")])
        hook_input = {
            HookInputField.TRANSCRIPT_PATH: path,
            "stop_hook_active": True,
        }
        assert handler.matches(hook_input) is False

    def test_no_match_stop_hook_active_camel_case(self, handler: Any) -> None:
        """Should not match when stopHookActive (camelCase) is set."""
        path = _make_transcript([_assistant_message("This is a pre-existing issue")])
        hook_input = {
            HookInputField.TRANSCRIPT_PATH: path,
            "stopHookActive": True,
        }
        assert handler.matches(hook_input) is False


class TestDismissiveLanguageDetectorHandle:
    """Test handle() returns correct advisory response."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        return DismissiveLanguageDetectorHandler()

    def test_returns_allow_decision(self, handler: Any) -> None:
        """Handle should return ALLOW (advisory, not blocking)."""
        path = _make_transcript(
            [_assistant_message("This is a pre-existing issue in the codebase")]
        )
        result = handler.handle({HookInputField.TRANSCRIPT_PATH: path})
        assert result.decision == Decision.ALLOW

    def test_context_warns_about_dismissive(self, handler: Any) -> None:
        """Context should warn about dismissive language detected."""
        path = _make_transcript(
            [_assistant_message("This is a pre-existing issue in the codebase")]
        )
        result = handler.handle({HookInputField.TRANSCRIPT_PATH: path})
        context = "\n".join(result.context)
        assert "DISMISSIVE" in context

    def test_context_tells_to_fix(self, handler: Any) -> None:
        """Context should tell agent to offer to fix issues."""
        path = _make_transcript(
            [_assistant_message("That error is outside the scope of this task")]
        )
        result = handler.handle({HookInputField.TRANSCRIPT_PATH: path})
        context = "\n".join(result.context)
        assert "FIX" in context
        assert "ACKNOWLEDGE" in context

    def test_context_includes_matched_phrases(self, handler: Any) -> None:
        """Context should include which phrases were detected."""
        path = _make_transcript(
            [_assistant_message("This is a pre-existing issue and out of scope")]
        )
        result = handler.handle({HookInputField.TRANSCRIPT_PATH: path})
        context = "\n".join(result.context)
        assert "pre-existing issue" in context.lower() or "out of scope" in context.lower()

    def test_handle_with_no_transcript(self, handler: Any) -> None:
        """Handle with no transcript should still return ALLOW."""
        result = handler.handle({})
        assert result.decision == Decision.ALLOW


class TestDismissiveLanguageDetectorEdgeCases:
    """Test edge cases for coverage."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        return DismissiveLanguageDetectorHandler()

    def test_skips_non_message_type(self, handler: Any) -> None:
        """Should skip JSONL entries with type != 'message'."""
        path = _make_transcript(
            [
                {"type": "tool_use", "tool": "Bash"},
                _assistant_message("This is a pre-existing issue"),
            ]
        )
        result = handler._get_last_assistant_message(path)
        assert "pre-existing issue" in result

    def test_handles_malformed_jsonl_line(self, handler: Any) -> None:
        """Should continue past malformed JSONL lines."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write("this is not valid json\n")
        tmp.write(json.dumps(_assistant_message("That's out of scope")) + "\n")
        tmp.flush()
        result = handler._get_last_assistant_message(tmp.name)
        assert "out of scope" in result

    def test_handles_oserror(self, handler: Any, tmp_path: Any) -> None:
        """Should return empty string on OSError."""
        result = handler._get_last_assistant_message(str(tmp_path))
        assert result == ""

    def test_transcript_with_empty_lines(self, handler: Any) -> None:
        """Empty lines in JSONL are skipped."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write("\n")
        tmp.write("\n")
        tmp.write(json.dumps(_assistant_message("This is a pre-existing issue")) + "\n")
        tmp.write("\n")
        tmp.flush()
        assert handler.matches({HookInputField.TRANSCRIPT_PATH: tmp.name}) is True


class TestDismissiveLanguageDetectorAcceptanceTests:
    """Test acceptance test definitions."""

    def test_has_acceptance_tests(self) -> None:
        """Handler should define acceptance tests."""
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        handler = DismissiveLanguageDetectorHandler()
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0

    def test_acceptance_tests_have_titles(self) -> None:
        """Each acceptance test should have a title."""
        from claude_code_hooks_daemon.handlers.stop.dismissive_language_detector import (
            DismissiveLanguageDetectorHandler,
        )

        handler = DismissiveLanguageDetectorHandler()
        tests = handler.get_acceptance_tests()
        for test in tests:
            assert hasattr(test, "title")
            assert test.title
