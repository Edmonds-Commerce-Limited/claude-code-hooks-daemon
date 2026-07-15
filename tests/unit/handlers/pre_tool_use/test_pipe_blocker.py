"""Tests for PipeBlockerHandler progressive verbosity."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

_PROJECT_CONTEXT_PATH = "claude_code_hooks_daemon.core.project_context.ProjectContext"


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
        count: int,
        daemon_dir: Path | None = None,
    ) -> str:
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = count
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
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
        reason = self._handle(handler, blacklisted_input, 0, daemon_dir=tmp_path)
        assert "echd-capture" in reason
        assert str(tmp_path / "scripts" / "echd-capture") in reason
        assert "pipefail" in reason

    def test_terse_blacklisted_recommends_echd_capture(
        self, handler: PipeBlockerHandler, blacklisted_input: dict, tmp_path: Path
    ) -> None:
        _deploy_fake_helper(tmp_path)
        assert "echd-capture" in self._handle(handler, blacklisted_input, 3, daemon_dir=tmp_path)

    def test_verbose_unknown_recommends_echd_capture(
        self, handler: PipeBlockerHandler, unknown_input: dict, tmp_path: Path
    ) -> None:
        _deploy_fake_helper(tmp_path)
        reason = self._handle(handler, unknown_input, 0, daemon_dir=tmp_path)
        assert "echd-capture" in reason
        assert "pipefail" in reason

    def test_terse_unknown_recommends_echd_capture(
        self, handler: PipeBlockerHandler, unknown_input: dict, tmp_path: Path
    ) -> None:
        _deploy_fake_helper(tmp_path)
        assert "echd-capture" in self._handle(handler, unknown_input, 3, daemon_dir=tmp_path)

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
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with (
            patch(
                "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
                return_value=mock_dl,
            ),
            patch(
                f"{_PROJECT_CONTEXT_PATH}.daemon_untracked_dir",
                side_effect=RuntimeError("not initialised"),
            ),
        ):
            reason = handler.handle(blacklisted_input).reason

        assert reason is not None
        assert "echd-capture" not in reason
        assert "TEMP_FILE" in reason
        assert "RECOMMENDED ALTERNATIVE" in reason


# ── _get_block_count() ────────────────────────────────────────────────────────


class TestGetBlockCount:
    """Tests for _get_block_count() method."""

    def test_returns_zero_when_no_previous_blocks(self, handler: PipeBlockerHandler) -> None:
        """Returns 0 when data layer reports no previous blocks."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            assert handler._get_block_count() == 0

    def test_returns_count_from_data_layer(self, handler: PipeBlockerHandler) -> None:
        """Returns the count provided by data layer."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 5
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            assert handler._get_block_count() == 5

    def test_returns_zero_on_data_layer_exception(self, handler: PipeBlockerHandler) -> None:
        """Falls back to 0 when data layer raises an exception."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.side_effect = Exception("Data layer error")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            assert handler._get_block_count() == 0

    def test_queries_handler_name(self, handler: PipeBlockerHandler) -> None:
        """Passes handler name to count_blocks_by_handler."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            handler._get_block_count()
        mock_dl.history.count_blocks_by_handler.assert_called_once_with(handler.name)


# ── Blacklisted path: verbose (first block) ──────────────────────────────────


class TestBlacklistedVerboseMessage:
    """First block (count=0) for blacklisted commands produces verbose message."""

    def test_first_block_blacklisted_contains_pipe_blocked(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Verbose blacklisted message contains 'Pipe to tail/head detected'."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "Pipe to tail/head detected" in result.reason

    def test_first_block_blacklisted_contains_why_blocked(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Verbose blacklisted message contains 'WHY BLOCKED' section."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "WHY BLOCKED" in result.reason

    def test_first_block_blacklisted_contains_expensive(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Verbose blacklisted message mentions 'expensive'."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "expensive" in result.reason

    def test_first_block_blacklisted_contains_recommended_alternative(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Verbose blacklisted message contains 'RECOMMENDED ALTERNATIVE' section."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "RECOMMENDED ALTERNATIVE" in result.reason


# ── Blacklisted path: terse (subsequent blocks) ───────────────────────────────


class TestBlacklistedTerseMessage:
    """Subsequent blocks (count>=1) for blacklisted commands produce terse message."""

    def test_second_block_blacklisted_terse(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """count=1 produces terse message for blacklisted command."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "BLOCKED" in result.reason
        assert "expensive" in result.reason
        assert "TEMP_FILE" in result.reason

    def test_second_block_blacklisted_no_why_blocked_section(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Terse blacklisted message omits 'WHY BLOCKED' section."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "WHY BLOCKED" not in result.reason

    def test_second_block_blacklisted_no_recommended_alternative_section(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Terse blacklisted message omits 'RECOMMENDED ALTERNATIVE' section."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "RECOMMENDED ALTERNATIVE" not in result.reason

    def test_many_blocks_blacklisted_still_terse(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """count=10 still produces terse message for blacklisted command."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 10
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "BLOCKED" in result.reason
        assert "expensive" in result.reason
        assert "WHY BLOCKED" not in result.reason

    def test_terse_blacklisted_contains_command(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Terse blacklisted message includes the blocked command."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "COMMAND:" in result.reason

    def test_terse_blacklisted_contains_disable_hint(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Terse blacklisted message includes disable hint."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "pipe_blocker" in result.reason


# ── Unknown path: verbose (first block) ──────────────────────────────────────


class TestUnknownVerboseMessage:
    """First block (count=0) for unknown commands produces verbose message."""

    def test_first_block_unknown_contains_pipe_blocked(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Verbose unknown message contains 'Pipe to tail/head detected'."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "Pipe to tail/head detected" in result.reason

    def test_first_block_unknown_contains_extra_whitelist(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Verbose unknown message mentions extra_whitelist."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "extra_whitelist" in result.reason

    def test_first_block_unknown_contains_why_blocked(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Verbose unknown message contains 'WHY BLOCKED' section."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "WHY BLOCKED" in result.reason

    def test_first_block_unknown_contains_whitelisted_info(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Verbose unknown message contains WHITELISTED COMMANDS section."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "WHITELISTED" in result.reason


# ── Unknown path: terse (subsequent blocks) ───────────────────────────────────


class TestUnknownTerseMessage:
    """Subsequent blocks (count>=1) for unknown commands produce terse message."""

    def test_second_block_unknown_terse(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """count=1 produces terse message for unknown command."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "BLOCKED" in result.reason
        assert "unrecognized" in result.reason
        assert "extra_whitelist" in result.reason

    def test_second_block_unknown_no_why_blocked_section(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message omits 'WHY BLOCKED' section."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "WHY BLOCKED" not in result.reason

    def test_second_block_unknown_no_whitelisted_section(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message omits WHITELISTED COMMANDS section."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "WHITELISTED COMMANDS" not in result.reason

    def test_many_blocks_unknown_still_terse(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """count=10 still produces terse message for unknown command."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 10
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "BLOCKED" in result.reason
        assert "unrecognized" in result.reason
        assert "WHY BLOCKED" not in result.reason

    def test_terse_unknown_contains_command(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message includes the blocked command."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "COMMAND:" in result.reason

    def test_terse_unknown_contains_temp_file_alternative(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message includes temp file alternative."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "TEMP_FILE" in result.reason

    def test_terse_unknown_contains_disable_hint(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Terse unknown message includes disable hint."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "pipe_blocker" in result.reason


# ── Data layer error fallback ─────────────────────────────────────────────────


class TestDataLayerErrorFallback:
    """When data layer errors, falls back to verbose (count=0) message."""

    def test_data_layer_error_blacklisted_falls_back_to_verbose(
        self, handler: PipeBlockerHandler, blacklisted_input: dict
    ) -> None:
        """Data layer error for blacklisted path falls back to verbose message."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.side_effect = Exception("Data layer error")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(blacklisted_input)
        assert "WHY BLOCKED" in result.reason
        assert "expensive" in result.reason

    def test_data_layer_error_unknown_falls_back_to_verbose(
        self, handler: PipeBlockerHandler, unknown_input: dict
    ) -> None:
        """Data layer error for unknown path falls back to verbose message."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.side_effect = Exception("Data layer error")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(unknown_input)
        assert "WHY BLOCKED" in result.reason
        assert "extra_whitelist" in result.reason
