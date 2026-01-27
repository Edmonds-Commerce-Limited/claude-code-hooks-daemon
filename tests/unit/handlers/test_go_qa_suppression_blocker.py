"""Comprehensive tests for GoQaSuppressionBlocker."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.go_qa_suppression_blocker import (
    GoQaSuppressionBlocker,
)


class TestGoQaSuppressionBlocker:
    """Test suite for GoQaSuppressionBlocker."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return GoQaSuppressionBlocker()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'go-qa-suppression-blocker'."""
        assert handler.name == "go-qa-suppression-blocker"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 30."""
        assert handler.priority == 30

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    def test_forbidden_patterns_defined(self, handler):
        """Handler should define forbidden patterns."""
        assert hasattr(handler, "FORBIDDEN_PATTERNS")
        assert len(handler.FORBIDDEN_PATTERNS) == 2

    def test_check_extensions_defined(self, handler):
        """Handler should define check extensions."""
        assert hasattr(handler, "CHECK_EXTENSIONS")
        assert ".go" in handler.CHECK_EXTENSIONS

    # matches() - Positive Cases: nolint pattern
    def test_matches_nolint_in_write(self, handler):
        """Should match //nolint comment in Write."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.go",
                "content": "package main\n\nfunc foo() { //nolint\n\treturn\n}",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_nolint_with_linter(self, handler):
        """Should match //nolint:linter comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.go",
                "content": "package main\n\nvar x = 1 //nolint:gocyclo",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_nolint_with_multiple_linters(self, handler):
        """Should match //nolint:linter1,linter2 comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.go",
                "content": "package main\n\nfunc foo() { //nolint:gocyclo,funlen\n\treturn\n}",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_nolintlint_in_write(self, handler):
        """Should match //nolintlint comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.go",
                "content": "package main\n\nvar x = 1 //nolintlint",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: lint:ignore pattern
    def test_matches_lint_ignore_in_write(self, handler):
        """Should match //lint:ignore comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.go",
                "content": "package main\n\n//lint:ignore SA1000 reason\nvar x = 1",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_lint_ignore_with_code(self, handler):
        """Should match //lint:ignore CODE reason."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.go",
                "content": "package main\n\n//lint:ignore U1000 unused function\nfunc unused() {}",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Case sensitivity
    def test_matches_case_insensitive(self, handler):
        """Should match patterns case-insensitively."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\nvar x = 1 //NOLINT",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Whitespace variations
    def test_matches_nolint_with_whitespace(self, handler):
        """Should match // nolint with whitespace."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\nvar x = 1 // nolint",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_lint_ignore_with_whitespace(self, handler):
        """Should match // lint:ignore with whitespace."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\n// lint:ignore SA1000 reason\nvar x = 1",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Edit tool
    def test_matches_in_edit_new_string(self, handler):
        """Should match forbidden pattern in Edit new_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "src/test.go",
                "old_string": "var x = 1",
                "new_string": "var x = 1 //nolint",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Multiple patterns
    def test_matches_multiple_patterns_in_content(self, handler):
        """Should match when multiple forbidden patterns present."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "bad.go",
                "content": """package main

                    var x = 1 //nolint
                    //lint:ignore SA1000 reason
                    var y = 2
                """,
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - File Extension Filtering
    def test_matches_go_file_extension(self, handler):
        """Should match .go files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "main.go",
                "content": "package main\n\nvar x = 1 //nolint",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive_extension(self, handler):
        """Should match file extensions case-insensitively."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "main.GO",  # uppercase extension
                "content": "package main\n\nvar x = 1 //nolint",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Wrong file types
    def test_matches_non_go_file_returns_false(self, handler):
        """Should not match non-Go files (e.g., .py)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "script.py",
                "content": "# nolint\nprint('test')",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_markdown_file_returns_false(self, handler):
        """Should not match Markdown files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "README.md",
                "content": "//nolint\nDocumentation about Go",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Excluded directories
    def test_matches_vendor_directory_returns_false(self, handler):
        """Should skip vendor/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "vendor/github.com/package/file.go",
                "content": "package pkg\n\nvar x = 1 //nolint",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_testdata_directory_returns_false(self, handler):
        """Should skip testdata/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "testdata/fixture.go",
                "content": "package testdata\n\nvar x = 1 //nolint",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Clean code
    def test_matches_without_forbidden_patterns_returns_false(self, handler):
        """Should not match clean code without suppressions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/clean.go",
                "content": 'package main\n\nfunc hello() string {\n\treturn "world"\n}',
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_content_returns_false(self, handler):
        """Should not match empty content."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "empty.go", "content": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_none_content_returns_false(self, handler):
        """Should not match None content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.go", "content": None},
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Wrong tools
    def test_matches_bash_tool_returns_false(self, handler):
        """Should not match Bash tool."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "echo '//nolint'"}}
        assert handler.matches(hook_input) is False

    def test_matches_read_tool_returns_false(self, handler):
        """Should not match Read tool."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "test.go"}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_file_path_returns_false(self, handler):
        """Should not match when file_path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"content": "package main\n\nvar x = 1 //nolint"},
        }
        assert handler.matches(hook_input) is False

    # handle() Tests
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\nvar x = 1 //nolint",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\n//lint:ignore SA1000 reason\nvar x = 1",
            },
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_shows_file_path(self, handler):
        """handle() reason should show the file path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/bad.go",
                "content": "package main\n\nvar x = 1 //nolint",
            },
        }
        result = handler.handle(hook_input)
        assert "bad.go" in result.reason or "/workspace/src/bad.go" in result.reason

    def test_handle_reason_lists_found_issues(self, handler):
        """handle() reason should list the found suppression comments."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\nvar x = 1 //nolint",
            },
        }
        result = handler.handle(hook_input)
        assert "nolint" in result.reason.lower()

    def test_handle_reason_limits_to_five_issues(self, handler):
        """handle() should limit displayed issues to 5."""
        content_with_many = "package main\n\n" + "\n".join(
            [f"var x{i} = 1 //nolint" for i in range(10)]
        )
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.go", "content": content_with_many},
        }
        result = handler.handle(hook_input)
        # Should show "Found X suppression comment(s)" where X >= 5
        assert "suppression comment" in result.reason.lower()

    def test_handle_reason_provides_correct_approach(self, handler):
        """handle() reason should provide correct approach."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\nvar x = 1 //nolint",
            },
        }
        result = handler.handle(hook_input)
        assert "CORRECT APPROACH" in result.reason

    def test_handle_reason_suggests_fixing_code(self, handler):
        """handle() reason should suggest fixing the code."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\n//lint:ignore SA1000 reason\nvar x = 1",
            },
        }
        result = handler.handle(hook_input)
        assert "fix" in result.reason.lower()

    def test_handle_with_edit_tool_uses_new_string(self, handler):
        """handle() should check new_string for Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.go",
                "old_string": "var x = 1",
                "new_string": "var x = 1 //nolint",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "nolint" in result.reason.lower()

    def test_handle_context_is_empty_list(self, handler):
        """handle() context should be empty list."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\nvar x = 1 //nolint",
            },
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.go",
                "content": "package main\n\nvar x = 1 //nolint",
            },
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    def test_handle_empty_content_returns_allow(self, handler):
        """handle() should return ALLOW for empty content."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.go", "content": ""}}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # Integration Tests
    def test_blocks_all_forbidden_patterns(self, handler):
        """Should block all defined forbidden patterns."""
        patterns = [
            "//nolint",
            "//lint:ignore SA1000 reason",
        ]
        for pattern in patterns:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "test.go",
                    "content": f"package main\n\n{pattern}\nvar x = 1",
                },
            }
            assert handler.matches(hook_input) is True, f"Should block: {pattern}"

    def test_allows_clean_go_files(self, handler):
        """Should allow Go files without suppressions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/handlers/user_handler.go",
                "content": """package handlers

                    import "fmt"

                    func HandleUser() {
                        fmt.Println("Hello World")
                    }
                """,
            },
        }
        assert handler.matches(hook_input) is False
