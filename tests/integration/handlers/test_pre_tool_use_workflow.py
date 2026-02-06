"""Integration tests for PreToolUse workflow handlers.

Tests: NpmCommandHandler, GhIssueCommentsHandler, GlobalNpmAdvisorHandler,
       WebSearchYearHandler, BritishEnglishHandler, PlanTimeEstimatesHandler
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from tests.integration.handlers.conftest import (
    make_bash_hook_input,
    make_web_search_input,
    make_write_hook_input,
)


# ---------------------------------------------------------------------------
# NpmCommandHandler
# ---------------------------------------------------------------------------
class TestNpmCommandHandler:
    """Integration tests for NpmCommandHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.npm_command import (
            NpmCommandHandler,
        )

        return NpmCommandHandler()

    @pytest.mark.parametrize(
        "command",
        [
            "npm run build",
            "npm run lint",
            "npm run test",
            "npm run format",
        ],
        ids=["build", "lint", "test", "format"],
    )
    def test_blocks_non_llm_npm_commands(self, handler: Any, command: str) -> None:
        hook_input = make_bash_hook_input(command)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "llm:" in result.reason

    @pytest.mark.parametrize(
        "command",
        [
            "npm run llm:build",
            "npm run llm:lint",
            "npm run llm:test",
            "npm run clean",
        ],
        ids=["llm-build", "llm-lint", "llm-test", "clean-allowed"],
    )
    def test_allows_llm_prefixed_commands(self, handler: Any, command: str) -> None:
        hook_input = make_bash_hook_input(command)
        assert handler.matches(hook_input) is False

    def test_blocks_npx_with_llm_equivalent(self, handler: Any) -> None:
        hook_input = make_bash_hook_input("npx tsc --noEmit")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_blocks_piped_npm_commands(self, handler: Any) -> None:
        hook_input = make_bash_hook_input("npm run llm:build | grep error")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_non_npm_command_not_matched(self, handler: Any) -> None:
        hook_input = make_bash_hook_input("git status")
        assert handler.matches(hook_input) is False


# ---------------------------------------------------------------------------
# GhIssueCommentsHandler
# ---------------------------------------------------------------------------
class TestGhIssueCommentsHandler:
    """Integration tests for GhIssueCommentsHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.gh_issue_comments import (
            GhIssueCommentsHandler,
        )

        return GhIssueCommentsHandler()

    @pytest.mark.parametrize(
        "command",
        [
            "gh issue view 123",
            "gh issue view 456 --repo owner/repo",
            "gh issue view 789 --json title,body",
        ],
        ids=["simple-view", "with-repo", "json-without-comments"],
    )
    def test_blocks_gh_issue_view_without_comments(self, handler: Any, command: str) -> None:
        hook_input = make_bash_hook_input(command)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "--comments" in result.reason

    @pytest.mark.parametrize(
        "command",
        [
            "gh issue view 123 --comments",
            "gh issue view 123 --json title,body,comments",
            "gh issue list",
            "gh pr view 123",
        ],
        ids=["with-comments", "json-with-comments", "issue-list", "pr-not-issue"],
    )
    def test_allows_commands_with_comments(self, handler: Any, command: str) -> None:
        hook_input = make_bash_hook_input(command)
        assert handler.matches(hook_input) is False

    def test_non_bash_not_matched(self, handler: Any) -> None:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/test.py", "content": "gh issue view 1"},
        }
        assert handler.matches(hook_input) is False


# ---------------------------------------------------------------------------
# GlobalNpmAdvisorHandler
# ---------------------------------------------------------------------------
class TestGlobalNpmAdvisorHandler:
    """Integration tests for GlobalNpmAdvisorHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.global_npm_advisor import (
            GlobalNpmAdvisorHandler,
        )

        return GlobalNpmAdvisorHandler()

    @pytest.mark.parametrize(
        "command",
        [
            "npm install -g typescript",
            "npm i -g eslint",
            "yarn global add prettier",
        ],
        ids=["npm-install-g", "npm-i-g", "yarn-global-add"],
    )
    def test_matches_global_installs(self, handler: Any, command: str) -> None:
        hook_input = make_bash_hook_input(command)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        # Advisory - allows but with context
        assert result.decision == Decision.ALLOW
        assert len(result.context) > 0

    @pytest.mark.parametrize(
        "command",
        [
            "npm install typescript",
            "npm i eslint --save-dev",
            "yarn add prettier",
        ],
        ids=["npm-local", "npm-save-dev", "yarn-local"],
    )
    def test_ignores_local_installs(self, handler: Any, command: str) -> None:
        hook_input = make_bash_hook_input(command)
        assert handler.matches(hook_input) is False

    def test_non_bash_not_matched(self, handler: Any) -> None:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/x.sh", "content": "npm install -g pkg"},
        }
        assert handler.matches(hook_input) is False


# ---------------------------------------------------------------------------
# WebSearchYearHandler
# ---------------------------------------------------------------------------
class TestWebSearchYearHandler:
    """Integration tests for WebSearchYearHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.web_search_year import (
            WebSearchYearHandler,
        )

        return WebSearchYearHandler()

    def test_matches_outdated_year(self, handler: Any) -> None:
        hook_input = make_web_search_input("React best practices 2023")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context is not None
        assert len(result.context) > 0

    def test_allows_current_year(self, handler: Any) -> None:
        from datetime import datetime

        current_year = datetime.now().year
        hook_input = make_web_search_input(f"Python tutorial {current_year}")
        assert handler.matches(hook_input) is False

    def test_allows_no_year(self, handler: Any) -> None:
        hook_input = make_web_search_input("Python asyncio tutorial")
        assert handler.matches(hook_input) is False

    def test_non_websearch_not_matched(self, handler: Any) -> None:
        hook_input = make_bash_hook_input("echo 2023")
        assert handler.matches(hook_input) is False


# ---------------------------------------------------------------------------
# BritishEnglishHandler
# ---------------------------------------------------------------------------
class TestBritishEnglishHandler:
    """Integration tests for BritishEnglishHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.british_english import (
            BritishEnglishHandler,
        )

        return BritishEnglishHandler()

    @pytest.mark.parametrize(
        "content",
        [
            "The color of the text",
            "Please organize the files",
            "The center of the page",
        ],
        ids=["color", "organize", "center"],
    )
    def test_matches_american_spellings(self, handler: Any, content: str) -> None:
        hook_input = make_write_hook_input("/docs/guide.md", content)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        # Advisory - allows but with guidance
        assert result.decision == Decision.ALLOW

    def test_allows_british_spellings(self, handler: Any) -> None:
        hook_input = make_write_hook_input(
            "/docs/guide.md", "The colour of the text is organised by the centre."
        )
        assert handler.matches(hook_input) is False

    def test_ignores_non_content_files(self, handler: Any) -> None:
        hook_input = make_write_hook_input("/src/module.py", "color = 'red'")
        assert handler.matches(hook_input) is False

    def test_ignores_non_content_directories(self, handler: Any) -> None:
        hook_input = make_write_hook_input("/random/dir/guide.md", "The color is red.")
        assert handler.matches(hook_input) is False

    def test_skips_code_blocks(self, handler: Any) -> None:
        content = "# Guide\n\n```python\ncolor = 'red'\n```\n\nText here."
        hook_input = make_write_hook_input("/docs/guide.md", content)
        # Should not match because 'color' is inside a code block
        assert handler.matches(hook_input) is False


# ---------------------------------------------------------------------------
# PlanTimeEstimatesHandler
# ---------------------------------------------------------------------------
class TestPlanTimeEstimatesHandler:
    """Integration tests for PlanTimeEstimatesHandler."""

    @pytest.fixture()
    def handler(self) -> Any:
        from claude_code_hooks_daemon.handlers.pre_tool_use.plan_time_estimates import (
            PlanTimeEstimatesHandler,
        )

        return PlanTimeEstimatesHandler()

    def test_blocks_time_estimates_in_plan(self, handler: Any) -> None:
        content = "## Tasks\n\nThis should take approximately 2 hours to complete.\n"
        hook_input = make_write_hook_input("/workspace/CLAUDE/Plan/00001-test/PLAN.md", content)
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == Decision.DENY

    def test_allows_plan_without_time_estimates(self, handler: Any) -> None:
        content = "## Tasks\n\n- [ ] Task 1: Implement feature\n- [ ] Task 2: Write tests\n"
        hook_input = make_write_hook_input("/workspace/CLAUDE/Plan/00001-test/PLAN.md", content)
        assert handler.matches(hook_input) is False

    def test_ignores_non_plan_files(self, handler: Any) -> None:
        content = "This task takes about 3 hours.\n"
        hook_input = make_write_hook_input("/workspace/README.md", content)
        assert handler.matches(hook_input) is False
