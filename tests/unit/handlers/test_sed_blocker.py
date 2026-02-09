"""Comprehensive tests for SedBlockerHandler."""

from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker import SedBlockerHandler


class TestSedBlockerHandler:
    """Test suite for SedBlockerHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return SedBlockerHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'block-sed-command'."""
        assert handler.name == "block-sed-command"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    def test_init_compiles_sed_pattern(self, handler):
        """Handler should compile sed pattern regex."""
        assert hasattr(handler, "_sed_pattern")
        assert handler._sed_pattern is not None

    # matches() - Positive Cases: Bash tool with sed commands (BLOCK)
    def test_matches_bash_sed_simple(self, handler):
        """Should match simple sed command in Bash."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sed 's/foo/bar/g' file.txt"}}
        assert handler.matches(hook_input) is True

    def test_matches_bash_sed_in_place(self, handler):
        """Should match sed -i (in-place) command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/old/new/g' file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_sed_with_find(self, handler):
        """Should match sed in find -exec command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.txt' -exec sed -i 's/foo/bar/g' {} \\;"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_sed_in_pipeline_without_grep(self, handler):
        """Should match sed in pipeline (without grep)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat file.txt | sed 's/old/new/' | wc -l"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_sed_pipeline_with_grep_returns_false(self, handler):
        """Should NOT match sed in pipeline with grep (grep makes it safe)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat file.txt | sed 's/old/new/' | grep result"},
        }
        # grep presence makes this a "safe readonly command"
        assert handler.matches(hook_input) is False

    def test_matches_bash_sed_in_command_chain_without_echo(self, handler):
        """Should match sed in command chain (without echo/grep)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la && sed -i 's/a/b/g' file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_sed_chained_after_echo_blocks(self, handler):
        """Should BLOCK sed when chained after echo (sed still executes!)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'test' && sed -i 's/a/b/g' file.txt"},
        }
        # This is dangerous! echo runs, THEN sed executes destructively
        assert handler.matches(hook_input) is True

    def test_matches_bash_sed_case_insensitive(self, handler):
        """Should match sed with different casing."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "SED 's/foo/bar/' file.txt"}}
        assert handler.matches(hook_input) is True

    def test_matches_bash_sed_after_git_diff(self, handler):
        """Should match sed when it's separate from git command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git diff && sed -i 's/foo/bar/g' file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_sed_before_git_commit(self, handler):
        """Should match sed when it comes before git commit."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt && git commit"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Bash git commands mentioning sed (ALLOW)
    def test_matches_git_commit_message_with_sed_returns_false(self, handler):
        """Should NOT match git commit with 'sed' in message."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'Fix sed blocker'"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_git_commit_heredoc_with_sed_returns_false(self, handler):
        """Should NOT match git commit with heredoc mentioning sed."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": """git commit -m "$(cat <<'EOF'
Block sed command

sed is dangerous
EOF
)"""},
        }
        assert handler.matches(hook_input) is False

    def test_matches_git_add_and_commit_with_sed_message_returns_false(self, handler):
        """Should NOT match git add && commit with sed in message."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git add . && git commit -m 'Implement sed blocker'"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_git_commit_long_message_with_sed_returns_false(self, handler):
        """Should NOT match git commit with sed mentioned in long message."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "git commit -m 'This commit adds sed blocker handler to prevent sed usage'"
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Safe read-only commands (ALLOW)
    def test_matches_grep_for_sed_returns_false(self, handler):
        """Should NOT match grep searching for 'sed'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "grep 'sed' *.py"}}
        assert handler.matches(hook_input) is False

    def test_matches_echo_with_sed_command_pattern_blocks(self, handler):
        """Should BLOCK echo containing actual sed command pattern."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo \"sed -i 's/foo/bar/g' /nonexistent/safe/test.txt\""},
        }
        # Echo containing a full sed command should be blocked - it's demonstrating dangerous patterns
        assert handler.matches(hook_input) is True

    def test_matches_echo_mentioning_sed_word_only_returns_false(self, handler):
        """Should NOT match echo command only mentioning the word 'sed'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "echo 'Do not use sed'"}}
        assert handler.matches(hook_input) is False

    def test_matches_grep_with_sed_at_start_of_command_returns_false(self, handler):
        """Should NOT match grep when it's at start of command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "grep sed file.txt"}}
        assert handler.matches(hook_input) is False

    def test_matches_echo_with_sed_after_semicolon_returns_false(self, handler):
        """Should NOT match echo after semicolon mentioning sed."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls; echo 'avoid sed'"}}
        assert handler.matches(hook_input) is False

    # matches() - Write tool: Shell scripts with sed (BLOCK)
    def test_matches_write_sh_file_with_sed(self, handler):
        """Should match Write creating .sh file containing sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.sh",
                "content": "#!/bin/bash\nsed -i 's/foo/bar/g' file.txt",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_bash_file_with_sed(self, handler):
        """Should match Write creating .bash file containing sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.bash",
                "content": "#!/bin/bash\ncat file.txt | sed 's/old/new/'",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_shell_script_with_sed_in_function(self, handler):
        """Should match Write creating shell script with sed in function."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/functions.sh",
                "content": """#!/bin/bash
function update_file() {
    sed -i 's/pattern/replacement/g' "$1"
}
""",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Write tool: Markdown files with sed (ALLOW)
    def test_matches_write_md_file_with_sed_returns_false(self, handler):
        """Should NOT match Write creating .md file with sed documentation."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/README.md",
                "content": "# Usage\n\nDo not use sed command, use Edit tool instead.",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_write_md_file_with_sed_example_returns_false(self, handler):
        """Should NOT match markdown with sed code example."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/docs/guide.md",
                "content": "Example of what NOT to do:\n\n```bash\nsed -i 's/foo/bar/g' file.txt\n```",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_non_bash_or_write_tool_returns_false(self, handler):
        """Should NOT match non-Bash/Write tools."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "/workspace/script.sh"}}
        assert handler.matches(hook_input) is False

    def test_matches_bash_without_sed_returns_false(self, handler):
        """Should NOT match Bash commands without sed."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
        assert handler.matches(hook_input) is False

    def test_matches_empty_bash_command_returns_false(self, handler):
        """Should NOT match empty Bash command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_none_bash_command_returns_false(self, handler):
        """Should NOT match when Bash command is None."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": None}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_bash_command_returns_false(self, handler):
        """Should NOT match when command key is missing."""
        hook_input = {"tool_name": "Bash", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_matches_write_non_shell_file_with_sed_returns_false(self, handler):
        """Should NOT match Write to non-shell files with sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/code.py",
                "content": "# This mentions sed but is Python code",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_write_missing_file_path_returns_false(self, handler):
        """Should NOT match Write when file_path is missing."""
        hook_input = {"tool_name": "Write", "tool_input": {"content": "sed 's/foo/bar/g' file.txt"}}
        assert handler.matches(hook_input) is False

    def test_matches_write_none_file_path_returns_false(self, handler):
        """Should NOT match Write when file_path is None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": None, "content": "sed 's/foo/bar/g' file.txt"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_write_empty_content_returns_false(self, handler):
        """Should NOT match Write with empty content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/script.sh", "content": ""},
        }
        assert handler.matches(hook_input) is False

    def test_matches_write_none_content_returns_false(self, handler):
        """Should NOT match Write when content is None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/script.sh", "content": None},
        }
        assert handler.matches(hook_input) is False

    def test_matches_word_containing_sed_returns_false(self, handler):
        """Should NOT match words containing 'sed' but not the command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "grep 'based' file.txt"}}
        # Word boundary should prevent matching 'based'
        assert handler.matches(hook_input) is False

    # _is_git_command() Tests
    def test_is_git_command_detects_commit_with_sed_message(self, handler):
        """_is_git_command() should detect git commit with sed in message."""
        command = "git commit -m 'Fix sed blocker'"
        assert handler._is_git_command(command) is True

    def test_is_git_command_detects_commit_with_sed_in_heredoc(self, handler):
        """_is_git_command() should detect git commit with sed in heredoc."""
        command = """git commit -m "$(cat <<'EOF'
Block sed usage
EOF
)"""
        assert handler._is_git_command(command) is True

    def test_is_git_command_detects_add_and_commit_with_sed_in_message(self, handler):
        """_is_git_command() should detect git add && commit with sed in message."""
        command = "git add . && git commit -m 'sed blocker'"
        assert handler._is_git_command(command) is True

    def test_is_git_command_detects_add_and_commit_with_sed_after_commit(self, handler):
        """_is_git_command() should detect sed appearing after git commit in add chain."""
        command = "git add file.txt && git commit -m 'Fix sed issue'"
        assert handler._is_git_command(command) is True

    def test_is_git_command_rejects_sed_before_commit(self, handler):
        """_is_git_command() should reject sed appearing before git commit."""
        command = "sed -i 's/foo/bar/g' file.txt && git commit -m 'message'"
        assert handler._is_git_command(command) is False

    def test_is_git_command_detects_sed_command_after_commit(self, handler):
        """_is_git_command() should detect sed command after git commit (not part of message)."""
        command = "git add file.txt && git commit -m 'message' && sed -i 's/foo/bar/g' file.txt"
        # This returns True because sed appears after commit, triggering line 108
        assert handler._is_git_command(command) is True

    def test_is_git_command_rejects_git_diff_and_sed(self, handler):
        """_is_git_command() should reject git diff && sed (separate commands)."""
        command = "git diff && sed -i 's/foo/bar/g' file.txt"
        assert handler._is_git_command(command) is False

    def test_is_git_command_rejects_non_git_commands(self, handler):
        """_is_git_command() should reject non-git commands."""
        command = "sed -i 's/foo/bar/g' file.txt"
        assert handler._is_git_command(command) is False

    def test_is_git_command_rejects_git_without_commit(self, handler):
        """_is_git_command() should reject git commands without commit."""
        command = "git status && sed -i 's/foo/bar/g' file.txt"
        assert handler._is_git_command(command) is False

    def test_is_git_command_rejects_add_without_sed_in_commit_message(self, handler):
        """_is_git_command() should reject git add && commit when sed not in message."""
        # This command has git add, git commit, but sed appears BEFORE commit
        command = "git add modified_by_sed.txt && git commit -m 'Update file'"
        # 'sed' in filename happens before 'git commit', so it returns False
        assert handler._is_git_command(command) is False

    # _is_gh_command() Tests
    def test_is_gh_command_detects_issue_create_with_sed(self, handler):
        """_is_gh_command() should detect gh issue create with sed in body."""
        command = "gh issue create --title 'Block sed' --body 'sed is dangerous'"
        assert handler._is_gh_command(command) is True

    def test_is_gh_command_detects_pr_create_with_sed(self, handler):
        """_is_gh_command() should detect gh pr create with sed in body."""
        command = "gh pr create --title 'Fix' --body 'Blocks sed usage'"
        assert handler._is_gh_command(command) is True

    def test_is_gh_command_detects_issue_comment_with_sed(self, handler):
        """_is_gh_command() should detect gh issue comment with sed."""
        command = "gh issue comment 123 --body 'Do not use sed'"
        assert handler._is_gh_command(command) is True

    def test_is_gh_command_detects_pr_comment_with_sed_heredoc(self, handler):
        """_is_gh_command() should detect gh pr comment with sed in heredoc."""
        command = """gh pr comment 456 --body "$(cat <<'EOF'
Package.resolved file
sed commands blocked
EOF
)" """
        assert handler._is_gh_command(command) is True

    def test_is_gh_command_detects_release_with_sed(self, handler):
        """_is_gh_command() should detect gh release with sed in notes."""
        command = "gh release create v1.0 --notes 'Blocks sed commands'"
        assert handler._is_gh_command(command) is True

    def test_is_gh_command_rejects_sed_before_gh(self, handler):
        """_is_gh_command() should reject sed appearing before gh command."""
        command = "sed -i 's/foo/bar/g' file.txt && gh issue create --title 'Fix'"
        assert handler._is_gh_command(command) is False

    def test_is_gh_command_rejects_sed_after_command_separator(self, handler):
        """_is_gh_command() should reject sed as separate command after gh."""
        command = "gh issue list && sed -i 's/foo/bar/g' file.txt"
        assert handler._is_gh_command(command) is False

    def test_is_gh_command_rejects_sed_after_pipe(self, handler):
        """_is_gh_command() should reject sed piped from gh command."""
        command = "gh issue list | sed 's/foo/bar/g'"
        assert handler._is_gh_command(command) is False

    def test_is_gh_command_rejects_sed_after_semicolon(self, handler):
        """_is_gh_command() should reject sed after semicolon separator."""
        command = "gh pr list; sed -i 's/foo/bar/g' file.txt"
        assert handler._is_gh_command(command) is False

    def test_is_gh_command_rejects_non_gh_commands(self, handler):
        """_is_gh_command() should reject non-gh commands."""
        command = "sed -i 's/foo/bar/g' file.txt"
        assert handler._is_gh_command(command) is False

    def test_is_gh_command_rejects_gh_without_sed(self, handler):
        """_is_gh_command() should reject gh commands without sed."""
        command = "gh issue create --title 'New feature' --body 'Description'"
        assert handler._is_gh_command(command) is False

    # _is_safe_readonly_command() Tests
    def test_is_safe_readonly_command_detects_grep(self, handler):
        """_is_safe_readonly_command() should detect grep commands."""
        command = "grep 'sed' file.txt"
        assert handler._is_safe_readonly_command(command) is True

    def test_is_safe_readonly_command_detects_echo(self, handler):
        """_is_safe_readonly_command() should detect echo commands."""
        command = "echo 'Do not use sed'"
        assert handler._is_safe_readonly_command(command) is True

    def test_is_safe_readonly_command_detects_grep_after_semicolon(self, handler):
        """_is_safe_readonly_command() should detect grep after semicolon."""
        command = "cd /workspace; grep sed file.txt"
        assert handler._is_safe_readonly_command(command) is True

    def test_is_safe_readonly_command_detects_echo_after_pipe(self, handler):
        """_is_safe_readonly_command() should detect echo after pipe."""
        command = "ls | echo 'sed blocker'"
        assert handler._is_safe_readonly_command(command) is True

    def test_is_safe_readonly_command_rejects_cat_pipe_sed(self, handler):
        """_is_safe_readonly_command() should reject cat | sed pipeline."""
        command = "cat file.txt | sed 's/foo/bar/'"
        assert handler._is_safe_readonly_command(command) is False

    def test_is_safe_readonly_command_rejects_actual_sed(self, handler):
        """_is_safe_readonly_command() should reject actual sed execution."""
        command = "sed -i 's/foo/bar/g' file.txt"
        assert handler._is_safe_readonly_command(command) is False

    def test_is_safe_readonly_command_rejects_find_exec_sed(self, handler):
        """_is_safe_readonly_command() should reject find -exec sed."""
        command = "find . -name '*.txt' -exec sed -i 's/foo/bar/g' {} \\;"
        assert handler._is_safe_readonly_command(command) is False

    # handle() Tests - Message content
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_bash_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sed 's/foo/bar/' file.txt"}}
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_bash_reason_contains_command(self, handler):
        """handle() reason should include the blocked command."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "sed -i 's/foo/bar/g' file.txt" in result.reason

    def test_handle_bash_shows_command_context_type(self, handler):
        """handle() should show 'command' as context type for Bash."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sed 's/foo/bar/' file.txt"}}
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "command" in result.reason.lower()

    def test_handle_write_reason_contains_file_path(self, handler):
        """handle() reason should include file path for Write tool."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.sh",
                "content": "sed -i 's/foo/bar/g' file.txt",
            },
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "/workspace/script.sh" in result.reason

    def test_handle_write_shows_script_context_type(self, handler):
        """handle() should show 'script' as context type for Write."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.sh",
                "content": "sed 's/foo/bar/' file.txt",
            },
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "script" in result.reason.lower()

    def test_handle_reason_explains_why_banned(self, handler):
        """handle() reason should explain why sed is banned."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "WHY BANNED" in result.reason
        assert "Claude gets sed syntax wrong" in result.reason

    def test_handle_reason_mentions_file_corruption(self, handler):
        """handle() reason should mention file corruption risk."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sed 's/foo/bar/' file.txt"}}
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "corruption" in result.reason.lower()

    def test_handle_reason_suggests_haiku_agents(self, handler):
        """handle() reason should suggest using parallel haiku agents."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "haiku" in result.reason.lower()
        assert "Edit tool" in result.reason

    def test_handle_reason_provides_example(self, handler):
        """handle() reason should provide good vs bad example."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 3
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sed 's/foo/bar/' file.txt"}}
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert "EXAMPLE" in result.reason
        assert "Bad:" in result.reason
        assert "Good:" in result.reason

    def test_handle_context_is_none(self, handler):
        """handle() context should be None."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sed 's/foo/bar/' file.txt"}}
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "sed 's/foo/bar/' file.txt"}}
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_full_workflow_blocks_dangerous_sed(self, handler):
        """Complete workflow: Block dangerous sed command."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.txt' -exec sed -i 's/foo/bar/g' {} \\;"},
        }

        # Should match
        assert handler.matches(hook_input) is True

        # Should deny
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "sed" in result.reason.lower()

    def test_full_workflow_allows_git_commit_mentioning_sed(self, handler):
        """Complete workflow: Allow git commit with sed in message."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'Block sed command usage'"},
        }

        # Should not match
        assert handler.matches(hook_input) is False

    def test_full_workflow_allows_grep_for_sed(self, handler):
        """Complete workflow: Allow grep searching for sed."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "grep 'sed' handler.py"}}

        # Should not match
        assert handler.matches(hook_input) is False

    def test_full_workflow_blocks_shell_script_with_sed(self, handler):
        """Complete workflow: Block shell script creation with sed."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/update.sh",
                "content": "#!/bin/bash\nsed -i 's/old/new/g' *.txt",
            },
        }

        # Should match
        assert handler.matches(hook_input) is True

        # Should deny
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "/workspace/update.sh" in result.reason

    def test_full_workflow_allows_markdown_documentation(self, handler):
        """Complete workflow: Allow markdown mentioning sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/README.md",
                "content": "# Warning\n\nDo not use sed. Use Edit tool instead.",
            },
        }

        # Should not match
        assert handler.matches(hook_input) is False

    def test_comprehensive_sed_detection_in_bash(self, handler):
        """Should detect sed in all common Bash patterns."""
        sed_commands = [
            "sed 's/foo/bar/' file.txt",
            "sed -i 's/foo/bar/g' file.txt",
            "cat file.txt | sed 's/old/new/'",
            "find . -name '*.txt' -exec sed -i 's/a/b/g' {} \\;",
            "sed -e 's/foo/bar/' -e 's/baz/qux/' file.txt",
            "SED 's/upper/CASE/' file.txt",
        ]

        for cmd in sed_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            # Note: git commit cases will be False, but these are direct sed usage
            if "git commit" not in cmd:
                assert handler.matches(hook_input) is True, f"Should block: {cmd}"

    def test_comprehensive_safe_commands_allowed(self, handler):
        """Should allow all safe commands mentioning sed."""
        safe_commands = [
            "git commit -m 'Add sed blocker'",
            "git add . && git commit -m 'Block sed usage'",
            "grep 'sed' file.txt",
            "echo 'Do not use sed'",
            # Note: git log --grep='sed' contains 'grep' so it's treated as safe
        ]

        for cmd in safe_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"

    def test_git_log_grep_with_sed_returns_true(self, handler):
        """git log --grep='sed' will be blocked (--grep= doesn't match safe pattern)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git log --grep='sed'"}}
        # The pattern requires whitespace after grep/echo: (grep|echo)\s+
        # So --grep='sed' doesn't match the safe readonly pattern
        # This will be blocked (which is probably overly cautious but safe)
        assert handler.matches(hook_input) is True

    def test_is_git_command_with_git_add_commit_without_sed_in_message(self, handler):
        """_is_git_command() should return False when git add && commit without sed after commit."""
        # This tests the branch at line 108: when command_after_commit doesn't contain sed
        command = "git add . && git commit -m 'Update files'"
        # No 'sed' appears after 'git commit', so the search returns None
        assert handler._is_git_command(command) is False

    def test_is_git_command_with_git_commit_sed_before_commit(self, handler):
        """_is_git_command() should return False when sed appears before git commit position."""
        # This tests the branch at line 97: when sed_pos <= git_pos
        command = "sed -i 's/foo/bar/' file.txt && git commit -m 'message'"
        # 'sed' appears before 'git commit', so sed_pos < git_pos, returns False
        assert handler._is_git_command(command) is False

    def test_is_git_command_without_sed_in_command(self, handler):
        """_is_git_command() should return False when git commit found but no sed."""
        # This tests the branch at line 94: when sed_match is None
        command = "git commit -m 'Update files without the s word'"
        # git commit found, but no 'sed' in command, so sed_match is None
        assert handler._is_git_command(command) is False

    def test_is_git_command_with_sed_after_git_add_commit_chain(self, handler):
        """_is_git_command() should detect sed in commit message in git add chain."""
        # This specifically tests line 108: return True when sed found after commit in add chain
        command = "git add file.txt && git commit -m 'Block sed usage'"
        # 'sed' appears in the commit message, after 'git commit' in the chain
        # Line 102: matches git add && git commit pattern
        # Line 104-105: finds commit_match, extracts command_after_commit
        # Line 107: finds 'sed' in " -m 'Block sed usage'"
        # Line 108: returns True
        assert handler._is_git_command(command) is True

    # GitHub CLI (gh) Commands - Should allow sed in documentation
    def test_matches_gh_issue_create_with_sed_in_body_returns_false(self, handler):
        """Should NOT match gh issue create with sed in body text (documentation)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": """gh issue create --title "Block sed" --body "$(cat <<'EOF'
sed commands are dangerous
EOF
)" """},
        }
        assert handler.matches(hook_input) is False

    def test_matches_gh_pr_create_with_sed_in_description_returns_false(self, handler):
        """Should NOT match gh pr create with sed in PR description."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr create --title 'Fix' --body 'Blocks sed usage'"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_gh_issue_comment_with_sed_returns_false(self, handler):
        """Should NOT match gh issue comment mentioning sed."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue comment 123 --body 'Do not use sed'"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_gh_pr_comment_with_sed_heredoc_returns_false(self, handler):
        """Should NOT match gh pr comment with sed in heredoc."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": """gh pr comment 456 --body "$(cat <<'EOF'
Package.resolved file
sed commands blocked
EOF
)" """},
        }
        assert handler.matches(hook_input) is False

    def test_matches_sed_command_after_gh_issue_blocks(self, handler):
        """Should BLOCK sed when it's separate from gh command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue list && sed -i 's/foo/bar/g' file.txt"},
        }
        assert handler.matches(hook_input) is True


class TestSedBlockerProgressiveVerbosity:
    """Test suite for SedBlockerHandler progressive verbosity feature."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return SedBlockerHandler()

    def test_terse_reason_on_first_block(self, handler):
        """First block (count=0) should return terse message."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 0
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Terse message should be short
        assert len(result.reason) < 200
        assert "BLOCKED" in result.reason
        assert "Edit tool" in result.reason
        # Should NOT have verbose sections
        assert "WHY BANNED" not in result.reason
        assert "EXAMPLE" not in result.reason

    def test_standard_reason_on_second_block(self, handler):
        """Second block (count=1) should return standard message without EXAMPLE."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 1
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Standard message should have WHY BANNED but not EXAMPLE
        assert "WHY BANNED" in result.reason
        assert "Claude gets sed syntax wrong" in result.reason
        assert "PARALLEL HAIKU AGENTS" in result.reason
        assert "EXAMPLE" not in result.reason
        assert "Bad:" not in result.reason
        assert "Good:" not in result.reason

    def test_standard_reason_on_third_block(self, handler):
        """Third block (count=2) should return standard message without EXAMPLE."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 2
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Standard message should have WHY BANNED but not EXAMPLE
        assert "WHY BANNED" in result.reason
        assert "Claude gets sed syntax wrong" in result.reason
        assert "PARALLEL HAIKU AGENTS" in result.reason
        assert "EXAMPLE" not in result.reason

    def test_verbose_reason_on_fourth_block(self, handler):
        """Fourth block (count=3) should return verbose message with EXAMPLE."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 3
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Verbose message should have everything including EXAMPLE
        assert "WHY BANNED" in result.reason
        assert "PARALLEL HAIKU AGENTS" in result.reason
        assert "EXAMPLE" in result.reason
        assert "Bad:" in result.reason
        assert "Good:" in result.reason

    def test_verbose_reason_on_many_blocks(self, handler):
        """Many blocks (count=10) should still return verbose message."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.return_value = 10
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Verbose message should have everything including EXAMPLE
        assert "WHY BANNED" in result.reason
        assert "EXAMPLE" in result.reason
        assert "Bad:" in result.reason
        assert "Good:" in result.reason

    def test_data_layer_error_falls_back_to_terse(self, handler):
        """If data layer raises exception, should fall back to terse (count=0)."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.side_effect = Exception("Data layer error")
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            result = handler.handle(hook_input)

        # Should fall back to terse message (count=0)
        assert len(result.reason) < 200
        assert "BLOCKED" in result.reason
        assert "Edit tool" in result.reason
