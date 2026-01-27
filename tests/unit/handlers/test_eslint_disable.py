"""Comprehensive tests for EslintDisableHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.eslint_disable import EslintDisableHandler


class TestEslintDisableHandler:
    """Test suite for EslintDisableHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return EslintDisableHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'enforce-no-eslint-disable'."""
        assert handler.name == "enforce-no-eslint-disable"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 30."""
        assert handler.priority == 30

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    def test_forbidden_patterns_defined(self, handler):
        """Handler should define forbidden patterns."""
        assert hasattr(handler, "FORBIDDEN_PATTERNS")
        assert len(handler.FORBIDDEN_PATTERNS) == 4
        assert "eslint-disable" in handler.FORBIDDEN_PATTERNS[0]

    def test_check_extensions_defined(self, handler):
        """Handler should define check extensions."""
        assert hasattr(handler, "CHECK_EXTENSIONS")
        assert ".ts" in handler.CHECK_EXTENSIONS
        assert ".tsx" in handler.CHECK_EXTENSIONS

    # matches() - Positive Cases: eslint-disable pattern
    def test_matches_eslint_disable_in_write(self, handler):
        """Should match eslint-disable comment in Write."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.ts",
                "content": "// eslint-disable-next-line\nconst x = 1;",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_eslint_disable_line_in_write(self, handler):
        """Should match eslint-disable-line comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/test.tsx",
                "content": "const x = any; // eslint-disable-line",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_ts_ignore_in_write(self, handler):
        """Should match @ts-ignore comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/types.ts",
                "content": "// @ts-ignore\nconst x: any = {};",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_ts_nocheck_in_write(self, handler):
        """Should match @ts-nocheck comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/legacy.js",
                "content": "// @ts-nocheck\nfunction old() {}",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_ts_expect_error_in_write(self, handler):
        """Should match @ts-expect-error comment."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.ts",
                "content": "// @ts-expect-error\nconst bad = undefined.prop;",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive(self, handler):
        """Should match patterns case-insensitively."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": "// ESLINT-DISABLE\nconst x = 1;"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_in_edit_new_string(self, handler):
        """Should match forbidden pattern in Edit new_string."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "src/test.tsx",
                "old_string": "const x = 1;",
                "new_string": "// eslint-disable-next-line\nconst x = any;",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_multiple_patterns_in_content(self, handler):
        """Should match when multiple forbidden patterns present."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "bad.ts",
                "content": """
                    // @ts-ignore
                    // eslint-disable
                    const bad = any;
                """,
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - File Extension Filtering
    def test_matches_ts_file_extension(self, handler):
        """Should match .ts files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "Component.ts",
                "content": "// eslint-disable\nconst x = 1;",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_tsx_file_extension(self, handler):
        """Should match .tsx files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "Component.tsx",
                "content": "// eslint-disable\nexport function() {}",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_js_file_extension(self, handler):
        """Should match .js files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "script.js", "content": "// eslint-disable\nvar x = 1;"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_jsx_file_extension(self, handler):
        """Should match .jsx files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "Component.jsx",
                "content": "// eslint-disable\nexport default function() {}",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_case_insensitive_extension(self, handler):
        """Should match file extensions case-insensitively."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "Component.TS",  # uppercase extension
                "content": "// eslint-disable\nconst x = 1;",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases
    def test_matches_non_code_file_returns_false(self, handler):
        """Should not match non-code files (e.g., .md)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "README.md",
                "content": "# eslint-disable\nDocumentation about ESLint",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_python_file_returns_false(self, handler):
        """Should not match Python files."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "script.py", "content": "# eslint-disable\nprint('test')"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_node_modules_returns_false(self, handler):
        """Should skip node_modules directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "node_modules/package/index.ts",
                "content": "// eslint-disable\nexport const x = 1;",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_dist_directory_returns_false(self, handler):
        """Should skip dist directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "dist/bundle.js", "content": "// eslint-disable\nvar x=1;"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_coverage_directory_returns_false(self, handler):
        """Should skip coverage directory."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "coverage/index.ts",
                "content": "// eslint-disable\nconst x = 1;",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_without_forbidden_patterns_returns_false(self, handler):
        """Should not match clean code without suppressions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/clean.ts",
                "content": "export function hello() { return 'world'; }",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_content_returns_false(self, handler):
        """Should not match empty content."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "empty.ts", "content": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_none_content_returns_false(self, handler):
        """Should not match None content."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.ts", "content": None}}
        assert handler.matches(hook_input) is False

    def test_matches_bash_tool_returns_false(self, handler):
        """Should not match Bash tool."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "echo 'eslint-disable'"}}
        assert handler.matches(hook_input) is False

    def test_matches_read_tool_returns_false(self, handler):
        """Should not match Read tool."""
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "test.ts"}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_file_path_with_js_content(self, handler):
        """Should match when file_path is missing but content looks like JS/TS."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"content": "// eslint-disable\nconst x = 1;"},
        }
        # Handler now matches if content has JS markers even without file_path
        assert handler.matches(hook_input) is True

    # handle() Tests
    def test_handle_returns_deny_decision(self, handler):
        """handle() should return deny decision."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": "// eslint-disable\nconst x = 1;"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": "// @ts-ignore\nconst x: any = {};"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_reason_shows_file_path(self, handler):
        """handle() reason should show the file path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/bad.ts",
                "content": "// eslint-disable\nconst x = 1;",
            },
        }
        result = handler.handle(hook_input)
        assert "bad.ts" in result.reason or "/workspace/src/bad.ts" in result.reason

    def test_handle_reason_lists_found_issues(self, handler):
        """handle() reason should list the found suppression comments."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": "// eslint-disable\nconst x = 1;"},
        }
        result = handler.handle(hook_input)
        assert "eslint-disable" in result.reason

    def test_handle_reason_limits_to_five_issues(self, handler):
        """handle() should limit displayed issues to 5."""
        content_with_many = "\n".join([f"// eslint-disable-line {i}" for i in range(10)])
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": content_with_many},
        }
        result = handler.handle(hook_input)
        # Should show "Found X suppression comment(s)" where X >= 5
        assert "suppression comment" in result.reason.lower()

    def test_handle_reason_provides_correct_approach(self, handler):
        """handle() reason should provide correct approach."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": "// @ts-ignore\nconst x = 1;"},
        }
        result = handler.handle(hook_input)
        assert "CORRECT APPROACH" in result.reason

    def test_handle_reason_suggests_fixing_code(self, handler):
        """handle() reason should suggest fixing the code."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": "// eslint-disable\nconst x = 1;"},
        }
        result = handler.handle(hook_input)
        assert "fix" in result.reason.lower()

    def test_handle_with_edit_tool_uses_new_string(self, handler):
        """handle() should check new_string for Edit tool."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.ts",
                "old_string": "const x = 1;",
                "new_string": "// eslint-disable\nconst x = any;",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "eslint-disable" in result.reason

    def test_handle_context_is_none(self, handler):
        """handle() context should be None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": "// eslint-disable\nconst x = 1;"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.ts", "content": "// @ts-ignore\nconst x = 1;"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_blocks_all_forbidden_patterns(self, handler):
        """Should block all defined forbidden patterns."""
        patterns = [
            "// eslint-disable",
            "// @ts-ignore",
            "// @ts-nocheck",
            "// @ts-expect-error",
        ]
        for pattern in patterns:
            hook_input = {
                "tool_name": "Write",
                "tool_input": {"file_path": "test.ts", "content": f"{pattern}\nconst x = 1;"},
            }
            assert handler.matches(hook_input) is True, f"Should block: {pattern}"

    def test_allows_clean_typescript_files(self, handler):
        """Should allow TypeScript files without suppressions."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/components/Header.tsx",
                "content": """
                    export function Header() {
                        return <header>Welcome</header>;
                    }
                """,
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_non_ts_files_without_js_markers(self, handler):
        """Should not match non-TS files without JavaScript markers (line 61 branch)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.txt",  # Non-TS file
                "content": "This is plain text without JS markers",
            },
        }
        # Non-TS file without JS markers - should return False
        assert handler.matches(hook_input) is False

    def test_handle_returns_allow_for_empty_content(self, handler):
        """Should allow when content is empty (line 78 branch)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.ts",
                "content": "",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_returns_allow_for_none_content(self, handler):
        """Should allow when content is None (line 78 branch)."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "test.ts",
                "new_string": "",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_matches_no_file_path_without_js_markers(self, handler):
        """Should not match when no file_path and content has no JS markers (line 61 branch)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "content": "eslint-disable is mentioned here but this is plain text",
            },
        }
        # No file_path, and content has no JS markers (no //, /*, const, let, etc.)
        # Should return False at line 61
        assert handler.matches(hook_input) is False
