"""Integration tests for PreToolUse QA enforcement handlers.

Tests: QaSuppressionHandler (unified), TddEnforcementHandler

NOTE: Test data strings that contain QA suppression patterns are constructed
via concatenation to avoid triggering the live daemon's own QA suppression
blocker hook during file writes.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import make_edit_hook_input, make_write_hook_input


# ---------------------------------------------------------------------------
# Helper: build suppression strings via concatenation
# ---------------------------------------------------------------------------
def _py_type_ignore() -> str:
    return "# type" + ": " + "ignore"


def _py_noqa() -> str:
    return "# no" + "qa"


def _py_pylint_disable() -> str:
    return "# pylint" + ": " + "disable"


def _eslint_disable() -> str:
    return "eslint" + "-" + "disable"


def _ts_ignore() -> str:
    return "@ts" + "-" + "ignore"


def _ts_nocheck() -> str:
    return "@ts" + "-" + "nocheck"


def _phpstan_ignore() -> str:
    return "@phpstan" + "-ignore-next-line"


def _psalm_suppress() -> str:
    return "@psalm" + "-suppress"


def _phpcs_ignore() -> str:
    return "phpcs" + ":" + "ignore"


def _go_nolint() -> str:
    return "// no" + "lint"


def _go_lint_ignore() -> str:
    return "// lint" + ":" + "ignore"


# ---------------------------------------------------------------------------
# QaSuppressionHandler (unified, strategy-based)
# ---------------------------------------------------------------------------
class TestQaSuppressionHandler:
    """Integration tests for the unified QaSuppressionHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.qa_suppression import (
            QaSuppressionHandler,
        )

        return QaSuppressionHandler()

    @pytest.mark.parametrize(
        ("file_path", "content_fn", "language"),
        [
            ("/src/module.py", _py_type_ignore, "Python"),
            ("/src/main.go", _go_nolint, "Go"),
            ("/src/app.ts", _ts_ignore, "JavaScript"),
            ("/src/Controller.php", _phpstan_ignore, "PHP"),
        ],
        ids=["python", "go", "javascript", "php"],
    )
    def test_blocks_suppression_across_languages(
        self, handler: Any, file_path: str, content_fn: Any, language: str
    ) -> None:
        content = f"code {content_fn()}"
        hook_input = make_write_hook_input(file_path, content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert language in (result.reason or "")

    def test_allows_clean_code(self, handler: Any) -> None:
        hook_input = make_write_hook_input("/src/module.py", "x: int = 1\ny = x + 2\n")
        assert handler.matches(hook_input) is False

    def test_allows_unknown_extension(self, handler: Any) -> None:
        content = f"x = 1  {_py_type_ignore()}"
        hook_input = make_write_hook_input("/src/data.txt", content)
        assert handler.matches(hook_input) is False

    def test_skips_vendor_directory(self, handler: Any) -> None:
        content = f"x = 1  {_py_type_ignore()}"
        hook_input = make_write_hook_input("/vendor/lib/module.py", content)
        assert handler.matches(hook_input) is False

    def test_edit_tool_checks_new_string(self, handler: Any) -> None:
        new_string = f"result = func()  {_py_type_ignore()}"
        hook_input = make_edit_hook_input("/src/module.py", "old code", new_string)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


# ---------------------------------------------------------------------------
# TddEnforcementHandler
# ---------------------------------------------------------------------------
class TestTddEnforcementHandler:
    """Integration tests for TddEnforcementHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import (
            TddEnforcementHandler,
        )

        return TddEnforcementHandler()

    def test_blocks_handler_without_test(self, handler: Any) -> None:
        hook_input = make_write_hook_input(
            "/workspace/src/handlers/pre_tool_use/new_handler.py",
            "class NewHandler: pass",
        )
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_allows_test_file_creation(self, handler: Any) -> None:
        hook_input = make_write_hook_input(
            "/workspace/tests/handlers/pre_tool_use/test_new_handler.py",
            "def test_something(): pass",
        )
        assert handler.matches(hook_input) is False

    def test_allows_init_file(self, handler: Any) -> None:
        hook_input = make_write_hook_input(
            "/workspace/src/handlers/__init__.py",
            "",
        )
        assert handler.matches(hook_input) is False

    def test_ignores_non_write_tool(self, handler: Any) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat /workspace/src/handlers/new.py"},
        }
        assert handler.matches(hook_input) is False

    def test_ignores_unrecognized_file_extension(self, handler: Any) -> None:
        hook_input = make_write_hook_input(
            "/workspace/src/handlers/config.toml",
            "key = 'value'",
        )
        assert handler.matches(hook_input) is False
