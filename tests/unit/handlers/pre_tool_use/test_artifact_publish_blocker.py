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

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.artifact_publish_blocker import (
    ArtifactPublishBlockerHandler,
)


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


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


def _handler_with_source_disable(tmp_path: Path, *, enabled: bool = True) -> Any:
    """Build a handler wired to a temp workspace with the option set."""
    handler = ArtifactPublishBlockerHandler()
    handler._source_disable = enabled
    handler._workspace_root = tmp_path
    return handler


def _non_artifact_event() -> dict[str, Any]:
    """Any ordinary PreToolUse event — enforcement must not need an Artifact call."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    }


class TestSourceDisable:
    """The opt-in `source_disable` option (Plan 00293).

    When enabled, the handler ensures `.claude/settings.json` carries
    `"enableArtifact": false` — the documented settings-level switch that
    removes the Artifact tool (and its ~6k-token schema) from every future
    session at source. The call-time deny stays as the in-session backstop,
    since settings are only read at session start.
    """

    def test_off_by_default_and_touches_nothing(self, tmp_path: Path) -> None:
        """Ships disabled: no settings file is created or modified."""
        handler = _handler_with_source_disable(tmp_path, enabled=False)
        handler.matches(_non_artifact_event())
        assert not (tmp_path / ".claude" / "settings.json").exists()

    def test_creates_settings_file_when_absent(self, tmp_path: Path) -> None:
        """No settings.json yet: one is created holding only the disable key."""
        handler = _handler_with_source_disable(tmp_path)
        handler.matches(_non_artifact_event())
        settings_path = tmp_path / ".claude" / "settings.json"
        assert json.loads(settings_path.read_text()) == {"enableArtifact": False}

    def test_adds_key_preserving_existing_settings(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({"plansDirectory": "CLAUDE/Plan", "hooks": {}}))
        handler = _handler_with_source_disable(tmp_path)
        handler.matches(_non_artifact_event())
        settings = json.loads(settings_path.read_text())
        assert settings["enableArtifact"] is False
        assert settings["plansDirectory"] == "CLAUDE/Plan"
        assert settings["hooks"] == {}

    def test_backs_up_an_existing_file_once(self, tmp_path: Path) -> None:
        """A pre-edit backup is written, and never overwritten if present."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        original = json.dumps({"plansDirectory": "CLAUDE/Plan"})
        settings_path.write_text(original)
        handler = _handler_with_source_disable(tmp_path)
        handler.matches(_non_artifact_event())
        backup = claude_dir / "settings.json.bak.pre-artifact-source-disable"
        assert backup.read_text() == original

    def test_noop_when_already_disabled(self, tmp_path: Path) -> None:
        """Idempotent: `enableArtifact: false` already present means no write."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({"enableArtifact": False}))
        before = settings_path.stat().st_mtime_ns
        handler = _handler_with_source_disable(tmp_path)
        handler.matches(_non_artifact_event())
        assert settings_path.stat().st_mtime_ns == before
        assert not (claude_dir / "settings.json.bak.pre-artifact-source-disable").exists()

    def test_overrides_an_explicit_true(self, tmp_path: Path) -> None:
        """`enableArtifact: true` is still a never-want violation — flipped."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text(json.dumps({"enableArtifact": True}))
        handler = _handler_with_source_disable(tmp_path)
        handler.matches(_non_artifact_event())
        assert json.loads(settings_path.read_text())["enableArtifact"] is False

    def test_enforces_only_once_per_handler_instance(self, tmp_path: Path) -> None:
        """The check runs on the first event only, not on every tool call."""
        handler = _handler_with_source_disable(tmp_path)
        handler.matches(_non_artifact_event())
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.unlink()
        handler.matches(_non_artifact_event())
        assert not settings_path.exists()

    def test_malformed_settings_survive_untouched(self, tmp_path: Path) -> None:
        """A broken client file must never crash the chain or be clobbered."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_path = claude_dir / "settings.json"
        settings_path.write_text("{not json")
        handler = _handler_with_source_disable(tmp_path)
        handler.matches(_non_artifact_event())
        assert settings_path.read_text() == "{not json"

    def test_matching_behaviour_is_unchanged(self, tmp_path: Path) -> None:
        """The option adds enforcement; it must not alter what is denied."""
        handler = _handler_with_source_disable(tmp_path)
        assert handler.matches(_artifact_input({"file_path": "/w/r.html"})) is True
        assert handler.matches(_artifact_input({"action": "list"})) is False

    def test_deny_reason_names_the_source_disable(self, tmp_path: Path) -> None:
        """With the option on, the deny explains the tool is disabled at source."""
        handler = _handler_with_source_disable(tmp_path)
        result = handler.handle(_artifact_input({"file_path": "/w/r.html"}))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "enableArtifact" in result.reason

    def test_default_deny_reason_does_not_claim_source_disable(self, tmp_path: Path) -> None:
        """Without the option, the reason must not assert a disable that is absent."""
        handler = _handler_with_source_disable(tmp_path, enabled=False)
        result = handler.handle(_artifact_input({"file_path": "/w/r.html"}))
        assert result.reason is not None
        assert "enableArtifact" not in result.reason

    def test_get_claude_md_documents_the_option(self, tmp_path: Path) -> None:
        handler = ArtifactPublishBlockerHandler()
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "source_disable" in guidance


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


class TestArtifactPublishBlockerGetRules:
    """get_rules() declares the single Rule backing this handler (Plan 00116)."""

    def test_returns_one_rule(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        rules = handler.get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        assert handler.get_rules()[0].rule_id == RuleID.ARTIFACT_PUBLISH

    def test_rule_has_non_empty_verbose(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        assert handler.get_rules()[0].verbose


class TestArtifactPublishBlockerDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Decision G)."""

    def _hook_input(self, transcript_path: str) -> dict[str, Any]:
        hook_input = _artifact_input({"file_path": "/workspace/r.html"})
        hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_first_fire_for_agent_is_verbose(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        result = handler.handle(self._hook_input("/tmp/agent-a/transcript.jsonl"))

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "DO INSTEAD" in result.reason

    def test_second_fire_for_same_agent_is_terse(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input(transcript_path))
        result = handler.handle(self._hook_input(transcript_path))

        assert result.reason is not None
        assert "DO INSTEAD" not in result.reason

    def test_terse_message_leads_with_rule_id(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input(transcript_path))
        result = handler.handle(self._hook_input(transcript_path))

        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.ARTIFACT_PUBLISH}]")

    def test_missing_transcript_path_is_always_verbose(self) -> None:
        handler = ArtifactPublishBlockerHandler()
        hook_input = _artifact_input({"file_path": "/workspace/r.html"})
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert result.reason is not None
        assert "DO INSTEAD" in result.reason
