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

    def test_matches_bash_sed_readonly_pipeline_with_grep_allowed(self, handler):
        """Should NOT match read-only sed in pipeline — no file modification."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat file.txt | sed 's/old/new/' | grep result"},
        }
        # Read-only pipeline: sed transforms stdout, no -i flag, no file modification
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

    def test_is_git_command_rejects_sed_command_chained_after_commit(self, handler):
        """sed chained after git commit via a separator is a SEPARATE command, NOT safe.

        Previously this returned True (treated as part of the message) — a bypass that
        allowed destructive in-place sed to run after a commit. It must be rejected.
        """
        command = "git add file.txt && git commit -m 'message' && sed -i 's/foo/bar/g' file.txt"
        assert handler._is_git_command(command) is False

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

    def test_is_git_command_rejects_sed_after_commit_and_separator(self, handler):
        """_is_git_command() should reject sed chained after git commit via '&&'."""
        command = 'git commit -m "msg" && sed -i s/a/b/ f.py'
        assert handler._is_git_command(command) is False

    def test_is_git_command_rejects_sed_after_commit_semicolon(self, handler):
        """_is_git_command() should reject sed chained after git commit via ';'."""
        command = 'git commit -m "msg"; sed -i s/a/b/ f.py'
        assert handler._is_git_command(command) is False

    def test_is_git_command_rejects_sed_after_commit_pipe(self, handler):
        """_is_git_command() should reject sed chained after git commit via '|'."""
        command = 'git commit -m "msg" | sed -i s/a/b/ f.py'
        assert handler._is_git_command(command) is False

    def test_is_git_command_allows_sed_in_commit_message_no_separator(self, handler):
        """_is_git_command() should still allow sed mentioned inside the commit message."""
        command = 'git commit -m "Fix sed blocker"'
        assert handler._is_git_command(command) is True

    def test_matches_sed_after_commit_separator_blocks(self, handler):
        """matches() should block destructive sed chained after git commit."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "msg" && sed -i s/a/b/ f.py'},
        }
        assert handler.matches(hook_input) is True

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

    def test_is_safe_readonly_command_rejects_grep_pipe_xargs_sed(self, handler):
        """_is_safe_readonly_command() should reject grep piped to xargs sed."""
        command = "grep -rl 'pattern' | xargs sed -i 's/old/new/g'"
        assert handler._is_safe_readonly_command(command) is False

    def test_is_safe_readonly_command_allows_grep_pipe_sed_readonly(self, handler):
        """_is_safe_readonly_command() should allow grep piped to sed (read-only pipeline)."""
        command = "grep -rl 'pattern' | sed 's/old/new/g'"
        assert handler._is_safe_readonly_command(command) is True

    def test_is_safe_readonly_command_rejects_grep_pipe_xargs_sed_complex(self, handler):
        """_is_safe_readonly_command() should reject complex grep | xargs sed."""
        command = (
            "grep -rl 'CLAUDE/Plans' --include='*.md' --include='*.yaml' "
            "| xargs sed -i 's|CLAUDE/Plans|CLAUDE/Plan|g'"
        )
        assert handler._is_safe_readonly_command(command) is False

    def test_is_safe_readonly_command_rejects_sed_i_after_grep_semicolon(self, handler):
        """Destructive sed -i chained after grep via ';' must NOT be treated as safe."""
        command = "grep foo bar.txt; sed -i s/x/y/ f.py"
        assert handler._is_safe_readonly_command(command) is False

    def test_is_safe_readonly_command_rejects_sed_i_after_grep_and(self, handler):
        """Destructive sed -i chained after grep via '&&' must NOT be treated as safe."""
        command = "grep -q x f && sed -i s/a/b/ f.py"
        assert handler._is_safe_readonly_command(command) is False

    def test_is_safe_readonly_command_rejects_sed_after_grep_or(self, handler):
        """sed executed after grep via '||' must NOT be treated as safe."""
        command = "grep x f || sed -i s/a/b/ f.py"
        assert handler._is_safe_readonly_command(command) is False

    def test_matches_sed_i_after_grep_semicolon_blocks(self, handler):
        """matches() should block destructive sed -i chained after grep via ';'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep foo bar.txt; sed -i s/x/y/ f.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_sed_i_after_grep_and_blocks(self, handler):
        """matches() should block destructive sed -i chained after grep via '&&'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -q x f && sed -i s/a/b/ f.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_grep_searching_for_sed_word_still_allowed(self, handler):
        """matches() should still allow grep merely searching for the word 'sed'."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd /workspace; grep sed file.txt"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_grep_pipe_xargs_sed(self, handler):
        """matches() should block grep piped to xargs sed."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -rl 'pattern' | xargs sed -i 's/old/new/g'"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_grep_pipe_sed_readonly_allowed(self, handler):
        """matches() should allow grep piped to sed (read-only pipeline)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -rl 'X' | sed 's/X/Y/g'"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_find_pipe_xargs_sed(self, handler):
        """matches() should block find piped to xargs sed."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.md' | xargs sed -i 's/old/new/g'"},
        }
        assert handler.matches(hook_input) is True

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

    def test_data_layer_unavailable_falls_back_to_terse(self, handler):
        """If data layer/history is unavailable (AttributeError), fall back to terse."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.side_effect = AttributeError("no history")
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

    def test_block_count_does_not_swallow_unexpected_errors(self, handler):
        """Unexpected errors from the data layer must propagate (FAIL FAST)."""
        mock_dl = MagicMock()
        mock_dl.history.count_blocks_by_handler.side_effect = RuntimeError("unexpected")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker.get_data_layer",
            return_value=mock_dl,
        ):
            with pytest.raises(RuntimeError):
                handler._get_block_count()


class TestSedBlockerHandlerBlockingMode:
    """Tests for SedBlockerHandler blocking_mode option.

    blocking_mode controls which tool invocations are blocked:
    - "strict" (default): Block both Bash direct invocation AND Write creating shell scripts
    - "direct_invocation_only": Only block Bash direct invocation, allow Write to create scripts
    """

    @pytest.fixture
    def strict_handler(self):
        """Create handler in strict mode (default, no _blocking_mode set)."""
        return SedBlockerHandler()

    @pytest.fixture
    def direct_invocation_handler(self):
        """Create handler in direct_invocation_only mode."""
        handler = SedBlockerHandler()
        handler._blocking_mode = "direct_invocation_only"
        return handler

    # Tests for strict mode (default behaviour)

    def test_default_mode_blocks_write_sh_with_sed(self, strict_handler):
        """Default strict mode should block Write creating .sh file with sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.sh",
                "content": "#!/bin/bash\nsed -i 's/foo/bar/g' file.txt",
            },
        }
        assert strict_handler.matches(hook_input) is True

    def test_default_mode_blocks_write_bash_with_sed(self, strict_handler):
        """Default strict mode should block Write creating .bash file with sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.bash",
                "content": "#!/bin/bash\ncat file.txt | sed 's/old/new/'",
            },
        }
        assert strict_handler.matches(hook_input) is True

    def test_explicit_strict_mode_blocks_write_sh_with_sed(self, strict_handler):
        """Explicit strict mode should block Write creating .sh file with sed."""
        strict_handler._blocking_mode = "strict"
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.sh",
                "content": "#!/bin/bash\nsed -i 's/foo/bar/g' file.txt",
            },
        }
        assert strict_handler.matches(hook_input) is True

    # Tests for direct_invocation_only mode

    def test_direct_invocation_only_allows_write_sh_with_sed(self, direct_invocation_handler):
        """direct_invocation_only mode should allow Write creating .sh file with sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.sh",
                "content": "#!/bin/bash\nsed -i 's/foo/bar/g' file.txt",
            },
        }
        assert direct_invocation_handler.matches(hook_input) is False

    def test_direct_invocation_only_allows_write_bash_with_sed(self, direct_invocation_handler):
        """direct_invocation_only mode should allow Write creating .bash file with sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/script.bash",
                "content": "#!/bin/bash\ncat file.txt | sed 's/old/new/'",
            },
        }
        assert direct_invocation_handler.matches(hook_input) is False

    def test_direct_invocation_only_allows_write_sh_with_sed_in_function(
        self, direct_invocation_handler
    ):
        """direct_invocation_only mode should allow Write creating .sh with sed in a function."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/functions.sh",
                "content": "#!/bin/bash\nfunction update_file() {\n    sed -i 's/pattern/replacement/g' \"$1\"\n}\n",
            },
        }
        assert direct_invocation_handler.matches(hook_input) is False

    def test_direct_invocation_only_still_blocks_bash_sed(self, direct_invocation_handler):
        """direct_invocation_only mode should still block Bash direct sed invocation."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"},
        }
        assert direct_invocation_handler.matches(hook_input) is True

    def test_direct_invocation_only_still_blocks_bash_sed_with_find(
        self, direct_invocation_handler
    ):
        """direct_invocation_only mode should still block sed via find -exec in Bash."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find . -name '*.txt' -exec sed -i 's/foo/bar/g' {} \\;"},
        }
        assert direct_invocation_handler.matches(hook_input) is True

    def test_direct_invocation_only_still_allows_markdown_writes(self, direct_invocation_handler):
        """direct_invocation_only mode should still allow Write to .md files with sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/README.md",
                "content": "# Usage\n\nDo not use sed, use Edit instead.",
            },
        }
        assert direct_invocation_handler.matches(hook_input) is False

    def test_direct_invocation_only_still_allows_non_shell_file_writes(
        self, direct_invocation_handler
    ):
        """direct_invocation_only mode should still allow Write to non-shell files with sed."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/code.py",
                "content": "# This Python file mentions sed but that is fine",
            },
        }
        assert direct_invocation_handler.matches(hook_input) is False


class TestGuidanceMatchesBehaviour:
    """The resident guidance must describe the rule the code actually enforces.

    Plan 00260 Finding 1: `get_claude_md()` documented `sed -i` / `sed -e` and
    offered an "Allowed (read-only, no file modification)" section, while the
    code blocks strictly more than that -- `sed -n`, a flagless `sed` at a
    command head, and any pipe stage in a command carrying neither `grep` nor
    `echo`. An agent that finds the guidance wrong starts working around the
    guard, so a guard whose published rule is narrower than its real one is a
    defect even when the blocking behaviour is correct.

    DBF: the missing guard was that NOTHING checked guidance against behaviour.
    These tests are that guard. Each asserts the real verdict AND that the
    guidance mentions the case, so changing one without the other fails.
    """

    @pytest.fixture
    def handler(self):
        return SedBlockerHandler()

    @staticmethod
    def _bash(command: str) -> dict:
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    def test_quiet_flag_is_blocked_and_guidance_says_so(self, handler):
        """`sed -n` cannot write, and is blocked anyway. The guidance must admit it."""
        assert handler.matches(self._bash("sed -n '1,20p' /workspace/PLAN.md")) is True

        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "-n" in guidance, "guidance must name the quiet flag it blocks"

    def test_command_head_without_flags_is_blocked_and_guidance_says_so(self, handler):
        """A bare `sed` at a command head is blocked regardless of arguments."""
        assert handler.matches(self._bash("sed 's/x/y/' /workspace/file.txt")) is True

        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "command HEAD" in guidance or "command head" in guidance

    def test_pipe_stage_with_grep_is_allowed(self, handler):
        """The one shape the old guidance documented -- still true, still allowed."""
        assert handler.matches(self._bash("cat f | sed 's/x/y/' | grep z")) is False

    def test_pipe_stage_without_grep_or_echo_is_blocked(self, handler):
        """The surprising half, and the reason the old guidance misled.

        Neither this nor the grep form can modify a file. They differ only by
        whether a `grep`/`echo` appears elsewhere in the command, which the old
        guidance never hinted at -- its single example happened to be the
        allowed one, so the boundary was invisible.
        """
        assert handler.matches(self._bash("cat f | sed 's/x/y/' | wc -l")) is True

    def test_guidance_states_the_grep_echo_condition_with_its_counterexample(self, handler):
        """A rule stated only by a passing example teaches the wrong boundary."""
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert (
            "wc -l" in guidance
        ), "guidance must give the DENIED counter-example, not only the allowed one"
        assert "grep" in guidance and "echo" in guidance


class TestHeredocWrittenShellScripts:
    """A shell script written BY HEREDOC must be judged like one written by `Write`.

    Plan 00260 Task 1.5. The handler's Write branch blocks a `.sh`/`.bash` file
    whose content contains sed. The Bash branch is meant to agree, but
    `_SED_AS_COMMAND_HEAD` is compiled with `re.IGNORECASE` only, so its `^` is
    start-of-STRING. A flagless `sed` on its own line inside a heredoc body sits
    at start-of-LINE and matches neither that pattern nor
    `_SED_WITH_EXECUTION_FLAG` -- so the heredoc route writes a script the Write
    route would have refused.

    The flagged spelling (`sed -i`) IS still caught, because that pattern is
    position-independent. That asymmetry is what makes the gap easy to miss:
    the obvious probe passes.

    The naive fix -- adding `re.MULTILINE` -- is what the third test guards
    against. It would also block a heredoc writing MARKDOWN, and the handler's
    own guidance promises that sed mentioned in `.md` documentation is allowed.
    Widening a guard until it blocks documentation is how a guard gets disabled.
    """

    @pytest.fixture
    def handler(self):
        return SedBlockerHandler()

    @staticmethod
    def _bash(command: str) -> dict:
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    _FLAGLESS_SCRIPT_HEREDOC = (
        "cat > deploy.sh <<'EOF'\n"
        "#!/bin/bash\n"
        "sed 's/old/new/' input.txt > output.txt\n"
        "EOF"
    )

    _FLAGGED_SCRIPT_HEREDOC = (
        "cat > deploy.sh <<'EOF'\n" "#!/bin/bash\n" "sed -i 's/old/new/' input.txt\n" "EOF"
    )

    _MARKDOWN_HEREDOC = (
        "cat > NOTES.md <<'EOF'\n"
        "# Stream editors\n"
        "\n"
        "sed is blocked in this project because it is easy to get wrong.\n"
        "Use the Edit tool instead.\n"
        "EOF"
    )

    def test_flagless_sed_in_a_heredoc_written_script_is_blocked(self, handler):
        """The gap: this writes a .sh containing sed, which `Write` would refuse."""
        assert handler.matches(self._bash(self._FLAGLESS_SCRIPT_HEREDOC)) is True

    def test_flagged_sed_in_a_heredoc_written_script_is_blocked(self, handler):
        """Control: proves the flag pattern is position-independent already.

        This one passed before the fix too. Keeping it pins the asymmetry so a
        future change cannot quietly lose the half that already worked.
        """
        assert handler.matches(self._bash(self._FLAGGED_SCRIPT_HEREDOC)) is True

    def test_bare_word_in_an_unrelated_command_is_blocked(self, handler):
        """Deny-by-default, demonstrated where a pattern list would predict 'allowed'.

        No `-i`, no command-head position, no pipe stage, no xargs. Under the old
        guidance's list-of-blocked-shapes framing an agent would confidently
        expect this to pass. It does not.
        """
        assert handler.matches(self._bash("python3 -c \"print('sed')\"")) is True

    def test_xargs_without_a_flag_is_blocked(self, handler):
        """Also unlisted by the old framing, also blocked."""
        assert handler.matches(self._bash("xargs sed 's/a/b/' file.txt")) is True

    def test_word_inside_a_filename_is_not_blocked(self, handler):
        """The boundary of deny-by-default: it matches the WORD, not substrings.

        Included so the rule is not over-stated in the other direction --
        `sed_notes.txt` contains the letters but not the word.
        """
        assert handler.matches(self._bash("ls sed_notes.txt")) is False

    def test_guidance_states_deny_by_default_not_a_pattern_list(self, handler):
        """The framing itself is the thing under test.

        A list of blocked shapes and a deny-by-default rule with exemptions are
        not two wordings of one rule -- they make opposite predictions about
        every case nobody thought to list. The guidance must say which it is.
        """
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "DENY-BY-DEFAULT" in guidance
        assert "exemption" in guidance.lower()

    def test_guidance_admits_the_md_exemption_is_write_tool_only(self, handler):
        """The guidance must not promise a `.md` allowance the Bash route lacks.

        Plan 00260 Decision 1: a guidance defect is fixed IMMEDIATELY; only the
        behaviour change is deferred. The old wording listed "`.md`
        documentation files" as flatly Allowed, which is true for `Write` and
        false for a Bash heredoc -- so an agent following it got denied and
        learned the guard was unreliable.

        This is the same guard shape as the rest of this file: verdict and
        guidance asserted together, so neither can drift alone.
        """
        # The behaviour the guidance must now describe honestly.
        assert handler.matches(self._bash(self._MARKDOWN_HEREDOC)) is True

        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "Write` tool" in guidance, "guidance must say the .md exemption is Write-tool-only"
        assert "heredoc" in guidance, "guidance must name the heredoc case that is denied"

    def test_guidance_gives_the_allowed_bash_markdown_form(self, handler):
        """Naming only the denial teaches avoidance; name the working route too.

        `echo` carries the command into `_is_safe_readonly_command`, so an
        echo-redirect to markdown genuinely is allowed. Stating that keeps the
        guidance a map rather than a warning.
        """
        assert handler.matches(self._bash("echo 'avoid sed' > NOTES.md")) is False

        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "echo 'avoid sed' > NOTES.md" in guidance

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known BEHAVIOUR defect, Plan 00260 Task 3.1: the Bash branch blocks a "
            "heredoc writing MARKDOWN while the Write branch allows .md. The GUIDANCE "
            "half was fixed immediately per Decision 1 (it now states the exemption is "
            "Write-tool-only and names the working echo-redirect form), so nothing "
            "published is false any more. Only the behaviour is deferred, because "
            "fixing it needs Task 3.1's redirect-target parsing -- a .md check bolted "
            "into the Bash branch would be a second, weaker copy of it and would still "
            "have to keep `cat > x.md <<EOF && sed -i ... real.py` blocked. Flips to a "
            "plain pass when 3.1 lands; fails loudly if 'fixed' by accident."
        ),
    )
    def test_markdown_heredoc_mentioning_sed_is_not_blocked(self, handler):
        """`.md` documentation mentioning sed must be writable by EITHER route.

        `get_claude_md()` promises sed is allowed in `.md` documentation files.
        That promise holds for `Write` and is false for a Bash heredoc.
        Documenting the rule must not trip the rule -- this repository writes
        exactly such prose, and a guard that blocks its own documentation is one
        an agent learns to route around.
        """
        assert handler.matches(self._bash(self._MARKDOWN_HEREDOC)) is False
