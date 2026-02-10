"""Comprehensive tests for PipeBlockerHandler."""

from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestPipeBlockerHandler:
    """Test suite for PipeBlockerHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return PipeBlockerHandler()

    # ===================================================================================
    # Phase 1: Initialization Tests (5 tests)
    # ===================================================================================

    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'pipe-blocker'."""
        assert handler.name == "pipe-blocker"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 15."""
        assert handler.priority == 15

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal."""
        assert handler.terminal is True

    def test_init_sets_correct_tags(self, handler):
        """Handler should have correct tags."""
        expected_tags = ["safety", "bash", "blocking", "terminal"]
        assert handler.tags == expected_tags

    def test_init_sets_default_allowed_pipe_sources(self, handler):
        """Handler should initialize with default whitelist."""
        # Default whitelist should include common filtering commands
        expected_defaults = ["grep", "rg", "awk", "sed", "jq", "cut", "sort", "uniq"]
        assert hasattr(handler, "_allowed_pipe_sources")
        assert isinstance(handler._allowed_pipe_sources, list)
        # Check that key defaults are present
        for cmd in expected_defaults:
            assert cmd in handler._allowed_pipe_sources

    # ===================================================================================
    # Phase 3: Basic Pipe Detection Tests (10+ tests)
    # ===================================================================================

    def test_matches_find_piped_to_tail(self, handler):
        """Should match expensive find command piped to tail."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.py' | tail -n 20"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_test_piped_to_head(self, handler):
        """Should match expensive npm test piped to head."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "npm run test | head -n 10"}}
        assert handler.matches(hook_input) is True

    def test_no_match_tail_without_pipe(self, handler):
        """Should NOT match direct file operation without pipe."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "tail -n 20 /var/log/syslog"}}
        assert handler.matches(hook_input) is False

    def test_no_match_tail_follow_mode(self, handler):
        """Should NOT match tail -f (follow mode)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "tail -f /var/log/syslog"}}
        assert handler.matches(hook_input) is False

    def test_no_match_head_byte_count(self, handler):
        """Should NOT match head -c (byte count mode)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "head -c 1024 file.txt"}}
        assert handler.matches(hook_input) is False

    def test_no_match_empty_command(self, handler):
        """Should NOT match empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert handler.matches(hook_input) is False

    def test_no_match_non_bash_tool(self, handler):
        """Should NOT match non-Bash tool."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/test.txt"}}
        assert handler.matches(hook_input) is False

    def test_no_match_missing_command_field(self, handler):
        """Should NOT match when command field is missing."""
        hook_input = {"tool_name": "Bash", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_matches_case_insensitive_tail(self, handler):
        """Should match TAIL with uppercase."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | TAIL -n 10"}}
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive_head(self, handler):
        """Should match Head with mixed case."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "docker ps | Head -n 5"}}
        assert handler.matches(hook_input) is True

    def test_matches_spacing_variation_no_space(self, handler):
        """Should match pipe with no space before tail."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls -la|tail -n 10"}}
        assert handler.matches(hook_input) is True

    def test_matches_spacing_variation_multiple_spaces(self, handler):
        """Should match pipe with multiple spaces."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls -la |  tail -n 10"}}
        assert handler.matches(hook_input) is True

    def test_matches_docker_ps_piped_to_tail(self, handler):
        """Should match docker ps piped to tail."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "docker ps -a | tail -n 20"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_log_piped_to_head(self, handler):
        """Should match git log piped to head."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git log --oneline | head -n 10"},
        }
        assert handler.matches(hook_input) is True

    # ===================================================================================
    # Phase 4: Whitelist Logic Tests (25+ tests)
    # ===================================================================================

    def test_no_match_grep_piped_to_tail(self, handler):
        """Should NOT match grep piped to tail (whitelisted)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep error /var/log/syslog | tail -n 20"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_rg_piped_to_head(self, handler):
        """Should NOT match ripgrep piped to head (whitelisted)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "rg 'pattern' . | head -n 10"}}
        assert handler.matches(hook_input) is False

    def test_no_match_awk_piped_to_tail(self, handler):
        """Should NOT match awk piped to tail (whitelisted)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "awk '{print $1}' data.txt | tail -n 5"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_jq_piped_to_tail(self, handler):
        """Should NOT match jq piped to tail (whitelisted)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "jq '.items' data.json | tail -n 15"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_sed_piped_to_head(self, handler):
        """Should NOT match sed piped to head (whitelisted)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -n '1,100p' file.txt | head -n 20"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_cut_piped_to_tail(self, handler):
        """Should NOT match cut piped to tail (whitelisted)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cut -d: -f1 /etc/passwd | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_sort_piped_to_head(self, handler):
        """Should NOT match sort piped to head (whitelisted)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sort names.txt | head -n 5"}}
        assert handler.matches(hook_input) is False

    def test_no_match_uniq_piped_to_tail(self, handler):
        """Should NOT match uniq piped to tail (whitelisted)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "uniq -c data.txt | tail -n 20"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_tr_piped_to_head(self, handler):
        """Should NOT match tr piped to head (whitelisted)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "tr '[:lower:]' '[:upper:]' < file.txt | head -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_wc_piped_to_tail(self, handler):
        """Should NOT match wc piped to tail (whitelisted)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "wc -l *.txt | tail -n 5"}}
        assert handler.matches(hook_input) is False

    def test_no_match_complex_chain_grep_awk_tail(self, handler):
        """Should NOT match complex chain ending with whitelisted command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat large.log | grep error | awk '{print $2}' | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_command_chain_grep_tail(self, handler):
        """Should NOT match command chain with grep before tail."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test && grep FAIL output.log | tail -n 5"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_non_whitelisted_docker_tail(self, handler):
        """Should match non-whitelisted docker command piped to tail."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "docker ps -a | tail -n 20"}}
        assert handler.matches(hook_input) is True

    def test_matches_non_whitelisted_npm_head(self, handler):
        """Should match non-whitelisted npm command piped to head."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "npm run test | head -n 10"}}
        assert handler.matches(hook_input) is True

    def test_matches_non_whitelisted_find_tail(self, handler):
        """Should match non-whitelisted find command piped to tail."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.log' | tail -n 50"},
        }
        assert handler.matches(hook_input) is True

    def test_no_match_grep_case_insensitive(self, handler):
        """Should match whitelisted command with case insensitivity."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "GREP error log | tail -n 5"}}
        assert handler.matches(hook_input) is False

    def test_matches_cat_piped_to_tail(self, handler):
        """Should match cat (not whitelisted) piped to tail."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat /var/log/syslog | tail -n 20"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_ls_piped_to_head(self, handler):
        """Should match ls (not whitelisted) piped to head."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls -la /tmp | head -n 15"}}
        assert handler.matches(hook_input) is True

    def test_no_match_multiple_pipes_ending_with_grep(self, handler):
        """Should NOT match if last command before tail is whitelisted."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker ps | grep running | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_multiple_pipes_ending_with_docker(self, handler):
        """Should match if last command before tail is not whitelisted."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "grep running logs | docker exec -i container bash | tail -n 10"
            },
        }
        assert handler.matches(hook_input) is True

    def test_no_match_grep_with_options_piped_to_tail(self, handler):
        """Should NOT match grep with various options piped to tail."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -rn 'error' /var/log/ | tail -n 25"},
        }
        assert handler.matches(hook_input) is False

    def test_custom_whitelist_allows_custom_command(self):
        """Should respect custom whitelist from options."""
        handler = PipeBlockerHandler(options={"allowed_pipe_sources": ["custom-cmd"]})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "custom-cmd --flag | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_custom_whitelist_blocks_default_commands(self):
        """Should block default commands when custom whitelist provided."""
        handler = PipeBlockerHandler(options={"allowed_pipe_sources": ["custom-cmd"]})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep pattern file | tail -n 10"},
        }
        assert handler.matches(hook_input) is True

    def test_empty_whitelist_blocks_all(self):
        """Should block all commands when whitelist is empty."""
        handler = PipeBlockerHandler(options={"allowed_pipe_sources": []})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep pattern file | tail -n 10"},
        }
        assert handler.matches(hook_input) is True

    # ===================================================================================
    # Phase 5: Edge Cases Tests (15+ tests)
    # ===================================================================================

    def test_no_match_git_commit_with_tail_in_message(self, handler):
        """Should NOT match git commit with 'tail' in commit message."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'Fix tail behavior' && git push"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_echo_with_tail_in_string(self, handler):
        """Should NOT match echo with 'tail' in the string."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "echo 'tail command example'"}}
        assert handler.matches(hook_input) is False

    def test_matches_malformed_pipe_with_tail(self, handler):
        """Should handle malformed pipe gracefully."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cmd | "}}
        # Should not match because there's no tail/head after pipe
        assert handler.matches(hook_input) is False

    def test_matches_multiple_tail_head_in_pipeline(self, handler):
        """Should match multiple tail/head in pipeline."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . | tail -n 100 | head -n 10"},
        }
        # Should match because find is piped to tail
        assert handler.matches(hook_input) is True

    def test_no_match_subshell_with_tail_string(self, handler):
        """Should handle subshell appropriately."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "VAR=$(echo tail)"}}
        # No pipe to tail command, just a string
        assert handler.matches(hook_input) is False

    def test_matches_tail_in_file_path(self, handler):
        """Should NOT match tail when it's part of a file path."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cat /home/tail/file.txt"}}
        # No pipe to tail
        assert handler.matches(hook_input) is False

    def test_no_match_none_command_value(self, handler):
        """Should handle None command value gracefully."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": None}}
        assert handler.matches(hook_input) is False

    def test_no_match_empty_string_command(self, handler):
        """Should handle empty string command gracefully."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert handler.matches(hook_input) is False

    def test_no_match_missing_tool_input_dict(self, handler):
        """Should handle missing tool_input dict gracefully."""
        hook_input = {"tool_name": "Bash"}
        assert handler.matches(hook_input) is False

    def test_no_match_command_with_no_pipes(self, handler):
        """Should NOT match commands without any pipes."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "npm run test"}}
        assert handler.matches(hook_input) is False

    def test_no_match_pipe_to_wc(self, handler):
        """Should NOT match pipe to wc (not tail/head)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . -name '*.py' | wc -l"}}
        assert handler.matches(hook_input) is False

    def test_matches_tail_with_multiple_flags(self, handler):
        """Should match tail with various flags."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker logs container | tail -n 20 -v"},
        }
        assert handler.matches(hook_input) is True

    def test_no_match_head_with_follow_like_flag(self, handler):
        """Should match head even with other flags (only -c is exception)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls -la | head -n 10 -v"}}
        # head -v is not an exception like head -c
        assert handler.matches(hook_input) is True

    def test_matches_command_with_quotes_containing_pipe(self, handler):
        """Should handle quoted strings with pipe characters."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'this | is | fine' && find . | tail -n 10"},
        }
        # The actual pipe to tail should still be detected
        assert handler.matches(hook_input) is True

    def test_no_match_heredoc_with_tail(self, handler):
        """Should handle heredoc appropriately."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat <<EOF\ntail example\nEOF"},
        }
        # No actual pipe to tail command
        assert handler.matches(hook_input) is False

    # ===================================================================================
    # Phase 6: handle() Method Tests (12+ tests)
    # ===================================================================================

    def test_handle_returns_deny_decision(self, handler):
        """Should return DENY decision."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        from claude_code_hooks_daemon.core import Decision

        assert result.decision == Decision.DENY

    def test_handle_reason_contains_blocked_command(self, handler):
        """Reason should contain the blocked command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "docker ps -a | tail -n 20"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "docker ps -a | tail -n 20" in result.reason

    def test_handle_reason_explains_why_blocked(self, handler):
        """Reason should explain information loss."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "npm test | head -n 10"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "information" in result.reason.lower()
        # Should mention the problem with re-running
        assert "re-run" in result.reason.lower() or "rerun" in result.reason.lower()

    def test_handle_reason_suggests_temp_file(self, handler):
        """Reason should suggest redirecting to temp file."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "temp" in result.reason.lower() or "/tmp" in result.reason

    def test_handle_reason_shows_whitelist(self, handler):
        """Reason should show whitelist commands."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "docker ps | tail -n 20"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 3
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        # Should mention at least some whitelist commands
        assert "grep" in result.reason.lower() or "awk" in result.reason.lower()

    def test_handle_message_is_clear_and_actionable(self, handler):
        """Message should be clear and provide alternatives."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        # Should have some structure (sections)
        assert "BLOCKED" in result.reason or "blocked" in result.reason.lower()
        # Should provide alternative
        assert ">" in result.reason or "redirect" in result.reason.lower()

    def test_handle_with_head_command(self, handler):
        """Should handle head command appropriately."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls -la | head -n 5"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        from claude_code_hooks_daemon.core import Decision

        assert result.decision == Decision.DENY
        assert "head" in result.reason.lower()

    def test_handle_with_complex_command(self, handler):
        """Should handle complex command appropriately."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.log' -exec cat {} \\; | tail -n 100"},
        }
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        from claude_code_hooks_daemon.core import Decision

        assert result.decision == Decision.DENY

    def test_handle_mentions_source_command(self, handler):
        """Reason should mention the source command being piped."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker logs container | tail -n 50"},
        }
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        # Should identify docker as the expensive command
        assert "docker" in result.reason.lower()

    def test_handle_reason_format_has_sections(self, handler):
        """Reason should have clear sections."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "npm run test | tail -n 20"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        # Check for section markers (newlines, headers)
        assert "\n\n" in result.reason  # Should have paragraph breaks

    def test_handle_includes_emoji_or_marker(self, handler):
        """Reason should include visual marker for clarity."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        # Should have some visual indicator
        assert "🚫" in result.reason or "BLOCKED" in result.reason or "❌" in result.reason

    def test_handle_with_tail_flag(self, handler):
        """Should handle tail with -n flag appropriately."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "docker ps | tail -n 20"}}
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        from claude_code_hooks_daemon.core import Decision

        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert len(result.reason) > 50  # Should be a helpful message


class TestPipeBlockerProgressiveVerbosity:
    """Test progressive verbosity based on block count."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return PipeBlockerHandler()

    @pytest.fixture
    def hook_input(self):
        """Create sample hook input."""
        return {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}

    def test_terse_reason_on_first_block(self, handler, hook_input):
        """First block should return terse message."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Terse message should be short
        assert len(result.reason) < 200
        # Should contain key elements
        assert "BLOCKED" in result.reason
        assert "temp file" in result.reason.lower() or "/tmp" in result.reason

    def test_standard_reason_on_second_block(self, handler, hook_input):
        """Second block should return standard message without whitelist."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Standard message should contain WHY BLOCKED section
        assert "WHY BLOCKED" in result.reason
        # Should NOT contain whitelist section
        assert "WHITELISTED COMMANDS" not in result.reason

    def test_standard_reason_on_third_block(self, handler, hook_input):
        """Third block should return standard message without whitelist."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 2
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Standard message should contain WHY BLOCKED section
        assert "WHY BLOCKED" in result.reason
        # Should NOT contain whitelist section
        assert "WHITELISTED COMMANDS" not in result.reason

    def test_verbose_reason_on_fourth_block(self, handler, hook_input):
        """Fourth block should return verbose message with whitelist."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 3
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Verbose message should contain whitelist section
        assert "WHITELISTED COMMANDS" in result.reason

    def test_verbose_reason_on_many_blocks(self, handler, hook_input):
        """Many blocks should return verbose message with whitelist."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 10
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Verbose message should contain whitelist section
        assert "WHITELISTED COMMANDS" in result.reason

    def test_data_layer_error_falls_back_to_terse(self, handler, hook_input):
        """Data layer error should fall back to terse message."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker.get_data_layer",
            side_effect=Exception("Data layer error"),
        ):
            result = handler.handle(hook_input)

        # Should fall back to terse message (block count 0)
        assert len(result.reason) < 200
        assert "BLOCKED" in result.reason
        assert "temp file" in result.reason.lower() or "/tmp" in result.reason


class TestPipeBlockerAdditionalCoverage:
    """Additional tests for pipe blocker edge cases to boost coverage."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return PipeBlockerHandler()

    def test_no_match_tail_follow_piped(self, handler):
        """Should NOT match tail -f even when piped (follow mode exception)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "some_cmd | tail -f /var/log/syslog"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_head_bytes_piped(self, handler):
        """Should NOT match head -c even when piped (byte count exception)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "some_cmd | head -c 1024 file.bin"},
        }
        assert handler.matches(hook_input) is False

    def test_no_pipe_match_returns_false(self, handler):
        """Should return False when pipe pattern does not match in _extract_source_command."""
        # _extract_source_command returns None when no pipe match
        result = handler._extract_source_command("ls -la")
        assert result is None

    def test_empty_before_pipe_returns_none(self, handler):
        """Should return None when segment before pipe is empty."""
        # Edge case: pipe immediately to tail with nothing before
        result = handler._extract_source_command("| tail -n 10")
        assert result is None

    def test_extract_source_command_exception_returns_none(self, handler):
        """Should return None when extraction raises unexpected exception."""
        with patch.object(handler, "_pipe_pattern") as mock_pattern:
            mock_pattern.search.side_effect = Exception("unexpected")
            result = handler._extract_source_command("cmd | tail -n 10")
        assert result is None

    def test_get_acceptance_tests_returns_non_empty(self, handler):
        """get_acceptance_tests returns a non-empty list."""
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0
