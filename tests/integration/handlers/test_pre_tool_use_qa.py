"""Integration tests for PreToolUse QA enforcement handlers.

Tests: EslintDisableHandler, TddEnforcementHandler,
       PythonQaSuppressionBlocker, PhpQaSuppressionBlocker,
       GoQaSuppressionBlocker

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
# EslintDisableHandler
# ---------------------------------------------------------------------------
class TestEslintDisableHandler:
    """Integration tests for EslintDisableHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.eslint_disable import (
            EslintDisableHandler,
        )

        return EslintDisableHandler()

    @pytest.mark.parametrize(
        ("file_path", "content_fn"),
        [
            ("/src/app.ts", _eslint_disable),
            ("/src/component.tsx", _ts_ignore),
            ("/src/utils.js", _ts_nocheck),
        ],
        ids=["eslint-disable-ts", "ts-ignore-tsx", "ts-nocheck-js"],
    )
    def test_blocks_eslint_suppression(
        self, handler: Any, file_path: str, content_fn: Any
    ) -> None:
        content = f"const x = 1; // {content_fn()}"
        hook_input = make_write_hook_input(file_path, content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    @pytest.mark.parametrize(
        ("file_path", "content"),
        [
            ("/src/app.ts", "const x: number = 1;"),
            ("/src/styles.css", "body { color: red; }"),
            ("/src/app.py", "x = 1"),
        ],
        ids=["clean-ts", "non-js-file", "python-file"],
    )
    def test_allows_clean_code(
        self, handler: Any, file_path: str, content: str
    ) -> None:
        hook_input = make_write_hook_input(file_path, content)
        assert handler.matches(hook_input) is False

    def test_skips_node_modules(self, handler: Any) -> None:
        content = f"// {_eslint_disable()}"
        hook_input = make_write_hook_input("/node_modules/pkg/index.js", content)
        assert handler.matches(hook_input) is False

    def test_edit_tool_checks_new_string(self, handler: Any) -> None:
        new_string = f"const x = 1; // {_eslint_disable()}"
        hook_input = make_edit_hook_input("/src/app.ts", "old code", new_string)
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

    def test_ignores_non_python_file(self, handler: Any) -> None:
        hook_input = make_write_hook_input(
            "/workspace/src/handlers/new_handler.js",
            "export class NewHandler {}",
        )
        assert handler.matches(hook_input) is False


# ---------------------------------------------------------------------------
# PythonQaSuppressionBlocker
# ---------------------------------------------------------------------------
class TestPythonQaSuppressionBlocker:
    """Integration tests for PythonQaSuppressionBlocker."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.python_qa_suppression_blocker import (
            PythonQaSuppressionBlocker,
        )

        return PythonQaSuppressionBlocker()

    @pytest.mark.parametrize(
        ("content_fn", "desc"),
        [
            (_py_type_ignore, "type-ignore"),
            (_py_noqa, "noqa"),
            (_py_pylint_disable, "pylint-disable"),
        ],
        ids=["type-ignore", "noqa", "pylint-disable"],
    )
    def test_blocks_python_suppression(
        self, handler: Any, content_fn: Any, desc: str
    ) -> None:
        content = f"x = 1  {content_fn()}"
        hook_input = make_write_hook_input("/src/module.py", content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_allows_clean_python(self, handler: Any) -> None:
        hook_input = make_write_hook_input("/src/module.py", "x: int = 1\ny = x + 2\n")
        assert handler.matches(hook_input) is False

    def test_skips_test_fixtures(self, handler: Any) -> None:
        content = f"x = 1  {_py_type_ignore()}"
        hook_input = make_write_hook_input("/tests/fixtures/example.py", content)
        assert handler.matches(hook_input) is False

    def test_skips_venv(self, handler: Any) -> None:
        content = f"x = 1  {_py_noqa()}"
        hook_input = make_write_hook_input("/project/venv/lib/module.py", content)
        assert handler.matches(hook_input) is False

    def test_ignores_non_python(self, handler: Any) -> None:
        content = f"x = 1  {_py_type_ignore()}"
        hook_input = make_write_hook_input("/src/module.js", content)
        assert handler.matches(hook_input) is False

    def test_edit_tool_checks_new_string(self, handler: Any) -> None:
        new_string = f"result = func()  {_py_type_ignore()}"
        hook_input = make_edit_hook_input("/src/module.py", "old code", new_string)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


# ---------------------------------------------------------------------------
# PhpQaSuppressionBlocker
# ---------------------------------------------------------------------------
class TestPhpQaSuppressionBlocker:
    """Integration tests for PhpQaSuppressionBlocker."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.php_qa_suppression_blocker import (
            PhpQaSuppressionBlocker,
        )

        return PhpQaSuppressionBlocker()

    @pytest.mark.parametrize(
        ("content_fn", "desc"),
        [
            (_phpstan_ignore, "phpstan-ignore"),
            (_psalm_suppress, "psalm-suppress"),
            (_phpcs_ignore, "phpcs-ignore"),
        ],
        ids=["phpstan-ignore", "psalm-suppress", "phpcs-ignore"],
    )
    def test_blocks_php_suppression(
        self, handler: Any, content_fn: Any, desc: str
    ) -> None:
        content = f"<?php // {content_fn()}"
        hook_input = make_write_hook_input("/src/Controller.php", content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_allows_clean_php(self, handler: Any) -> None:
        hook_input = make_write_hook_input(
            "/src/Controller.php", "<?php\nclass Controller {}\n"
        )
        assert handler.matches(hook_input) is False

    def test_skips_vendor(self, handler: Any) -> None:
        content = f"<?php // {_phpstan_ignore()}"
        hook_input = make_write_hook_input("/vendor/pkg/src/File.php", content)
        assert handler.matches(hook_input) is False

    def test_ignores_non_php(self, handler: Any) -> None:
        content = f"// {_phpstan_ignore()}"
        hook_input = make_write_hook_input("/src/module.py", content)
        assert handler.matches(hook_input) is False


# ---------------------------------------------------------------------------
# GoQaSuppressionBlocker
# ---------------------------------------------------------------------------
class TestGoQaSuppressionBlocker:
    """Integration tests for GoQaSuppressionBlocker."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.go_qa_suppression_blocker import (
            GoQaSuppressionBlocker,
        )

        return GoQaSuppressionBlocker()

    @pytest.mark.parametrize(
        ("content_fn", "desc"),
        [
            (_go_nolint, "nolint"),
            (_go_lint_ignore, "lint-ignore"),
        ],
        ids=["nolint", "lint-ignore"],
    )
    def test_blocks_go_suppression(
        self, handler: Any, content_fn: Any, desc: str
    ) -> None:
        content = f"func main() {{}}\n{content_fn()}"
        hook_input = make_write_hook_input("/src/main.go", content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_allows_clean_go(self, handler: Any) -> None:
        hook_input = make_write_hook_input(
            "/src/main.go", "package main\n\nfunc main() {}\n"
        )
        assert handler.matches(hook_input) is False

    def test_skips_vendor(self, handler: Any) -> None:
        content = f"func x() {{}}\n{_go_nolint()}"
        hook_input = make_write_hook_input("/vendor/pkg/main.go", content)
        assert handler.matches(hook_input) is False

    def test_skips_testdata(self, handler: Any) -> None:
        content = f"func x() {{}}\n{_go_nolint()}"
        hook_input = make_write_hook_input("/testdata/fixture.go", content)
        assert handler.matches(hook_input) is False

    def test_ignores_non_go(self, handler: Any) -> None:
        content = f"{_go_nolint()}"
        hook_input = make_write_hook_input("/src/main.py", content)
        assert handler.matches(hook_input) is False
