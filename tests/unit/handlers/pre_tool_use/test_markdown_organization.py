"""Tests for MarkdownOrganizationHandler."""

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization import (
    MarkdownOrganizationHandler,
)


class TestMarkdownOrganizationHandler:
    """Tests for MarkdownOrganizationHandler."""

    @pytest.fixture
    def handler(self) -> MarkdownOrganizationHandler:
        """Create handler instance."""
        return MarkdownOrganizationHandler()

    @pytest.fixture
    def write_input(self) -> dict[str, Any]:
        """Create sample Write hook input."""
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/test.md", "content": "Test content"},
        }

    def test_init_creates_handler_with_correct_attributes(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Handler initializes with correct name and priority."""
        assert handler.name == "enforce-markdown-organization"
        assert handler.priority == 35
        assert "workflow" in handler.tags
        assert "markdown" in handler.tags
        assert "terminal" in handler.tags
        assert handler.terminal is True

    def test_normalize_path_strips_leading_slash(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Normalize path strips leading slash."""
        result = handler.normalize_path("/CLAUDE/test.md")
        assert result == "CLAUDE/test.md"

    def test_normalize_path_handles_workspace_prefix(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Normalize path removes workspace/ prefix."""
        result = handler.normalize_path("workspace/CLAUDE/test.md")
        assert result == "CLAUDE/test.md"

    def test_normalize_path_handles_absolute_paths_with_project_markers(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Normalize path finds project markers and strips prefix."""
        result = handler.normalize_path("/home/user/project/CLAUDE/test.md")
        assert result == "CLAUDE/test.md"

    def test_normalize_path_returns_empty_for_empty_input(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Normalize path returns empty string for empty input."""
        result = handler.normalize_path("")
        assert result == ""

    def test_is_adhoc_instruction_file_returns_true_for_claude_md(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """CLAUDE.md is recognized as ad-hoc instruction file."""
        assert handler.is_adhoc_instruction_file("CLAUDE.md") is True
        assert handler.is_adhoc_instruction_file("/workspace/CLAUDE.md") is True

    def test_is_adhoc_instruction_file_returns_true_for_readme_md(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """README.md is recognized as ad-hoc instruction file."""
        assert handler.is_adhoc_instruction_file("README.md") is True
        assert handler.is_adhoc_instruction_file("/workspace/src/README.md") is True

    def test_is_adhoc_instruction_file_returns_true_for_skill_md_in_skills(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """SKILL.md in .claude/skills/ is recognized as ad-hoc instruction file."""
        assert handler.is_adhoc_instruction_file(".claude/skills/test/SKILL.md") is True
        assert handler.is_adhoc_instruction_file("/workspace/.claude/skills/test/SKILL.md") is True

    def test_is_adhoc_instruction_file_returns_false_for_skill_md_elsewhere(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """SKILL.md outside .claude/skills/ is not recognized as ad-hoc instruction file."""
        assert handler.is_adhoc_instruction_file("SKILL.md") is False
        assert handler.is_adhoc_instruction_file("CLAUDE/SKILL.md") is False

    def test_is_adhoc_instruction_file_returns_true_for_agent_files(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Agent definition files in .claude/agents/ are recognized."""
        assert handler.is_adhoc_instruction_file(".claude/agents/test.md") is True
        assert handler.is_adhoc_instruction_file("/workspace/.claude/agents/python.md") is True

    def test_is_adhoc_instruction_file_returns_true_for_command_files(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Command definition files in .claude/commands/ are recognized."""
        assert handler.is_adhoc_instruction_file(".claude/commands/test.md") is True
        assert handler.is_adhoc_instruction_file("/workspace/.claude/commands/deploy.md") is True

    def test_is_page_colocated_file_returns_true_for_research_files(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Research files in src/pages/ are recognized."""
        assert handler.is_page_colocated_file("src/pages/test-research.md") is True
        assert handler.is_page_colocated_file("src/pages/subfolder/test-research.md") is True

    def test_is_page_colocated_file_returns_true_for_rules_files(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Rules files in src/pages/ are recognized."""
        assert handler.is_page_colocated_file("src/pages/test-rules.md") is True
        assert handler.is_page_colocated_file("src/pages/subfolder/test-rules.md") is True

    def test_is_page_colocated_file_returns_true_for_article_files(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Article files in src/pages/articles/ are recognized."""
        assert (
            handler.is_page_colocated_file("src/pages/articles/subfolder/article-test-slug.md")
            is True
        )

    def test_is_page_colocated_file_returns_false_for_non_matching(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Non-matching files are not recognized as page co-located."""
        assert handler.is_page_colocated_file("src/pages/test.md") is False
        assert handler.is_page_colocated_file("src/test-research.md") is False

    def test_matches_returns_false_for_non_write_edit_tools(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Handler does not match non-Write/Edit tools."""
        input_data = {"tool_name": "Bash", "tool_input": {"command": "echo test"}}
        assert handler.matches(input_data) is False

    def test_matches_returns_false_for_non_markdown_files(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Handler does not match non-markdown files."""
        input_data = {"tool_name": "Write", "tool_input": {"file_path": "test.txt"}}
        assert handler.matches(input_data) is False

    def test_matches_returns_false_for_claude_md(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows CLAUDE.md anywhere."""
        write_input["tool_input"]["file_path"] = "/workspace/CLAUDE.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_readme_md(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows README.md anywhere."""
        write_input["tool_input"]["file_path"] = "/workspace/src/README.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_plan_directory(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in CLAUDE/Plan/NNN-*/ directories."""
        write_input["tool_input"]["file_path"] = "CLAUDE/Plan/066-test-plan/PLAN.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_claude_root_level(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in CLAUDE/ root level."""
        write_input["tool_input"]["file_path"] = "CLAUDE/test.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_claude_research(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in CLAUDE/research/."""
        write_input["tool_input"]["file_path"] = "CLAUDE/research/test.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_claude_sitemap(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in CLAUDE/Sitemap/."""
        write_input["tool_input"]["file_path"] = "CLAUDE/Sitemap/test.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_docs_directory(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in docs/ directory."""
        write_input["tool_input"]["file_path"] = "docs/test.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_untracked_directory(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in untracked/ directory."""
        write_input["tool_input"]["file_path"] = "untracked/test.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_eslint_rules(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in eslint-rules/ directory."""
        write_input["tool_input"]["file_path"] = "eslint-rules/test.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_page_colocated_files(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows page co-located files (*-research.md, *-rules.md, article-*.md)."""
        write_input["tool_input"]["file_path"] = "src/pages/test-research.md"
        assert handler.matches(write_input) is False

        write_input["tool_input"]["file_path"] = "src/pages/test-rules.md"
        assert handler.matches(write_input) is False

        write_input["tool_input"]["file_path"] = "src/pages/articles/subfolder/article-test.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_true_for_invalid_location(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler matches markdown in invalid location."""
        write_input["tool_input"]["file_path"] = "src/invalid.md"
        assert handler.matches(write_input) is True

    def test_matches_returns_true_for_root_level_invalid(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler matches markdown at project root (invalid)."""
        write_input["tool_input"]["file_path"] = "test.md"
        assert handler.matches(write_input) is True

    def test_handle_returns_deny_with_reason(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler denies with helpful reason message."""
        write_input["tool_input"]["file_path"] = "src/invalid.md"
        result = handler.handle(write_input)
        assert result.decision == Decision.DENY
        assert "MARKDOWN FILE IN WRONG LOCATION" in result.reason
        assert "src/invalid.md" in result.reason
        assert "CLAUDE/Plan" in result.reason
        assert "docs/" in result.reason
