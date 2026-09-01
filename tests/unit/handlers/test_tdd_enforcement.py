"""Comprehensive tests for TddEnforcementHandler."""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import LayoutConfig
from claude_code_hooks_daemon.core.workspace import DeclaredProject, ProjectRegistry
from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import (
    _DEFAULT_TEST_LOCATIONS,
    _SRC_DIR,
    _TEST_LOCATION_COLLOCATED,
    _TEST_LOCATION_SEPARATE,
    _TEST_LOCATION_TEST_SUBDIR,
    _TEST_SUBDIR_NAME,
    DeclaredTestDir,
    TddEnforcementHandler,
)
from claude_code_hooks_daemon.strategies.tdd.go_strategy import GoTddStrategy
from claude_code_hooks_daemon.strategies.tdd.java_strategy import JavaTddStrategy
from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import JavaScriptTddStrategy
from claude_code_hooks_daemon.strategies.tdd.php_strategy import PhpTddStrategy
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy
from claude_code_hooks_daemon.strategies.tdd.python_strategy import PythonTddStrategy
from claude_code_hooks_daemon.strategies.tdd.rust_strategy import RustTddStrategy


def _primary_separate_test_path(
    handler: TddEnforcementHandler, source_path: str, strategy: TddStrategy
) -> Path:
    """Compute the package-stripped (src->tests/unit) test path for a source file.

    Exercises the shared mapping helpers (_map_src_to_test_path / _map_fallback_test_path)
    that the live _get_test_file_paths() uses. Replaces direct coverage of the removed
    deprecated _get_test_file_path() singular method (Finding #65) without losing the
    path-mapping assertions.
    """
    test_filename = strategy.compute_test_filename(Path(source_path).name)
    path_parts = Path(source_path).parts
    if _SRC_DIR in path_parts:
        mapped = handler._map_src_to_test_path(path_parts, test_filename)
        if mapped is not None:
            return mapped
    return handler._map_fallback_test_path(source_path, path_parts, test_filename)


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

    def test_matches_honours_declared_source_dir_from_facade(self, handler):
        """A declared layout.source_dirs entry gates TDD for a file
        per-language inference would MISS (Plan 00288 Task 4.4): 'backend/'
        is not in Python's own (/src/,) _SOURCE_DIRECTORIES, so without the
        facade this file would never match."""
        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        handler._project_layout = ProjectLayout(
            source_dirs=("backend",),
            test_dirs=("tests",),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=("Completed",),
        )
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/backend/my_module.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_honours_declared_test_dir_from_facade(self, handler):
        """A file under a declared layout.test_dirs entry is never itself
        gated as a production source (Plan 00288 Task 4.4)."""
        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        handler._project_layout = ProjectLayout(
            source_dirs=(),
            test_dirs=("qa-suite",),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=("Completed",),
        )
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/qa-suite/my_module.py"},
        }
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

    def test_handle_unknown_extension_returns_allow(self, handler):
        """handle() should return ALLOW for unknown file extensions (no strategy found)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/config/settings.toml"},
        }
        result = handler.handle(hook_input)
        assert result.decision.value == "allow"

    # _get_test_file_path() Tests
    def test_get_test_file_path_converts_handler_to_test_filename(self, handler):
        """_get_test_file_path() should convert handler filename to test filename."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
        assert test_path.name == "test_my_handler.py"

    def test_get_test_file_path_finds_controller_directory(self, handler):
        """_get_test_file_path() should find controller directory in path."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
        assert "controller" in str(test_path)
        assert "tests" in str(test_path)

    def test_get_test_file_path_puts_test_in_tests_directory(self, handler):
        """_get_test_file_path() should put test file in tests/unit/ directory."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
        assert str(test_path).endswith("controller/tests/unit/pre_tool_use/test_my_handler.py")

    def test_get_test_file_path_handles_nested_handler_path(self, handler):
        """_get_test_file_path() should handle deeply nested handler paths."""
        handler_path = "/very/deep/path/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
        assert "controller/tests/unit/pre_tool_use/test_my_handler.py" in str(test_path)

    def test_get_test_file_path_handles_complex_handler_name(self, handler):
        """_get_test_file_path() should handle complex handler names."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_complex_handler_v2.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
        assert test_path.name == "test_my_complex_handler_v2.py"

    def test_get_test_file_path_fallback_when_controller_not_in_path(self, handler):
        """_get_test_file_path() should use fallback when 'controller' not in path."""
        handler_path = "/workspace/project/src/handlers/pre_tool_use/my_handler.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
        # Should use fallback logic (parent.parent.parent)
        assert test_path.name == "test_my_handler.py"

    def test_get_test_file_path_returns_path_object(self, handler):
        """_get_test_file_path() should return pathlib.Path object."""
        handler_path = "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
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
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())

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
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())

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
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
        assert test_path.name == "test_my_handler.py"
        assert "controller" in str(test_path)
        assert "tests" in str(test_path)

    def test_get_test_file_path_no_src_no_controller(self, handler):
        """_get_test_file_path uses fallback when neither 'src' nor 'controller' in path."""
        handler_path = "/workspace/lib/handlers/pre_tool_use/my_handler.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
        assert test_path.name == "test_my_handler.py"
        # Falls back to parent.parent.parent / "tests" / test_filename
        assert "tests" in str(test_path)

    def test_get_test_file_path_src_with_only_package_and_file(self, handler):
        """_get_test_file_path handles src/{package}/file.py (len(after_src)==2)."""
        handler_path = "/workspace/src/mypackage/module.py"
        test_path = _primary_separate_test_path(handler, handler_path, PythonTddStrategy())
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
        test_path = _primary_separate_test_path(handler, handler_path, JavaScriptTddStrategy())
        assert test_path.name == "helpers.test.js"

    def test_get_test_file_path_typescript_naming(self, handler):
        """_get_test_file_path() should use TS naming convention: basename.test.ts."""
        handler_path = "/workspace/src/mypackage/utils/helpers.ts"
        test_path = _primary_separate_test_path(handler, handler_path, JavaScriptTddStrategy())
        assert test_path.name == "helpers.test.ts"

    def test_get_test_file_path_tsx_naming(self, handler):
        """_get_test_file_path() should use TSX naming convention: basename.test.tsx."""
        handler_path = "/workspace/src/mypackage/components/App.tsx"
        test_path = _primary_separate_test_path(handler, handler_path, JavaScriptTddStrategy())
        assert test_path.name == "App.test.tsx"

    def test_get_test_file_path_go_naming(self, handler):
        """_get_test_file_path() should use Go naming convention: basename_test.go."""
        handler_path = "/workspace/src/mypackage/pkg/server.go"
        test_path = _primary_separate_test_path(handler, handler_path, GoTddStrategy())
        assert test_path.name == "server_test.go"

    def test_get_test_file_path_php_naming(self, handler):
        """_get_test_file_path() should use PHP naming convention: basenameTest.php."""
        handler_path = "/workspace/src/mypackage/Controllers/UserController.php"
        test_path = _primary_separate_test_path(handler, handler_path, PhpTddStrategy())
        assert test_path.name == "UserControllerTest.php"

    def test_get_test_file_path_rust_naming(self, handler):
        """_get_test_file_path() should use Rust naming convention: basename_test.rs."""
        handler_path = "/workspace/src/mypackage/handlers/parser.rs"
        test_path = _primary_separate_test_path(handler, handler_path, RustTddStrategy())
        assert test_path.name == "parser_test.rs"

    def test_get_test_file_path_java_naming(self, handler):
        """_get_test_file_path() should use Java naming convention: basenameTest.java."""
        handler_path = "/workspace/src/mypackage/main/java/Service.java"
        test_path = _primary_separate_test_path(handler, handler_path, JavaTddStrategy())
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

    # Regression tests for Plan 00055: Multi-path detection bug
    def test_bug_mirror_structure_allows_file_creation(self, handler):
        """Regression test: Should find test in tests/{package}/ mirror structure.

        Bug: Handler only checks tests/unit/ (strips package), missing valid tests
        in mirror structure like tests/mypackage/services/test_user.py.

        This test MUST FAIL before fix (false positive - blocks valid file creation).
        """
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/services/user.py"},
        }

        # Simulate: test file EXISTS in mirror location, NOT in stripped location
        # After fix, handler checks multiple paths and finds the mirror location
        def path_exists_side_effect(self):
            path_str = str(self)
            # Mirror location: EXISTS (PHP PSR-4, Java style)
            if path_str == "/workspace/tests/mypackage/services/test_user.py":
                return True
            # Current location (strips package): does NOT exist
            if path_str == "/workspace/tests/unit/services/test_user.py":
                return False
            # Fallback location: does NOT exist
            return False

        with patch.object(Path, "exists", path_exists_side_effect):
            result = handler.handle(hook_input)

        # EXPECTED: Should ALLOW (test exists in mirror structure)
        # ACTUAL (before fix): Will DENY (handler only checks stripped path, gets False)
        assert result.decision == "allow", (
            f"Should ALLOW when test exists in mirror structure. " f"Got decision={result.decision}"
        )

    def test_bug_current_structure_still_works(self, handler):
        """Ensure existing Python convention (strip package) still works after fix."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/services/user.py"},
        }

        # Simulate: test exists in current Python convention (tests/unit/services/)
        def path_exists_side_effect(self):
            path_str = str(self)
            # Current location (strips package): EXISTS
            if path_str == "/workspace/tests/unit/services/test_user.py":
                return True
            # Mirror location: does NOT exist
            if path_str == "/workspace/tests/mypackage/services/test_user.py":
                return False
            return False

        with patch.object(Path, "exists", path_exists_side_effect):
            result = handler.handle(hook_input)

        assert result.decision == "allow", (
            "Should ALLOW when test exists in current Python convention "
            "(tests/unit/services/test_user.py)"
        )

    def test_no_test_in_any_location_denies(self, handler):
        """Should deny if test doesn't exist in ANY candidate location."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/services/user.py"},
        }

        # Simulate: no test exists anywhere
        with patch.object(Path, "exists", return_value=False):
            result = handler.handle(hook_input)

        assert result.decision == "deny", "Should DENY when test missing in all locations"
        assert (
            "Searched locations:" in result.reason
        ), "Error message should show all searched locations"

    def test_php_psr4_mirror_structure(self, handler):
        """PHP PSR-4 should work with mirror structure (real-world scenario).

        PHP source: src/SupFeeds/Logging/DTO/File.php
        PHP test: tests/SupFeeds/Logging/DTO/FileTest.php (mirrors full structure)
        """
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/SupFeeds/Logging/DTO/File.php"},
        }

        # Simulate: test exists in mirror location
        def path_exists_side_effect(self):
            path_str = str(self)
            # Mirror location: EXISTS (PSR-4 style)
            if path_str == "/workspace/tests/SupFeeds/Logging/DTO/FileTest.php":
                return True
            return False

        with patch.object(Path, "exists", path_exists_side_effect):
            result = handler.handle(hook_input)

        assert (
            result.decision == "allow"
        ), "Should ALLOW PHP file when test exists in PSR-4 mirror structure"

    # ================================================================
    # Collocated Test Location Support (Plan 00076)
    # ================================================================

    # --- Phase 1: Constants and Config ---

    def test_constants_test_location_separate(self):
        """Module constant _TEST_LOCATION_SEPARATE should be 'separate'."""
        assert _TEST_LOCATION_SEPARATE == "separate"

    def test_constants_test_location_collocated(self):
        """Module constant _TEST_LOCATION_COLLOCATED should be 'collocated'."""
        assert _TEST_LOCATION_COLLOCATED == "collocated"

    def test_constants_test_location_test_subdir(self):
        """Module constant _TEST_LOCATION_TEST_SUBDIR should be 'test_subdir'."""
        assert _TEST_LOCATION_TEST_SUBDIR == "test_subdir"

    def test_constants_test_subdir_name(self):
        """Module constant _TEST_SUBDIR_NAME should be '__tests__'."""
        assert _TEST_SUBDIR_NAME == "__tests__"

    def test_constants_default_test_locations(self):
        """_DEFAULT_TEST_LOCATIONS should contain all three location types."""
        assert _DEFAULT_TEST_LOCATIONS == frozenset({"separate", "collocated", "test_subdir"})

    def test_init_test_locations_defaults_to_none(self):
        """Handler _test_locations should default to None."""
        handler = TddEnforcementHandler()
        assert handler._test_locations is None

    def test_effective_test_locations_returns_all_when_none(self):
        """_effective_test_locations returns all 3 when _test_locations is None."""
        handler = TddEnforcementHandler()
        handler._test_locations = None
        assert handler._effective_test_locations == _DEFAULT_TEST_LOCATIONS

    def test_effective_test_locations_returns_all_when_empty(self):
        """_effective_test_locations returns all 3 when _test_locations is empty."""
        handler = TddEnforcementHandler()
        handler._test_locations = []
        assert handler._effective_test_locations == _DEFAULT_TEST_LOCATIONS

    def test_effective_test_locations_respects_config(self):
        """_effective_test_locations returns frozenset of configured values."""
        handler = TddEnforcementHandler()
        handler._test_locations = ["collocated", "test_subdir"]
        assert handler._effective_test_locations == frozenset({"collocated", "test_subdir"})

    def test_effective_test_locations_single_value(self):
        """_effective_test_locations works with single config value."""
        handler = TddEnforcementHandler()
        handler._test_locations = ["separate"]
        assert handler._effective_test_locations == frozenset({"separate"})

    # --- Phase 2: Collocated Path Method ---

    def test_map_collocated_test_path_typescript(self):
        """Collocated: src/pkg/utils/helpers.ts -> src/pkg/utils/helpers.test.ts."""
        result = TddEnforcementHandler._map_collocated_test_path(
            "/workspace/src/pkg/utils/helpers.ts", "helpers.test.ts"
        )
        assert result == Path("/workspace/src/pkg/utils/helpers.test.ts")

    def test_map_collocated_test_path_python(self):
        """Collocated: src/mypackage/services/user.py -> src/mypackage/services/test_user.py."""
        result = TddEnforcementHandler._map_collocated_test_path(
            "/workspace/src/mypackage/services/user.py", "test_user.py"
        )
        assert result == Path("/workspace/src/mypackage/services/test_user.py")

    def test_map_collocated_test_path_go(self):
        """Collocated: src/pkg/server/handler.go -> src/pkg/server/handler_test.go."""
        result = TddEnforcementHandler._map_collocated_test_path(
            "/workspace/src/pkg/server/handler.go", "handler_test.go"
        )
        assert result == Path("/workspace/src/pkg/server/handler_test.go")

    def test_map_collocated_test_path_deeply_nested(self):
        """Collocated: works for deeply nested paths."""
        result = TddEnforcementHandler._map_collocated_test_path(
            "/workspace/src/a/b/c/d/e/file.ts", "file.test.ts"
        )
        assert result == Path("/workspace/src/a/b/c/d/e/file.test.ts")

    # --- Phase 3: Test Subdir Path Method ---

    def test_map_test_subdir_path_typescript(self):
        """Test subdir: src/pkg/utils/helpers.ts -> src/pkg/utils/__tests__/helpers.test.ts."""
        result = TddEnforcementHandler._map_test_subdir_path(
            "/workspace/src/pkg/utils/helpers.ts", "helpers.test.ts"
        )
        assert result == Path("/workspace/src/pkg/utils/__tests__/helpers.test.ts")

    def test_map_test_subdir_path_python(self):
        """Test subdir: src/mypackage/services/user.py -> src/mypackage/services/__tests__/test_user.py."""
        result = TddEnforcementHandler._map_test_subdir_path(
            "/workspace/src/mypackage/services/user.py", "test_user.py"
        )
        assert result == Path("/workspace/src/mypackage/services/__tests__/test_user.py")

    def test_map_test_subdir_path_go(self):
        """Test subdir: src/pkg/server/handler.go -> src/pkg/server/__tests__/handler_test.go."""
        result = TddEnforcementHandler._map_test_subdir_path(
            "/workspace/src/pkg/server/handler.go", "handler_test.go"
        )
        assert result == Path("/workspace/src/pkg/server/__tests__/handler_test.go")

    def test_map_test_subdir_path_deeply_nested(self):
        """Test subdir: works for deeply nested paths."""
        result = TddEnforcementHandler._map_test_subdir_path(
            "/workspace/src/a/b/c/d/e/file.ts", "file.test.ts"
        )
        assert result == Path("/workspace/src/a/b/c/d/e/__tests__/file.test.ts")

    # --- Phase 4: Integration with _get_test_file_paths ---

    def test_get_test_file_paths_includes_collocated_candidate(self, handler):
        """_get_test_file_paths() should include collocated candidate in results."""
        from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import (
            JavaScriptTddStrategy,
        )

        paths = handler._get_test_file_paths(
            "/workspace/src/mypackage/utils/helpers.ts", JavaScriptTddStrategy()
        )
        collocated = Path("/workspace/src/mypackage/utils/helpers.test.ts")
        assert collocated in paths, f"Collocated path {collocated} not in {paths}"

    def test_get_test_file_paths_includes_test_subdir_candidate(self, handler):
        """_get_test_file_paths() should include __tests__/ candidate in results."""
        from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import (
            JavaScriptTddStrategy,
        )

        paths = handler._get_test_file_paths(
            "/workspace/src/mypackage/utils/helpers.ts", JavaScriptTddStrategy()
        )
        test_subdir = Path("/workspace/src/mypackage/utils/__tests__/helpers.test.ts")
        assert test_subdir in paths, f"Test subdir path {test_subdir} not in {paths}"

    def test_get_test_file_paths_config_separate_only(self):
        """Config ['separate'] should exclude collocated and test_subdir candidates."""
        from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import (
            JavaScriptTddStrategy,
        )

        handler = TddEnforcementHandler()
        handler._test_locations = ["separate"]
        paths = handler._get_test_file_paths(
            "/workspace/src/mypackage/utils/helpers.ts", JavaScriptTddStrategy()
        )
        collocated = Path("/workspace/src/mypackage/utils/helpers.test.ts")
        test_subdir = Path("/workspace/src/mypackage/utils/__tests__/helpers.test.ts")
        assert collocated not in paths, "Collocated should be excluded with ['separate']"
        assert test_subdir not in paths, "Test subdir should be excluded with ['separate']"

    def test_get_test_file_paths_config_collocated_only(self):
        """Config ['collocated'] should exclude separate and test_subdir candidates."""
        from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import (
            JavaScriptTddStrategy,
        )

        handler = TddEnforcementHandler()
        handler._test_locations = ["collocated"]
        paths = handler._get_test_file_paths(
            "/workspace/src/mypackage/utils/helpers.ts", JavaScriptTddStrategy()
        )
        collocated = Path("/workspace/src/mypackage/utils/helpers.test.ts")
        assert collocated in paths, "Collocated should be included"
        # Separate-style paths (mirror + unit) should NOT be present
        mirror = Path("/workspace/tests/mypackage/utils/helpers.test.ts")
        unit = Path("/workspace/tests/unit/utils/helpers.test.ts")
        assert mirror not in paths, "Mirror path should be excluded with ['collocated']"
        assert unit not in paths, "Unit path should be excluded with ['collocated']"

    def test_get_test_file_paths_config_collocated_and_test_subdir(self):
        """Config ['collocated', 'test_subdir'] should include both, exclude separate."""
        from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import (
            JavaScriptTddStrategy,
        )

        handler = TddEnforcementHandler()
        handler._test_locations = ["collocated", "test_subdir"]
        paths = handler._get_test_file_paths(
            "/workspace/src/mypackage/utils/helpers.ts", JavaScriptTddStrategy()
        )
        collocated = Path("/workspace/src/mypackage/utils/helpers.test.ts")
        test_subdir = Path("/workspace/src/mypackage/utils/__tests__/helpers.test.ts")
        assert collocated in paths, "Collocated should be included"
        assert test_subdir in paths, "Test subdir should be included"
        # No separate-style paths
        mirror = Path("/workspace/tests/mypackage/utils/helpers.test.ts")
        assert mirror not in paths, "Mirror should be excluded"

    def test_handle_allows_when_collocated_test_exists_go(self):
        """handle() should ALLOW when collocated Go test exists (e.g., handler_test.go)."""
        handler = TddEnforcementHandler()
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/pkg/server/handler.go"},
        }

        def path_exists_side_effect(self):
            path_str = str(self)
            # Collocated test exists (Go convention)
            if path_str == "/workspace/src/pkg/server/handler_test.go":
                return True
            return False

        with patch.object(Path, "exists", path_exists_side_effect):
            result = handler.handle(hook_input)

        assert (
            result.decision == "allow"
        ), "Should ALLOW Go file when collocated test (handler_test.go) exists"

    def test_handle_allows_when_collocated_test_exists_js(self):
        """handle() should ALLOW when collocated JS test exists (e.g., helpers.test.ts)."""
        handler = TddEnforcementHandler()
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/utils/helpers.ts"},
        }

        def path_exists_side_effect(self):
            path_str = str(self)
            if path_str == "/workspace/src/mypackage/utils/helpers.test.ts":
                return True
            return False

        with patch.object(Path, "exists", path_exists_side_effect):
            result = handler.handle(hook_input)

        assert (
            result.decision == "allow"
        ), "Should ALLOW TS file when collocated test (helpers.test.ts) exists"

    def test_handle_allows_when_tests_subdir_test_exists(self):
        """handle() should ALLOW when __tests__/ subdirectory test exists."""
        handler = TddEnforcementHandler()
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/utils/helpers.ts"},
        }

        def path_exists_side_effect(self):
            path_str = str(self)
            if path_str == "/workspace/src/mypackage/utils/__tests__/helpers.test.ts":
                return True
            return False

        with patch.object(Path, "exists", path_exists_side_effect):
            result = handler.handle(hook_input)

        assert result.decision == "allow", "Should ALLOW TS file when __tests__/ test exists"

    def test_regression_existing_mirror_tests_still_found(self, handler):
        """Regression: existing mirror/unit test detection must still work."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/mypackage/services/user.py"},
        }

        def path_exists_side_effect(self):
            path_str = str(self)
            if path_str == "/workspace/tests/mypackage/services/test_user.py":
                return True
            return False

        with patch.object(Path, "exists", path_exists_side_effect):
            result = handler.handle(hook_input)

        assert result.decision == "allow", "Regression: mirror-structure tests must still be found"


class TestExcludePathsEscape:
    """A project must be able to exempt a directory from TDD enforcement.

    Plan 00150 wired `exclude_paths` into the content-scanning blockers and
    recorded in its Non-Goals: "Not wiring lint_on_edit / tdd_enforcement this
    plan (follow-up if wanted)." This is that follow-up. Until it landed,
    `tdd_enforcement` was the only blocking path-based handler with NO
    configuration that could exempt a path — which is what a field report from a
    client monorepo ran into: a custom PHPStan rule under `qaConfig/` is
    classified production source, and its real test dir is not a location the
    resolver searches, so the file could not be written at all.
    """

    @staticmethod
    def _write(file_path: str) -> dict:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": "<?php\n\nclass Foo {}\n"},
        }

    def test_matches_an_unexcluded_source_file(self) -> None:
        """Control: without exclusions the handler still fires (the premise)."""
        handler = TddEnforcementHandler()
        assert handler.matches(self._write("/proj/apps/app/qaConfig/PHPStan/Rules/Foo.php"))

    def test_a_handler_exclude_pattern_stops_it_firing(self) -> None:
        handler = TddEnforcementHandler()
        handler._exclude_paths = ["**/qaConfig/**"]
        assert not handler.matches(self._write("/proj/apps/app/qaConfig/PHPStan/Rules/Foo.php"))

    def test_a_project_wide_exclude_pattern_stops_it_firing(self) -> None:
        """`daemon.exclude_paths` must apply even with no per-handler option."""
        handler = TddEnforcementHandler()
        handler._project_exclude_paths = ["**/qaConfig/**"]
        assert not handler.matches(self._write("/proj/apps/app/qaConfig/PHPStan/Rules/Foo.php"))

    def test_an_exclusion_does_not_exempt_genuine_source(self) -> None:
        """Excluding the QA-tooling dir must not disable enforcement elsewhere."""
        handler = TddEnforcementHandler()
        handler._exclude_paths = ["**/qaConfig/**"]
        assert handler.matches(self._write("/proj/apps/app/src/Entity/Company.php"))


class TestDeclaredTestDirFailFast:
    """`DeclaredTestDir` is the TRUSTED construction path, so it raises.

    The asymmetry is deliberate and mirrors `command_hints`: the parser at the
    config boundary degrades gracefully (one bad YAML line must not disable the
    handler), while the dataclass it constructs refuses to hold a meaningless
    value. The parser depends on that refusal instead of re-checking.
    """

    def test_an_empty_source_glob_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="source_glob"):
            DeclaredTestDir(source_glob="", test_dir="tests")

    def test_an_empty_test_dir_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="test_dir"):
            DeclaredTestDir(source_glob="**/x/**", test_dir="")


class TestDeclaredTestPathMap:
    """A project must be able to DECLARE its non-`src/` test root.

    This is the outcome the field report calls "best long-term" and it is
    strictly better than the exclusion escape of `TestExcludePathsEscape`:
    excluding turns enforcement OFF for the path, while declaring keeps the gate
    ON and merely tells it where to look. The reporter's own repo TDDs 40+ custom
    PHPStan rules with a worked `RuleTestCase` example, so giving that up would
    be a real loss.

    The layout under test is the reporter's, exactly: rules in
    `apps/app/qaConfig/PHPStan/Rules/` (no `src/` segment anywhere, so both
    mirror resolvers bail) with tests in `apps/app/qaConfig/Tests/` (capital T,
    the only directory their `phpunit.xml` scans, so a test in either
    hook-accepted alternative would never be executed).
    """

    _RULE_REL = ("apps", "app", "qaConfig", "PHPStan", "Rules", "SampleColumnPolicy.php")
    _TEST_REL = ("apps", "app", "qaConfig", "Tests", "SampleColumnPolicyTest.php")
    _SOURCE_GLOB = "**/qaConfig/PHPStan/Rules/**"
    _TEST_DIR = "apps/app/qaConfig/Tests"

    @staticmethod
    def _write(file_path: Path) -> dict:
        return {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(file_path),
                "content": "<?php\n\nclass SampleColumnPolicy {}\n",
            },
        }

    @staticmethod
    def _anchor_project_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
        """Make `resolve_project_root()` report `root`.

        A relative `test_dir` is project-root-relative, so these tests cannot use
        the real uninitialised-ProjectContext state — they would be asserting the
        unanchorable branch by accident. Same monkeypatch shape as
        `tests/unit/utils/test_path_exclusion.py`.
        """
        import claude_code_hooks_daemon.core.project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: root), raising=False
        )

    def _rule(self, root: Path) -> Path:
        return root.joinpath(*self._RULE_REL)

    def _place_real_test(self, root: Path) -> Path:
        """Create the correctly-placed test file the reporter already had."""
        test_path = root.joinpath(*self._TEST_REL)
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text("<?php\n\nclass SampleColumnPolicyTest {}\n")
        return test_path

    def _mapped(self) -> list[dict[str, str]]:
        return [{"source_glob": self._SOURCE_GLOB, "test_dir": self._TEST_DIR}]

    def test_unconfigured_the_correctly_placed_test_is_not_found(self, tmp_path: Path) -> None:
        """RED baseline: the built-in resolvers cannot reach `qaConfig/Tests/`.

        Pinned as a regression test rather than deleted once green, because the
        whole justification for a config surface is that no amount of inference
        finds this directory: both mirror resolvers are gated on a `src/` path
        segment, and the fallback yields lowercase `tests/`.
        """
        self._place_real_test(tmp_path)
        handler = TddEnforcementHandler()
        rule = self._rule(tmp_path)

        assert handler.matches(self._write(rule))
        result = handler.handle(self._write(rule))
        assert result.decision == "deny"
        assert str(Path(*self._TEST_REL).parent) not in (result.reason or "")

    def test_a_declared_test_dir_satisfies_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GREEN: enforcement stays ON and now finds the real test."""
        self._anchor_project_root(monkeypatch, tmp_path)
        self._place_real_test(tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = self._mapped()
        rule = self._rule(tmp_path)

        assert handler.matches(
            self._write(rule)
        ), "the gate must still fire — this is not an escape"
        assert handler.handle(self._write(rule)).decision == "allow"

    def test_a_missing_declared_test_still_denies_and_names_the_right_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The declaration must not weaken the gate, only redirect it.

        With no test on disk the write is still denied — and the deny message
        must name the DECLARED location, because that string is the instruction
        the author follows. Suggesting the lowercase `tests/` fallback here would
        send them to a directory their phpunit config does not scan.
        """
        self._anchor_project_root(monkeypatch, tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = self._mapped()
        rule = self._rule(tmp_path)

        result = handler.handle(self._write(rule))
        assert result.decision == "deny"
        assert str(tmp_path.joinpath(*self._TEST_REL)) in (result.reason or "")

    def test_the_declared_candidate_is_searched_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Most-specific-first: a declaration outranks every inferred candidate."""
        self._anchor_project_root(monkeypatch, tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = self._mapped()
        rule = self._rule(tmp_path)
        strategy = handler._registry.get_strategy(str(rule))
        assert strategy is not None

        candidates = handler._get_test_file_paths(str(rule), strategy)
        assert candidates[0] == tmp_path.joinpath(*self._TEST_REL)

    def test_a_non_matching_source_glob_contributes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mapping is scoped by its glob, exactly like `exclude_paths`."""
        self._anchor_project_root(monkeypatch, tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = self._mapped()
        other = tmp_path / "apps" / "app" / "src" / "Entity" / "Company.php"
        strategy = handler._registry.get_strategy(str(other))
        assert strategy is not None

        candidates = handler._get_test_file_paths(str(other), strategy)
        assert tmp_path.joinpath(*self._TEST_REL).parent not in [path.parent for path in candidates]

    def test_a_declaration_is_not_gated_by_test_locations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`test_locations` selects among INFERENCE styles; this is a FACT.

        Gating the map behind the style selector would mean a project that sets
        `test_locations: ["collocated"]` silently loses its own declared test
        root — the opposite of what declaring something means.
        """
        self._anchor_project_root(monkeypatch, tmp_path)
        self._place_real_test(tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = self._mapped()
        handler._test_locations = [_TEST_LOCATION_COLLOCATED]
        rule = self._rule(tmp_path)

        assert handler.handle(self._write(rule)).decision == "allow"

    def test_an_absolute_test_dir_is_rejected_at_the_config_boundary(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Plan 00296 zero-absolute-paths ruling: an absolute `test_dir` is skipped, not used.

        Rewritten from `test_an_absolute_test_dir_needs_no_project_root`, which
        pinned the OLD contract ("absolute is usable where the root is
        unresolvable"). The owner ruling supersedes that: every configured path
        must be repository-root-relative, because a repository is mounted at
        different places on different machines and an absolute path in
        committed config is correct on exactly one of them. The mapping now
        degrades gracefully (skip + warn, matching every other malformed
        `test_path_map` entry) rather than being honoured.
        """
        self._place_real_test(tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = [
            {
                "source_glob": self._SOURCE_GLOB,
                "test_dir": str(tmp_path.joinpath(*self._TEST_REL).parent),
            }
        ]
        with caplog.at_level("WARNING"):
            result = handler.handle(self._write(self._rule(tmp_path)))

        assert result.decision == "deny"
        assert any("absolute" in record.message for record in caplog.records)

    def test_a_relative_test_dir_without_a_project_root_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unanchorable: degrade to the built-in candidates, never crash."""
        import claude_code_hooks_daemon.core.project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", False, raising=False)
        self._place_real_test(tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = self._mapped()

        assert handler.handle(self._write(self._rule(tmp_path))).decision == "deny"

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param("not-a-list", id="not-a-list"),
            pytest.param([["source_glob", "x"]], id="entry-not-a-mapping"),
            pytest.param([{"source_glob": "**/qaConfig/**"}], id="missing-test-dir"),
            pytest.param([{"test_dir": "x/Tests"}], id="missing-source-glob"),
            pytest.param([{"source_glob": "", "test_dir": "x/Tests"}], id="empty-source-glob"),
            pytest.param([{"source_glob": "**/qaConfig/**", "test_dir": ""}], id="empty-test-dir"),
        ],
    )
    def test_malformed_config_degrades_instead_of_breaking_the_handler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: object
    ) -> None:
        """One bad YAML line must not take the handler down.

        Fail-open at the config boundary, per the `command_hints` convention. The
        author is not left guessing: the deny message lists every location that
        WAS searched, so a mapping that did not take is visible exactly where
        they are already looking.
        """
        self._anchor_project_root(monkeypatch, tmp_path)
        self._place_real_test(tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = raw

        result = handler.handle(self._write(self._rule(tmp_path)))
        assert result.decision == "deny"

    def test_several_declarations_all_contribute_in_config_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A monorepo declares one entry per app; every match is searched."""
        self._anchor_project_root(monkeypatch, tmp_path)
        handler = TddEnforcementHandler()
        handler._test_path_map = [
            {"source_glob": self._SOURCE_GLOB, "test_dir": "apps/admin/qaConfig/Tests"},
            {"source_glob": self._SOURCE_GLOB, "test_dir": self._TEST_DIR},
        ]
        rule = self._rule(tmp_path)
        strategy = handler._registry.get_strategy(str(rule))
        assert strategy is not None

        candidates = handler._get_test_file_paths(str(rule), strategy)
        assert candidates[0] == tmp_path / "apps/admin/qaConfig/Tests" / candidates[0].name
        assert candidates[1] == tmp_path.joinpath(*self._TEST_REL)


class TestDeclaredTestPathMapWorkspaceAnchoring:
    """A relative `test_dir` anchors against the source file's DECLARED project.

    Plan 00296 Task 2.4: `test_path_map` is orthogonal to *which* project (see
    `CLAUDE/Code/WorkspaceResolution.md`), so resolution only changes what a
    relative `test_dir` is anchored against -- the workspace-anchored candidate
    is added AHEAD of the repo-root candidate. Projects are declared, never
    inferred: an undeclared subproject that merely LOOKS like a workspace must
    still anchor at the repository root.
    """

    _SOURCE_GLOB = "**/Rules/**"
    _TEST_DIR = "qaConfig/Tests"

    @staticmethod
    def _anchor_project_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
        import claude_code_hooks_daemon.core.project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: root), raising=False
        )

    @staticmethod
    def _write(file_path: Path) -> dict:
        return {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(file_path),
                "content": "<?php\n\nclass SampleColumnPolicy {}\n",
            },
        }

    def test_a_declared_project_anchors_the_relative_test_dir_at_its_own_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The workspace-anchored candidate is searched, and searched FIRST."""
        self._anchor_project_root(monkeypatch, tmp_path)
        rule = tmp_path / "web" / "qaConfig" / "PHPStan" / "Rules" / "SampleColumnPolicy.php"

        handler = TddEnforcementHandler()
        handler._test_path_map = [{"source_glob": self._SOURCE_GLOB, "test_dir": self._TEST_DIR}]
        # Simulate an injected registry with a declared "web" project without
        # depending on Config wiring -- ProjectRegistry.for_path only needs the
        # DeclaredProject dataclass, constructed the same way from_config does.
        handler._project_registry = ProjectRegistry(
            project_root=tmp_path,
            projects=(DeclaredProject(name="web", root=tmp_path / "web"),),
        )

        strategy = handler._registry.get_strategy(str(rule))
        assert strategy is not None
        candidates = handler._get_test_file_paths(str(rule), strategy)

        assert candidates[0] == tmp_path / "web" / self._TEST_DIR / candidates[0].name

        test_path = candidates[0]
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text("<?php\n\nclass SampleColumnPolicyTest {}\n")
        assert handler.handle(self._write(rule)).decision == "allow"

    def test_an_undeclared_subproject_still_anchors_at_the_repository_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-inference pin: nothing declared means one project, the repo root.

        `web/` here has nothing marking it a project -- with no `projects:`
        entry the resolver must NOT guess a boundary at `web/`, so the only
        candidate is the repo-root-anchored path, exactly as before this task.
        """
        self._anchor_project_root(monkeypatch, tmp_path)
        rule = tmp_path / "web" / "qaConfig" / "PHPStan" / "Rules" / "SampleColumnPolicy.php"

        handler = TddEnforcementHandler()
        handler._test_path_map = [{"source_glob": self._SOURCE_GLOB, "test_dir": self._TEST_DIR}]
        # No registry injected: resolve_workspace() falls back to single-project,
        # which resolves every file to the repository root (Plan 00296).

        strategy = handler._registry.get_strategy(str(rule))
        assert strategy is not None
        candidates = handler._get_test_file_paths(str(rule), strategy)

        assert candidates[0] == tmp_path / self._TEST_DIR / candidates[0].name
        assert tmp_path / "web" / self._TEST_DIR not in [c.parent for c in candidates]

    def test_absolute_test_dir_is_skipped_with_a_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Config-boundary rejection: an absolute `test_dir` contributes no candidate."""
        self._anchor_project_root(monkeypatch, tmp_path)
        rule = tmp_path / "web" / "qaConfig" / "PHPStan" / "Rules" / "SampleColumnPolicy.php"

        handler = TddEnforcementHandler()
        handler._test_path_map = [
            {"source_glob": self._SOURCE_GLOB, "test_dir": "/etc/absolute/tests"}
        ]

        strategy = handler._registry.get_strategy(str(rule))
        assert strategy is not None
        with caplog.at_level("WARNING"):
            candidates = handler._get_test_file_paths(str(rule), strategy)

        assert Path("/etc/absolute/tests") not in [c.parent for c in candidates]
        assert any("absolute" in record.message for record in caplog.records)


class TestTddEnforcementGetRules:
    """get_rules() (Plan 00116): one rule, language dimension lives in verbose."""

    def test_get_rules_returns_one_rule(self) -> None:
        handler = TddEnforcementHandler()
        rules = handler.get_rules()
        assert len(rules) == 1

    def test_get_rules_rule_id_is_constant(self) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        handler = TddEnforcementHandler()
        rule = handler.get_rules()[0]
        assert rule.rule_id == RuleID.TDD_TEST_FIRST

    def test_get_rules_verbose_is_non_empty(self) -> None:
        handler = TddEnforcementHandler()
        rule = handler.get_rules()[0]
        assert rule.verbose


class TestTddEnforcementDisclosureLadder:
    """Verbose-first/terse-after per (transcript_path, rule_id) (Plan 00116)."""

    @pytest.fixture(autouse=True)
    def _reset_disclosure_tracker(self):
        from claude_code_hooks_daemon.core import reset_data_layer

        reset_data_layer()
        yield
        reset_data_layer()

    def _hook_input(self, transcript_path: str | None) -> dict:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/controller/src/handlers/pre_tool_use/my_handler.py"
            },
        }
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    @patch("pathlib.Path.exists")
    def test_deny_reason_starts_with_rule_id_prefix(self, mock_exists) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        mock_exists.return_value = False
        handler = TddEnforcementHandler()
        result = handler.handle(self._hook_input("/tmp/transcript-a.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.TDD_TEST_FIRST}]")

    @patch("pathlib.Path.exists")
    def test_first_fire_is_verbose(self, mock_exists) -> None:
        mock_exists.return_value = False
        handler = TddEnforcementHandler()
        result = handler.handle(self._hook_input("/tmp/transcript-b.jsonl"))
        assert "PHILOSOPHY" in result.reason

    @patch("pathlib.Path.exists")
    def test_second_fire_same_agent_is_terse(self, mock_exists) -> None:
        mock_exists.return_value = False
        handler = TddEnforcementHandler()
        transcript = "/tmp/transcript-c.jsonl"
        handler.handle(self._hook_input(transcript))
        second = handler.handle(self._hook_input(transcript))
        assert "PHILOSOPHY" not in second.reason
        # Dynamic diagnostic detail always stays present, even when terse.
        assert "Searched locations:" in second.reason

    @patch("pathlib.Path.exists")
    def test_different_agent_is_independently_verbose(self, mock_exists) -> None:
        mock_exists.return_value = False
        handler = TddEnforcementHandler()
        handler.handle(self._hook_input("/tmp/transcript-d.jsonl"))
        other = handler.handle(self._hook_input("/tmp/transcript-e.jsonl"))
        assert "PHILOSOPHY" in other.reason

    @patch("pathlib.Path.exists")
    def test_missing_transcript_path_always_verbose(self, mock_exists) -> None:
        mock_exists.return_value = False
        handler = TddEnforcementHandler()
        first = handler.handle(self._hook_input(None))
        second = handler.handle(self._hook_input(None))
        assert "PHILOSOPHY" in first.reason
        assert "PHILOSOPHY" in second.reason


class TestPerProjectLayoutRouting:
    """Plan 00300: matches() routes through the file's OWNING project's
    layout, via `resolve_layout` — never blindly the root `_project_layout`.

    A declared project without its own `layout:` uses built-in defaults for
    ITS root, not the root project's declared lists (no leaking).
    """

    @staticmethod
    def _write(file_path: Path) -> dict:
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": str(file_path)},
        }

    def test_declared_projects_own_layout_source_dirs_gates_tdd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'backend' is not in Python's own inferred source dirs -- only the
        sub-project's OWN declared `layout.source_dirs` makes it match."""
        import claude_code_hooks_daemon.core.project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: tmp_path), raising=False
        )

        handler = TddEnforcementHandler()
        handler._project_registry = ProjectRegistry(
            project_root=tmp_path,
            projects=(
                DeclaredProject(
                    name="api",
                    root=tmp_path / "apps" / "api",
                    layout=LayoutConfig(source_dirs=["backend"]),
                ),
            ),
        )

        rule = tmp_path / "apps" / "api" / "backend" / "my_module.py"
        assert handler.matches(self._write(rule)) is True

    def test_declared_project_without_own_layout_does_not_inherit_the_roots(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ROOT's declared `layout.source_dirs` must not leak into a
        sub-project that declares no `layout:` of its own."""
        import claude_code_hooks_daemon.core.project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: tmp_path), raising=False
        )

        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        handler = TddEnforcementHandler()
        handler._project_layout = ProjectLayout(
            source_dirs=("root-only-src",),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=("Completed",),
        )
        handler._project_registry = ProjectRegistry(
            project_root=tmp_path,
            projects=(DeclaredProject(name="api", root=tmp_path / "apps" / "api"),),
            root_layout=handler._project_layout,
        )

        rule = tmp_path / "apps" / "api" / "root-only-src" / "my_module.py"
        assert handler.matches(self._write(rule)) is False

    def test_path_outside_every_declared_project_still_uses_the_root_layout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import claude_code_hooks_daemon.core.project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: tmp_path), raising=False
        )

        from claude_code_hooks_daemon.core.project_layout import ProjectLayout

        handler = TddEnforcementHandler()
        root_layout = ProjectLayout(
            source_dirs=("root-src",),
            test_dirs=(),
            config_dirs=("config",),
            vendor_dirs=frozenset(),
            agent_docs_dir="CLAUDE",
            human_docs_dir="docs",
            plan_dir="CLAUDE/Plan",
            plan_archive_dirs=("Completed",),
        )
        handler._project_layout = root_layout
        handler._project_registry = ProjectRegistry(
            project_root=tmp_path,
            projects=(
                DeclaredProject(
                    name="api",
                    root=tmp_path / "apps" / "api",
                    layout=LayoutConfig(source_dirs=["backend"]),
                ),
            ),
            root_layout=root_layout,
        )

        rule = tmp_path / "root-src" / "my_module.py"
        assert handler.matches(self._write(rule)) is True
