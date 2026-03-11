"""Tests for PostClearAutoExecuteHandler.

PROTOTYPE tests: Validates that the handler correctly detects first prompts
of new sessions and injects execution guidance.
"""

from claude_code_hooks_daemon.core import Decision


class TestPostClearAutoExecuteInit:
    """Test handler initialisation."""

    def test_handler_id(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        assert handler.name == "post_clear_auto_execute"

    def test_is_non_terminal(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        assert handler.terminal is False

    def test_initial_session_state(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        assert handler._last_session_id is None
        assert handler._fired_for_session is False


class TestPostClearAutoExecuteMatches:
    """Test matches() logic - should match first prompt of new sessions only."""

    def test_matches_first_prompt_of_session(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        hook_input = {"session_id": "session-001", "prompt": "execute plan 85"}
        assert handler.matches(hook_input) is True

    def test_does_not_match_second_prompt_same_session(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        hook_input = {"session_id": "session-001", "prompt": "execute plan 85"}

        # First prompt - matches and handle updates state
        assert handler.matches(hook_input) is True
        handler.handle(hook_input)

        # Second prompt same session - should NOT match
        hook_input_2 = {"session_id": "session-001", "prompt": "now do this other thing"}
        assert handler.matches(hook_input_2) is False

    def test_matches_first_prompt_of_new_session_after_clear(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()

        # First session
        hook_input_1 = {"session_id": "session-001", "prompt": "hello"}
        assert handler.matches(hook_input_1) is True
        handler.handle(hook_input_1)

        # Second prompt same session - no match
        hook_input_2 = {"session_id": "session-001", "prompt": "do stuff"}
        assert handler.matches(hook_input_2) is False

        # New session after /clear - should match again
        hook_input_3 = {"session_id": "session-002", "prompt": "execute plan 85"}
        assert handler.matches(hook_input_3) is True

    def test_does_not_match_without_session_id(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        hook_input = {"prompt": "execute plan 85"}
        assert handler.matches(hook_input) is False

    def test_does_not_match_empty_session_id(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        hook_input = {"session_id": "", "prompt": "execute plan 85"}
        assert handler.matches(hook_input) is False


class TestPostClearAutoExecuteHandle:
    """Test handle() logic - should inject guidance and update session state."""

    def test_returns_allow_decision(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        hook_input = {"session_id": "session-001", "prompt": "execute plan 85"}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_injects_guidance_context(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        hook_input = {"session_id": "session-001", "prompt": "execute plan 85"}
        result = handler.handle(hook_input)
        assert len(result.context) == 1
        assert "POST-CLEAR INSTRUCTION DETECTED" in result.context[0]
        assert "execute the instruction immediately" in result.context[0].lower()

    def test_updates_session_tracking(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        hook_input = {"session_id": "session-001", "prompt": "execute plan 85"}
        handler.handle(hook_input)
        assert handler._last_session_id == "session-001"
        assert handler._fired_for_session is True

    def test_resets_tracking_on_new_session(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()

        # First session
        handler.handle({"session_id": "session-001", "prompt": "hello"})
        assert handler._last_session_id == "session-001"

        # New session
        handler.handle({"session_id": "session-002", "prompt": "execute plan 85"})
        assert handler._last_session_id == "session-002"

    def test_has_acceptance_tests(self) -> None:
        from claude_code_hooks_daemon.handlers.user_prompt_submit.post_clear_auto_execute import (
            PostClearAutoExecuteHandler,
        )

        handler = PostClearAutoExecuteHandler()
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1
