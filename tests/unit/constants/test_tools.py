"""Tests for Claude Code tool name constants.

Tests that all tool name constants are properly defined and match
the actual tool names used by Claude Code.
"""

from typing import get_args

from claude_code_hooks_daemon.constants.tools import ToolName, ToolNameLiteral


class TestToolNameConstants:
    """Tests for ToolName constant values."""

    def test_bash_tool(self) -> None:
        """Test Bash tool constant."""
        assert ToolName.BASH == "Bash"

    def test_file_operation_tools(self) -> None:
        """Test file operation tool constants."""
        assert ToolName.WRITE == "Write"
        assert ToolName.EDIT == "Edit"
        assert ToolName.READ == "Read"
        assert ToolName.GLOB == "Glob"
        assert ToolName.GREP == "Grep"

    def test_web_access_tools(self) -> None:
        """Test web access tool constants."""
        assert ToolName.WEB_SEARCH == "WebSearch"
        assert ToolName.WEB_FETCH == "WebFetch"

    def test_task_management_tools(self) -> None:
        """Test task management tool constants."""
        assert ToolName.TASK == "Task"
        assert ToolName.TASK_CREATE == "TaskCreate"
        assert ToolName.TASK_UPDATE == "TaskUpdate"
        assert ToolName.TASK_GET == "TaskGet"
        assert ToolName.TASK_LIST == "TaskList"
        assert ToolName.TASK_OUTPUT == "TaskOutput"
        assert ToolName.TASK_STOP == "TaskStop"

    def test_skill_tool(self) -> None:
        """Test Skill tool constant."""
        assert ToolName.SKILL == "Skill"

    def test_plan_mode_tools(self) -> None:
        """Test plan mode tool constants."""
        assert ToolName.ENTER_PLAN_MODE == "EnterPlanMode"
        assert ToolName.EXIT_PLAN_MODE == "ExitPlanMode"

    def test_user_interaction_tools(self) -> None:
        """Test user interaction tool constants."""
        assert ToolName.ASK_USER_QUESTION == "AskUserQuestion"

    def test_notebook_tools(self) -> None:
        """Test notebook tool constants."""
        assert ToolName.NOTEBOOK_EDIT == "NotebookEdit"


class TestToolNameLiteralType:
    """Tests for ToolNameLiteral type."""

    def test_tool_name_literal_includes_all_tools(self) -> None:
        """Test that ToolNameLiteral includes all ToolName values."""
        tool_literal_values = set(get_args(ToolNameLiteral))

        # Get all ToolName constant values
        tool_name_values = {
            value
            for key, value in vars(ToolName).items()
            if not key.startswith("_") and isinstance(value, str)
        }

        assert tool_literal_values == tool_name_values

    def test_tool_name_literal_count(self) -> None:
        """Test that ToolNameLiteral has expected number of values."""
        tool_literal_values = get_args(ToolNameLiteral)
        # Should have 20+ tools
        assert len(tool_literal_values) >= 20


class TestToolNameUsage:
    """Tests for tool name usage patterns."""

    def test_tool_names_can_be_compared(self) -> None:
        """Test that tool names can be used in comparisons."""
        tool_name = "Bash"
        assert tool_name == ToolName.BASH

    def test_tool_names_can_be_used_in_list(self) -> None:
        """Test that tool names can be used in lists."""
        file_tools = [ToolName.WRITE, ToolName.EDIT, ToolName.READ]
        assert len(file_tools) == 3
        assert ToolName.WRITE in file_tools

    def test_tool_names_are_strings(self) -> None:
        """Test that all tool name constants are strings."""
        for key, value in vars(ToolName).items():
            if not key.startswith("_"):
                assert isinstance(value, str), f"{key} should be a string"

    def test_no_duplicate_values(self) -> None:
        """Test that there are no duplicate tool name values."""
        tool_values = [
            value
            for key, value in vars(ToolName).items()
            if not key.startswith("_") and isinstance(value, str)
        ]
        assert len(tool_values) == len(set(tool_values)), "Duplicate tool names found"

    def test_tool_names_use_pascalcase(self) -> None:
        """Test that tool names follow PascalCase convention."""
        for key, value in vars(ToolName).items():
            if not key.startswith("_") and isinstance(value, str):
                # First character should be uppercase (PascalCase)
                assert value[0].isupper(), f"{key}={value} not PascalCase"
                # No spaces or special chars (except for compound names)
                assert " " not in value, f"{key}={value} contains spaces"


class TestCriticalToolNames:
    """Tests for commonly used tool names."""

    def test_most_common_tools(self) -> None:
        """Test the most commonly used tools are defined."""
        # These are the tools most frequently checked in handlers
        assert ToolName.BASH == "Bash"
        assert ToolName.WRITE == "Write"
        assert ToolName.EDIT == "Edit"
        assert ToolName.READ == "Read"

    def test_file_operation_group(self) -> None:
        """Test file operation tools can be grouped."""
        file_ops = [ToolName.WRITE, ToolName.EDIT]
        assert "Write" in file_ops
        assert "Edit" in file_ops


class TestToolNamePatterns:
    """Tests for tool name patterns used in handlers."""

    def test_tool_name_comparison_pattern(self) -> None:
        """Test common pattern: tool_name == ToolName.X."""
        hook_input = {"toolName": "Bash"}
        tool_name = hook_input.get("toolName")
        assert tool_name == ToolName.BASH

    def test_tool_name_in_list_pattern(self) -> None:
        """Test common pattern: tool_name in [ToolName.X, ToolName.Y]."""
        hook_input = {"toolName": "Write"}
        tool_name = hook_input.get("toolName")
        assert tool_name in [ToolName.WRITE, ToolName.EDIT]

    def test_tool_name_membership_check(self) -> None:
        """Test membership checks with tool names."""
        tool_name = "Edit"
        file_modification_tools = [ToolName.WRITE, ToolName.EDIT]
        assert tool_name in file_modification_tools


class TestToolNameExport:
    """Tests for module exports."""

    def test_all_exports(self) -> None:
        """Test that __all__ contains expected exports."""
        from claude_code_hooks_daemon.constants import tools

        assert hasattr(tools, "__all__")
        assert "ToolName" in tools.__all__
        assert "ToolNameLiteral" in tools.__all__

    def test_tool_name_importable_from_constants(self) -> None:
        """Test that ToolName can be imported from constants package."""
        from claude_code_hooks_daemon.constants import ToolName as ImportedToolName

        assert ImportedToolName.BASH == "Bash"
        assert ImportedToolName.WRITE == "Write"


class TestTaskTools:
    """Tests for task-related tool names."""

    def test_all_task_tools_defined(self) -> None:
        """Test that all task management tools are defined."""
        task_tools = [
            ToolName.TASK,
            ToolName.TASK_CREATE,
            ToolName.TASK_UPDATE,
            ToolName.TASK_GET,
            ToolName.TASK_LIST,
            ToolName.TASK_OUTPUT,
            ToolName.TASK_STOP,
        ]
        assert len(task_tools) == 7
        assert all(isinstance(tool, str) for tool in task_tools)


class TestPlanModeTools:
    """Tests for plan mode tool names."""

    def test_plan_mode_tools_defined(self) -> None:
        """Test that plan mode tools are defined."""
        assert ToolName.ENTER_PLAN_MODE == "EnterPlanMode"
        assert ToolName.EXIT_PLAN_MODE == "ExitPlanMode"

    def test_plan_mode_tools_are_distinct(self) -> None:
        """Test that enter and exit plan mode have different values."""
        assert ToolName.ENTER_PLAN_MODE != ToolName.EXIT_PLAN_MODE
