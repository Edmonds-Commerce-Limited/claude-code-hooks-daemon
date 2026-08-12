"""Tests for StandingAuthorisationsHandler (Plan 00223).

The handler replays authorisations a project's owner has actually recorded in
config. Two properties matter more than any of the mechanics, and both have
dedicated test classes below:

- **Nothing is authorised by default** (Plan 00223 Decision 3). The handler
  ships on so the options are discoverable; every entry ships off so the
  daemon never fabricates the consent its own text claims.
- **The text is a recorded request, never a countermand** (Decision 2). It
  must never tell the agent to disregard, ignore or override its
  instructions — that framing is both a worse prompt and a mechanism that
  should not exist.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.user_prompt_submit.standing_authorisations import (
    AUTHORISATION_SUBAGENT_DELEGATION,
    AUTHORISATION_WORKFLOWS,
    StandingAuthorisationsHandler,
)

_PROMPT = "Please refactor the config loader and add tests for the new branch."


def _hook_input(prompt: str = _PROMPT) -> dict[str, Any]:
    return {"hook_event_name": "UserPromptSubmit", "prompt": prompt}


def _enable(handler: StandingAuthorisationsHandler, *ids: str) -> None:
    """Apply config options the way the registry does — via setattr."""
    handler._authorisations = [{"id": entry_id, "enabled": True} for entry_id in ids]


class TestInitialisation:
    def test_handler_identity_and_priority(self) -> None:
        handler = StandingAuthorisationsHandler()
        assert handler.handler_id == HandlerID.STANDING_AUTHORISATIONS
        assert handler.priority == Priority.STANDING_AUTHORISATIONS

    def test_handler_is_never_terminal(self) -> None:
        """An advisory that can end dispatch would be a bug."""
        assert StandingAuthorisationsHandler().terminal is False


class TestNothingIsAuthorisedByDefault:
    """Decision 3 — the mechanism ships on, every authorisation ships off."""

    def test_fresh_handler_emits_no_context(self) -> None:
        result = StandingAuthorisationsHandler().handle(_hook_input())
        assert result.context == []

    def test_fresh_handler_never_denies(self) -> None:
        result = StandingAuthorisationsHandler().handle(_hook_input())
        assert result.decision == Decision.ALLOW

    def test_every_builtin_entry_ships_disabled(self) -> None:
        """The default set exists to be discoverable, not to be active."""
        handler = StandingAuthorisationsHandler()
        assert handler._resolve_entries() == []

    def test_explicitly_disabled_entry_stays_silent(self) -> None:
        handler = StandingAuthorisationsHandler()
        handler._authorisations = [
            {"id": AUTHORISATION_SUBAGENT_DELEGATION, "enabled": False},
        ]
        assert handler.handle(_hook_input()).context == []


class TestEnablingAnAuthorisation:
    def test_enabled_entry_is_injected(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        assert handler.handle(_hook_input()).context

    def test_injected_text_names_where_it_is_configured(self) -> None:
        """It must be auditable and revocable, or it is not a recorded request."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        text = " ".join(handler.handle(_hook_input()).context)
        assert "hooks-daemon.yaml" in text
        assert "standing_authorisations" in text

    def test_the_two_restrictions_are_independently_authorisable(self) -> None:
        """Authorising delegation says nothing about authorising workflows."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        text = " ".join(handler.handle(_hook_input()).context).lower()
        assert "workflow" not in text

    def test_both_can_be_enabled_together(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION, AUTHORISATION_WORKFLOWS)
        assert len(handler.handle(_hook_input()).context) == 2

    def test_unknown_entry_id_is_ignored_not_crashed(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, "no-such-authorisation")
        assert handler.handle(_hook_input()).context == []


class TestTextIsARecordedRequestNeverACountermand:
    """Decision 2 — the single most important property of this handler."""

    @pytest.mark.parametrize(
        "entry_id",
        [AUTHORISATION_SUBAGENT_DELEGATION, AUTHORISATION_WORKFLOWS],
    )
    def test_no_entry_tells_the_agent_to_disregard_instructions(self, entry_id: str) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, entry_id)
        text = " ".join(handler.handle(_hook_input()).context).lower()
        for forbidden in ("ignore", "disregard", "override", "overrule", "bypass"):
            assert forbidden not in text, f"{entry_id} text uses countermand word {forbidden!r}"

    @pytest.mark.parametrize(
        "entry_id",
        [AUTHORISATION_SUBAGENT_DELEGATION, AUTHORISATION_WORKFLOWS],
    )
    def test_every_entry_attributes_the_request_to_the_project(self, entry_id: str) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, entry_id)
        text = " ".join(handler.handle(_hook_input()).context).lower()
        assert "project" in text


class TestMatches:
    def test_matches_a_normal_prompt(self) -> None:
        assert StandingAuthorisationsHandler().matches(_hook_input()) is True

    def test_does_not_match_when_prompt_is_missing(self) -> None:
        assert StandingAuthorisationsHandler().matches({}) is False

    def test_does_not_match_a_non_string_prompt(self) -> None:
        assert StandingAuthorisationsHandler().matches({"prompt": 42}) is False


class TestDecayNotCooldown:
    """Task 3.3 — the rate limit must never SKIP a prompt.

    Phase 1's finding is that a system-prompt restriction re-sent on every
    request is answered only by a per-prompt channel. A cooldown that skips
    prompts would leave windows where the restriction is unopposed — exactly
    the SessionStart failure this handler exists to avoid. So the text decays
    to a short form; it never stops arriving.
    """

    def test_it_still_fires_on_every_prompt_long_after_the_decay(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        for _ in range(50):
            assert handler.handle(
                _hook_input()
            ).context, "a skipped prompt is a cooldown, not a decay"

    def test_early_deliveries_carry_the_full_text(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        first = " ".join(handler.handle(_hook_input()).context)
        assert "without pausing to ask permission" in first

    def test_the_text_shortens_once_the_point_has_been_made(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        first = " ".join(handler.handle(_hook_input()).context)
        later = ""
        for _ in range(10):
            later = " ".join(handler.handle(_hook_input()).context)
        assert len(later) < len(first)

    def test_the_short_form_still_names_where_it_is_recorded(self) -> None:
        """A decayed authorisation that cannot be audited is not a request."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        later = ""
        for _ in range(10):
            later = " ".join(handler.handle(_hook_input()).context)
        assert "hooks-daemon.yaml" in later

    def test_the_short_form_is_still_never_a_countermand(self) -> None:
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION, AUTHORISATION_WORKFLOWS)
        later = ""
        for _ in range(10):
            later = " ".join(handler.handle(_hook_input()).context).lower()
        for forbidden in ("ignore", "disregard", "override", "overrule", "bypass"):
            assert forbidden not in later

    def test_decay_is_tracked_per_session(self) -> None:
        """A new session gets the full text again — it has not been told yet."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        session_a = {**_hook_input(), "session_id": "aaaaaaaa"}
        for _ in range(10):
            handler.handle(session_a)
        session_b = {**_hook_input(), "session_id": "bbbbbbbb"}
        fresh = " ".join(handler.handle(session_b).context)
        assert "without pausing to ask permission" in fresh

    def test_session_tracking_map_is_bounded(self) -> None:
        """A long-lived daemon must not leak one entry per session forever."""
        handler = StandingAuthorisationsHandler()
        _enable(handler, AUTHORISATION_SUBAGENT_DELEGATION)
        for index in range(600):
            handler.handle({**_hook_input(), "session_id": f"session-{index}"})
        assert len(handler._delivery_counts) <= 512


class TestClaudeMdGuidance:
    def test_guidance_documents_the_setting(self) -> None:
        guidance = StandingAuthorisationsHandler().get_claude_md()
        assert guidance is not None
        assert "standing_authorisations" in guidance

    def test_guidance_does_not_itself_carry_the_authorisation(self) -> None:
        """CLAUDE.md documents the setting; the handler delivers it (Decision 1).

        Phase 1 measured CLAUDE.md as the LOWEST-position lever of four, so a
        second copy of the authorisation text here would be the copy that goes
        stale while reading as authoritative.
        """
        guidance = StandingAuthorisationsHandler().get_claude_md()
        assert guidance is not None
        assert "STANDING AUTHORISATION" not in guidance
