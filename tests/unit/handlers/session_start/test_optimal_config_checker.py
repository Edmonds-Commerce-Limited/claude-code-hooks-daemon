"""Tests for optimal config checker handler.

Checks Claude Code environment for optimal configuration on session start.
Reports issues with explanations, benefits, and how-to-fix instructions.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta
from claude_code_hooks_daemon.core import Decision

# A project root with no `.claude/` settings of its own, for the checks that
# have nothing to do with project settings.
_NO_PROJECT = Path("/nonexistent/optimal-config-checker-test-project")


class TestOptimalConfigCheckerInit:
    """Test handler initialization."""

    def test_handler_id(self) -> None:
        """Test handler has correct ID."""
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        handler = OptimalConfigCheckerHandler()
        assert isinstance(handler.handler_id, HandlerIDMeta)
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
            checks = handler._run_checks(_NO_PROJECT)
            agent_teams = [c for c in checks if c["name"] == "Agent Teams"]
            assert len(agent_teams) == 1
            assert agent_teams[0]["passed"] is True

    def test_agent_teams_missing_fails(self, handler: Any) -> None:
        """Issue when CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS not set."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", None)
        with patch.dict(os.environ, env, clear=True):
            checks = handler._run_checks(_NO_PROJECT)
            agent_teams = [c for c in checks if c["name"] == "Agent Teams"]
            assert len(agent_teams) == 1
            assert agent_teams[0]["passed"] is False

    def test_agent_teams_zero_fails(self, handler: Any) -> None:
        """Issue when CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0."""
        with patch.dict(os.environ, {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "0"}):
            checks = handler._run_checks(_NO_PROJECT)
            agent_teams = [c for c in checks if c["name"] == "Agent Teams"]
            assert agent_teams[0]["passed"] is False


_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


class TestEffortSourceCheck:
    """Plan 00466 N47 review 4 finding 2: settings.json decides effort, per model.

    The owner sets a level per model in `modelSettings` (Fable low, its
    fallbacks xhigh, Opus 5.5 left at its medium default). Three things pin
    ONE level on every model and silently defeat that: the
    `CLAUDE_CODE_EFFORT_LEVEL` environment variable, and a top-level
    `effortLevel` in the project's or the local settings file. The check warns
    about exactly those and never recommends a level of its own -- the daemon
    holding an effort opinion is what the single-source-of-truth rule forbids.
    A top-level `effortLevel` in the USER file is not a pin: a per-model entry
    in the same file outranks it, and it does not apply to Opus 5.5 at all.
    """

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    @pytest.fixture(autouse=True)
    def _no_ambient_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAUDE_CODE_EFFORT_LEVEL", raising=False)

    @staticmethod
    def _effort(handler: Any, project_root: Path) -> dict[str, Any]:
        with patch.object(handler, "_read_global_settings", return_value={}):
            checks = handler._run_checks(project_root)
        found = [c for c in checks if c["name"] == "Effort Source"]
        assert len(found) == 1
        return cast("dict[str, Any]", found[0])

    @staticmethod
    def _write(project_root: Path, name: str, text: str) -> None:
        (project_root / ".claude").mkdir(parents=True, exist_ok=True)
        (project_root / ".claude" / name).write_text(text, encoding="utf-8")

    def test_nothing_pinning_effort_passes(self, handler: Any, tmp_path: Path) -> None:
        effort = self._effort(handler, tmp_path)

        assert effort["passed"] is True
        assert "modelSettings" in effort["current"]

    def test_user_settings_levels_are_not_a_pin(self, handler: Any, tmp_path: Path) -> None:
        user = {
            "effortLevel": "high",
            "modelSettings": {"claude-fable-5-1": {"effortLevel": "low"}},
        }
        with patch.object(handler, "_read_global_settings", return_value=user):
            checks = handler._run_checks(tmp_path)

        effort = [c for c in checks if c["name"] == "Effort Source"]
        assert effort[0]["passed"] is True

    @pytest.mark.parametrize("level", _EFFORT_LEVELS)
    def test_the_environment_variable_is_a_warning_at_any_level(
        self, handler: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", level)

        effort = self._effort(handler, tmp_path)

        assert effort["passed"] is False
        assert effort["warn"] is True
        assert "CLAUDE_CODE_EFFORT_LEVEL" in effort["current"]
        assert level in effort["current"]
        assert "unset CLAUDE_CODE_EFFORT_LEVEL" in effort["fix"]

    @pytest.mark.parametrize("value", ["auto", "unset", "AUTO", ""])
    def test_an_environment_value_claude_code_ignores_is_not_a_pin(
        self, handler: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """`auto` and `unset` resolve to no explicit level, so nothing is pinned."""
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", value)

        assert self._effort(handler, tmp_path)["passed"] is True

    @pytest.mark.parametrize("name", ["settings.json", "settings.local.json"])
    def test_a_top_level_level_in_project_or_local_settings_is_a_warning(
        self, handler: Any, tmp_path: Path, name: str
    ) -> None:
        self._write(tmp_path, name, json.dumps({"effortLevel": "high"}))

        effort = self._effort(handler, tmp_path)

        assert effort["passed"] is False
        assert effort["warn"] is True
        assert f".claude/{name}" in effort["current"]
        assert "effortLevel" in effort["fix"]

    @pytest.mark.parametrize("name", ["settings.json", "settings.local.json"])
    def test_per_model_levels_in_project_settings_are_not_a_pin(
        self, handler: Any, tmp_path: Path, name: str
    ) -> None:
        self._write(
            tmp_path,
            name,
            json.dumps({"modelSettings": {"claude-opus-5": {"effortLevel": "xhigh"}}}),
        )

        assert self._effort(handler, tmp_path)["passed"] is True

    @pytest.mark.parametrize("text", ["{not json", "[1, 2]"], ids=["malformed", "not-an-object"])
    def test_an_unreadable_project_settings_file_cannot_be_confirmed(
        self, handler: Any, tmp_path: Path, text: str
    ) -> None:
        """Not knowing is not the same as nothing being pinned."""
        self._write(tmp_path, "settings.json", text)

        effort = self._effort(handler, tmp_path)

        assert effort["passed"] is False
        assert effort["warn"] is True
        assert ".claude/settings.json" in effort["current"]

    def test_a_settings_file_raising_oserror_on_read_cannot_be_confirmed(
        self, handler: Any, tmp_path: Path
    ) -> None:
        """Review 5 finding 4 (K1): only malformed JSON (`ValueError`) was ever

        exercised here, leaving the `OSError` arm of the same `except` clause
        untested. A directory where the settings file should be raises
        `IsADirectoryError` (an `OSError`) on `read_text()` -- no chmod, so
        this is not vacuous running as root.
        """
        (tmp_path / ".claude" / "settings.json").mkdir(parents=True)

        effort = self._effort(handler, tmp_path)

        assert effort["passed"] is False
        assert effort["warn"] is True
        assert ".claude/settings.json" in effort["current"]

    def test_every_pin_is_named_at_once(
        self, handler: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "medium")
        self._write(tmp_path, "settings.json", json.dumps({"effortLevel": "low"}))
        self._write(tmp_path, "settings.local.json", json.dumps({"effortLevel": "max"}))

        current = self._effort(handler, tmp_path)["current"]

        assert "CLAUDE_CODE_EFFORT_LEVEL" in current
        assert ".claude/settings.json" in current
        assert ".claude/settings.local.json" in current

    def test_no_state_ever_recommends_a_level(
        self, handler: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The advice may name what to REMOVE, never a level to set."""
        results = [self._effort(handler, tmp_path)]
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "high")
        self._write(tmp_path, "settings.json", json.dumps({"effortLevel": "high"}))
        results.append(self._effort(handler, tmp_path))

        for result in results:
            advice = f"{result['why']} {result['fix']} {result['where']}"
            for level in _EFFORT_LEVELS:
                assert f'"{level}"' not in advice
                assert f"={level}" not in advice

    def test_the_old_prescriptive_effort_check_is_gone(self, handler: Any, tmp_path: Path) -> None:
        with patch.object(handler, "_read_global_settings", return_value={}):
            names = [c["name"] for c in handler._run_checks(tmp_path)]

        assert "Effort Level" not in names

    @pytest.mark.parametrize("name", ["settings.json", "settings.local.json"])
    def test_an_env_object_pin_in_project_or_local_settings_is_a_warning(
        self, handler: Any, tmp_path: Path, name: str
    ) -> None:
        """Review 5 finding 3: Claude Code applies a settings `env` object like

        the shell -- a pin there is the same every-model override as
        `CLAUDE_CODE_EFFORT_LEVEL` itself, and the check's own `where` line
        already claimed to look here.
        """
        self._write(tmp_path, name, json.dumps({"env": {"CLAUDE_CODE_EFFORT_LEVEL": "high"}}))

        effort = self._effort(handler, tmp_path)

        assert effort["passed"] is False
        assert effort["warn"] is True
        assert f".claude/{name}" in effort["current"]
        assert "CLAUDE_CODE_EFFORT_LEVEL" in effort["current"]

    def test_an_env_object_pin_in_user_settings_is_a_warning(
        self, handler: Any, tmp_path: Path
    ) -> None:
        """Unlike a top-level `effortLevel`, a user-file `env` pin is NOT

        outranked by a per-model `modelSettings` entry in the same file --
        it is an unconditional environment override, applied before Claude
        Code even looks at `modelSettings`.
        """
        user = {
            "env": {"CLAUDE_CODE_EFFORT_LEVEL": "low"},
            "modelSettings": {"claude-fable-5-1": {"effortLevel": "low"}},
        }
        with patch.object(handler, "_read_global_settings", return_value=user):
            checks = handler._run_checks(tmp_path)

        effort = next(c for c in checks if c["name"] == "Effort Source")
        assert effort["passed"] is False
        assert effort["warn"] is True
        assert "~/.claude/settings.json" in effort["current"]
        assert "CLAUDE_CODE_EFFORT_LEVEL" in effort["current"]

    @pytest.mark.parametrize("value", ["auto", "unset", "AUTO", ""])
    def test_a_non_pinning_env_object_value_is_not_a_pin(
        self, handler: Any, tmp_path: Path, value: str
    ) -> None:
        self._write(
            tmp_path, "settings.json", json.dumps({"env": {"CLAUDE_CODE_EFFORT_LEVEL": value}})
        )

        assert self._effort(handler, tmp_path)["passed"] is True

    @pytest.mark.parametrize("level", [None, "auto", "AUTO", "unset", ""])
    def test_a_non_pinning_top_level_effort_level_is_not_a_pin(
        self, handler: Any, tmp_path: Path, level: str | None
    ) -> None:
        """`null`/`auto`/`unset` resolve to no explicit level, same as the env var."""
        self._write(tmp_path, "settings.json", json.dumps({"effortLevel": level}))

        assert self._effort(handler, tmp_path)["passed"] is True


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
            checks = handler._run_checks(_NO_PROJECT)
            thinking = [c for c in checks if c["name"] == "Extended Thinking"]
            assert thinking[0]["passed"] is True

    def test_thinking_disabled_fails(self, handler: Any) -> None:
        """Issue when alwaysThinkingEnabled is false."""
        settings = {"alwaysThinkingEnabled": False}
        with patch.object(handler, "_read_global_settings", return_value=settings):
            checks = handler._run_checks(_NO_PROJECT)
            thinking = [c for c in checks if c["name"] == "Extended Thinking"]
            assert thinking[0]["passed"] is False

    def test_thinking_not_set_fails(self, handler: Any) -> None:
        """Issue when alwaysThinkingEnabled not in settings."""
        with patch.object(handler, "_read_global_settings", return_value={}):
            checks = handler._run_checks(_NO_PROJECT)
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
            checks = handler._run_checks(_NO_PROJECT)
            tokens = [c for c in checks if c["name"] == "Max Output Tokens"]
            assert tokens[0]["passed"] is True

    def test_max_tokens_not_set_fails(self, handler: Any) -> None:
        """Issue when max output tokens not set (default 32000)."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_MAX_OUTPUT_TOKENS", None)
        with patch.dict(os.environ, env, clear=True):
            checks = handler._run_checks(_NO_PROJECT)
            tokens = [c for c in checks if c["name"] == "Max Output Tokens"]
            assert tokens[0]["passed"] is False

    def test_max_tokens_32000_fails(self, handler: Any) -> None:
        """Issue when max output tokens is default 32000."""
        with patch.dict(os.environ, {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000"}):
            checks = handler._run_checks(_NO_PROJECT)
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
        """No issue when CLAUDE_CODE_DISABLE_AUTO_MEMORY is not set.

        Policy forced inactive so this isolates the auto-memory env-var branch
        (the policy-active branch has its own test class).
        """
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_DISABLE_AUTO_MEMORY", None)
        with patch.object(handler, "_untracked_memory_forbidden", return_value=False):
            with patch.dict(os.environ, env, clear=True):
                checks = handler._run_checks(_NO_PROJECT)
                memory = [c for c in checks if c["name"] == "Auto Memory"]
                assert memory[0]["passed"] is True

    def test_auto_memory_disabled_fails(self, handler: Any) -> None:
        """Issue when auto-memory is explicitly disabled (policy inactive)."""
        with patch.object(handler, "_untracked_memory_forbidden", return_value=False):
            with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}):
                checks = handler._run_checks(_NO_PROJECT)
                memory = [c for c in checks if c["name"] == "Auto Memory"]
                assert memory[0]["passed"] is False

    def test_auto_memory_zero_passes(self, handler: Any) -> None:
        """No issue when CLAUDE_CODE_DISABLE_AUTO_MEMORY=0 (policy inactive)."""
        with patch.object(handler, "_untracked_memory_forbidden", return_value=False):
            with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0"}):
                checks = handler._run_checks(_NO_PROJECT)
                memory = [c for c in checks if c["name"] == "Auto Memory"]
                assert memory[0]["passed"] is True


class TestAutoMemoryUnderTrackedDocsPolicy:
    """Auto-memory check reconciled with allow_untracked_claude_memory: false (Plan 00131).

    When a project forbids untracked Claude memory, the daemon BLOCKS the writes —
    so optimal_config_checker must NOT also nag the user to re-enable memory.
    """

    @pytest.fixture
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        return OptimalConfigCheckerHandler()

    def test_policy_active_memory_enabled_does_not_nag(self, handler: Any) -> None:
        """Under policy, memory ENABLED must still pass (no contradictory advice)."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_DISABLE_AUTO_MEMORY", None)
        with patch.object(handler, "_untracked_memory_forbidden", return_value=True):
            with patch.dict(os.environ, env, clear=True):
                check = handler._check_auto_memory()
        assert check["passed"] is True
        # Must NOT advise re-enabling memory under the policy
        assert "Remove or unset" not in check["fix"]
        assert "tracked" in check["why"].lower()

    def test_policy_active_memory_disabled_passes(self, handler: Any) -> None:
        """Under policy, memory DISABLED is fine — still passes, no nag."""
        with patch.object(handler, "_untracked_memory_forbidden", return_value=True):
            with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}):
                check = handler._check_auto_memory()
        assert check["passed"] is True

    def test_policy_active_mentions_block(self, handler: Any) -> None:
        """Under policy, the check explains the daemon block / tracked-docs policy."""
        with patch.object(handler, "_untracked_memory_forbidden", return_value=True):
            with patch.dict(os.environ, {}, clear=True):
                check = handler._check_auto_memory()
        assert "allow_untracked_claude_memory" in check["why"]

    def test_policy_inactive_preserves_default_nag(self, handler: Any) -> None:
        """Without the policy, default behaviour is unchanged (disabled => fails)."""
        with patch.object(handler, "_untracked_memory_forbidden", return_value=False):
            with patch.dict(os.environ, {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}):
                check = handler._check_auto_memory()
        assert check["passed"] is False
        assert "Remove or unset" in check["fix"]

    def test_unset_option_reads_as_forbidden_after_default_flip(self, handler: Any) -> None:
        """SSoT default flip (v3.24.0): an UNSET option now reads as forbidden.

        Regression guard for the drift bug — _untracked_memory_forbidden must use
        the shipped default (False) as its fallback, so an upgraded client who
        never set the option is not nagged to re-enable memory while the daemon
        is in fact blocking it.
        """
        from pathlib import Path
        from unittest.mock import MagicMock

        fake_config = MagicMock()
        fake_config.handlers.pre_tool_use = {}  # no markdown_organization entry
        with patch(
            "claude_code_hooks_daemon.core.ProjectContext.config_path",
            return_value=Path("/tmp/does-not-matter.yaml"),
        ):
            with patch(
                "claude_code_hooks_daemon.config.models.Config.load_or_default",
                return_value=fake_config,
            ):
                assert handler._untracked_memory_forbidden() is True


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
            checks = handler._run_checks(_NO_PROJECT)
            bash_dir = [c for c in checks if c["name"] == "Bash Working Directory"]
            assert bash_dir[0]["passed"] is True

    def test_maintain_dir_not_set_fails(self, handler: Any) -> None:
        """Issue when CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR not set."""
        env = os.environ.copy()
        env.pop("CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR", None)
        with patch.dict(os.environ, env, clear=True):
            checks = handler._run_checks(_NO_PROJECT)
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

    def test_all_pass_is_silent(self, handler: Any) -> None:
        """Lean SessionStart (Plan 00128): the config audit is NOT reported at
        session start. With nothing enforced, the handler emits no context.

        The verbose audit (optimal/fix/docs content) now lives in the
        ``cli check`` command, tested in tests/unit/daemon/test_cli_check.py.
        """
        with patch.object(handler, "_enforce_settings_sync", return_value=[]):
            result = handler.handle(_session_start_input())
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_failures_are_silent_at_session_start(self, handler: Any) -> None:
        """Even when checks would fail, the handler stays silent at session start
        (the report moved to the ``cli check`` command)."""
        env = os.environ.copy()
        env.pop("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", None)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(handler, "_read_global_settings", return_value={}),
            patch.object(handler, "_enforce_settings_sync", return_value=[]),
        ):
            result = handler.handle(_session_start_input())
        assert result.context == []


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

    def test_does_not_write_effort_level_when_missing(self, handler: Any, tmp_path: Any) -> None:
        """Never auto-writes effortLevel (Plan 00466 N47 review 3 finding 10).

        Writing an effort opinion into the owner's settings.json is exactly
        the second-party-to-the-fight problem the ccy supervisor redesign
        removed; this handler must not reintroduce it via a different path.
        `cli check` only warns about a pin that overrides settings.json
        (`_check_effort_source`).
        """
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"alwaysThinkingEnabled": True}))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert not any("effortLevel" in item for item in written)
        updated = json.loads(settings_path.read_text())
        assert "effortLevel" not in updated
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

    def test_writes_only_thinking_when_both_missing(self, handler: Any, tmp_path: Any) -> None:
        """Should write alwaysThinkingEnabled only; effortLevel is never auto-set."""
        import json

        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(json.dumps({"model": "opus"}))

        with patch.object(handler, "_get_settings_path", return_value=settings_path):
            written = handler._enforce_settings_sync()

        assert written == ["alwaysThinkingEnabled=true"]
        updated = json.loads(settings_path.read_text())
        assert "effortLevel" not in updated
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

        assert written == ["alwaysThinkingEnabled=true"]

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

    def test_acceptance_pattern_matches_real_output(self, tmp_path: Any) -> None:
        """The acceptance pattern must match the string handle() actually emits.

        handle() only ever emits 'CONFIG SYNC: ...' (never 'CONFIG CHECK') and
        only when settings are written. The acceptance expected_message_pattern
        must match that real output.
        """
        import json
        import re

        from claude_code_hooks_daemon.handlers.session_start.optimal_config_checker import (
            OptimalConfigCheckerHandler,
        )

        handler = OptimalConfigCheckerHandler()
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

        rendered = "\n".join(result.context)
        patterns = handler.get_acceptance_tests()[0].expected_message_patterns
        assert patterns
        assert all(re.search(pattern, rendered) for pattern in patterns)
