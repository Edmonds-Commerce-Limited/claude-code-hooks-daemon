"""Unit tests for DisclosureResetSessionStartHandler (Plan 00116, Phase 4, Task 4.2).

Decision E: disclosure state resets on clear/new session. The hook input does
not reliably distinguish "clear" from an ordinary SessionStart, so this
handler resets on EVERY SessionStart (cheap: worst case one extra verbose
block on a resume, per the plan's risk table).
"""

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import get_data_layer, reset_data_layer
from claude_code_hooks_daemon.handlers.session_start.disclosure_reset_session_start import (
    DisclosureResetSessionStartHandler,
)

_TRANSCRIPT_PATH = "/tmp/agent-a/transcript.jsonl"
_RULE_ID = "R-GIT-RESET-HARD"


class TestDisclosureResetSessionStartHandler:
    def setup_method(self) -> None:
        reset_data_layer()

    def teardown_method(self) -> None:
        reset_data_layer()

    def handler(self) -> DisclosureResetSessionStartHandler:
        return DisclosureResetSessionStartHandler()

    # ---- metadata ---------------------------------------------------------

    def test_init_name(self) -> None:
        assert self.handler().name == HandlerID.DISCLOSURE_RESET_SESSION_START.display_name

    def test_init_priority(self) -> None:
        assert self.handler().priority == Priority.DISCLOSURE_RESET_SESSION_START

    def test_init_non_terminal(self) -> None:
        assert self.handler().terminal is False

    def test_init_tags(self) -> None:
        assert HandlerTag.NON_TERMINAL in self.handler().tags

    def test_enabled_by_default(self) -> None:
        assert self.handler().get_default_enabled() is True

    # ---- behaviour ----------------------------------------------------------

    def test_matches_every_session_start_including_resume(self) -> None:
        """Decision E: reset on every SessionStart, not only new sessions."""
        assert self.handler().matches({"source": "startup"}) is True
        assert self.handler().matches({"source": "resume"}) is True
        assert self.handler().matches({}) is True

    def test_handle_allows(self) -> None:
        hook_input = {"transcript_path": _TRANSCRIPT_PATH}
        result = self.handler().handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_resets_disclosure_for_transcript_path(self) -> None:
        tracker = get_data_layer().disclosure
        tracker.mark_disclosed(_TRANSCRIPT_PATH, _RULE_ID)
        assert tracker.was_disclosed(_TRANSCRIPT_PATH, _RULE_ID) is True

        self.handler().handle({"transcript_path": _TRANSCRIPT_PATH})

        assert tracker.was_disclosed(_TRANSCRIPT_PATH, _RULE_ID) is False

    def test_handle_does_not_reset_a_different_agent(self) -> None:
        other_path = "/tmp/agent-b/transcript.jsonl"
        tracker = get_data_layer().disclosure
        tracker.mark_disclosed(other_path, _RULE_ID)

        self.handler().handle({"transcript_path": _TRANSCRIPT_PATH})

        assert tracker.was_disclosed(other_path, _RULE_ID) is True

    def test_handle_missing_transcript_path_is_a_safe_no_op(self) -> None:
        result = self.handler().handle({})
        assert result.decision == Decision.ALLOW

    def test_get_claude_md_returns_none(self) -> None:
        assert self.handler().get_claude_md() is None

    def test_get_acceptance_tests_returns_at_least_one(self) -> None:
        assert len(self.handler().get_acceptance_tests()) >= 1
