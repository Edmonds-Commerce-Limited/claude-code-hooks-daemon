"""Tests for PipeBlockerHandler verbose-first/terse-after disclosure ladder."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

_PROJECT_CONTEXT_PATH = "claude_code_hooks_daemon.core.project_context.ProjectContext"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """get_data_layer() is a process-wide singleton (Plan 00116, Decision G).

    Without this, one test's ``mark_disclosed`` for a rule_id + transcript_path
    leaks into a later test that reuses the same pair, turning a genuine
    "first fire" into a stale "already disclosed".
    """
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> PipeBlockerHandler:
    """Create handler instance."""
    return PipeBlockerHandler()


@pytest.fixture
def blacklisted_input() -> dict:
    """Hook input for a blacklisted (expensive) command."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest tests/ | tail -20"},
    }


@pytest.fixture
def unknown_input() -> dict:
    """Hook input for an unknown (unrecognized) command."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": "docker ps -a | tail -20"},
    }


def _with_transcript(hook_input: dict, transcript_path: str) -> dict:
    return {**hook_input, "transcript_path": transcript_path}


# ── echd-capture recommendation (Plan 00164 Phase 6) ─────────────────────────


def _deploy_fake_helper(daemon_dir: Path, executable: bool = True) -> Path:
    """Create a fake ``scripts/echd-capture`` under ``daemon_dir``."""
    helper_dir = daemon_dir / "scripts"
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper = helper_dir / "echd-capture"
    helper.write_text("#!/bin/bash\necho fake\n")
    helper.chmod(0o755 if executable else 0o644)
    return helper


class TestEchdCaptureRecommendation:
    """Every block message must recommend `echd-capture` (when resolvable) so
    agents stop the pointless 'capture to file then echo it all to stdout'
    theatre — and must NEVER recommend a bare, possibly not-on-PATH
    `echd-capture` token when the helper cannot be found."""

    def _handle(
        self,
        handler: PipeBlockerHandler,
        hook_input: dict,
        transcript_path: str,
        daemon_dir: Path | None = None,
    ) -> str:
        hook_input = _with_transcript(hook_input, transcript_path)
        if daemon_dir is not None:
            with patch(f"{_PROJECT_CONTEXT_PATH}.daemon_untracked_dir") as mock_dut:
                mock_dut.return_value = daemon_dir / "untracked"
                reason = handler.handle(hook_input).reason
        else:
            # No ProjectContext deployment mocked — simulates the helper
            # being unresolvable (not initialised / not found anywhere).
            with patch(
                f"{_PROJECT_CONTEXT_PATH}.daemon_untracked_dir",
                side_effect=RuntimeError("not initialised"),
            ):
                reason = handler.handle(hook_input).reason
        assert reason is not None
        return reason

    def test_verbose_blacklisted_recommends_echd_capture(
        self, handler: PipeBlockerHandler, blacklisted_input: dict, tmp_path: Path
    ) -> None:
        _deploy_fake_helper(tmp_path)
        reason = self._handle(
            handler, blacklisted_input, "/tmp/agent-a/transcript.jsonl", daemon_dir=tmp_path
        )
        assert "echd-capture" in reason
        assert str(tmp_path / "scripts" / "echd-capture") in reason
        assert "pipefail" in reason

    def test_terse_blacklisted_recommends_echd_capture(
        self, handler: PipeBlockerHandler, blacklisted_input: dict, tmp_path: Path
    ) -> None:
        _deploy_fake_helper(tmp_path)
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        self._handle(handler, blacklisted_input, transcript_path, daemon_dir=tmp_path)
        reason = self._handle(handler, blacklisted_input, transcript_path, daemon_dir=tmp_path)
        assert "echd-capture" in reason

    def test_verbose_unknown_recommends_echd_capture(
        self, handler: PipeBlockerHandler, unknown_input: dict, tmp_path: Path
    ) -> None:
        _deploy_fake_helper(tmp_path)
        reason = self._handle(
            handler, unknown_input, "/tmp/agent-a/transcript.jsonl", daemon_dir=tmp_path
        )
        assert "echd-capture" in reason
        assert "pipefail" in reason

    def test_terse_unknown_recommends_echd_capture(
        self, handler: PipeBlockerHandler, unknown_input: dict, tmp_path: Path
    ) -> None:
        _deploy_fake_helper(tmp_path)
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        self._handle(handler, unknown_input, transcript_path, daemon_dir=tmp_path)
        reason = self._handle(handler, unknown_input, transcript_path, daemon_dir=tmp_path)
        assert "echd-capture" in reason

    def test_claude_md_documents_echd_capture(self, handler: PipeBlockerHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "echd-capture" in guidance
        assert "pipefail" in guidance


class TestEchdCaptureResolution:
    """Resolver contract (dogfooding bug fix): resolve an ABSOLUTE deployed
    path when present, self-heal a missing exec bit, and NEVER fall back to
    a bare (not-on-PATH) command name."""

    def test_resolves_absolute_path_in_simulated_client_install(
        self, handler: PipeBlockerHandler, tmp_path: Path
    ) -> None:
        """Simulated client-install layout: {project}/.claude/hooks-daemon/scripts/echd-capture."""
        project_root = tmp_path / "client-project"
        daemon_dir = project_root / ".claude" / "hooks-daemon"
        helper = _deploy_fake_helper(daemon_dir)

        with patch(f"{_PROJECT_CONTEXT_PATH}.daemon_untracked_dir") as mock_dut:
            mock_dut.return_value = daemon_dir / "untracked"
            resolved = handler._capture_helper_invocation()

        assert resolved == str(helper)

    def test_self_heals_missing_executable_bit(
        self, handler: PipeBlockerHandler, tmp_path: Path
    ) -> None:
        """A deployed helper that lost its exec bit (e.g. core.fileMode=false
        checkout) is chmod'd back to executable rather than falling back."""
        helper = _deploy_fake_helper(tmp_path, executable=False)
        assert not os.access(helper, os.X_OK)

        with patch(f"{_PROJECT_CONTEXT_PATH}.daemon_untracked_dir") as mock_dut:
            mock_dut.return_value = tmp_path / "untracked"
            resolved = handler._capture_helper_invocation()

        assert resolved == str(helper)
        assert os.access(helper, os.X_OK)

    def test_returns_none_when_project_context_not_initialised(
        self, handler: PipeBlockerHandler
    ) -> None:
        with patch(
            f"{_PROJECT_CONTEXT_PATH}.daemon_untracked_dir",
            side_effect=RuntimeError("not initialised"),
        ):
            assert handler._capture_helper_invocation() is None

    def test_returns_none_when_helper_missing_everywhere(
        self, handler: PipeBlockerHandler, tmp_path: Path
    ) -> None:
        """Helper genuinely absent (no scripts/echd-capture deployed at all)."""
        with patch(f"{_PROJECT_CONTEXT_PATH}.daemon_untracked_dir") as mock_dut:
            mock_dut.return_value = tmp_path / "untracked"
            assert handler._capture_helper_invocation() is None

    def test_never_recommends_bare_echd_capture_token_when_unresolved(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """When the helper cannot be resolved anywhere, the block message must
        fall back to the temp-file redirect and must NOT present a bare
        `echd-capture` as a runnable command."""
        with patch(
            f"{_PROJECT_CONTEXT_PATH}.daemon_untracked_dir",
            side_effect=RuntimeError("not initialised"),
        ):
            reason = handler.handle(
                _with_transcript(blacklisted_input, "/tmp/agent-a/transcript.jsonl")
            ).reason

        assert reason is not None
        assert "echd-capture" not in reason
        assert "TEMP_FILE" in reason
        assert "RECOMMENDED ALTERNATIVE" in reason


# ── Blacklisted path: verbose (first fire) ────────────────────────────────────


class TestBlacklistedVerboseMessage:
    """First fire for a given agent produces a verbose message for blacklisted commands."""

    def test_first_fire_blacklisted_contains_pipe_blocked(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Verbose blacklisted message contains 'Pipe to tail/head detected'."""
        result = handler.handle(
            _with_transcript(blacklisted_input, "/tmp/agent-a/transcript.jsonl")
        )
        assert "Pipe to tail/head detected" in result.reason

    def test_first_fire_blacklisted_contains_why_blocked(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Verbose blacklisted message contains 'WHY BLOCKED' section."""
        result = handler.handle(
            _with_transcript(blacklisted_input, "/tmp/agent-a/transcript.jsonl")
        )
        assert "WHY BLOCKED" in result.reason

    def test_first_fire_blacklisted_contains_expensive(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Verbose blacklisted message mentions 'expensive'."""
        result = handler.handle(
            _with_transcript(blacklisted_input, "/tmp/agent-a/transcript.jsonl")
        )
        assert "expensive" in result.reason

    def test_first_fire_blacklisted_contains_recommended_alternative(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Verbose blacklisted message contains 'RECOMMENDED ALTERNATIVE' section."""
        result = handler.handle(
            _with_transcript(blacklisted_input, "/tmp/agent-a/transcript.jsonl")
        )
        assert "RECOMMENDED ALTERNATIVE" in result.reason

    def test_first_fire_blacklisted_leads_with_rule_id(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """The deny reason leads with a rule_id (Plan 00116 parity contract)."""
        result = handler.handle(
            _with_transcript(blacklisted_input, "/tmp/agent-a/transcript.jsonl")
        )
        assert result.reason.startswith(f"BLOCKED [{RuleID.PIPE_TO_TAIL}]")


# ── Blacklisted path: terse (repeat fires) ────────────────────────────────────


class TestBlacklistedTerseMessage:
    """A repeat fire of the SAME rule for the SAME agent is terse."""

    def _second_fire(self, handler: PipeBlockerHandler, blacklisted_input: dict) -> str:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(_with_transcript(blacklisted_input, transcript_path))
        result = handler.handle(_with_transcript(blacklisted_input, transcript_path))
        assert result.reason is not None
        return result.reason

    def test_second_fire_blacklisted_terse(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """A repeat fire produces a terse message for a blacklisted command."""
        reason = self._second_fire(handler, blacklisted_input)
        assert "BLOCKED" in reason
        assert "expensive" in reason
        assert "TEMP_FILE" in reason

    def test_second_fire_blacklisted_no_why_blocked_section(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Terse blacklisted message omits 'WHY BLOCKED' section."""
        assert "WHY BLOCKED" not in self._second_fire(handler, blacklisted_input)

    def test_second_fire_blacklisted_no_recommended_alternative_section(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Terse blacklisted message omits 'RECOMMENDED ALTERNATIVE' section."""
        assert "RECOMMENDED ALTERNATIVE" not in self._second_fire(handler, blacklisted_input)

    def test_many_fires_blacklisted_still_terse(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """A long run of repeat fires for the same agent stays terse."""
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        for _ in range(10):
            result = handler.handle(_with_transcript(blacklisted_input, transcript_path))
        assert result.reason is not None
        assert "BLOCKED" in result.reason
        assert "expensive" in result.reason
        assert "WHY BLOCKED" not in result.reason

    def test_terse_blacklisted_contains_command(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Terse blacklisted message includes the blocked command."""
        assert "COMMAND:" in self._second_fire(handler, blacklisted_input)

    def test_terse_blacklisted_contains_disable_hint(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Terse blacklisted message includes disable hint."""
        assert "pipe_blocker" in self._second_fire(handler, blacklisted_input)

    def test_terse_blacklisted_leads_with_rule_id(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """The terse reminder still leads with the rule_id."""
        assert self._second_fire(handler, blacklisted_input).startswith(
            f"BLOCKED [{RuleID.PIPE_TO_TAIL}]"
        )


# ── Unknown path: verbose (first fire) ────────────────────────────────────────


class TestUnknownVerboseMessage:
    """First fire for a given agent produces a verbose message for unknown commands."""

    def test_first_fire_unknown_contains_pipe_blocked(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Verbose unknown message contains 'Pipe to tail/head detected'."""
        result = handler.handle(_with_transcript(unknown_input, "/tmp/agent-a/transcript.jsonl"))
        assert "Pipe to tail/head detected" in result.reason

    def test_first_fire_unknown_contains_extra_whitelist(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Verbose unknown message mentions extra_whitelist."""
        result = handler.handle(_with_transcript(unknown_input, "/tmp/agent-a/transcript.jsonl"))
        assert "extra_whitelist" in result.reason

    def test_first_fire_unknown_contains_why_blocked(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Verbose unknown message contains 'WHY BLOCKED' section."""
        result = handler.handle(_with_transcript(unknown_input, "/tmp/agent-a/transcript.jsonl"))
        assert "WHY BLOCKED" in result.reason

    def test_first_fire_unknown_contains_whitelisted_info(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Verbose unknown message contains WHITELISTED COMMANDS section."""
        result = handler.handle(_with_transcript(unknown_input, "/tmp/agent-a/transcript.jsonl"))
        assert "WHITELISTED" in result.reason

    def test_first_fire_unknown_leads_with_rule_id(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """The deny reason leads with a rule_id (Plan 00116 parity contract)."""
        result = handler.handle(_with_transcript(unknown_input, "/tmp/agent-a/transcript.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.PIPE_TO_TAIL}]")


# ── Unknown path: terse (repeat fires) ─────────────────────────────────────────


class TestUnknownTerseMessage:
    """A repeat fire of the SAME rule for the SAME agent is terse."""

    def _second_fire(self, handler: PipeBlockerHandler, unknown_input: dict) -> str:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(_with_transcript(unknown_input, transcript_path))
        result = handler.handle(_with_transcript(unknown_input, transcript_path))
        assert result.reason is not None
        return result.reason

    def test_second_fire_unknown_terse(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """A repeat fire produces a terse message for an unknown command."""
        reason = self._second_fire(handler, unknown_input)
        assert "BLOCKED" in reason
        assert "unrecognized" in reason
        assert "extra_whitelist" in reason

    def test_second_fire_unknown_no_why_blocked_section(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message omits 'WHY BLOCKED' section."""
        assert "WHY BLOCKED" not in self._second_fire(handler, unknown_input)

    def test_second_fire_unknown_no_whitelisted_section(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message omits WHITELISTED COMMANDS section."""
        assert "WHITELISTED COMMANDS" not in self._second_fire(handler, unknown_input)

    def test_many_fires_unknown_still_terse(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """A long run of repeat fires for the same agent stays terse."""
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        for _ in range(10):
            result = handler.handle(_with_transcript(unknown_input, transcript_path))
        assert result.reason is not None
        assert "BLOCKED" in result.reason
        assert "unrecognized" in result.reason
        assert "WHY BLOCKED" not in result.reason

    def test_terse_unknown_contains_command(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message includes the blocked command."""
        assert "COMMAND:" in self._second_fire(handler, unknown_input)

    def test_terse_unknown_contains_temp_file_alternative(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message includes temp file alternative."""
        assert "TEMP_FILE" in self._second_fire(handler, unknown_input)

    def test_terse_unknown_contains_disable_hint(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message includes disable hint."""
        assert "pipe_blocker" in self._second_fire(handler, unknown_input)


# ── Disclosure ladder isolation ────────────────────────────────────────────────


class TestPipeBlockerDisclosureLadderIsolation:
    """Multi-agent / multi-rule isolation (Plan 00116, Decision G)."""

    def test_different_rule_same_agent_is_independently_verbose(
        self, handler: PipeBlockerHandler, blacklisted_input: dict, unknown_input: dict
    ) -> None:
        """A different consumer (head vs tail) for the same agent gets its own first fire."""
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(_with_transcript(blacklisted_input, transcript_path))
        head_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pytest tests/ | head -20"},
            "transcript_path": transcript_path,
        }
        result = handler.handle(head_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{RuleID.PIPE_TO_HEAD}]")
        assert "WHY BLOCKED" in result.reason

    def test_same_rule_different_agent_is_independently_verbose(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """A sub-agent (different transcript_path) never inherits another agent's disclosure."""
        handler.handle(_with_transcript(blacklisted_input, "/tmp/agent-a/transcript.jsonl"))
        result = handler.handle(
            _with_transcript(blacklisted_input, "/tmp/agent-b/transcript.jsonl")
        )
        assert result.reason is not None
        assert "WHY BLOCKED" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """No transcript_path in the payload -> always verbose (unknown state -> more info)."""
        first = handler.handle(blacklisted_input)
        second = handler.handle(blacklisted_input)
        assert first.reason is not None
        assert second.reason is not None
        assert "WHY BLOCKED" in first.reason
        assert "WHY BLOCKED" in second.reason


class TestPipeBlockerGetRules:
    """get_rules() declares the 2 Rule objects backing this handler (Plan 00116)."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_returns_two_rules(self, handler: PipeBlockerHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 2
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_ids_match_constants(self, handler: PipeBlockerHandler) -> None:
        actual = {rule.rule_id for rule in handler.get_rules()}
        assert actual == {RuleID.PIPE_TO_TAIL, RuleID.PIPE_TO_HEAD}

    def test_no_duplicate_rule_ids(self, handler: PipeBlockerHandler) -> None:
        rule_ids = [rule.rule_id for rule in handler.get_rules()]
        assert len(rule_ids) == len(set(rule_ids))

    def test_every_rule_has_non_empty_verbose(self, handler: PipeBlockerHandler) -> None:
        for rule in handler.get_rules():
            assert rule.verbose, f"{rule.rule_id} has empty verbose content"
