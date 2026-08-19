"""Tests for the artefact publishing blocker (Plan 00259).

The `Artifact` tool renders a local file to a page hosted on claude.ai and
returns a URL. The page starts private, but it lives OUTSIDE the repository and
the entire purpose of the URL is that a human can then share it. That is an
egress path the project cannot audit and cannot retract, so publishing is
blocked by default and only a human may lift the block.

The payload shape asserted here is not assumed — it was captured from the live
daemon (Plan 00259 Task 1.1) via `payload_capture` while calling the real tool:

    {"hook_event_name": "PreToolUse", "tool_name": "Artifact",
     "tool_input": {"action": "list", "limit": 3}}
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.artifact_publish_blocker import (
    ArtifactPublishBlockerHandler,
)


def _artifact_input(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Build a PreToolUse payload in the shape the daemon actually receives."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Artifact",
        "tool_input": tool_input,
    }


class TestInitialization:
    """Handler identity, priority and terminality."""

    def test_handler_id_is_registered_constant(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        assert handler.handler_id == HandlerID.ARTIFACT_PUBLISH_BLOCKER

    def test_priority_sits_in_the_disclosure_band(self) -> None:
        """Priority 14 groups it with the other disclosure guards.

        `sensitive_content` and `security_antipattern` both sit at 14. This is
        the same class of risk — content leaving the project — so it belongs
        with them rather than in the workflow band.
        """
        handler = ArtifactPublishBlockerHandler()
        assert handler.priority == Priority.ARTIFACT_PUBLISH_BLOCKER
        assert handler.priority == Priority.SENSITIVE_CONTENT

    def test_handler_is_terminal(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        assert handler.terminal is True


class TestMatches:
    """What the handler fires on."""

    def test_matches_publish_with_no_explicit_action(self) -> None:
        """An omitted `action` means publish - this is the default call shape."""
        handler = ArtifactPublishBlockerHandler()
        hook_input = _artifact_input({"file_path": "/workspace/report.html"})
        assert handler.matches(hook_input) is True

    def test_matches_explicit_publish_action(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        hook_input = _artifact_input({"action": "publish", "file_path": "/workspace/report.html"})
        assert handler.matches(hook_input) is True

    def test_matches_update_of_an_existing_artefact(self) -> None:
        """Passing `url` updates a published page - still an outward write."""
        handler = ArtifactPublishBlockerHandler()
        hook_input = _artifact_input(
            {
                "file_path": "/workspace/report.html",
                "url": "https://claude.ai/code/artifact/abc",
            }
        )
        assert handler.matches(hook_input) is True

    def test_does_not_match_list_action(self) -> None:
        """Enumerating is not disclosure - nothing leaves the project."""
        handler = ArtifactPublishBlockerHandler()
        hook_input = _artifact_input({"action": "list", "limit": 3})
        assert handler.matches(hook_input) is False

    def test_does_not_match_list_action_regardless_of_case(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        hook_input = _artifact_input({"action": "LIST"})
        assert handler.matches(hook_input) is False

    @pytest.mark.parametrize("tool_name", ["Write", "Edit", "Bash", "Read", "Task"])
    def test_does_not_match_other_tools(self, tool_name: str) -> None:
        handler = ArtifactPublishBlockerHandler()
        hook_input = {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"action": "publish"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_tool_input(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        assert handler.matches({"tool_name": "Artifact"}) is False


class TestHandle:
    """What the deny message must say."""

    def test_denies_publish(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        result = handler.handle(_artifact_input({"file_path": "/workspace/r.html"}))
        assert result.decision == Decision.DENY

    def test_reason_names_the_config_key(self) -> None:
        """A block the agent cannot act on is a dead end.

        The message must name the exact key, so the HUMAN reading it over the
        agent's shoulder knows precisely what to change.
        """
        handler = ArtifactPublishBlockerHandler()
        result = handler.handle(_artifact_input({"file_path": "/workspace/r.html"}))
        assert result.reason is not None
        assert "artifact_publish_blocker" in result.reason

    def test_reason_tells_the_agent_to_ask_rather_than_self_authorise(self) -> None:
        """The whole point: the agent must not lift this itself."""
        handler = ArtifactPublishBlockerHandler()
        result = handler.handle(_artifact_input({"file_path": "/workspace/r.html"}))
        assert result.reason is not None
        lowered = result.reason.lower()
        assert "ask" in lowered
        assert "human" in lowered or "user" in lowered

    def test_reason_offers_a_local_alternative(self) -> None:
        """Blocking without an alternative just strands the task."""
        handler = ArtifactPublishBlockerHandler()
        result = handler.handle(_artifact_input({"file_path": "/workspace/r.html"}))
        assert result.reason is not None
        assert "file" in result.reason.lower()

    def test_allows_when_matches_is_false(self) -> None:
        """Defensive symmetry with the other blocking handlers."""
        handler = ArtifactPublishBlockerHandler()
        result = handler.handle(_artifact_input({"action": "list"}))
        assert result.decision == Decision.ALLOW


class TestGuidanceAndAcceptanceTests:
    """Coverage obligations every blocking handler carries."""

    def test_get_claude_md_is_present(self) -> None:
        """A blocking handler with no resident guidance is what the gate catches."""
        handler = ArtifactPublishBlockerHandler()
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "artifact_publish_blocker" in guidance

    def test_acceptance_tests_include_a_deny_and_an_allow_case(self) -> None:
        """A positive-only suite cannot catch over-broad matching."""
        handler = ArtifactPublishBlockerHandler()
        tests = handler.get_acceptance_tests()
        decisions = {test.expected_decision for test in tests}
        assert Decision.DENY in decisions
        assert Decision.ALLOW in decisions
