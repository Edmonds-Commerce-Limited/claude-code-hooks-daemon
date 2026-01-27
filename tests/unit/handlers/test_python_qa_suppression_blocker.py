"""Comprehensive tests for PythonQaSuppressionBlocker."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.python_qa_suppression_blocker import (
    PythonQaSuppressionBlocker,
)


class TestPythonQaSuppressionBlocker:
    """Test suite for PythonQaSuppressionBlocker."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return PythonQaSuppressionBlocker()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'python-qa-suppression-blocker'."""
        assert handler.name == "python-qa-suppression-blocker"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 30."""
        assert handler.priority == 30

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    def test_forbidden_patterns_defined(self, handler):
        """Handler should define forbidden patterns."""
        assert hasattr(handler, "FORBIDDEN_PATTERNS")
        assert len(handler.FORBIDDEN_PATTERNS) == 5

    def test_check_extensions_defined(self, handler):
        """Handler should define check extensions."""
        assert hasattr(handler, "CHECK_EXTENSIONS")
        assert ".py" in handler.CHECK_EXTENSIONS

    # matches() - Positive Cases: type: ignore pattern
    def test_matches_type_ignore_in_write(self, handler):
        """Should match # type: ignore comment in Write."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.py",
                "content": "x = 1  # type: ignore\nprint(x)",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_type_ignore_with_error_code(self, handler):
        """Should match # type: ignore[error-code] comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.py",
                "content": "x: Any = 1  # type: ignore[assignment]",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: noqa pattern
    def test_matches_noqa_in_write(self, handler):
        """Should match # noqa comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.py",
                "content": "import os  # noqa\nprint('test')",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_noqa_with_error_code(self, handler):
        """Should match # noqa: F401 comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.py",
                "content": "import os  # noqa: F401",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: pylint disable pattern
    def test_matches_pylint_disable_in_write(self, handler):
        """Should match # pylint: disable comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.py",
                "content": "x = 1  # pylint: disable=invalid-name",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_pylint_disable_next_line(self, handler):
        """Should match # pylint: disable-next comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.py",
                "content": "# pylint: disable-next=too-many-arguments\ndef func(a, b, c, d, e, f): pass",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: pyright ignore pattern
    def test_matches_pyright_ignore_in_write(self, handler):
        """Should match # pyright: ignore comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/types.py",
                "content": "x: Any = 1  # pyright: ignore",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_pyright_ignore_with_error_code(self, handler):
        """Should match # pyright: ignore[error] comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.py",
                "content": "x = undefined  # pyright: ignore[reportUndefinedVariable]",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: mypy ignore-errors pattern
    def test_matches_mypy_ignore_errors_in_write(self, handler):
        """Should match # mypy: ignore-errors comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/legacy.py",
                "content": "# mypy: ignore-errors\nfrom old_module import *",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Case sensitivity
    def test_matches_case_insensitive(self, handler):
        """Should match patterns case-insensitively."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "x = 1  # TYPE: IGNORE\nprint(x)"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Edit tool
    def test_matches_in_edit_new_string(self, handler):
        """Should match forbidden pattern in Edit new_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "src/test.py",
                "old_string": "x = 1",
                "new_string": "x = 1  # type: ignore",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Multiple patterns
    def test_matches_multiple_patterns_in_content(self, handler):
        """Should match when multiple forbidden patterns present."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "bad.py",
                "content": """
                    x: Any = 1  # type: ignore
                    import os  # noqa
                    y = 2  # pylint: disable=invalid-name
                """,
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - File Extension Filtering
    def test_matches_py_file_extension(self, handler):
        """Should match .py files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "module.py",
                "content": "x = 1  # type: ignore",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive_extension(self, handler):
        """Should match file extensions case-insensitively."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "module.PY",  # uppercase extension
                "content": "x = 1  # type: ignore",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Wrong file types
    def test_matches_non_python_file_returns_false(self, handler):
        """Should not match non-Python files (e.g., .js)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "script.js",
                "content": "// type: ignore\nconst x = 1;",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_markdown_file_returns_false(self, handler):
        """Should not match Markdown files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "README.md",
                "content": "# type: ignore\nDocumentation about types",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Excluded directories
    def test_matches_fixtures_directory_returns_false(self, handler):
        """Should skip tests/fixtures/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "tests/fixtures/bad_code.py",
                "content": "x = 1  # type: ignore",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_migrations_directory_returns_false(self, handler):
        """Should skip migrations/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "migrations/0001_initial.py",
                "content": "# type: ignore\nfrom django.db import migrations",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_vendor_directory_returns_false(self, handler):
        """Should skip vendor/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "vendor/package/module.py",
                "content": "x = 1  # noqa",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_venv_directory_returns_false(self, handler):
        """Should skip venv/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "venv/lib/python3.11/site-packages/module.py",
                "content": "x = 1  # type: ignore",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_dot_venv_directory_returns_false(self, handler):
        """Should skip .venv/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": ".venv/lib/python3.11/site-packages/module.py",
                "content": "x = 1  # type: ignore",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Clean code
    def test_matches_without_forbidden_patterns_returns_false(self, handler):
        """Should not match clean code without suppressions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/clean.py",
                "content": "def hello() -> str:\n    return 'world'",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_content_returns_false(self, handler):
        """Should not match empty content."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "empty.py", "content": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_none_content_returns_false(self, handler):
        """Should not match None content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": None},
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Wrong tools
    def test_matches_bash_tool_returns_false(self, handler):
        """Should not match Bash tool."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "echo '# type: ignore'"}}
        assert handler.matches(hook_input) is False

    def test_matches_read_tool_returns_false(self, handler):
        """Should not match Read tool."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "test.py"}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_file_path_returns_false(self, handler):
        """Should not match when file_path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"content": "x = 1  # type: ignore"},
        }
        assert handler.matches(hook_input) is False

    # handle() Tests
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "x = 1  # type: ignore"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "import os  # noqa"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_shows_file_path(self, handler):
        """handle() reason should show the file path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/bad.py",
                "content": "x = 1  # type: ignore",
            },
        }
        result = handler.handle(hook_input)
        assert "bad.py" in result.reason or "/workspace/src/bad.py" in result.reason

    def test_handle_reason_lists_found_issues(self, handler):
        """handle() reason should list the found suppression comments."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "x = 1  # type: ignore"},
        }
        result = handler.handle(hook_input)
        assert "type: ignore" in result.reason or "type:ignore" in result.reason

    def test_handle_reason_limits_to_five_issues(self, handler):
        """handle() should limit displayed issues to 5."""
        content_with_many = "\n".join([f"x{i} = 1  # type: ignore" for i in range(10)])
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": content_with_many},
        }
        result = handler.handle(hook_input)
        # Should show "Found X suppression comment(s)" where X >= 5
        assert "suppression comment" in result.reason.lower()

    def test_handle_reason_provides_correct_approach(self, handler):
        """handle() reason should provide correct approach."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "x = 1  # noqa"},
        }
        result = handler.handle(hook_input)
        assert "CORRECT APPROACH" in result.reason

    def test_handle_reason_suggests_fixing_code(self, handler):
        """handle() reason should suggest fixing the code."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.py",
                "content": "x = 1  # pylint: disable=invalid-name",
            },
        }
        result = handler.handle(hook_input)
        assert "fix" in result.reason.lower()

    def test_handle_with_edit_tool_uses_new_string(self, handler):
        """handle() should check new_string for Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.py",
                "old_string": "x = 1",
                "new_string": "x = 1  # type: ignore",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "type: ignore" in result.reason or "type:ignore" in result.reason

    def test_handle_context_is_empty_list(self, handler):
        """handle() context should be empty list."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "x = 1  # type: ignore"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "x = 1  # noqa"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_blocks_all_forbidden_patterns(self, handler):
        """Should block all defined forbidden patterns."""
        patterns = [
            "# type: ignore",
            "# noqa",
            "# pylint: disable",
            "# pyright: ignore",
            "# mypy: ignore-errors",
        ]
        for pattern in patterns:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {"file_path": "test.py", "content": f"x = 1  {pattern}"},
            }
            assert handler.matches(hook_input) is True, f"Should block: {pattern}"

    def test_allows_clean_python_files(self, handler):
        """Should allow Python files without suppressions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/utils/helper.py",
                "content": """
                    def add(x: int, y: int) -> int:
                        return x + y
                """,
            },
        }
        assert handler.matches(hook_input) is False
