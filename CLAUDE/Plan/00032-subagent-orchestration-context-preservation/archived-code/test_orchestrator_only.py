"""Comprehensive tests for OrchestratorOnlyHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.orchestrator_only import (
    OrchestratorOnlyHandler,
)


class TestOrchestratorOnlyHandler:
    """Test suite for OrchestratorOnlyHandler."""

    @pytest.fixture
    def handler(self) -> OrchestratorOnlyHandler:
        """Create handler instance (enabled)."""
        handler = OrchestratorOnlyHandler()
        handler.set_enabled(True)
        return handler

    @pytest.fixture
    def disabled_handler(self) -> OrchestratorOnlyHandler:
        """Create handler instance (disabled - default)."""
        return OrchestratorOnlyHandler()

    # ===== Initialization Tests =====

    def test_init_sets_correct_name(self, handler: OrchestratorOnlyHandler) -> None:
        """Handler name should be 'orchestrator-only-mode'."""
        assert handler.name == "orchestrator-only-mode"

    def test_init_sets_correct_priority(self, handler: OrchestratorOnlyHandler) -> None:
        """Handler priority should be 8 (before all other handlers)."""
        assert handler.priority == 8

    def test_init_sets_terminal_true(self, handler: OrchestratorOnlyHandler) -> None:
        """Handler should be terminal (blocks execution chain)."""
        assert handler.terminal is True

    def test_init_disabled_by_default(self, disabled_handler: OrchestratorOnlyHandler) -> None:
        """Handler should be disabled by default (opt-in)."""
        assert disabled_handler.enabled is False

    # ===== matches() - Disabled handler allows everything =====

    def test_disabled_allows_edit(self, disabled_handler: OrchestratorOnlyHandler) -> None:
        """When disabled (default), should allow Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/src/main.py", "old_string": "a", "new_string": "b"},
        }
        assert disabled_handler.matches(hook_input) is False

    def test_disabled_allows_write(self, disabled_handler: OrchestratorOnlyHandler) -> None:
        """When disabled (default), should allow Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/src/main.py", "content": "hello"},
        }
        assert disabled_handler.matches(hook_input) is False

    def test_disabled_allows_bash(self, disabled_handler: OrchestratorOnlyHandler) -> None:
        """When disabled (default), should allow Bash tool."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp/test"},
        }
        assert disabled_handler.matches(hook_input) is False

    # ===== matches() - Enabled: Blocks work tools =====

    def test_enabled_blocks_edit(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/src/main.py", "old_string": "a", "new_string": "b"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_write(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/src/main.py", "content": "hello"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_notebook_edit(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block NotebookEdit tool."""
        hook_input = {
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": "/notebook.ipynb", "new_source": "print('hi')"},
        }
        assert handler.matches(hook_input) is True

    # ===== matches() - Enabled: Blocks mutating Bash =====

    def test_enabled_blocks_rm_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block rm command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp/test"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_mv_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block mv command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "mv file1.txt file2.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_mkdir_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block mkdir command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p /tmp/new_dir"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_cp_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block cp command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cp file1.txt file2.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_touch_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block touch command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "touch newfile.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_chmod_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block chmod command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "chmod +x script.sh"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_npm_install(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block npm install."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install express"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_pip_install(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block pip install."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pip install requests"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_python_script(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block running python scripts."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "python setup.py install"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_sed_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block sed command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i 's/old/new/g' file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_enabled_blocks_tee_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block tee command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "tee output.txt"},
        }
        assert handler.matches(hook_input) is True

    # ===== matches() - Enabled: Allows orchestration tools =====

    def test_enabled_allows_task(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow Task tool (delegation)."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {"prompt": "Implement the feature"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_task_create(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow TaskCreate tool."""
        hook_input = {
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "New task"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_task_update(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow TaskUpdate tool."""
        hook_input = {
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "1", "status": "completed"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_task_get(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow TaskGet tool."""
        hook_input = {
            "tool_name": "TaskGet",
            "tool_input": {"taskId": "1"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_task_list(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow TaskList tool."""
        hook_input = {
            "tool_name": "TaskList",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_read(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow Read tool."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/src/main.py"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_glob(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow Glob tool."""
        hook_input = {
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_grep(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow Grep tool."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "def main"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_web_search(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow WebSearch tool."""
        hook_input = {
            "tool_name": "WebSearch",
            "tool_input": {"query": "python docs"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_web_fetch(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow WebFetch tool."""
        hook_input = {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://example.com"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_ask_user_question(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow AskUserQuestion tool."""
        hook_input = {
            "tool_name": "AskUserQuestion",
            "tool_input": {"question": "Should I proceed?"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_enter_plan_mode(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow EnterPlanMode tool."""
        hook_input = {
            "tool_name": "EnterPlanMode",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_exit_plan_mode(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow ExitPlanMode tool."""
        hook_input = {
            "tool_name": "ExitPlanMode",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_skill(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow Skill tool."""
        hook_input = {
            "tool_name": "Skill",
            "tool_input": {"skill": "commit"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_send_message(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow SendMessage tool."""
        hook_input = {
            "tool_name": "SendMessage",
            "tool_input": {"type": "message", "recipient": "agent", "content": "hi"},
        }
        assert handler.matches(hook_input) is False

    # ===== matches() - Enabled: Allows read-only Bash commands =====

    def test_enabled_allows_git_status(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow git status."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_git_log(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow git log."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git log --oneline -10"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_git_diff(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow git diff."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git diff HEAD~1"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_git_branch(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow git branch (listing)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git branch -a"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_git_show(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow git show."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git show HEAD"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_ls_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow ls command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la /src"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_cat_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow cat command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat /src/main.py"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_head_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow head command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "head -20 /src/main.py"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_tail_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow tail command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "tail -50 /var/log/app.log"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_find_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow find command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "find /src -name '*.py'"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_grep_bash(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow grep in bash."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -rn 'import' /src"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_wc_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow wc command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "wc -l /src/main.py"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_pwd_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow pwd command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "pwd"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_which_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow which command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "which python"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_echo_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow echo command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'hello world'"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_env_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow env command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "env"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_printenv_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow printenv command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "printenv PATH"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_whoami_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow whoami command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "whoami"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_hostname_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow hostname command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "hostname"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_date_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow date command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "date"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_file_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow file command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "file /src/main.py"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_du_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow du command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "du -sh /src"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_df_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow df command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "df -h"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_tree_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow tree command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "tree /src -L 2"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_allows_gh_command(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow gh (GitHub CLI) commands."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "gh issue list"},
        }
        assert handler.matches(hook_input) is False

    # ===== matches() - Edge cases =====

    def test_enabled_empty_command_allows(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should allow empty bash command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": ""},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_none_tool_name(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should not match if tool_name is missing."""
        hook_input: dict[str, object] = {
            "tool_input": {"command": "rm -rf /"},
        }
        assert handler.matches(hook_input) is False

    def test_enabled_unknown_tool_blocks(self, handler: OrchestratorOnlyHandler) -> None:
        """When enabled, should block unknown tools (deny by default)."""
        hook_input = {
            "tool_name": "SomeNewTool",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is True

    # ===== handle() Tests =====

    def test_handle_returns_deny(self, handler: OrchestratorOnlyHandler) -> None:
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/src/main.py"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_mentions_task_tool(self, handler: OrchestratorOnlyHandler) -> None:
        """handle() reason should direct user to Task tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/src/main.py"},
        }
        result = handler.handle(hook_input)
        assert "Task" in result.reason

    def test_handle_reason_mentions_tool_name(self, handler: OrchestratorOnlyHandler) -> None:
        """handle() reason should mention the blocked tool name."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/src/main.py"},
        }
        result = handler.handle(hook_input)
        assert "Write" in result.reason

    def test_handle_reason_mentions_orchestrator(self, handler: OrchestratorOnlyHandler) -> None:
        """handle() reason should mention orchestrator mode."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/src/main.py"},
        }
        result = handler.handle(hook_input)
        assert "orchestrator" in result.reason.lower()

    def test_handle_bash_mentions_command(self, handler: OrchestratorOnlyHandler) -> None:
        """handle() reason should include the blocked bash command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install express"},
        }
        result = handler.handle(hook_input)
        assert "npm install express" in result.reason

    # ===== Configurable allowlist =====

    def test_custom_readonly_bash_prefixes(self) -> None:
        """Should support configurable read-only Bash prefix allowlist."""
        handler = OrchestratorOnlyHandler()
        handler.set_enabled(True)
        handler.set_readonly_bash_prefixes(["git status", "git log", "custom-tool"])

        # Allowed by custom list
        hook_input_allowed = {
            "tool_name": "Bash",
            "tool_input": {"command": "custom-tool --check"},
        }
        assert handler.matches(hook_input_allowed) is False

        # Blocked because not in custom list
        hook_input_blocked = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
        }
        assert handler.matches(hook_input_blocked) is True

    # ===== Integration-style tests =====

    def test_blocks_all_work_tools(self, handler: OrchestratorOnlyHandler) -> None:
        """Should block all work tools when enabled."""
        blocked_tools = [
            ("Edit", {"file_path": "/f.py", "old_string": "a", "new_string": "b"}),
            ("Write", {"file_path": "/f.py", "content": "hello"}),
            ("NotebookEdit", {"notebook_path": "/n.ipynb", "new_source": "x"}),
        ]
        for tool_name, tool_input in blocked_tools:
            hook_input = {"tool_name": tool_name, "tool_input": tool_input}
            assert handler.matches(hook_input) is True, f"Should block: {tool_name}"

    def test_allows_all_orchestration_tools(self, handler: OrchestratorOnlyHandler) -> None:
        """Should allow all orchestration tools when enabled."""
        allowed_tools = [
            ("Task", {"prompt": "do work"}),
            ("TaskCreate", {"subject": "task"}),
            ("TaskUpdate", {"taskId": "1"}),
            ("TaskGet", {"taskId": "1"}),
            ("TaskList", {}),
            ("Read", {"file_path": "/f.py"}),
            ("Glob", {"pattern": "*.py"}),
            ("Grep", {"pattern": "main"}),
            ("WebSearch", {"query": "docs"}),
            ("WebFetch", {"url": "https://example.com"}),
            ("AskUserQuestion", {"question": "yes?"}),
            ("EnterPlanMode", {}),
            ("ExitPlanMode", {}),
            ("Skill", {"skill": "commit"}),
            ("SendMessage", {"type": "message"}),
            ("TaskOutput", {"taskId": "1"}),
            ("TaskStop", {"taskId": "1"}),
        ]
        for tool_name, tool_input in allowed_tools:
            hook_input = {"tool_name": tool_name, "tool_input": tool_input}
            assert handler.matches(hook_input) is False, f"Should allow: {tool_name}"

    def test_allows_all_readonly_bash(self, handler: OrchestratorOnlyHandler) -> None:
        """Should allow all read-only bash commands when enabled."""
        readonly_commands = [
            "git status",
            "git log --oneline",
            "git diff HEAD",
            "git branch -a",
            "git show HEAD",
            "ls -la /src",
            "cat README.md",
            "head -20 file.txt",
            "tail -50 file.txt",
            "find /src -name '*.py'",
            "grep -rn 'import' /src",
            "wc -l file.txt",
            "pwd",
            "which python",
            "echo hello",
            "env",
            "printenv PATH",
            "whoami",
            "hostname",
            "date",
            "file /src/main.py",
            "du -sh /src",
            "df -h",
            "tree /src",
            "gh issue list",
        ]
        for cmd in readonly_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"

    def test_blocks_all_mutating_bash(self, handler: OrchestratorOnlyHandler) -> None:
        """Should block all mutating bash commands when enabled."""
        mutating_commands = [
            "rm -rf /tmp/test",
            "mv file1.txt file2.txt",
            "mkdir -p /tmp/new_dir",
            "cp file1.txt file2.txt",
            "touch newfile.txt",
            "chmod +x script.sh",
            "npm install express",
            "pip install requests",
            "python setup.py install",
            "sed -i 's/old/new/g' file.txt",
        ]
        for cmd in mutating_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is True, f"Should block: {cmd}"
