"""Integration tests for PostToolUse handlers.

Tests: ValidateEslintOnWriteHandler
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.handlers.conftest import make_post_tool_write_input


# ---------------------------------------------------------------------------
# ValidateEslintOnWriteHandler
# ---------------------------------------------------------------------------
class TestValidateEslintOnWriteHandler:
    """Integration tests for ValidateEslintOnWriteHandler."""

    @pytest.fixture()
    def handler(self, tmp_path: Any) -> Any:
        from claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write import (
            ValidateEslintOnWriteHandler,
        )

        return ValidateEslintOnWriteHandler(workspace_root=tmp_path)

    def test_matches_typescript_write(self, handler: Any, tmp_path: Any) -> None:
        ts_file = tmp_path / "src" / "app.ts"
        ts_file.parent.mkdir(parents=True, exist_ok=True)
        ts_file.write_text("const x = 1;")
        hook_input = make_post_tool_write_input(str(ts_file))
        assert handler.matches(hook_input) is True

    def test_matches_tsx_write(self, handler: Any, tmp_path: Any) -> None:
        tsx_file = tmp_path / "src" / "Component.tsx"
        tsx_file.parent.mkdir(parents=True, exist_ok=True)
        tsx_file.write_text("export default function App() { return <div/>; }")
        hook_input = make_post_tool_write_input(str(tsx_file))
        assert handler.matches(hook_input) is True

    def test_ignores_non_typescript(self, handler: Any) -> None:
        hook_input = make_post_tool_write_input("/src/module.py")
        assert handler.matches(hook_input) is False

    def test_skips_node_modules(self, handler: Any, tmp_path: Any) -> None:
        nm_file = tmp_path / "node_modules" / "pkg" / "index.ts"
        nm_file.parent.mkdir(parents=True, exist_ok=True)
        nm_file.write_text("const x = 1;")
        hook_input = make_post_tool_write_input(str(nm_file))
        assert handler.matches(hook_input) is False

    def test_skips_dist(self, handler: Any) -> None:
        hook_input = make_post_tool_write_input("/project/dist/bundle.ts")
        assert handler.matches(hook_input) is False
