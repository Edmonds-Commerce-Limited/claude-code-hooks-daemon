"""Tests for optimal config checker handler.

Checks Claude Code environment for optimal configuration on session start.
Reports issues with explanations, benefits, and how-to-fix instructions.
"""

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.core import Decision


class TestOptimalConfigCheckerInit:
    """Test handler initialization."""

    def test_handler_id(self) -> None:
        """Test handler has correct ID."""
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        handler = OptimalConfigCheckerHandler()
        assert handler.handler_id.config_key == "optimal_config_checker"

    def test_non_terminal(self) -> None:
        """Test handler is non-terminal (advisory only)."""
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        handler = OptimalConfigCheckerHandler()
        assert handler.terminal is False

    def test_tags(self) -> None:
        """Test handler has correct tags."""
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        handler = OptimalConfigCheckerHandler()
        assert HandlerTag.ADVISORY in handler.tags
        assert HandlerTag.WORKFLOW in handler.tags
        assert HandlerTag.NON_TERMINAL in handler.tags


def _session_start_input(transcript_path: str | None = None) -> dict[str, Any]:
    """Create a SessionStart hook input."""
    hook_input: dict[str, Any] = {
        HookInputField.HOOK_EVENT_NAME: "SessionStart",
    }
    if transcript_path:
        hook_input[HookInputField.TRANSCRIPT_PATH] = transcript_path
    return hook_input


class TestOptimalConfigCheckerMatches:
    """Test matches() - should only match new sessions."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_matches_new_session(self, handler: Any) -> None:
        """Should match new sessions (no transcript or empty transcript)."""
        assert handler.matches(_session_start_input()) is True

    def test_matches_new_session_empty_transcript(self, handler: Any) -> None:
        """Should match when transcript file is empty."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.close()
        assert handler.matches(_session_start_input(tmp.name)) is True

    def test_no_match_resume_session(self, handler: Any) -> None:
        """Should NOT match resumed sessions (transcript has content)."""
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write("x" * 200)
        tmp.flush()
        tmp.close()
        assert handler.matches(_session_start_input(tmp.name)) is False


class TestAgentTeamsCheck:
    """Test agent teams env var check."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_agent_teams_enabled_passes(self, handler: Any) -> None:
        """No issue when CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1."""
        with patch.dict(os.environ, {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"}):
            checks = handler._run_checks()
            agent_teams = [c for c in checks if c["name"] == "Agent Teams"]
            assert len(agent_teams) == 1
            assert agent_teams[0]["passed"] is True

    def test_agent_teams_missing_fails(self, handler: Any) -> None:
        """Issue when CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS not set."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", None)
        with patch.dict(os.environ, env, clear=True):
            checks = handler._run_checks()
            agent_teams = [c for c in checks if c["name"] == "Agent Teams"]
            assert len(agent_teams) == 1
            assert agent_teams[0]["passed"] is False

    def test_agent_teams_zero_fails(self, handler: Any) -> None:
        """Issue when CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0."""
        with patch.dict(os.environ, {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "0"}):
            checks = handler._run_checks()
            agent_teams = [c for c in checks if c["name"] == "Agent Teams"]
            assert agent_teams[0]["passed"] is False


class TestEffortLevelCheck:
    """Test effort level check."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_effort_high_passes(self, handler: Any) -> None:
        """No issue when effort level is high."""
        with patch.dict(os.environ, {"CLAUDE_CODE_EFFORT_LEVEL": "high"}):
            checks = handler._run_checks()
            effort = [c for c in checks if c["name"] == "Effort Level"]
            assert effort[0]["passed"] is True

    def test_effort_medium_fails(self, handler: Any) -> None:
        """Issue when effort level is medium."""
        with patch.dict(os.environ, {"CLAUDE_CODE_EFFORT_LEVEL": "medium"}):
            checks = handler._run_checks()
            effort = [c for c in checks if c["name"] == "Effort Level"]
            assert effort[0]["passed"] is False

    def test_effort_low_fails(self, handler: Any) -> None:
        """Issue when effort level is low."""
        with patch.dict(os.environ, {"CLAUDE_CODE_EFFORT_LEVEL": "low"}):
            checks = handler._run_checks()
            effort = [c for c in checks if c["name"] == "Effort Level"]
            assert effort[0]["passed"] is False

    def test_effort_not_set_checks_settings(self, handler: Any) -> None:
        """When env var not set, checks settings.json."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
        settings = {"effortLevel": "high"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(handler, "_read_global_settings", return_value=settings),
        ):
            checks = handler._run_checks()
            effort = [c for c in checks if c["name"] == "Effort Level"]
            assert effort[0]["passed"] is True

    def test_effort_not_set_anywhere_fails(self, handler: Any) -> None:
        """Issue when effort level not set anywhere."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(handler, "_read_global_settings", return_value={}),
        ):
            checks = handler._run_checks()
            effort = [c for c in checks if c["name"] == "Effort Level"]
            assert effort[0]["passed"] is False


class TestExtendedThinkingCheck:
    """Test extended thinking check."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_thinking_enabled_passes(self, handler: Any) -> None:
        """No issue when alwaysThinkingEnabled is true."""
        settings = {"alwaysThinkingEnabled": True}
        with patch.object(handler, "_read_global_settings", return_value=settings):
            checks = handler._run_checks()
            thinking = [c for c in checks if c["name"] == "Extended Thinking"]
            assert thinking[0]["passed"] is True

    def test_thinking_disabled_fails(self, handler: Any) -> None:
        """Issue when alwaysThinkingEnabled is false."""
        settings = {"alwaysThinkingEnabled": False}
        with patch.object(handler, "_read_global_settings", return_value=settings):
            checks = handler._run_checks()
            thinking = [c for c in checks if c["name"] == "Extended Thinking"]
            assert thinking[0]["passed"] is False

    def test_thinking_not_set_fails(self, handler: Any) -> None:
        """Issue when alwaysThinkingEnabled not in settings."""
        with patch.object(handler, "_read_global_settings", return_value={}):
            checks = handler._run_checks()
            thinking = [c for c in checks if c["name"] == "Extended Thinking"]
            assert thinking[0]["passed"] is False


class TestMaxOutputTokensCheck:
    """Test max output tokens check."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_max_tokens_64000_passes(self, handler: Any) -> None:
        """No issue when max output tokens is 64000."""
        with patch.dict(os.environ, {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000"}):
            checks = handler._run_checks()
            tokens = [c for c in checks if c["name"] == "Max Output Tokens"]
            assert tokens[0]["passed"] is True

    def test_max_tokens_not_set_fails(self, handler: Any) -> None:
        """Issue when max output tokens not set (default 32000)."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_MAX_OUTPUT_TOKENS", None)
        with patch.dict(os.environ, env, clear=True):
            checks = handler._run_checks()
            tokens = [c for c in checks if c["name"] == "Max Output Tokens"]
            assert tokens[0]["passed"] is False

    def test_max_tokens_32000_fails(self, handler: Any) -> None:
        """Issue when max output tokens is default 32000."""
        with patch.dict(os.environ, {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000"}):
            checks = handler._run_checks()
            tokens = [c for c in checks if c["name"] == "Max Output Tokens"]
            assert tokens[0]["passed"] is False


class TestAutoMemoryCheck:
    """Test auto-memory check."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_auto_memory_not_disabled_passes(self, handler: Any) -> None:
        """No issue when CLAUDE_CODE_DISABLE_AUTO_MEMORY is not set."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_DISABLE_AUTO_MEMORY", None)
        with patch.dict(os.environ, env, clear=True):
            checks = handler._run_checks()
            memory = [c for c in checks if c["name"] == "Auto Memory"]
            assert memory[0]["passed"] is True

    def test_auto_memory_disabled_fails(self, handler: Any) -> None:
        """Issue when auto-memory is explicitly disabled."""
        with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}):
            checks = handler._run_checks()
            memory = [c for c in checks if c["name"] == "Auto Memory"]
            assert memory[0]["passed"] is False

    def test_auto_memory_zero_passes(self, handler: Any) -> None:
        """No issue when CLAUDE_CODE_DISABLE_AUTO_MEMORY=0 (not disabled)."""
        with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}):
            checks = handler._run_checks()
            memory = [c for c in checks if c["name"] == "Auto Memory"]
            assert memory[0]["passed"] is True


class TestBashMaintainWorkingDirCheck:
    """Test bash maintain working dir check."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_maintain_dir_enabled_passes(self, handler: Any) -> None:
        """No issue when CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1."""
        with patch.dict(os.environ, {"CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1"}):
            checks = handler._run_checks()
            bash_dir = [c for c in checks if c["name"] == "Bash Working Directory"]
            assert bash_dir[0]["passed"] is True

    def test_maintain_dir_not_set_fails(self, handler: Any) -> None:
        """Issue when CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR not set."""
        env = os.environ.copy()
        env.pop("CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR", None)
        with patch.dict(os.environ, env, clear=True):
            checks = handler._run_checks()
            bash_dir = [c for c in checks if c["name"] == "Bash Working Directory"]
            assert bash_dir[0]["passed"] is False


class TestHandleOutput:
    """Test handle() output formatting."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_returns_allow_decision(self, handler: Any) -> None:
        """Handle always returns ALLOW (advisory only)."""
        result = handler.handle(_session_start_input())
        assert result.decision == Decision.ALLOW

    def test_all_pass_shows_optimal(self, handler: Any) -> None:
        """When all checks pass, context should say optimal."""
        with (
            patch.dict(
                os.environ,
                {
                    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
                    "CLAUDE_CODE_EFFORT_LEVEL": "high",
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
                    "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1",
                },
            ),
            patch.object(
                handler,
                "_read_global_settings",
                return_value={"alwaysThinkingEnabled": True},
            ),
        ):
            env = os.environ.copy()
            env.pop("CLAUDE_CODE_DISABLE_AUTO_MEMORY", None)
            with patch.dict(os.environ, env, clear=True):
                # Re-set the values since clear=True wiped them
                with patch.dict(
                    os.environ,
                    {
                        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
                        "CLAUDE_CODE_EFFORT_LEVEL": "high",
                        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
                        "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1",
                    },
                ):
                    result = handler.handle(_session_start_input())
                    context = "\n".join(result.context)
                    assert "optimal" in context.lower() or "all checks passed" in context.lower()

    def test_failure_includes_how_to_fix(self, handler: Any) -> None:
        """Failed checks should include fix instructions."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(handler, "_read_global_settings", return_value={}),
        ):
            result = handler.handle(_session_start_input())
            context = "\n".join(result.context)
            # Should include fix instructions
            assert (
                "fix" in context.lower() or "set" in context.lower() or "enable" in context.lower()
            )

    def test_failure_includes_docs_link(self, handler: Any) -> None:
        """Failed checks should include link to docs."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(handler, "_read_global_settings", return_value={}),
        ):
            result = handler.handle(_session_start_input())
            context = "\n".join(result.context)
            assert "code.claude.com" in context or "docs" in context.lower()


class TestIsResumeSessionEdgeCases:
    """Test _is_resume_session edge cases for coverage."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_nonexistent_transcript_path_returns_false(self, handler: Any) -> None:
        """Non-existent transcript path returns False."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: "/nonexistent/path/transcript.jsonl"}
        assert handler._is_resume_session(hook_input) is False

    def test_stat_raises_oserror_returns_false(self, handler: Any, tmp_path: Any) -> None:
        """OSError from path.stat() returns False."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 200)
        hook_input = {HookInputField.TRANSCRIPT_PATH: str(transcript)}
        with patch("pathlib.Path.stat", side_effect=OSError("Permission denied")):
            assert handler._is_resume_session(hook_input) is False

    def test_value_error_returns_false(self, handler: Any) -> None:
        """ValueError from Path construction returns False."""
        hook_input = {HookInputField.TRANSCRIPT_PATH: "\x00invalid"}
        assert handler._is_resume_session(hook_input) is False


class TestReadGlobalSettingsEdgeCases:
    """Test _read_global_settings edge cases for coverage."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_settings_file_does_not_exist_returns_empty(self, handler: Any) -> None:
        """Returns empty dict when settings.json doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = handler._read_global_settings()
            assert result == {}

    def test_invalid_json_returns_empty(self, handler: Any, tmp_path: Any) -> None:
        """Returns empty dict when settings.json has invalid JSON."""
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("not valid json {{{")
        with patch("pathlib.Path.home", return_value=tmp_path):
            # Create the .claude directory structure
            claude_dir = tmp_path / ".claude"
            claude_dir.mkdir(exist_ok=True)
            real_settings = claude_dir / "settings.json"
            real_settings.write_text("not valid json {{{")
            result = handler._read_global_settings()
            assert result == {}

    def test_oserror_returns_empty(self, handler: Any) -> None:
        """Returns empty dict when OSError is raised."""
        with patch("pathlib.Path.home", side_effect=OSError("Home not found")):
            result = handler._read_global_settings()
            assert result == {}


class TestMaxOutputTokensNonNumeric:
    """Test _check_max_output_tokens with non-numeric values."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_non_numeric_env_var_fails(self, handler: Any) -> None:
        """Non-numeric CLAUDE_CODE_MAX_OUTPUT_TOKENS fails check."""
        with patch.dict(os.environ, {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "abc"}):
            result = handler._check_max_output_tokens()
            assert result["passed"] is False


class TestHandleMixedResults:
    """Test handle() with mix of passing and failing checks."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_mixed_pass_fail_shows_ok_line(self, handler: Any) -> None:
        """When some checks pass and some fail, output includes OK line."""
        # Set some passing, some failing
        with (
            patch.dict(
                os.environ,
                {
                    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
                    "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1",
                },
            ),
            patch.object(handler, "_read_global_settings", return_value={}),
        ):
            # Agent Teams and Bash Working Dir pass, others fail
            env = os.environ.copy()
            env.pop("CLAUDE_CODE_EFFORT_LEVEL", None)
            env.pop("CLAUDE_CODE_MAX_OUTPUT_TOKENS", None)
            with patch.dict(os.environ, env, clear=True):
                with patch.dict(
                    os.environ,
                    {
                        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
                        "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1",
                    },
                ):
                    result = handler.handle(_session_start_input())
                    context = "\n".join(result.context)
                    assert "OK:" in context
                    assert "Agent Teams" in context or "Bash Working Directory" in context


class TestWriteGlobalSettings:
    """Test _write_global_settings method."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_writes_settings_to_file(self, handler: Any, tmp_path: Any) -> None:
        """Should write settings dict as JSON to settings.json."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            result = handler._write_global_settings({"effortLevel": "high"})

        assert result is True
        written = json.loads(settings_path.read_text())
        assert written == {"effortLevel": "high"}

    def test_creates_parent_directory(self, handler: Any, tmp_path: Any) -> None:
        """Should create parent .claude directory if missing."""
        settings_path = tmp_path / ".claude" / "settings.json"
        assert not settings_path.parent.exists()

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            handler._write_global_settings({"key": "value"})

        assert settings_path.parent.exists()
        assert settings_path.exists()

    def test_returns_false_on_oserror(self, handler: Any) -> None:
        """Should return False when write fails."""
        with patch.object(
            handler, "_get_settings_path", return_value=Path("/nonexistent/deep/settings.json")
        ):
            with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
                result = handler._write_global_settings({"key": "value"})

        assert result is False


class TestEnforceSettingsSync:
    """Test _enforce_settings_sync method."""

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_writes_effort_level_when_missing(self, handler: Any, tmp_path: Any) -> None:
        """Should write effortLevel=high when missing from settings."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"alwaysThinkingEnabled": True}))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert "effortLevel=high" in written
        updated = json.loads(settings_path.read_text())
        assert updated["effortLevel"] == "high"
        assert updated["alwaysThinkingEnabled"] is True

    def test_writes_thinking_when_missing(self, handler: Any, tmp_path: Any) -> None:
        """Should write alwaysThinkingEnabled=true when missing from settings."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"effortLevel": "high"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert "alwaysThinkingEnabled=true" in written
        updated = json.loads(settings_path.read_text())
        assert updated["alwaysThinkingEnabled"] is True
        assert updated["effortLevel"] == "high"

    def test_writes_both_when_both_missing(self, handler: Any, tmp_path: Any) -> None:
        """Should write both settings when both are missing."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"model": "opus"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert len(written) == 2
        updated = json.loads(settings_path.read_text())
        assert updated["effortLevel"] == "high"
        assert updated["alwaysThinkingEnabled"] is True
        assert updated["model"] == "opus"

    def test_no_write_when_both_present(self, handler: Any, tmp_path: Any) -> None:
        """Should not write when both settings already exist."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        original = {"effortLevel": "medium", "alwaysThinkingEnabled": False}
        settings_path.write_text(json.dumps(original))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert written == []
        # Settings should be unchanged
        updated = json.loads(settings_path.read_text())
        assert updated == original

    def test_respects_existing_values(self, handler: Any, tmp_path: Any) -> None:
        """Should not overwrite existing effortLevel or alwaysThinkingEnabled values."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"effortLevel": "low", "alwaysThinkingEnabled": False}))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert written == []
        updated = json.loads(settings_path.read_text())
        assert updated["effortLevel"] == "low"
        assert updated["alwaysThinkingEnabled"] is False

    def test_handles_empty_settings_file(self, handler: Any, tmp_path: Any) -> None:
        """Should handle empty/no settings file gracefully."""
        settings_path = tmp_path / ".claude" / "settings.json"

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert len(written) == 2

    def test_aborts_on_read_error_to_avoid_clobbering(self, handler: Any, tmp_path: Any) -> None:
        """Should NOT write when settings file read fails (avoids clobbering)."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        original = {"model": "opus", "env": {"KEY": "val"}}
        settings_path.write_text(json.dumps(original))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            with patch("pathlib.Path.read_text", side_effect=OSError("Permission denied")):
                written = handler._enforce_settings_sync()

        assert written == []
        # Original file should be untouched
        updated = json.loads(settings_path.read_text())
        assert updated == original

    def test_aborts_on_invalid_json(self, handler: Any, tmp_path: Any) -> None:
        """Should NOT write when settings file has invalid JSON."""
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text("{invalid json{{")

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert written == []
        # File should be untouched
        assert settings_path.read_text() == "{invalid json{{"

    def test_aborts_on_non_dict_settings(self, handler: Any, tmp_path: Any) -> None:
        """Should NOT write when settings file contains a non-dict value."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps([1, 2, 3]))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert written == []

    def test_handle_reports_enforced_settings(self, handler: Any, tmp_path: Any) -> None:
        """Handle output should include CONFIG SYNC line when settings are written."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"model": "opus"}))

        with (
            patch.object(handler, "_get_settings_path", return_value=settings_path),
            patch.dict(
                os.environ,
                {
                    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
                    "CLAUDE_CODE_EFFORT_LEVEL": "high",
                    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
                    "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1",
                },
            ),
        ):
            result = handler.handle(_session_start_input())
            context = "\n".join(result.context)
            assert "CONFIG SYNC" in context


class TestAcceptanceTests:
    """Test acceptance test definitions."""

    def test_has_acceptance_tests(self) -> None:
        """Handler should define acceptance tests."""
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        handler = OptimalConfigCheckerHandler()
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
