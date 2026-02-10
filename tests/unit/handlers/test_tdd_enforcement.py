"""Comprehensive tests for TddEnforcementHandler."""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import TddEnforcementHandler


class TestTddEnforcementHandler:
    """Test suite for TddEnforcementHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return TddEnforcementHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'enforce-tdd'."""
        assert handler.name == "enforce-tdd"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 15."""
        assert handler.priority == 15

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    # matches() - Positive Cases: Handler files in event directories
    def test_matches_pre_tool_use_handler_file(self, handler):
        """Should match handler file in pre_tool_use directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_post_tool_use_handler_file(self, handler):
        """Should match handler file in post_tool_use directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/post_tool_use/my_handler.py"
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_user_prompt_submit_handler_file(self, handler):
        """Should match handler file in user_prompt_submit directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/user_prompt_submit/my_handler.py"
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_subagent_stop_handler_file(self, handler):
        """Should match handler file in subagent_stop directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/subagent_stop/my_handler.py"
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_handler_file_with_different_path_prefix(self, handler):
        """Should match handler file regardless of path prefix."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/different/path/handlers/pre_tool_use/my_handler.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_handler_file_with_underscores_in_name(self, handler):
        """Should match handler file with underscores in name."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/handlers/pre_tool_use/my_complex_handler_v2.py"
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Exclusions and non-handlers
    def test_matches_init_file_returns_false(self, handler):
        """Should NOT match __init__.py files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/handlers/pre_tool_use/__init__.py"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_tool_returns_false(self, handler):
        """Should NOT match Edit tool (only Write)."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/handlers/pre_tool_use/my_handler.py"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_bash_tool_returns_false(self, handler):
        """Should NOT match Bash tool."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "touch /workspace/handlers/pre_tool_use/my_handler.py"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_non_py_file_returns_false(self, handler):
        """Should NOT match non-Python files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/handlers/pre_tool_use/config.json"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_src_directory_file(self, handler):
        """Should match files in src directory (production code)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/core/my_module.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_handlers_directory_file(self, handler):
        """Should match files in handlers/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/handlers/my_handler.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_test_file_returns_false(self, handler):
        """Should NOT match test files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/tests/handlers/test_my_handler.py"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_handler_in_test_named_directory(self, handler):
        """Should match handler file even in directory with 'test' in name."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/test-handlers/pre_tool_use/fake_handler.py"},
        }
        # This is a handler file (has /handlers/ in path), not a test file
        # The "test-" is in the parent directory name, not indicating a test file
        assert handler.matches(hook_input) is True

    def test_matches_missing_file_path_returns_false(self, handler):
        """Should NOT match when file_path is missing."""
        hook_input = {"tool_name": "Write", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_matches_none_file_path_returns_false(self, handler):
        """Should NOT match when file_path is None."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": None}}
        assert handler.matches(hook_input) is False

    def test_matches_empty_file_path_returns_false(self, handler):
        """Should NOT match when file_path is empty."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should NOT match when tool_input is missing."""
        hook_input = {"tool_name": "Write"}
        assert handler.matches(hook_input) is False

    # handle() Tests - Test file exists (allow)
    @patch("pathlib.Path.exists")
    def test_handle_allows_when_test_file_exists(self, mock_exists, handler):
        """handle() should allow when test file exists."""
        mock_exists.return_value = True
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert result.reason is None

    @patch("pathlib.Path.exists")
    def test_handle_calls_exists_on_test_file_path(self, mock_exists, handler):
        """handle() should check if test file exists."""
        mock_exists.return_value = True
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        handler.handle(hook_input)
        # Should call exists() on the Path object
        assert mock_exists.called

    # handle() Tests - Test file missing (deny)
    @patch("pathlib.Path.exists")
    def test_handle_denies_when_test_file_missing(self, mock_exists, handler):
        """handle() should deny when test file is missing."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    @patch("pathlib.Path.exists")
    def test_handle_reason_contains_handler_filename(self, mock_exists, handler):
        """handle() reason should include handler filename."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert "my_handler.py" in result.reason

    @patch("pathlib.Path.exists")
    def test_handle_reason_contains_test_filename(self, mock_exists, handler):
        """handle() reason should include expected test filename."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert "test_my_handler.py" in result.reason

    @patch("pathlib.Path.exists")
    def test_handle_reason_explains_tdd_philosophy(self, mock_exists, handler):
        """handle() reason should explain TDD philosophy."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert "PHILOSOPHY" in result.reason
        assert "test first" in result.reason.lower()

    @patch("pathlib.Path.exists")
    def test_handle_reason_provides_required_actions(self, mock_exists, handler):
        """handle() reason should provide required actions."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert "REQUIRED ACTION" in result.reason
        assert "Create the test file first" in result.reason

    @patch("pathlib.Path.exists")
    def test_handle_reason_mentions_red_green_refactor(self, mock_exists, handler):
        """handle() reason should mention red-green cycle."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert "red" in result.reason.lower()
        assert "green" in result.reason.lower()

    @patch("pathlib.Path.exists")
    def test_handle_reason_provides_test_file_path(self, mock_exists, handler):
        """handle() reason should provide exact test file path."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        # Should contain the full test path
        assert "/controller/tests/unit/pre_tool_use/test_my_handler.py" in result.reason

    @patch("pathlib.Path.exists")
    def test_handle_context_is_none(self, mock_exists, handler):
        """handle() context should be None."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert result.context == []

    @patch("pathlib.Path.exists")
    def test_handle_guidance_is_none(self, mock_exists, handler):
        """handle() guidance should be None."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # _get_test_file_path() Tests
    def test_get_test_file_path_converts_handler_to_test_filename(self, handler):
        """_get_test_file_path() should convert handler filename to test filename."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path)
        assert test_path.name == "test_my_handler.py"

    def test_get_test_file_path_finds_controller_directory(self, handler):
        """_get_test_file_path() should find controller directory in path."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path)
        assert "controller" in str(test_path)
        assert "tests" in str(test_path)

    def test_get_test_file_path_puts_test_in_tests_directory(self, handler):
        """_get_test_file_path() should put test file in tests/unit/ directory."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path)
        assert str(test_path).endswith("controller/tests/unit/pre_tool_use/test_my_handler.py")

    def test_get_test_file_path_handles_nested_handler_path(self, handler):
        """_get_test_file_path() should handle deeply nested handler paths."""
        handler_path = "/very/deep/path/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path)
        assert "controller/tests/unit/pre_tool_use/test_my_handler.py" in str(test_path)

    def test_get_test_file_path_handles_complex_handler_name(self, handler):
        """_get_test_file_path() should handle complex handler names."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_complex_handler_v2.py"
        test_path = handler._get_test_file_path(handler_path)
        assert test_path.name == "test_my_complex_handler_v2.py"

    def test_get_test_file_path_fallback_when_controller_not_in_path(self, handler):
        """_get_test_file_path() should use fallback when 'controller' not in path."""
        handler_path = "/workspace/project/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path)
        # Should use fallback logic (parent.parent.parent)
        assert test_path.name == "test_my_handler.py"

    def test_get_test_file_path_returns_path_object(self, handler):
        """_get_test_file_path() should return pathlib.Path object."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path)
        assert isinstance(test_path, Path)

    # Integration Tests
    @patch("pathlib.Path.exists")
    def test_workflow_blocks_handler_without_test(self, mock_exists, handler):
        """Complete workflow: Block handler creation when test missing."""
        mock_exists.return_value = False

        # Agent tries to create handler without test
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/new_handler.py"
            },
        }

        # Should match
        assert handler.matches(hook_input) is True

        # Should deny
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "test_new_handler.py" in result.reason

    @patch("pathlib.Path.exists")
    def test_workflow_allows_handler_with_test(self, mock_exists, handler):
        """Complete workflow: Allow handler creation when test exists."""
        mock_exists.return_value = True

        # Agent creates handler after test exists
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/new_handler.py"
            },
        }

        # Should match
        assert handler.matches(hook_input) is True

        # Should allow
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_workflow_ignores_init_files(self, handler):
        """Complete workflow: Ignore __init__.py files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/__init__.py"
            },
        }

        # Should not match __init__.py
        assert handler.matches(hook_input) is False

    @patch("pathlib.Path.exists")
    def test_multiple_handler_directories_all_enforced(self, mock_exists, handler):
        """All handler event directories should be enforced."""
        mock_exists.return_value = False

        handler_dirs = [
            "/workspace/controller/src/handlers/pre_tool_use/handler.py",
            "/workspace/controller/src/handlers/post_tool_use/handler.py",
            "/workspace/controller/src/handlers/user_prompt_submit/handler.py",
            "/workspace/controller/src/handlers/subagent_stop/handler.py",
        ]

        for handler_path in handler_dirs:
            hook_input = {"tool_name": "Write", "tool_input": {"file_path": handler_path}}
            # Should match all event directories
            assert handler.matches(hook_input) is True, f"Should match: {handler_path}"

            # Should deny if test missing
            result = handler.handle(hook_input)
            assert result.decision == "deny", f"Should deny: {handler_path}"

    def test_matches_returns_false_for_non_handler_non_src_path(self, handler):
        """Should not match paths that are neither /handlers/ nor /src/ (line 46 branch)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/docs/readme.py"},
        }
        # Not in /handlers/ or /src/ - should return False at line 46
        assert handler.matches(hook_input) is False

    def test_handle_returns_allow_for_non_write_edit_tool(self, handler):
        """Should allow when tool is not Write or Edit (line 52 branch)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
        }
        # get_file_path returns None for Bash - should return ALLOW at line 52
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # Regression test for hooks-daemon structure bug
    def test_get_test_file_path_handles_hooks_daemon_structure(self, handler):
        """Regression test: _get_test_file_path() should handle hooks-daemon structure.

        Bug: Handler doesn't find test files in hooks-daemon structure.
        Handler path: /workspace/src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py
        Expected test: /workspace/tests/unit/handlers/session_start/test_yolo_container_detection.py
        """
        handler_path = "/workspace/src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py"
        test_path = handler._get_test_file_path(handler_path)

        # Should construct correct test path for hooks-daemon structure
        expected = Path(
            "/workspace/tests/unit/handlers/session_start/test_yolo_container_detection.py"
        )
        assert test_path == expected, f"Expected {expected}, got {test_path}"

    @patch("pathlib.Path.exists")
    def test_handle_allows_hooks_daemon_handler_with_existing_test(self, mock_exists, handler):
        """Regression test: Should allow hooks-daemon handler when test exists.

        Bug: Handler claims test is missing even when it exists at correct location.
        This test MUST FAIL before fix (false negative - blocks valid handler creation).
        """
        # Mock filesystem - test file exists
        mock_exists.return_value = True
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py"
            },
        }

        result = handler.handle(hook_input)

        # Should ALLOW because test exists
        assert (
            result.decision == "allow"
        ), f"Should allow when test exists, but got: {result.reason}"

    def test_get_test_file_path_handles_utils_structure(self, handler):
        """Test: _get_test_file_path() should handle utils/ structure.

        Utils path: /workspace/src/claude_code_hooks_daemon/utils/formatting.py
        Expected test: /workspace/tests/unit/utils/test_formatting.py
        """
        handler_path = "/workspace/src/claude_code_hooks_daemon/utils/formatting.py"
        test_path = handler._get_test_file_path(handler_path)

        # Should construct correct test path for utils structure
        expected = Path("/workspace/tests/unit/utils/test_formatting.py")
        assert test_path == expected, f"Expected {expected}, got {test_path}"

    @patch("pathlib.Path.exists")
    def test_handle_allows_utils_file_with_existing_test(self, mock_exists, handler):
        """Test: Should allow utils file when test exists.

        This verifies that utils files follow the same TDD pattern as handlers.
        """
        mock_exists.return_value = True

        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/claude_code_hooks_daemon/utils/formatting.py"
            },
        }

        result = handler.handle(hook_input)

        # Should ALLOW because test exists
        assert result.decision == "allow"
