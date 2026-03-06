"""Tests for PipeBlockerHandler progressive verbosity."""

from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


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
