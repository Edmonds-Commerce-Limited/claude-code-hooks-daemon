"""Comprehensive tests for PhpQaSuppressionBlocker."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.php_qa_suppression_blocker import (
    PhpQaSuppressionBlocker,
)


class TestPhpQaSuppressionBlocker:
    """Test suite for PhpQaSuppressionBlocker."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return PhpQaSuppressionBlocker()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'php-qa-suppression-blocker'."""
        assert handler.name == "php-qa-suppression-blocker"

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
        assert ".php" in handler.CHECK_EXTENSIONS

    # matches() - Positive Cases: @phpstan-ignore-next-line pattern
    def test_matches_phpstan_ignore_next_line_in_write(self, handler):
        """Should match @phpstan-ignore-next-line comment in Write."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.php",
                "content": "<?php\n/** @phpstan-ignore-next-line */\n$x = doSomething();",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_phpstan_ignore_line_in_write(self, handler):
        """Should match @phpstan-ignore-line comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.php",
                "content": "<?php\n$x = doSomething(); /** @phpstan-ignore-line */",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: @psalm-suppress pattern
    def test_matches_psalm_suppress_in_write(self, handler):
        """Should match @psalm-suppress comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.php",
                "content": "<?php\n/** @psalm-suppress InvalidArgument */\nfunctionCall($arg);",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_psalm_suppress_multiple_issues(self, handler):
        """Should match @psalm-suppress with multiple issues."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.php",
                "content": "<?php\n/** @psalm-suppress InvalidArgument, TooManyArguments */",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: phpcs:ignore pattern
    def test_matches_phpcs_ignore_in_write(self, handler):
        """Should match phpcs:ignore comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.php",
                "content": "<?php\n// phpcs:ignore\n$x = functionCall();",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_phpcs_ignore_with_standard(self, handler):
        """Should match phpcs:ignore with standard specified."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.php",
                "content": "<?php\n// phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Positive Cases: @codingStandardsIgnoreLine pattern
    def test_matches_coding_standards_ignore_line_in_write(self, handler):
        """Should match @codingStandardsIgnoreLine comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.php",
                "content": "<?php\n// @codingStandardsIgnoreLine\n$x = $data['key'];",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Case sensitivity
    def test_matches_case_insensitive(self, handler):
        """Should match patterns case-insensitively."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.php",
                "content": "<?php\n/** @PHPSTAN-IGNORE-NEXT-LINE */\n$x = 1;",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Edit tool
    def test_matches_in_edit_new_string(self, handler):
        """Should match forbidden pattern in Edit new_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "src/test.php",
                "old_string": "$x = 1;",
                "new_string": "/** @phpstan-ignore-next-line */\n$x = 1;",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Multiple patterns
    def test_matches_multiple_patterns_in_content(self, handler):
        """Should match when multiple forbidden patterns present."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "bad.php",
                "content": """<?php
                    /** @phpstan-ignore-next-line */
                    /** @psalm-suppress InvalidArgument */
                    // phpcs:ignore
                    $x = doSomething();
                """,
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - File Extension Filtering
    def test_matches_php_file_extension(self, handler):
        """Should match .php files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "Controller.php",
                "content": "<?php\n/** @phpstan-ignore-line */\n$x = 1;",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive_extension(self, handler):
        """Should match file extensions case-insensitively."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "Controller.PHP",  # uppercase extension
                "content": "<?php\n/** @phpstan-ignore-line */\n$x = 1;",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Wrong file types
    def test_matches_non_php_file_returns_false(self, handler):
        """Should not match non-PHP files (e.g., .py)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "script.py",
                "content": "# @phpstan-ignore-next-line\nprint('test')",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_markdown_file_returns_false(self, handler):
        """Should not match Markdown files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "README.md",
                "content": "@phpstan-ignore-next-line\nDocumentation about PHP",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Excluded directories
    def test_matches_fixtures_directory_returns_false(self, handler):
        """Should skip tests/fixtures/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "tests/fixtures/bad_code.php",
                "content": "<?php\n/** @phpstan-ignore-line */\n$x = 1;",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_vendor_directory_returns_false(self, handler):
        """Should skip vendor/ directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "vendor/package/src/File.php",
                "content": "<?php\n/** @psalm-suppress InvalidArgument */",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Clean code
    def test_matches_without_forbidden_patterns_returns_false(self, handler):
        """Should not match clean code without suppressions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/clean.php",
                "content": "<?php\nfunction hello(): string {\n    return 'world';\n}",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_content_returns_false(self, handler):
        """Should not match empty content."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "empty.php", "content": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_none_content_returns_false(self, handler):
        """Should not match None content."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.php", "content": None},
        }
        assert handler.matches(hook_input) is False

    # matches() - Negative Cases: Wrong tools
    def test_matches_bash_tool_returns_false(self, handler):
        """Should not match Bash tool."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo '@phpstan-ignore-line'"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_tool_returns_false(self, handler):
        """Should not match Read tool."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "test.php"}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_file_path_returns_false(self, handler):
        """Should not match when file_path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"content": "<?php\n/** @phpstan-ignore-line */\n$x = 1;"},
        }
        assert handler.matches(hook_input) is False

    # handle() Tests
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.php",
                "content": "<?php\n/** @phpstan-ignore-line */\n$x = 1;",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.php",
                "content": "<?php\n/** @psalm-suppress InvalidArgument */",
            },
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_shows_file_path(self, handler):
        """handle() reason should show the file path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/bad.php",
                "content": "<?php\n// phpcs:ignore\n$x = 1;",
            },
        }
        result = handler.handle(hook_input)
        assert "bad.php" in result.reason or "/workspace/src/bad.php" in result.reason

    def test_handle_reason_lists_found_issues(self, handler):
        """handle() reason should list the found suppression comments."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.php",
                "content": "<?php\n/** @phpstan-ignore-next-line */\n$x = 1;",
            },
        }
        result = handler.handle(hook_input)
        assert "phpstan-ignore" in result.reason.lower()

    def test_handle_reason_limits_to_five_issues(self, handler):
        """handle() should limit displayed issues to 5."""
        content_with_many = "<?php\n" + "\n".join(
            [f"/** @phpstan-ignore-line */\n$x{i} = 1;" for i in range(10)]
        )
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.php", "content": content_with_many},
        }
        result = handler.handle(hook_input)
        # Should show "Found X suppression comment(s)" where X >= 5
        assert "suppression comment" in result.reason.lower()

    def test_handle_reason_provides_correct_approach(self, handler):
        """handle() reason should provide correct approach."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.php",
                "content": "<?php\n// phpcs:ignore\n$x = 1;",
            },
        }
        result = handler.handle(hook_input)
        assert "CORRECT APPROACH" in result.reason

    def test_handle_reason_suggests_fixing_code(self, handler):
        """handle() reason should suggest fixing the code."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.php",
                "content": "<?php\n/** @psalm-suppress InvalidArgument */",
            },
        }
        result = handler.handle(hook_input)
        assert "fix" in result.reason.lower()

    def test_handle_with_edit_tool_uses_new_string(self, handler):
        """handle() should check new_string for Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.php",
                "old_string": "$x = 1;",
                "new_string": "/** @phpstan-ignore-line */\n$x = 1;",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "phpstan-ignore" in result.reason.lower()

    def test_handle_context_is_empty_list(self, handler):
        """handle() context should be empty list."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.php",
                "content": "<?php\n/** @phpstan-ignore-line */\n$x = 1;",
            },
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.php",
                "content": "<?php\n// phpcs:ignore\n$x = 1;",
            },
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_blocks_all_forbidden_patterns(self, handler):
        """Should block all defined forbidden patterns."""
        patterns = [
            "@phpstan-ignore-next-line",
            "@psalm-suppress",
            "phpcs:ignore",
            "@codingStandardsIgnoreLine",
            "@phpstan-ignore-line",
        ]
        for pattern in patterns:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "test.php",
                    "content": f"<?php\n/** {pattern} */\n$x = 1;",
                },
            }
            assert handler.matches(hook_input) is True, f"Should block: {pattern}"

    def test_allows_clean_php_files(self, handler):
        """Should allow PHP files without suppressions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/controllers/UserController.php",
                "content": """<?php
                    namespace App\\Controllers;

                    class UserController {
                        public function index(): void {
                            echo 'Hello World';
                        }
                    }
                """,
            },
        }
        assert handler.matches(hook_input) is False
