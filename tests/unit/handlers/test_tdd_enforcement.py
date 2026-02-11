"""Comprehensive tests for TddEnforcementHandler."""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import TddEnforcementHandler
from claude_code_hooks_daemon.strategies.tdd.go_strategy import GoTddStrategy
from claude_code_hooks_daemon.strategies.tdd.java_strategy import JavaTddStrategy
from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import JavaScriptTddStrategy
from claude_code_hooks_daemon.strategies.tdd.php_strategy import PhpTddStrategy
from claude_code_hooks_daemon.strategies.tdd.python_strategy import PythonTddStrategy
from claude_code_hooks_daemon.strategies.tdd.rust_strategy import RustTddStrategy


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
            "tool_input": {
                "file_path": "/different/path/src/pkg/handlers/pre_tool_use/my_handler.py"
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_handler_file_with_underscores_in_name(self, handler):
        """Should match handler file with underscores in name."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/pkg/handlers/pre_tool_use/my_complex_handler_v2.py"
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
        """Should match files in src/pkg/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/my_handler.py"},
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
        """Should NOT match files outside source directories."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/test-handlers/pre_tool_use/fake_handler.py"},
        }
        # Without /src/ or other production source directories, should NOT match
        assert handler.matches(hook_input) is False

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
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        assert test_path.name == "test_my_handler.py"

    def test_get_test_file_path_finds_controller_directory(self, handler):
        """_get_test_file_path() should find controller directory in path."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        assert "controller" in str(test_path)
        assert "tests" in str(test_path)

    def test_get_test_file_path_puts_test_in_tests_directory(self, handler):
        """_get_test_file_path() should put test file in tests/unit/ directory."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        assert str(test_path).endswith("controller/tests/unit/pre_tool_use/test_my_handler.py")

    def test_get_test_file_path_handles_nested_handler_path(self, handler):
        """_get_test_file_path() should handle deeply nested handler paths."""
        handler_path = "/very/deep/path/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        assert "controller/tests/unit/pre_tool_use/test_my_handler.py" in str(test_path)

    def test_get_test_file_path_handles_complex_handler_name(self, handler):
        """_get_test_file_path() should handle complex handler names."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_complex_handler_v2.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        assert test_path.name == "test_my_complex_handler_v2.py"

    def test_get_test_file_path_fallback_when_controller_not_in_path(self, handler):
        """_get_test_file_path() should use fallback when 'controller' not in path."""
        handler_path = "/workspace/project/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        # Should use fallback logic (parent.parent.parent)
        assert test_path.name == "test_my_handler.py"

    def test_get_test_file_path_returns_path_object(self, handler):
        """_get_test_file_path() should return pathlib.Path object."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
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
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())

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
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())

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

    def test_get_test_file_path_controller_based_path(self, handler):
        """_get_test_file_path should handle paths containing 'controller' dir."""
        handler_path = "/workspace/controller/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        assert test_path.name == "test_my_handler.py"
        assert "controller" in str(test_path)
        assert "tests" in str(test_path)

    def test_get_test_file_path_no_src_no_controller(self, handler):
        """_get_test_file_path uses fallback when neither 'src' nor 'controller' in path."""
        handler_path = "/workspace/lib/handlers/pre_tool_use/my_handler.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        assert test_path.name == "test_my_handler.py"
        # Falls back to parent.parent.parent / "tests" / test_filename
        assert "tests" in str(test_path)

    def test_get_test_file_path_src_with_only_package_and_file(self, handler):
        """_get_test_file_path handles src/{package}/file.py (len(after_src)==2)."""
        handler_path = "/workspace/src/mypackage/module.py"
        test_path = handler._get_test_file_path(handler_path, PythonTddStrategy())
        expected = Path("/workspace/tests/unit/test_module.py")
        assert test_path == expected

    def test_get_acceptance_tests_returns_non_empty(self, handler):
        """get_acceptance_tests returns a non-empty list."""
        tests = handler.get_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0

    # ================================================================
    # Language-Agnostic Tests (Multi-Language Support)
    # ================================================================

    # matches() - JavaScript/TypeScript files
    def test_matches_javascript_file_in_src(self, handler):
        """Should match .js files in src/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/components/Button.js"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_typescript_file_in_src(self, handler):
        """Should match .ts files in src/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/utils/helpers.ts"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_tsx_file_in_src(self, handler):
        """Should match .tsx files in src/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/components/App.tsx"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_jsx_file_in_src(self, handler):
        """Should match .jsx files in src/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/components/Card.jsx"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Go files
    def test_matches_go_file_in_src(self, handler):
        """Should match .go files in production directories."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server/handler.go"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_go_test_file_returns_false(self, handler):
        """Should NOT match Go test files (_test.go)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server/handler_test.go"},
        }
        assert handler.matches(hook_input) is False

    # matches() - PHP files
    def test_matches_php_file_in_src(self, handler):
        """Should match .php files in src/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/Controllers/UserController.php"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Rust files
    def test_matches_rust_file_in_src(self, handler):
        """Should match .rs files in src/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/handlers/mod.rs"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Java files
    def test_matches_java_file_in_src(self, handler):
        """Should match .java files in src/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/main/java/com/app/Service.java"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Unknown file extensions should be ALLOWED (not blocked)
    def test_matches_unknown_extension_returns_false(self, handler):
        """Should NOT match unknown file extensions (allow them through)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/config/settings.toml"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_markdown_file_returns_false(self, handler):
        """Should NOT match markdown files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/docs/README.md"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_yaml_file_returns_false(self, handler):
        """Should NOT match YAML files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/config/app.yaml"},
        }
        assert handler.matches(hook_input) is False

    # matches() - Skip directories
    def test_matches_node_modules_returns_false(self, handler):
        """Should NOT match files in node_modules/."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/node_modules/lodash/index.js"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_vendor_dir_returns_false(self, handler):
        """Should NOT match files in vendor/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/vendor/autoload.php"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_dist_dir_returns_false(self, handler):
        """Should NOT match files in dist/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/dist/bundle.js"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_venv_dir_returns_false(self, handler):
        """Should NOT match files in venv/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/venv/lib/python3.11/site.py"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_build_dir_returns_false(self, handler):
        """Should NOT match files in build/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/build/output.js"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_target_dir_returns_false(self, handler):
        """Should NOT match files in target/ directory (Rust/Java)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/target/debug/main.rs"},
        }
        assert handler.matches(hook_input) is False

    # matches() - Test directories for various languages
    def test_matches_js_test_file_returns_false(self, handler):
        """Should NOT match JS test files (*.test.js)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/utils/helpers.test.js"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_js_spec_file_returns_false(self, handler):
        """Should NOT match JS spec files (*.spec.ts)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/utils/helpers.spec.ts"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_file_in__tests__dir_returns_false(self, handler):
        """Should NOT match files in __tests__/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/__tests__/Button.test.tsx"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_java_test_file_returns_false(self, handler):
        """Should NOT match Java test files (in test/ directory)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/test/java/com/app/ServiceTest.java"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_php_test_file_returns_false(self, handler):
        """Should NOT match PHP test files (in tests/ directory)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/tests/UserControllerTest.php"},
        }
        assert handler.matches(hook_input) is False

    # _get_test_file_path() - Language-specific test file naming
    def test_get_test_file_path_javascript_naming(self, handler):
        """_get_test_file_path() should use JS naming convention: basename.test.js."""
        handler_path = "/workspace/src/mypackage/utils/helpers.js"
        test_path = handler._get_test_file_path(handler_path, JavaScriptTddStrategy())
        assert test_path.name == "helpers.test.js"

    def test_get_test_file_path_typescript_naming(self, handler):
        """_get_test_file_path() should use TS naming convention: basename.test.ts."""
        handler_path = "/workspace/src/mypackage/utils/helpers.ts"
        test_path = handler._get_test_file_path(handler_path, JavaScriptTddStrategy())
        assert test_path.name == "helpers.test.ts"

    def test_get_test_file_path_tsx_naming(self, handler):
        """_get_test_file_path() should use TSX naming convention: basename.test.tsx."""
        handler_path = "/workspace/src/mypackage/components/App.tsx"
        test_path = handler._get_test_file_path(handler_path, JavaScriptTddStrategy())
        assert test_path.name == "App.test.tsx"

    def test_get_test_file_path_go_naming(self, handler):
        """_get_test_file_path() should use Go naming convention: basename_test.go."""
        handler_path = "/workspace/src/mypackage/pkg/server.go"
        test_path = handler._get_test_file_path(handler_path, GoTddStrategy())
        assert test_path.name == "server_test.go"

    def test_get_test_file_path_php_naming(self, handler):
        """_get_test_file_path() should use PHP naming convention: basenameTest.php."""
        handler_path = "/workspace/src/mypackage/Controllers/UserController.php"
        test_path = handler._get_test_file_path(handler_path, PhpTddStrategy())
        assert test_path.name == "UserControllerTest.php"

    def test_get_test_file_path_rust_naming(self, handler):
        """_get_test_file_path() should use Rust naming convention: basename_test.rs."""
        handler_path = "/workspace/src/mypackage/handlers/parser.rs"
        test_path = handler._get_test_file_path(handler_path, RustTddStrategy())
        assert test_path.name == "parser_test.rs"

    def test_get_test_file_path_java_naming(self, handler):
        """_get_test_file_path() should use Java naming convention: basenameTest.java."""
        handler_path = "/workspace/src/mypackage/main/java/Service.java"
        test_path = handler._get_test_file_path(handler_path, JavaTddStrategy())
        assert test_path.name == "ServiceTest.java"

    # handle() - Language-aware error messages
    @patch("pathlib.Path.exists")
    def test_handle_js_file_shows_correct_test_convention(self, mock_exists, handler):
        """handle() should show JS test naming convention in error message."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/utils/helpers.js"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "helpers.test.js" in result.reason

    @patch("pathlib.Path.exists")
    def test_handle_go_file_shows_correct_test_convention(self, mock_exists, handler):
        """handle() should show Go test naming convention in error message."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/pkg/server.go"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "server_test.go" in result.reason

    @patch("pathlib.Path.exists")
    def test_handle_java_file_shows_correct_test_convention(self, mock_exists, handler):
        """handle() should show Java test naming convention in error message."""
        mock_exists.return_value = False
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/main/Service.java"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "ServiceTest.java" in result.reason

    # ================================================================
    # Language Filtering Tests (Config Option: languages)
    # ================================================================

    def test_no_languages_config_enforces_all(self, handler):
        """With no languages config (default), ALL languages should be enforced."""
        # Default handler has _languages = None
        assert handler._languages is None
        # Python file should match
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input) is True
        # Go file should also match
        hook_input_go = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server.go"},
        }
        assert handler.matches(hook_input_go) is True

    def test_empty_languages_list_enforces_all(self):
        """With empty languages list, ALL languages should be enforced."""
        handler = TddEnforcementHandler()
        handler._languages = []
        # Python file should match
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input) is True
        # Go file should also match
        hook_input_go = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server.go"},
        }
        assert handler.matches(hook_input_go) is True

    def test_languages_filter_restricts_to_specified(self):
        """With languages=['Python'], only Python files should be enforced."""
        handler = TddEnforcementHandler()
        handler._languages = ["Python"]
        # Python file should match
        hook_input_py = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input_py) is True
        # Go file should NOT match (filtered out)
        hook_input_go = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server.go"},
        }
        assert handler.matches(hook_input_go) is False

    def test_languages_filter_case_insensitive(self):
        """Languages filter should be case-insensitive."""
        handler = TddEnforcementHandler()
        handler._languages = ["python"]
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input) is True

    def test_languages_filter_multiple_languages(self):
        """With multiple languages, all specified should be enforced."""
        handler = TddEnforcementHandler()
        handler._languages = ["Python", "Go"]
        # Python should match
        hook_input_py = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input_py) is True
        # Go should match
        hook_input_go = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server.go"},
        }
        assert handler.matches(hook_input_go) is True
        # JS should NOT match
        hook_input_js = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/components/App.js"},
        }
        assert handler.matches(hook_input_js) is False

    def test_languages_filter_applied_only_once(self):
        """Language filter should be applied lazily and only once."""
        handler = TddEnforcementHandler()
        handler._languages = ["Python"]
        assert handler._languages_applied is False
        # First call applies filter
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        handler.matches(hook_input)
        assert handler._languages_applied is True
        # Changing _languages after first call has no effect (already applied)
        handler._languages = ["Go"]
        hook_input_py = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input_py) is True  # Still Python-filtered

    # ================================================================
    # Project-Level Languages Fallback Tests
    # ================================================================

    def test_project_languages_used_when_handler_languages_not_set(self):
        """_project_languages should be used when _languages is None."""
        handler = TddEnforcementHandler()
        handler._languages = None
        handler._project_languages = ["Python"]
        # Python should match (project languages = ["Python"])
        hook_input_py = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input_py) is True
        # Go should NOT match (filtered by project languages)
        hook_input_go = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server.go"},
        }
        assert handler.matches(hook_input_go) is False

    def test_handler_languages_override_project_languages(self):
        """_languages (handler-level) should override _project_languages."""
        handler = TddEnforcementHandler()
        handler._languages = ["Go"]
        handler._project_languages = ["Python", "Go", "Rust"]
        # Go should match (handler override)
        hook_input_go = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server.go"},
        }
        assert handler.matches(hook_input_go) is True
        # Python should NOT match (handler says only Go)
        hook_input_py = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input_py) is False

    def test_no_languages_and_no_project_languages_enforces_all(self):
        """With neither _languages nor _project_languages, ALL should be enforced."""
        handler = TddEnforcementHandler()
        handler._languages = None
        handler._project_languages = None
        # Python should match
        hook_input_py = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input_py) is True
        # Go should match
        hook_input_go = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server.go"},
        }
        assert handler.matches(hook_input_go) is True

    def test_empty_project_languages_enforces_all(self):
        """With empty _project_languages list, ALL should be enforced."""
        handler = TddEnforcementHandler()
        handler._languages = None
        handler._project_languages = []
        # Python should match
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/module.py"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Production files outside handlers/ and src/ with recognized language
    def test_matches_recognized_lang_outside_src_and_handlers(self, handler):
        """Should NOT match recognized language files outside src/ and handlers/."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/scripts/deploy.py"},
        }
        # scripts/ is not in src/ or handlers/, so should not match
        assert handler.matches(hook_input) is False
