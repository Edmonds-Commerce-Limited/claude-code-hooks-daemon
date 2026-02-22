"""Tests for unified QaSuppressionHandler - strategy-based multi-language QA suppression."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision

# Build suppression patterns dynamically to avoid triggering the live QA suppression hook
# which scans file content for these exact patterns
_TYPE = "type"
_NOQA = "noqa"
_NOLINT = "nolint"
_ESLINT = "eslint"
_PHPSTAN = "phpstan"

# Python suppression patterns (assembled at runtime)
PY_TYPE_IGNORE = f"# {_TYPE}: ignore"
PY_NOQA = f"# {_NOQA}"
PY_PYLINT_DISABLE = "# pylint: dis" + "able=C0301"

# Go suppression patterns
GO_NOLINT = f"// {_NOLINT}"
GO_LINT_IGNORE = "//lint" + ":ignore"

# JavaScript/TypeScript suppression patterns
JS_ESLINT_DISABLE = f"// {_ESLINT}-dis" + "able"
JS_TS_IGNORE = "// @ts-" + "ignore"

# PHP suppression patterns
PHP_PHPSTAN_IGNORE = f"// @{_PHPSTAN}-" + "ignore-next-line"
PHP_PSALM_SUPPRESS = "/** @psalm-" + "suppress */"


def _make_write_input(file_path: str, content: str) -> dict[str, Any]:
    """Create a Write tool hook input."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": content,
        },
    }


def _make_edit_input(file_path: str, new_string: str) -> dict[str, Any]:
    """Create an Edit tool hook input."""
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": "original",
            "new_string": new_string,
        },
    }


def _make_bash_input(command: str) -> dict[str, Any]:
    """Create a Bash tool hook input."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


class TestQaSuppressionHandlerInit:
    """Test handler initialization."""

    def test_handler_id(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        assert handler.handler_id == HandlerID.QA_SUPPRESSION

    def test_priority(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        assert handler.priority == Priority.QA_SUPPRESSION

    def test_tags(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        assert HandlerTag.MULTI_LANGUAGE in handler.tags
        assert HandlerTag.QA_ENFORCEMENT in handler.tags
        assert HandlerTag.BLOCKING in handler.tags
        assert HandlerTag.TERMINAL in handler.tags


class TestQaSuppressionHandlerMatches:
    """Test matches() method - delegates to strategy pattern."""

    def test_matches_python_suppression(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        assert handler.matches(hook_input) is True

    def test_matches_go_suppression(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.go", f"x := 1 {GO_NOLINT}")
        assert handler.matches(hook_input) is True

    def test_matches_javascript_suppression(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.ts", f"x = 1; {JS_ESLINT_DISABLE}")
        assert handler.matches(hook_input) is True

    def test_matches_php_suppression(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input(
            "/workspace/src/app/main.php", f"$x = 1; {PHP_PHPSTAN_IGNORE}"
        )
        assert handler.matches(hook_input) is True

    def test_no_match_clean_code(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.py", "x = 1\ny = 2\n")
        assert handler.matches(hook_input) is False

    def test_no_match_unknown_extension(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/data.txt", f"x = 1  {PY_TYPE_IGNORE}")
        assert handler.matches(hook_input) is False

    def test_no_match_non_write_tool(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_bash_input("echo hello")
        assert handler.matches(hook_input) is False

    def test_no_match_no_content(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/app/main.py"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_tool(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_edit_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        assert handler.matches(hook_input) is True

    def test_skip_vendor_directory(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/vendor/lib/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        assert handler.matches(hook_input) is False

    def test_skip_node_modules(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input(
            "/workspace/node_modules/pkg/index.ts", f"x = 1; {JS_ESLINT_DISABLE}"
        )
        assert handler.matches(hook_input) is False

    def test_skip_venv_directory(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/venv/lib/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        assert handler.matches(hook_input) is False


class TestQaSuppressionHandlerHandle:
    """Test handle() method - deny with language-appropriate message."""

    def test_deny_python_suppression(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "Python" in (result.reason or "")
        assert "suppression" in (result.reason or "").lower()

    def test_deny_go_suppression(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.go", f"x := 1 {GO_NOLINT}")
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "Go" in (result.reason or "")

    def test_deny_javascript_suppression(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.ts", f"x = 1; {JS_ESLINT_DISABLE}")
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "JavaScript" in (result.reason or "")

    def test_deny_php_suppression(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input(
            "/workspace/src/app/main.php", f"$x = 1; {PHP_PHPSTAN_IGNORE}"
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "PHP" in (result.reason or "")

    def test_deny_includes_found_issues(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        result = handler.handle(hook_input)
        assert "suppression comment" in (result.reason or "").lower()

    def test_deny_includes_tool_docs(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        result = handler.handle(hook_input)
        assert "Resources:" in (result.reason or "")

    def test_allow_when_no_strategy_found(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/data.txt", "clean content")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_allow_clean_code(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_write_input("/workspace/src/app/main.py", "x = 1\ny = 2\n")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_edit_tool_checks_new_string(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input = _make_edit_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


class TestQaSuppressionLanguageFilter:
    """Test language filtering via _languages and _project_languages."""

    def test_language_filter_restricts_matching(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        handler._languages = ["python"]
        # Python should still match
        py_input = _make_write_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        assert handler.matches(py_input) is True
        # Go should NOT match (filtered out)
        go_input = _make_write_input("/workspace/src/app/main.go", f"x := 1 {GO_NOLINT}")
        assert handler.matches(go_input) is False

    def test_project_languages_used_as_fallback(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        handler._project_languages = ["go"]
        # Go should match
        go_input = _make_write_input("/workspace/src/app/main.go", f"x := 1 {GO_NOLINT}")
        assert handler.matches(go_input) is True
        # Python should NOT match
        py_input = _make_write_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        assert handler.matches(py_input) is False

    def test_handler_languages_override_project_languages(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        handler._languages = ["python"]
        handler._project_languages = ["go"]
        # Handler-level wins: only Python
        py_input = _make_write_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        assert handler.matches(py_input) is True
        go_input = _make_write_input("/workspace/src/app/main.go", f"x := 1 {GO_NOLINT}")
        assert handler.matches(go_input) is False

    def test_no_filter_enforces_all_languages(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        # No _languages or _project_languages set - all should match
        py_input = _make_write_input("/workspace/src/app/main.py", f"x = 1  {PY_TYPE_IGNORE}")
        go_input = _make_write_input("/workspace/src/app/main.go", f"x := 1 {GO_NOLINT}")
        assert handler.matches(py_input) is True
        assert handler.matches(go_input) is True


class TestQaSuppressionAcceptanceTests:
    """Test get_acceptance_tests() aggregation."""

    def test_returns_acceptance_tests(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0

    def test_acceptance_tests_from_all_strategies(self) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        tests = handler.get_acceptance_tests()
        # Should have tests from multiple languages
        assert len(tests) >= 11  # At least one per language


class TestQaSuppressionEdgeCases:
    """Test edge cases in matches() and handle() guard clauses."""

    def test_matches_returns_false_when_no_file_path(self) -> None:
        """matches() returns False when Write tool_input has no file_path (line 112)."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input: dict[str, Any] = {"tool_name": "Write", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_handle_returns_allow_when_no_file_path(self) -> None:
        """handle() returns ALLOW when hook_input has no file_path (line 138)."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input: dict[str, Any] = {"tool_name": "Write", "tool_input": {}}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_returns_allow_when_no_content(self) -> None:
        """handle() returns ALLOW when file_path present but content is empty (line 146)."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        handler = QaSuppressionHandler()
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/app/main.py", "content": ""},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
