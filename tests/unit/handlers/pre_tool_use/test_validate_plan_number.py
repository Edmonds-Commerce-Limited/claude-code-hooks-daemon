"""Tests for ValidatePlanNumberHandler.

Comprehensive test coverage for plan number validation.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for handler instantiation tests."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.validate_plan_number import (
    ValidatePlanNumberHandler,
)


class TestValidatePlanNumberHandler:
    """Test suite for ValidatePlanNumberHandler."""

    @pytest.fixture
    def temp_workspace(self, tmp_path: Path) -> Path:
        """Create temporary workspace directory."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        return workspace

    @pytest.fixture
    def handler(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> ValidatePlanNumberHandler:
        """Create handler instance with temporary workspace."""
        monkeypatch.setenv("PWD", str(temp_workspace))
        handler = ValidatePlanNumberHandler()
        handler.workspace_root = temp_workspace
        return handler

    @pytest.fixture
    def plan_root(self, temp_workspace: Path) -> Path:
        """Create CLAUDE/Plan directory structure."""
        plan_root = temp_workspace / "CLAUDE" / "Plan"
        plan_root.mkdir(parents=True)
        return plan_root

    # Tests for matches() method

    def test_matches_write_operation_with_plan_folder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler matches Write operation creating a plan folder."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test-plan/README.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_mkdir_with_plan_folder(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler matches Bash mkdir command for plan folder."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/001-test-plan"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_mkdir_with_multiple_flags(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler matches mkdir with various flags."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p -v CLAUDE/Plan/042-feature"},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_git_mv_to_completed(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler does not match git mv archiving a plan to Completed/."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "mkdir -p CLAUDE/Plan/Completed && "
                    "git mv CLAUDE/Plan/023-defence-before-fix-skill "
                    "CLAUDE/Plan/Completed/023-defence-before-fix-skill"
                )
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_git_mv_to_any_subfolder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler does not match git mv archiving a plan to any organizational subfolder."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "mkdir -p CLAUDE/Plan/Archive && "
                    "git mv CLAUDE/Plan/023-old CLAUDE/Plan/Archive/023-old"
                )
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_write_to_completed_folder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler does not match Write operations under Completed/."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/Completed/023-old-plan/PLAN.md"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_write_to_any_organizational_subfolder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler does not match Write under any non-numbered subfolder of Plan."""
        for subfolder in ["Archive", "Backlog", "OnHold", "v1"]:
            hook_input: dict[str, Any] = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": f"/workspace/CLAUDE/Plan/{subfolder}/023-old-plan/PLAN.md"
                },
            }
            assert handler.matches(hook_input) is False, f"Should not match subfolder {subfolder}"

    def test_does_not_match_mkdir_completed_folder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler does not match mkdir for Completed/ subdirectory."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/Completed/023-old-plan"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_mkdir_any_organizational_subfolder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler does not match mkdir under any non-numbered subfolder of Plan."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/Archive/023-old-plan"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_write_outside_plan_folder(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler does not match Write operations outside plan folders."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/main.py"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_bash_mkdir_outside_plan(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler does not match mkdir outside CLAUDE/Plan."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p src/handlers"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_documentation_command_file(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler skips slash command documentation files."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/.claude/commands/CLAUDE/Plan/001-example/README.md"
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_hook_documentation_file(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler skips hook documentation files."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/.claude/hooks/CLAUDE/Plan/001-example/README.md"
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_heredoc_command(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler skips heredoc commands (documentation examples)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat > example.md << 'EOF'\nmkdir CLAUDE/Plan/001-test\nEOF"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_heredoc_without_quotes(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """Handler skips heredoc without quotes around delimiter."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat > file << EOF\nmkdir CLAUDE/Plan/001-test\nEOF"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_other_tool_types(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler does not match non-Write/non-Bash tools."""
        hook_input: dict[str, Any] = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-test/README.md"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_empty_command(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler does not match when command is empty."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": ""},
        }
        assert handler.matches(hook_input) is False

    # Tests for _is_documentation_file() method

    def test_is_documentation_file_identifies_command_files(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_is_documentation_file identifies slash command files."""
        assert handler._is_documentation_file("/.claude/commands/test.md") is True
        assert handler._is_documentation_file("/workspace/.claude/commands/plan.md") is True

    def test_is_documentation_file_identifies_hook_md_files(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_is_documentation_file identifies hook markdown files."""
        assert handler._is_documentation_file("/.claude/hooks/example.md") is True
        assert handler._is_documentation_file("/workspace/.claude/hooks/readme.md") is True

    def test_is_documentation_file_case_insensitive(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_is_documentation_file is case insensitive."""
        assert handler._is_documentation_file("/.CLAUDE/COMMANDS/test.md") is True
        assert handler._is_documentation_file("/.Claude/Hooks/README") is True

    def test_is_documentation_file_rejects_non_docs(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_is_documentation_file rejects non-documentation files."""
        assert handler._is_documentation_file("/workspace/CLAUDE/Plan/001-test/README.md") is False
        assert handler._is_documentation_file("/src/handlers/test.py") is False

    # Tests for _is_heredoc_command() method

    def test_is_heredoc_command_with_single_quotes(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_is_heredoc_command identifies heredoc with single quotes."""
        assert handler._is_heredoc_command("cat > file << 'EOF'") is True

    def test_is_heredoc_command_with_double_quotes(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_is_heredoc_command identifies heredoc with double quotes."""
        assert handler._is_heredoc_command('cat > file << "EOF"') is True

    def test_is_heredoc_command_without_quotes(self, handler: ValidatePlanNumberHandler) -> None:
        """_is_heredoc_command identifies heredoc without quotes."""
        assert handler._is_heredoc_command("cat > file << EOF") is True

    def test_is_heredoc_command_with_different_delimiters(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_is_heredoc_command identifies various delimiters."""
        assert handler._is_heredoc_command("cat > file << 'MARKER'") is True
        assert handler._is_heredoc_command("cat > file << END") is True
        assert handler._is_heredoc_command("cat > file << CONTENT") is True

    def test_is_heredoc_command_rejects_non_heredoc(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_is_heredoc_command rejects non-heredoc commands."""
        assert handler._is_heredoc_command("mkdir -p CLAUDE/Plan/001-test") is False
        assert handler._is_heredoc_command("echo 'test' > file.txt") is False

    # Tests for _get_highest_plan_number() method

    def test_get_highest_plan_number_no_plan_directory(
        self, handler: ValidatePlanNumberHandler
    ) -> None:
        """_get_highest_plan_number returns 0 when CLAUDE/Plan doesn't exist."""
        highest = handler._get_highest_plan_number()
        assert highest == 0

    def test_get_highest_plan_number_empty_directory(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number returns 0 for empty plan directory."""
        highest = handler._get_highest_plan_number()
        assert highest == 0

    def test_get_highest_plan_number_single_active_plan(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number finds single active plan."""
        (plan_root / "001-first-plan").mkdir()
        highest = handler._get_highest_plan_number()
        assert highest == 1

    def test_get_highest_plan_number_multiple_active_plans(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number finds highest among multiple active plans."""
        (plan_root / "001-first").mkdir()
        (plan_root / "005-second").mkdir()
        (plan_root / "003-third").mkdir()
        highest = handler._get_highest_plan_number()
        assert highest == 5

    def test_get_highest_plan_number_single_completed_plan(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number finds completed plan."""
        completed_dir = plan_root / "Completed"
        completed_dir.mkdir()
        (completed_dir / "010-completed-plan").mkdir()
        highest = handler._get_highest_plan_number()
        assert highest == 10

    def test_get_highest_plan_number_active_and_completed(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number checks both active and completed plans."""
        (plan_root / "005-active").mkdir()
        completed_dir = plan_root / "Completed"
        completed_dir.mkdir()
        (completed_dir / "015-completed").mkdir()
        highest = handler._get_highest_plan_number()
        assert highest == 15

    def test_get_highest_plan_number_scans_all_organizational_subfolders(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number scans ALL non-numbered subfolders, not just Completed/."""
        (plan_root / "005-active").mkdir()
        archive_dir = plan_root / "Archive"
        archive_dir.mkdir()
        (archive_dir / "020-archived").mkdir()
        backlog_dir = plan_root / "Backlog"
        backlog_dir.mkdir()
        (backlog_dir / "025-backlogged").mkdir()
        highest = handler._get_highest_plan_number()
        assert highest == 25

    def test_get_highest_plan_number_ignores_non_numbered_dirs(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number ignores directories without numeric prefix."""
        (plan_root / "001-valid").mkdir()
        (plan_root / "template").mkdir()
        (plan_root / "README.md").touch()
        highest = handler._get_highest_plan_number()
        assert highest == 1

    def test_get_highest_plan_number_ignores_invalid_format(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number ignores directories with invalid format."""
        (plan_root / "005-valid").mkdir()
        (plan_root / "1-invalid").mkdir()  # Not 3 digits
        (plan_root / "abc-invalid").mkdir()  # No digits
        highest = handler._get_highest_plan_number()
        assert highest == 5

    def test_get_highest_plan_number_three_digit_format(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """_get_highest_plan_number requires three-digit format."""
        (plan_root / "099-high").mkdir()
        (plan_root / "100-higher").mkdir()
        highest = handler._get_highest_plan_number()
        assert highest == 100

    # Tests for handle() method - Write operations

    def test_handle_write_correct_plan_number_first_plan(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler allows Write operation with correct plan number (first plan)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/001-first-plan/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_correct_plan_number_sequential(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler allows Write operation with correct sequential plan number."""
        (plan_root / "001-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/002-new-plan/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_incorrect_plan_number_too_high(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler warns when plan number is too high."""
        (plan_root / "005-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/010-new-plan/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW  # Non-terminal handler
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]
        assert "You are creating: CLAUDE/Plan/010-new-plan/" in result.context[0]
        assert "Highest existing plan: 005" in result.context[0]
        assert "Expected next number: 006" in result.context[0]

    def test_handle_write_incorrect_plan_number_too_low(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler warns when plan number is too low (reusing old number)."""
        (plan_root / "010-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/005-new-plan/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]
        assert "Expected next number: 011" in result.context[0]

    def test_handle_write_with_completed_plans(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler considers completed plans when validating."""
        (plan_root / "003-active").mkdir()
        completed_dir = plan_root / "Completed"
        completed_dir.mkdir()
        (completed_dir / "020-completed").mkdir()

        # Should expect 021 (highest is 020 in Completed)
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/021-new-plan/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_write_incorrect_with_completed_plans(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler warns when ignoring completed plans."""
        (plan_root / "005-active").mkdir()
        completed_dir = plan_root / "Completed"
        completed_dir.mkdir()
        (completed_dir / "030-completed").mkdir()

        # Trying to use 006 when highest is 030
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/006-new-plan/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "Highest existing plan: 030" in result.context[0]
        assert "Expected next number: 031" in result.context[0]
        assert "BOTH active plans" in result.context[0]

    # Tests for handle() method - Bash operations

    def test_handle_bash_correct_plan_number(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler allows Bash mkdir with correct plan number."""
        (plan_root / "012-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/013-new-plan"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_bash_incorrect_plan_number(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler warns for Bash mkdir with incorrect plan number."""
        (plan_root / "007-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p CLAUDE/Plan/020-new-plan"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context
        assert "PLAN NUMBER INCORRECT" in result.context[0]
        assert "Expected next number: 008" in result.context[0]

    def test_handle_bash_mkdir_with_flags(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Handler extracts plan number from mkdir with various flags."""
        (plan_root / "015-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p -v -m 755 CLAUDE/Plan/016-new-plan"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    # Tests for edge cases

    def test_handle_no_plan_number_extracted(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler allows when plan number cannot be extracted."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/other/file.txt"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_handle_empty_file_path(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler allows when file path is empty."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": ""},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_missing_tool_input(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler allows when tool_input is missing."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_error_message_includes_find_command(
        self, handler: ValidatePlanNumberHandler, plan_root: Path
    ) -> None:
        """Error message includes find command for discovering correct number."""
        (plan_root / "042-existing").mkdir()
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/CLAUDE/Plan/050-wrong/README.md"},
        }
        result = handler.handle(hook_input)
        assert result.context
        assert "find CLAUDE/Plan -maxdepth 2 -type d -name '[0-9]*'" in result.context[0]
        assert "mkdir -p CLAUDE/Plan/043-wrong" in result.context[0]

    # Tests for handler metadata

    def test_handler_has_correct_name(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler has correct name."""
        assert handler.name == "validate-plan-number"

    def test_handler_has_correct_priority(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler has correct priority."""
        assert handler.priority == 30

    def test_handler_is_non_terminal(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler is non-terminal (advisory)."""
        assert handler.terminal is False

    def test_handler_has_correct_tags(self, handler: ValidatePlanNumberHandler) -> None:
        """Handler has correct tags."""
        assert "workflow" in handler.tags
        assert "planning" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags
