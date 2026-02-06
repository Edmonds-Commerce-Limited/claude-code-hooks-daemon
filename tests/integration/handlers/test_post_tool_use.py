"""Integration tests for PostToolUse handlers.

Tests: BashErrorDetectorHandler, ValidateEslintOnWriteHandler,
       ValidateSitemapHandler
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import (
    make_post_tool_bash_input,
    make_post_tool_write_input,
)


# ---------------------------------------------------------------------------
# BashErrorDetectorHandler
# ---------------------------------------------------------------------------
class TestBashErrorDetectorHandler:
    """Integration tests for BashErrorDetectorHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.post_tool_use.bash_error_detector import (
            BashErrorDetectorHandler,
        )

        return BashErrorDetectorHandler()

    @pytest.mark.parametrize(
        ("stdout", "stderr", "interrupted"),
        [
            ("error: file not found", "", False),
            ("", "fatal: not a git repository", False),
            ("Build failed: missing module", "", False),
            ("", "", True),
            ("warning: deprecated API", "", False),
        ],
        ids=["error-stdout", "fatal-stderr", "failed-stdout", "interrupted", "warning"],
    )
    def test_detects_issues(
        self,
        handler: Any,
        stdout: str,
        stderr: str,
        interrupted: bool,
    ) -> None:
        hook_input = make_post_tool_bash_input(
            "some command", stdout=stdout, stderr=stderr, interrupted=interrupted
        )
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context is not None
        assert len(result.context) > 0

    @pytest.mark.parametrize(
        ("stdout", "stderr"),
        [
            ("success: all tests passed", ""),
            ("3 files changed, 10 insertions(+)", ""),
            ("", ""),
        ],
        ids=["success-output", "clean-output", "no-output"],
    )
    def test_silent_on_clean_output(
        self, handler: Any, stdout: str, stderr: str
    ) -> None:
        hook_input = make_post_tool_bash_input("git status", stdout=stdout, stderr=stderr)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        # No context means silent allow
        assert result.context is None or len(result.context) == 0

    def test_non_bash_not_matched(self, handler: Any) -> None:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/test.py", "content": "x = 1"},
        }
        assert handler.matches(hook_input) is False

    def test_handles_missing_tool_response(self, handler: Any) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo test"},
        }
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


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


# ---------------------------------------------------------------------------
# ValidateSitemapHandler
# ---------------------------------------------------------------------------
class TestValidateSitemapHandler:
    """Integration tests for ValidateSitemapHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.post_tool_use.validate_sitemap import (
            ValidateSitemapHandler,
        )

        return ValidateSitemapHandler()

    def test_matches_sitemap_markdown(self, handler: Any) -> None:
        hook_input = make_post_tool_write_input("/workspace/CLAUDE/Sitemap/pages.md")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context is not None
        assert len(result.context) > 0

    def test_ignores_non_sitemap_files(self, handler: Any) -> None:
        hook_input = make_post_tool_write_input("/workspace/src/module.py")
        assert handler.matches(hook_input) is False

    def test_ignores_sitemap_claude_md(self, handler: Any) -> None:
        hook_input = make_post_tool_write_input("/workspace/CLAUDE/Sitemap/CLAUDE.md")
        assert handler.matches(hook_input) is False

    def test_ignores_non_markdown(self, handler: Any) -> None:
        hook_input = make_post_tool_write_input("/workspace/CLAUDE/Sitemap/data.json")
        assert handler.matches(hook_input) is False

    def test_non_write_not_matched(self, handler: Any) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat CLAUDE/Sitemap/pages.md"},
        }
        assert handler.matches(hook_input) is False
