"""Comprehensive tests for redesigned PipeBlockerHandler (three-tier logic)."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


class TestPipeBlockerHandlerInit:
    """Tests for handler initialization."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_init_sets_correct_name(self, handler: PipeBlockerHandler) -> None:
        assert handler.name == "pipe-blocker"

    def test_init_sets_correct_priority(self, handler: PipeBlockerHandler) -> None:
        assert handler.priority == 15

    def test_init_sets_correct_terminal_flag(self, handler: PipeBlockerHandler) -> None:
        assert handler.terminal is True

    def test_init_sets_correct_tags(self, handler: PipeBlockerHandler) -> None:
        expected_tags = ["safety", "bash", "blocking", "terminal"]
        assert handler.tags == expected_tags

    def test_init_has_registry(self, handler: PipeBlockerHandler) -> None:
        from claude_code_hooks_daemon.strategies.pipe_blocker.registry import (
            PipeBlockerStrategyRegistry,
        )

        assert hasattr(handler, "_registry")
        assert isinstance(handler._registry, PipeBlockerStrategyRegistry)

    def test_init_has_whitelist(self, handler: PipeBlockerHandler) -> None:
        assert hasattr(handler, "_whitelist")
        assert isinstance(handler._whitelist, list)
        assert len(handler._whitelist) > 0

    def test_init_has_empty_extra_whitelist_by_default(self, handler: PipeBlockerHandler) -> None:
        assert hasattr(handler, "_extra_whitelist")
        assert handler._extra_whitelist == []

    def test_init_has_empty_extra_blacklist_by_default(self, handler: PipeBlockerHandler) -> None:
        assert hasattr(handler, "_extra_blacklist")
        assert handler._extra_blacklist == []

    def test_init_extra_whitelist_from_options(self) -> None:
        handler = PipeBlockerHandler(options={"extra_whitelist": [r"^custom-cmd\b"]})
        assert len(handler._extra_whitelist) == 1

    def test_init_extra_blacklist_from_options(self) -> None:
        handler = PipeBlockerHandler(options={"extra_blacklist": [r"^my_tool\b"]})
        assert handler._extra_blacklist == [r"^my_tool\b"]


# ===================================================================================
# Phase 2: Pipe Detection — no pipe, tail -f, head -c, wrong tool
# ===================================================================================


class TestPipeBlockerBasicDetection:
    """Tests for basic pipe-to-tail/head detection."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_no_match_tail_without_pipe(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "tail -n 20 /var/log/syslog"}}
        assert handler.matches(hook_input) is False

    def test_no_match_tail_follow_mode(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "tail -f /var/log/syslog"}}
        assert handler.matches(hook_input) is False

    def test_no_match_head_byte_count(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "head -c 1024 file.txt"}}
        assert handler.matches(hook_input) is False

    def test_no_match_empty_command(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert handler.matches(hook_input) is False

    def test_no_match_non_bash_tool(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "/tmp/test.txt"}}
        assert handler.matches(hook_input) is False

    def test_no_match_missing_command_field(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_no_match_missing_tool_input_dict(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash"}
        assert handler.matches(hook_input) is False

    def test_no_match_none_command_value(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": None}}
        assert handler.matches(hook_input) is False

    def test_no_match_command_with_no_pipes(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "npm run test"}}
        assert handler.matches(hook_input) is False

    def test_no_match_pipe_to_wc(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.py' | wc -l"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_case_insensitive_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | TAIL -n 10"}}
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "docker ps | Head -n 5"}}
        assert handler.matches(hook_input) is True

    def test_no_match_tail_follow_piped(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "some_cmd | tail -f /var/log/syslog"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_head_bytes_piped(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "some_cmd | head -c 1024 file.bin"},
        }
        assert handler.matches(hook_input) is False


# ===================================================================================
# Phase 3: Whitelist Logic — grep, awk, ls, cat, git tag, etc.
# ===================================================================================


class TestPipeBlockerWhitelist:
    """Tests for whitelist logic (always allow)."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_no_match_grep_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep error /var/log/syslog | tail -n 20"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_rg_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rg 'pattern' . | head -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_awk_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "awk '{print $1}' data.txt | tail -n 5"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_jq_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "jq '.items' data.json | tail -n 15"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_sed_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -n '1,100p' file.txt | head -n 20"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_cut_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cut -d: -f1 /etc/passwd | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_sort_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sort names.txt | head -n 5"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_uniq_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "uniq -c data.txt | tail -n 20"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_tr_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "tr '[:lower:]' '[:upper:]' < file.txt | head -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_wc_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "wc -l *.txt | tail -n 5"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_ls_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        """ls is now in UNIVERSAL_WHITELIST_PATTERNS — should be allowed."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la /tmp | head -n 15"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_ls_pipe_no_space(self, handler: PipeBlockerHandler) -> None:
        """ls without space before pipe — still whitelisted."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la|tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_ls_pipe_multiple_spaces(self, handler: PipeBlockerHandler) -> None:
        """ls with extra spaces — still whitelisted."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la |  tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_cat_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        """cat is now in UNIVERSAL_WHITELIST_PATTERNS — should be allowed."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat /var/log/syslog | tail -n 20"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_echo_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'some output' | tail -n 5"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_git_tag_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git tag -l | tail -n 5"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_git_status_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status --short | head -n 20"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_git_diff_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git diff HEAD | tail -n 30"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_complex_chain_grep_awk_tail(self, handler: PipeBlockerHandler) -> None:
        """Complex chain ending with whitelisted command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat large.log | grep error | awk '{print $2}' | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_command_chain_grep_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test && grep FAIL output.log | tail -n 5"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_with_options_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -rn 'error' /var/log/ | tail -n 25"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_multiple_pipes_ending_with_grep(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker ps | grep running | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_case_insensitive(self, handler: PipeBlockerHandler) -> None:
        """Whitelist matching is case-insensitive."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "GREP error log | tail -n 5"},
        }
        assert handler.matches(hook_input) is False


# ===================================================================================
# Phase 4: Blocking Logic — blacklisted and unknown commands
# ===================================================================================


class TestPipeBlockerBlocking:
    """Tests for commands that SHOULD be blocked (blacklisted or unknown)."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    # Blacklisted (known expensive)
    def test_matches_pytest_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest tests/ | tail -20"}}
        assert handler.matches(hook_input) is True

    def test_matches_npm_test_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test | head -n 10"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_test_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test | tail -5"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_mypy_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "mypy src/ | tail -20"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_go_test_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "go test ./... | tail -20"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_cargo_test_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cargo test | tail -20"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_rspec_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rspec spec/ | head -n 30"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_make_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "make build | tail -20"},
        }
        assert handler.matches(hook_input) is True

    # Unknown (not in whitelist or blacklist)
    def test_matches_find_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.py' | tail -n 20"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_docker_ps_piped_to_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker ps -a | tail -n 20"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_log_piped_to_head(self, handler: PipeBlockerHandler) -> None:
        """git log is NOT whitelisted (only git tag, status, diff are)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git log --oneline | head -n 10"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_multiple_tail_head_in_pipeline(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . | tail -n 100 | head -n 10"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_multiple_pipes_ending_with_docker(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "grep running logs | docker exec -i container bash | tail -n 10"
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_tail_with_multiple_flags(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker logs container | tail -n 20 -v"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_head_with_non_c_flag(self, handler: PipeBlockerHandler) -> None:
        """head -v is not an exception (only head -c is)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker logs c | head -n 10 -v"},
        }
        assert handler.matches(hook_input) is True


# ===================================================================================
# Phase 5: Extra Whitelist / Extra Blacklist Options
# ===================================================================================


class TestPipeBlockerExtraOptions:
    """Tests for extra_whitelist and extra_blacklist options."""

    def test_extra_whitelist_allows_custom_command(self) -> None:
        handler = PipeBlockerHandler(options={"extra_whitelist": [r"^custom-cmd\b"]})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "custom-cmd --flag | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_extra_whitelist_does_not_break_universal_whitelist(self) -> None:
        """Adding extra_whitelist does not remove the universal whitelist."""
        handler = PipeBlockerHandler(options={"extra_whitelist": [r"^custom-cmd\b"]})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep pattern file | tail -n 10"},
        }
        assert handler.matches(hook_input) is False

    def test_extra_blacklist_blocks_custom_command(self) -> None:
        """extra_blacklist adds to the blacklist for handle() differentiation."""
        handler = PipeBlockerHandler(options={"extra_blacklist": [r"^my_tool\b"]})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "my_tool --run | tail -n 10"},
        }
        # matches() still returns True for unknown my_tool
        assert handler.matches(hook_input) is True
        # handle() should use blacklisted message
        result = handler.handle(hook_input)
        assert "information" in result.reason.lower()

    def test_extra_whitelist_multi_word_command(self) -> None:
        handler = PipeBlockerHandler(options={"extra_whitelist": [r"^git\s+log\b"]})
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git log --oneline | tail -n 10"},
        }
        assert handler.matches(hook_input) is False


# ===================================================================================
# Phase 6: Edge Cases
# ===================================================================================


class TestPipeBlockerEdgeCases:
    """Edge case tests for pipe blocker."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_no_match_git_commit_with_tail_in_message(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'Fix tail behavior' && git push"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_echo_with_tail_in_string(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'tail command example'"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_malformed_pipe_no_tail_head(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cmd | "}}
        assert handler.matches(hook_input) is False

    def test_no_match_subshell_with_tail_string(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "VAR=$(echo tail)"}}
        assert handler.matches(hook_input) is False

    def test_no_match_tail_in_file_path(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cat /home/tail/file.txt"}}
        assert handler.matches(hook_input) is False

    def test_no_match_heredoc_with_tail(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat <<EOF\ntail example\nEOF"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_command_with_quotes_containing_pipe(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'this | is | fine' && find . | tail -n 10"},
        }
        assert handler.matches(hook_input) is True


# ===================================================================================
# Phase 7: handle() method — blacklisted vs unknown messages
# ===================================================================================


class TestPipeBlockerHandleBlacklisted:
    """Tests for handle() when command is blacklisted (known expensive)."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_handle_returns_deny_for_blacklisted(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -n 20"}}
        result = handler.handle(hook_input)
        from claude_code_hooks_daemon.core import Decision

        assert result.decision == Decision.DENY

    def test_blacklisted_reason_mentions_command(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest tests/ | tail -20"}}
        result = handler.handle(hook_input)
        assert "pytest tests/ | tail -20" in result.reason

    def test_blacklisted_reason_mentions_information_loss(
        self, handler: PipeBlockerHandler
    ) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "npm test | head -n 10"}}
        result = handler.handle(hook_input)
        assert "information" in result.reason.lower()

    def test_blacklisted_reason_mentions_rerun(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "npm test | head -n 10"}}
        result = handler.handle(hook_input)
        assert "re-run" in result.reason.lower() or "rerun" in result.reason.lower()

    def test_blacklisted_reason_suggests_temp_file(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "mypy src/ | tail -20"}}
        result = handler.handle(hook_input)
        assert "temp" in result.reason.lower() or "/tmp" in result.reason

    def test_blacklisted_reason_names_source_command(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "cargo test | tail -20"}}
        result = handler.handle(hook_input)
        assert "cargo" in result.reason.lower()

    def test_blacklisted_reason_has_sections(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert "\n\n" in result.reason

    def test_blacklisted_reason_has_blocked_marker(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert "🚫" in result.reason or "BLOCKED" in result.reason

    def test_blacklisted_reason_does_not_mention_extra_whitelist(
        self, handler: PipeBlockerHandler
    ) -> None:
        """Blacklisted message should NOT mention extra_whitelist (different from unknown)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert "extra_whitelist" not in result.reason

    def test_blacklisted_reason_redirects_stdout_and_stderr(
        self, handler: PipeBlockerHandler
    ) -> None:
        """Snippet redirects both stdout and stderr to the temp file."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert '> "$TEMP_FILE" 2>&1' in result.reason

    def test_blacklisted_reason_captures_exit_code(self, handler: PipeBlockerHandler) -> None:
        """Snippet captures the exit code after running the command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert "EXIT_CODE=$?" in result.reason

    def test_blacklisted_reason_echoes_completed_ok_on_success(
        self, handler: PipeBlockerHandler
    ) -> None:
        """Snippet echoes 'Completed OK' when exit code is 0."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert "Completed OK" in result.reason

    def test_blacklisted_reason_echoes_completed_with_errors_on_failure(
        self, handler: PipeBlockerHandler
    ) -> None:
        """Snippet echoes 'Completed with errors' when exit code is non-zero."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert "Completed with errors (exit code: $EXIT_CODE)" in result.reason


class TestPipeBlockerHandleUnknown:
    """Tests for handle() when command is unknown (not in whitelist or blacklist)."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_handle_returns_deny_for_unknown(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        from claude_code_hooks_daemon.core import Decision

        assert result.decision == Decision.DENY

    def test_unknown_reason_mentions_command(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker ps -a | tail -n 20"},
        }
        result = handler.handle(hook_input)
        assert "docker ps -a | tail -n 20" in result.reason

    def test_unknown_reason_mentions_extra_whitelist(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert "extra_whitelist" in result.reason

    def test_unknown_reason_suggests_temp_file(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert "temp" in result.reason.lower() or "/tmp" in result.reason

    def test_unknown_reason_shows_whitelist_examples(self, handler: PipeBlockerHandler) -> None:
        """Unknown message should list some whitelisted commands as examples."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker ps | tail -n 20"},
        }
        result = handler.handle(hook_input)
        assert "grep" in result.reason.lower() or "awk" in result.reason.lower()

    def test_unknown_reason_mentions_source_command(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker logs container | tail -n 50"},
        }
        result = handler.handle(hook_input)
        assert "docker" in result.reason.lower()

    def test_unknown_reason_has_blocked_marker(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert "🚫" in result.reason or "BLOCKED" in result.reason

    def test_unknown_reason_has_sections(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert "\n\n" in result.reason

    def test_unknown_reason_does_not_mention_rerun(self, handler: PipeBlockerHandler) -> None:
        """Unknown message should NOT mention re-run (that's blacklisted-only messaging)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert "re-run" not in result.reason.lower() and "rerun" not in result.reason.lower()

    def test_unknown_reason_redirects_stdout_and_stderr(self, handler: PipeBlockerHandler) -> None:
        """Snippet redirects both stdout and stderr to the temp file."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert '> "$TEMP_FILE" 2>&1' in result.reason

    def test_unknown_reason_captures_exit_code(self, handler: PipeBlockerHandler) -> None:
        """Snippet captures the exit code after running the command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert "EXIT_CODE=$?" in result.reason

    def test_unknown_reason_echoes_completed_ok_on_success(
        self, handler: PipeBlockerHandler
    ) -> None:
        """Snippet echoes 'Completed OK' when exit code is 0."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert "Completed OK" in result.reason

    def test_unknown_reason_echoes_completed_with_errors_on_failure(
        self, handler: PipeBlockerHandler
    ) -> None:
        """Snippet echoes 'Completed with errors' when exit code is non-zero."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -n 20"}}
        result = handler.handle(hook_input)
        assert "Completed with errors (exit code: $EXIT_CODE)" in result.reason

    def test_handle_head_command_reason_mentions_head(self, handler: PipeBlockerHandler) -> None:
        """Reason should mention head when that's the dest command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "docker ps | head -n 5"},
        }
        result = handler.handle(hook_input)
        # Command appears in reason message
        assert "head" in result.reason.lower()

    def test_handle_with_complex_command(self, handler: PipeBlockerHandler) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.log' -exec cat {} \\; | tail -n 100"},
        }
        result = handler.handle(hook_input)
        from claude_code_hooks_daemon.core import Decision

        assert result.decision == Decision.DENY

    def test_handle_long_message(self, handler: PipeBlockerHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "docker ps | tail -n 20"}}
        result = handler.handle(hook_input)
        assert len(result.reason) > 50


# ===================================================================================
# Phase 8: Message Differentiation — blacklisted vs unknown have different messages
# ===================================================================================


class TestPipeBlockerMessageDifferentiation:
    """Tests that blacklisted and unknown commands produce different messages."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_blacklisted_has_information_loss_message(self, handler: PipeBlockerHandler) -> None:
        """Blacklisted commands get 'information loss' message."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert "information" in result.reason.lower()

    def test_unknown_has_extra_whitelist_message(self, handler: PipeBlockerHandler) -> None:
        """Unknown commands get 'add to extra_whitelist' message."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -20"}}
        result = handler.handle(hook_input)
        assert "extra_whitelist" in result.reason

    def test_blacklisted_does_not_have_extra_whitelist(self, handler: PipeBlockerHandler) -> None:
        """Blacklisted message should NOT suggest adding to whitelist."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        result = handler.handle(hook_input)
        assert "extra_whitelist" not in result.reason

    def test_unknown_does_not_have_information_loss(self, handler: PipeBlockerHandler) -> None:
        """Unknown message should NOT claim information loss (we don't know if expensive)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -20"}}
        result = handler.handle(hook_input)
        # find is unknown, not blacklisted, so no 'information loss' message
        assert "information" not in result.reason.lower()

    def test_both_have_deny_decision(self, handler: PipeBlockerHandler) -> None:
        from claude_code_hooks_daemon.core import Decision

        blacklisted = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        unknown = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -20"}}
        assert handler.handle(blacklisted).decision == Decision.DENY
        assert handler.handle(unknown).decision == Decision.DENY

    def test_both_have_blocked_marker(self, handler: PipeBlockerHandler) -> None:
        blacklisted = {"tool_name": "Bash", "tool_input": {"command": "pytest | tail -20"}}
        unknown = {"tool_name": "Bash", "tool_input": {"command": "find . | tail -20"}}
        assert "BLOCKED" in handler.handle(blacklisted).reason
        assert "BLOCKED" in handler.handle(unknown).reason


# ===================================================================================
# Phase 9: _extract_source_segment and internal helpers
# ===================================================================================


class TestPipeBlockerExtractSourceSegment:
    """Tests for _extract_source_segment helper method."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_no_pipe_returns_empty_string(self, handler: PipeBlockerHandler) -> None:
        assert handler._extract_source_segment("ls -la") == ""

    def test_empty_before_pipe_returns_empty_string(self, handler: PipeBlockerHandler) -> None:
        assert handler._extract_source_segment("| tail -n 10") == ""

    def test_simple_command(self, handler: PipeBlockerHandler) -> None:
        assert handler._extract_source_segment("find . | tail -n 20") == "find ."

    def test_multiword_command(self, handler: PipeBlockerHandler) -> None:
        assert handler._extract_source_segment("npm test | tail -5") == "npm test"

    def test_chain_takes_last_segment(self, handler: PipeBlockerHandler) -> None:
        result = handler._extract_source_segment("npm test && grep FAIL | tail -5")
        assert result == "grep FAIL"

    def test_multiple_pipes_takes_last(self, handler: PipeBlockerHandler) -> None:
        result = handler._extract_source_segment("docker ps | grep running | tail -n 10")
        assert result == "grep running"

    def test_exception_returns_empty_string(self, handler: PipeBlockerHandler) -> None:
        from unittest.mock import patch

        with patch.object(handler, "_pipe_pattern") as mock_pattern:
            mock_pattern.search.side_effect = Exception("unexpected")
            result = handler._extract_source_segment("cmd | tail -n 10")
        assert result == ""


class TestPipeBlockerInternalHelpers:
    """Tests for _matches_whitelist and _matches_blacklist."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_matches_whitelist_empty_segment(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_whitelist("") is False

    def test_matches_whitelist_grep(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_whitelist("grep -rn error /logs") is True

    def test_matches_whitelist_ls(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_whitelist("ls -la") is True

    def test_matches_whitelist_cat(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_whitelist("cat /etc/passwd") is True

    def test_matches_whitelist_git_tag(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_whitelist("git tag -l") is True

    def test_matches_whitelist_pytest_not_whitelisted(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_whitelist("pytest tests/") is False

    def test_matches_blacklist_empty_segment(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_blacklist("") is False

    def test_matches_blacklist_pytest(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_blacklist("pytest tests/") is True

    def test_matches_blacklist_npm_test(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_blacklist("npm test") is True

    def test_matches_blacklist_go_test(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_blacklist("go test ./...") is True

    def test_matches_blacklist_make(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_blacklist("make build") is True

    def test_matches_blacklist_find_not_blacklisted(self, handler: PipeBlockerHandler) -> None:
        assert handler._matches_blacklist("find . -name *.py") is False

    def test_matches_blacklist_extra_blacklist(self) -> None:
        handler = PipeBlockerHandler(options={"extra_blacklist": [r"^my_tool\b"]})
        assert handler._matches_blacklist("my_tool --run") is True


# ===================================================================================
# Phase 10: acceptance tests
# ===================================================================================


class TestPipeBlockerAcceptanceTests:
    """Tests for get_acceptance_tests()."""

    @pytest.fixture
    def handler(self) -> PipeBlockerHandler:
        return PipeBlockerHandler()

    def test_returns_non_empty_list(self, handler: PipeBlockerHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0

    def test_includes_blacklisted_test(self, handler: PipeBlockerHandler) -> None:
        # Blacklisted tests use "false && CMD | tail -N" pattern:
        # false exits 1, && short-circuits so CMD never runs, but source segment
        # extracted is CMD (after && split) which matches the blacklist.
        tests = handler.get_acceptance_tests()
        titles = [t.title for t in tests]
        assert any("blacklisted" in title.lower() for title in titles)

    def test_includes_unknown_test(self, handler: PipeBlockerHandler) -> None:
        tests = handler.get_acceptance_tests()
        titles = [t.title for t in tests]
        assert any("unknown" in title.lower() for title in titles)
