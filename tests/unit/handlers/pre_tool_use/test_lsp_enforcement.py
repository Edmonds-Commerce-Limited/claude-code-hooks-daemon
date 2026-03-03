"""Tests for LspEnforcementHandler - enforces LSP tool usage over Grep/Bash grep.

Tests cover:
- Initialization (name, priority, terminal, tags)
- matches() positive cases (symbol-like patterns in Grep and Bash grep/rg)
- matches() negative cases (regex patterns, non-symbol searches, other tools)
- handle() block_once mode (deny first, allow retry)
- handle() advisory mode (always allow with guidance)
- handle() strict mode (always deny)
- no_lsp_mode options (block, advisory, disable)
- LSP operation mapping (grep pattern -> suggested LSP operation)
"""

from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision


class TestLspEnforcementHandlerInit:
    """Test handler initialization."""

    def _make_handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        return LspEnforcementHandler()

    def test_init_sets_correct_name(self) -> None:
        handler = self._make_handler()
        assert handler.name == "enforce-lsp-usage"

    def test_init_sets_correct_priority(self) -> None:
        from claude_code_hooks_daemon.constants import Priority

        handler = self._make_handler()
        assert handler.priority == Priority.LSP_ENFORCEMENT
        assert handler.priority == 38

    def test_init_sets_terminal_true(self) -> None:
        handler = self._make_handler()
        assert handler.terminal is True

    def test_init_has_correct_tags(self) -> None:
        from claude_code_hooks_daemon.constants import HandlerTag

        handler = self._make_handler()
        assert HandlerTag.WORKFLOW in handler.tags
        assert HandlerTag.BLOCKING in handler.tags
        assert HandlerTag.TERMINAL in handler.tags


class TestLspEnforcementMatchesPositive:
    """Test matches() returns True for symbol-like grep patterns."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        return LspEnforcementHandler()

    # --- Grep tool: class/def/function/interface patterns ---

    def test_matches_grep_class_definition(self, handler: Any) -> None:
        """Grep for 'class ClassName' should trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_grep_def_function(self, handler: Any) -> None:
        """Grep for 'def function_name' should trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "def get_workspace_root"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_grep_function_keyword(self, handler: Any) -> None:
        """Grep for 'function functionName' should trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "function handleRequest"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_grep_interface_definition(self, handler: Any) -> None:
        """Grep for 'interface InterfaceName' should trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "interface EventHandler"},
        }
        assert handler.matches(hook_input) is True

    # --- Grep tool: identifier patterns ---

    def test_matches_grep_pascal_case_identifier(self, handler: Any) -> None:
        """Grep for PascalCase identifier should trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "FrontController"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_grep_snake_case_identifier(self, handler: Any) -> None:
        """Grep for snake_case exact identifier should trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "get_bash_command"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_grep_import_pattern(self, handler: Any) -> None:
        """Grep for import pattern should trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "import HandlerID"},
        }
        assert handler.matches(hook_input) is True

    # --- Bash tool: grep/rg commands ---

    def test_matches_bash_grep_class(self, handler: Any) -> None:
        """Bash grep for class definition should trigger."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": 'grep -rn "class FooHandler" src/'},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_rg_def(self, handler: Any) -> None:
        """Bash rg for function definition should trigger."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": 'rg "def process_event" src/'},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_grep_pascal_case(self, handler: Any) -> None:
        """Bash grep for PascalCase symbol should trigger."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -r HookResult src/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_bash_rg_snake_case(self, handler: Any) -> None:
        """Bash rg for snake_case symbol should trigger."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rg get_data_layer src/"},
        }
        assert handler.matches(hook_input) is True


class TestLspEnforcementMatchesNegative:
    """Test matches() returns False for non-symbol patterns."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        return LspEnforcementHandler()

    # --- Non-Grep/Bash tools ---

    def test_no_match_read_tool(self, handler: Any) -> None:
        """Read tool should never trigger."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/src/handler.py"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_write_tool(self, handler: Any) -> None:
        """Write tool should never trigger."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test.py", "content": "class Foo: pass"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_glob_tool(self, handler: Any) -> None:
        """Glob tool should never trigger (file discovery is legitimate)."""
        hook_input = {
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_edit_tool(self, handler: Any) -> None:
        """Edit tool should never trigger."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/test.py",
                "old_string": "class Foo",
                "new_string": "class Bar",
            },
        }
        assert handler.matches(hook_input) is False

    # --- Regex/content patterns (not symbols) ---

    def test_no_match_grep_regex_pattern(self, handler: Any) -> None:
        """Grep with regex pattern should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "log.*Error"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_complex_regex(self, handler: Any) -> None:
        """Grep with complex regex should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": r"\d{3}-\d{4}"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_string_literal(self, handler: Any) -> None:
        """Grep for string literal content should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "error message not found"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_todo_fixme(self, handler: Any) -> None:
        """Grep for TODO/FIXME should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "TODO"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_fixme(self, handler: Any) -> None:
        """Grep for FIXME should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "FIXME"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_hack(self, handler: Any) -> None:
        """Grep for HACK should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "HACK"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_with_many_metacharacters(self, handler: Any) -> None:
        """Grep with many regex metacharacters should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": r"(foo|bar)\s+\w+\(\)"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_dot_star_pattern(self, handler: Any) -> None:
        """Grep with .* pattern should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "import.*from"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_bash_grep_content_search(self, handler: Any) -> None:
        """Bash grep for non-symbol content should NOT trigger."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": 'grep -rn "error: file not found" logs/'},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_bash_non_grep_command(self, handler: Any) -> None:
        """Bash command that's not grep/rg should NOT trigger."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la src/"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_bash_grep_regex(self, handler: Any) -> None:
        """Bash grep with regex should NOT trigger."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": 'grep -rn "log.*Error" src/'},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_empty_tool_input(self, handler: Any) -> None:
        """Empty tool input should not trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_missing_tool_input(self, handler: Any) -> None:
        """Missing toolInput should not trigger."""
        hook_input: dict[str, Any] = {
            "tool_name": "Grep",
        }
        assert handler.matches(hook_input) is False

    def test_no_match_short_lowercase_word(self, handler: Any) -> None:
        """Short generic lowercase words should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "error"},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_grep_multiline_pattern(self, handler: Any) -> None:
        """Grep with multiline regex should NOT trigger."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": r"struct \{[\s\S]*?field", "multiline": True},
        }
        assert handler.matches(hook_input) is False

    def test_no_match_lsp_tool(self, handler: Any) -> None:
        """LSP tool itself should never trigger (would create infinite loop)."""
        hook_input = {
            "tool_name": "LSP",
            "tool_input": {
                "operation": "goToDefinition",
                "filePath": "test.py",
                "line": 1,
                "character": 1,
            },
        }
        assert handler.matches(hook_input) is False


class TestLspEnforcementHandleBlockOnce:
    """Test handle() in block_once mode (default)."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        return LspEnforcementHandler()

    def test_block_once_first_call_denies(self, handler: Any) -> None:
        """First grep-that-looks-like-LSP should be denied."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.object(handler, "_get_block_count", return_value=0):
            result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "LSP" in result.reason

    def test_block_once_second_call_allows(self, handler: Any) -> None:
        """Retry after first block should be allowed."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.object(handler, "_get_block_count", return_value=1):
            result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_block_once_third_call_still_allows(self, handler: Any) -> None:
        """Subsequent retries should continue to be allowed."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.object(handler, "_get_block_count", return_value=5):
            result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


class TestLspEnforcementHandleAdvisory:
    """Test handle() in advisory mode."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        h = LspEnforcementHandler()
        setattr(h, "_mode", "advisory")
        return h

    def test_advisory_always_allows(self, handler: Any) -> None:
        """Advisory mode should always allow with guidance."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.object(handler, "_get_block_count", return_value=0):
            result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_advisory_includes_lsp_guidance(self, handler: Any) -> None:
        """Advisory mode should include LSP guidance in reason."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.object(handler, "_get_block_count", return_value=0):
            result = handler.handle(hook_input)
        assert result.reason is not None
        assert "LSP" in result.reason


class TestLspEnforcementHandleStrict:
    """Test handle() in strict mode."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        h = LspEnforcementHandler()
        setattr(h, "_mode", "strict")
        return h

    def test_strict_always_denies(self, handler: Any) -> None:
        """Strict mode should always deny."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.object(handler, "_get_block_count", return_value=0):
            result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_strict_denies_on_retry(self, handler: Any) -> None:
        """Strict mode should deny even on retry."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.object(handler, "_get_block_count", return_value=5):
            result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


class TestLspEnforcementNoLspMode:
    """Test no_lsp_mode options (behavior when LSP is not configured)."""

    def _make_handler(self, no_lsp_mode: str = "block") -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        h = LspEnforcementHandler()
        setattr(h, "_no_lsp_mode", no_lsp_mode)
        return h

    def test_no_lsp_block_mode_still_matches(self) -> None:
        """With no_lsp_mode=block, handler matches even without LSP configured."""
        handler = self._make_handler("block")
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.dict("os.environ", {}, clear=True):
            assert handler.matches(hook_input) is True

    def test_no_lsp_block_mode_includes_setup_guidance(self) -> None:
        """With no_lsp_mode=block, handle() includes LSP setup instructions."""
        handler = self._make_handler("block")
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(handler, "_get_block_count", return_value=0),
        ):
            result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "LSP" in result.reason

    def test_no_lsp_advisory_mode_allows(self) -> None:
        """With no_lsp_mode=advisory, handler downgrades to advisory."""
        handler = self._make_handler("advisory")
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(handler, "_get_block_count", return_value=0),
        ):
            result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_no_lsp_disable_mode_no_match(self) -> None:
        """With no_lsp_mode=disable, handler doesn't match when LSP unavailable."""
        handler = self._make_handler("disable")
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.dict("os.environ", {}, clear=True):
            assert handler.matches(hook_input) is False

    def test_no_lsp_disable_mode_matches_when_lsp_available(self) -> None:
        """With no_lsp_mode=disable, handler matches when LSP IS configured."""
        handler = self._make_handler("disable")
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.dict("os.environ", {"ENABLE_LSP_TOOL": "1"}):
            assert handler.matches(hook_input) is True


class TestLspEnforcementLspOperationMapping:
    """Test that handler maps grep patterns to correct LSP operations."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        return LspEnforcementHandler()

    def test_class_pattern_suggests_go_to_definition(self, handler: Any) -> None:
        """'class X' pattern should suggest goToDefinition or workspaceSymbol."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "class MyHandler"},
        }
        with patch.object(handler, "_get_block_count", return_value=0):
            result = handler.handle(hook_input)
        assert "goToDefinition" in result.reason or "workspaceSymbol" in result.reason

    def test_def_pattern_suggests_go_to_definition(self, handler: Any) -> None:
        """'def func' pattern should suggest goToDefinition or workspaceSymbol."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "def process_event"},
        }
        with patch.object(handler, "_get_block_count", return_value=0):
            result = handler.handle(hook_input)
        assert "goToDefinition" in result.reason or "workspaceSymbol" in result.reason

    def test_identifier_suggests_find_references(self, handler: Any) -> None:
        """Plain identifier should suggest findReferences or workspaceSymbol."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "FrontController"},
        }
        with patch.object(handler, "_get_block_count", return_value=0):
            result = handler.handle(hook_input)
        assert "findReferences" in result.reason or "workspaceSymbol" in result.reason

    def test_import_pattern_suggests_find_references(self, handler: Any) -> None:
        """'import X' pattern should suggest findReferences."""
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "import HandlerID"},
        }
        with patch.object(handler, "_get_block_count", return_value=0):
            result = handler.handle(hook_input)
        assert "findReferences" in result.reason or "workspaceSymbol" in result.reason


class TestLspEnforcementAcceptanceTests:
    """Test that handler provides acceptance tests."""

    def test_has_acceptance_tests(self) -> None:
        """Handler must define acceptance tests."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        handler = LspEnforcementHandler()
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 2

    def test_acceptance_tests_have_required_fields(self) -> None:
        """Each acceptance test must have title, command, description."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
            LspEnforcementHandler,
        )

        handler = LspEnforcementHandler()
        tests = handler.get_acceptance_tests()
        for test in tests:
            assert test.title
            assert test.command
            assert test.description
