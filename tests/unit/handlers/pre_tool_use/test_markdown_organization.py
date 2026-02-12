"""Tests for MarkdownOrganizationHandler."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext for handler instantiation tests."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


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

    def test_matches_returns_false_for_changelog_md(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows CHANGELOG.md in project root."""
        write_input["tool_input"]["file_path"] = "CHANGELOG.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_releases_directory(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown files in RELEASES/ directory."""
        write_input["tool_input"]["file_path"] = "RELEASES/v2.5.0.md"
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

    def test_matches_returns_false_for_claude_subdirectories(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in any CLAUDE/ subdirectory."""
        test_paths = [
            "CLAUDE/AcceptanceTests/PLAYBOOK.md",
            "CLAUDE/AcceptanceTests/subfolder/test.md",
            "CLAUDE/SomeNewDirectory/document.md",
            "CLAUDE/deep/nested/path/file.md",
        ]
        for path in test_paths:
            write_input["tool_input"]["file_path"] = path
            assert handler.matches(write_input) is False, f"Should allow: {path}"

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

    def test_matches_returns_false_for_daemon_guides(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows markdown in src/claude_code_hooks_daemon/guides/ directory."""
        write_input["tool_input"][
            "file_path"
        ] = "src/claude_code_hooks_daemon/guides/llm-command-wrappers.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_true_for_other_src_markdown(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler still blocks markdown in other src/ locations."""
        write_input["tool_input"]["file_path"] = "src/claude_code_hooks_daemon/other.md"
        assert handler.matches(write_input) is True

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

    def test_matches_returns_false_for_paths_outside_project_root(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler does NOT match writes to paths outside the project root."""
        # Memory directory is outside project root
        write_input["tool_input"][
            "file_path"
        ] = "/root/.claude/projects/-workspace/memory/MEMORY.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_claude_auto_memory(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler does NOT match writes to Claude Code auto memory directory."""
        write_input["tool_input"][
            "file_path"
        ] = "/root/.claude/projects/my-project/memory/MEMORY.md"
        assert handler.matches(write_input) is False

    def test_matches_returns_false_for_memory_path_with_symlink_resolving_into_project(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler allows memory writes even when symlinks resolve into project root.

        Regression test: /root/.claude/ can be a symlink to /workspace/.claude/ccy/,
        causing Path.resolve() to map memory paths into the project root. The handler
        must detect auto-memory paths BEFORE resolve() to prevent false blocking.
        """
        memory_path = "/root/.claude/projects/-workspace/memory/MEMORY.md"
        write_input["tool_input"]["file_path"] = memory_path

        # Simulate symlink: resolve() maps /root/.claude/... -> /tmp/test/.claude/ccy/...
        # which IS under project root /tmp/test, so relative_to would succeed
        resolved_path = Path("/tmp/test/.claude/ccy/projects/-workspace/memory/MEMORY.md")
        with patch.object(Path, "resolve", return_value=resolved_path):
            assert handler.matches(write_input) is False

    def test_matches_returns_false_for_any_absolute_path_outside_project(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler does NOT match writes to any absolute path outside project root."""
        test_paths = [
            "/home/user/notes/test.md",
            "/tmp/scratch.md",
            "/var/log/notes.md",
            "/root/.claude/other-project/doc.md",
        ]
        for path in test_paths:
            write_input["tool_input"]["file_path"] = path
            assert (
                handler.matches(write_input) is False
            ), f"Should NOT match outside-project path: {path}"

    def test_matches_returns_true_for_project_relative_invalid_location(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Handler still matches writes to project-relative markdown in wrong locations."""
        # These paths are under project root but in invalid locations
        write_input["tool_input"]["file_path"] = "/tmp/test/src/invalid.md"
        assert handler.matches(write_input) is True

        write_input["tool_input"]["file_path"] = "/tmp/test/test.md"
        assert handler.matches(write_input) is True


class TestPlanningModeIntegration:
    """Tests for planning mode write interception."""

    @pytest.fixture
    def handler(self, tmp_path: Path) -> MarkdownOrganizationHandler:
        """Create handler with mocked workspace."""
        handler = MarkdownOrganizationHandler()
        # Mock workspace_root to use tmp_path
        handler._workspace_root = tmp_path
        return handler

    @pytest.fixture
    def planning_write_input(self, tmp_path: Path) -> dict[str, Any]:
        """Create sample planning mode Write hook input."""
        # Use tmp_path-based path to avoid filesystem permission errors
        plans_path = tmp_path / "fake_home" / ".claude" / "plans" / "my-awesome-plan.md"
        return {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(plans_path),
                "content": "# My Awesome Plan\n\nThis is a test plan.",
            },
        }

    def test_detects_planning_mode_write_to_claude_plans(
        self, handler: MarkdownOrganizationHandler, planning_write_input: dict[str, Any]
    ) -> None:
        """Handler detects writes to ~/.claude/plans/ as planning mode."""
        assert (
            handler.is_planning_mode_write(planning_write_input["tool_input"]["file_path"]) is True
        )

    def test_detects_planning_mode_with_various_home_paths(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Handler detects planning mode writes across different home path formats."""
        paths = [
            "/home/user/.claude/plans/plan.md",
            "/Users/bob/.claude/plans/another-plan.md",
            "~/.claude/plans/test.md",
            "/root/.claude/plans/root-plan.md",
        ]
        for path in paths:
            assert handler.is_planning_mode_write(path) is True

    def test_does_not_detect_planning_mode_for_other_claude_paths(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Handler does not detect other .claude paths as planning mode."""
        paths = [
            "/home/user/.claude/agents/test.md",
            "/home/user/.claude/commands/deploy.md",
            "/home/user/.claude/skills/skill.md",
            "/workspace/.claude/hooks-daemon.yaml",
        ]
        for path in paths:
            assert handler.is_planning_mode_write(path) is False

    def test_does_not_detect_planning_mode_for_project_plan_paths(
        self, handler: MarkdownOrganizationHandler
    ) -> None:
        """Handler does not detect project CLAUDE/Plan paths as planning mode."""
        paths = [
            "/workspace/CLAUDE/Plan/00001-test/PLAN.md",
            "CLAUDE/Plan/00002-another/notes.md",
        ]
        for path in paths:
            assert handler.is_planning_mode_write(path) is False

    def test_matches_returns_true_for_planning_mode_write_when_feature_enabled(
        self, handler: MarkdownOrganizationHandler, planning_write_input: dict[str, Any]
    ) -> None:
        """Handler matches planning mode writes when feature is enabled."""
        handler._track_plans_in_project = "CLAUDE/Plan"
        assert handler.matches(planning_write_input) is True

    def test_matches_returns_false_for_planning_mode_write_when_feature_disabled(
        self, handler: MarkdownOrganizationHandler, planning_write_input: dict[str, Any]
    ) -> None:
        """Handler does not match planning mode writes when feature is disabled."""
        handler._track_plans_in_project = None
        # When disabled, planning mode writes go through normal validation
        # and would be denied as wrong location (outside project)
        # But matches() should return False for planning mode detection
        assert (
            handler.is_planning_mode_write(planning_write_input["tool_input"]["file_path"]) is True
        )
        # Even though it's a planning mode write, if feature is disabled, handler should not intercept it

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization.get_next_plan_number"
    )
    def test_handle_creates_plan_folder_and_writes_plan_md(
        self,
        mock_get_next: MagicMock,
        handler: MarkdownOrganizationHandler,
        planning_write_input: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Handler creates numbered plan folder and writes PLAN.md."""
        handler._track_plans_in_project = "CLAUDE/Plan"
        mock_get_next.return_value = "00001"

        # Create CLAUDE/Plan directory
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)

        result = handler.handle(planning_write_input)

        # Should allow the write (we handled it)
        assert result.decision == Decision.ALLOW

        # Should create plan folder
        created_folder = plan_dir / "00001-my-awesome-plan"
        assert created_folder.exists()
        assert created_folder.is_dir()

        # Should write PLAN.md
        plan_file = created_folder / "PLAN.md"
        assert plan_file.exists()
        content = plan_file.read_text()
        assert "# My Awesome Plan" in content

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization.get_next_plan_number"
    )
    def test_handle_creates_stub_redirect_file(
        self,
        mock_get_next: MagicMock,
        handler: MarkdownOrganizationHandler,
        planning_write_input: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Handler creates stub redirect at original planning mode location."""
        handler._track_plans_in_project = "CLAUDE/Plan"
        mock_get_next.return_value = "00001"

        # Create directories
        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)

        # Create the original location
        original_path = Path(planning_write_input["tool_input"]["file_path"])
        original_path.parent.mkdir(parents=True, exist_ok=True)

        handler.handle(planning_write_input)

        # Should create stub file at original location
        assert original_path.exists()
        stub_content = original_path.read_text()
        assert "This plan has been moved to the project" in stub_content
        assert "00001-my-awesome-plan" in stub_content
        # Should include rename instructions
        assert "MUST rename this folder" in stub_content
        assert "00001-descriptive-name" in stub_content
        assert "Keep the plan number prefix (00001-) intact" in stub_content

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization.get_next_plan_number"
    )
    def test_handle_sanitizes_plan_folder_name(
        self,
        mock_get_next: MagicMock,
        handler: MarkdownOrganizationHandler,
        planning_write_input: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Handler sanitizes folder name from plan filename."""
        handler._track_plans_in_project = "CLAUDE/Plan"
        mock_get_next.return_value = "00001"

        # Use a filename with special characters
        planning_write_input["tool_input"][
            "file_path"
        ] = "/home/user/.claude/plans/My Plan: (with special chars!).md"

        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)

        handler.handle(planning_write_input)

        # Should sanitize folder name
        created_folder = plan_dir / "00001-my-plan-with-special-chars"
        assert created_folder.exists()

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization.get_next_plan_number"
    )
    def test_handle_returns_context_with_folder_location(
        self,
        mock_get_next: MagicMock,
        handler: MarkdownOrganizationHandler,
        planning_write_input: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Handler returns context informing Claude of new location."""
        handler._track_plans_in_project = "CLAUDE/Plan"
        mock_get_next.return_value = "00001"

        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)

        result = handler.handle(planning_write_input)

        assert result.decision == Decision.ALLOW
        assert result.context is not None
        assert len(result.context) > 0
        context_text = result.context[0]
        assert "00001-my-awesome-plan" in context_text
        assert "CLAUDE/Plan/" in context_text

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization.get_next_plan_number"
    )
    def test_handle_handles_folder_collision_with_suffix(
        self,
        mock_get_next: MagicMock,
        handler: MarkdownOrganizationHandler,
        planning_write_input: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Handler adds -2 suffix if folder name collides (same plan name, same number)."""
        handler._track_plans_in_project = "CLAUDE/Plan"
        # Mock returns 00002, but folder 00002-my-awesome-plan already exists
        mock_get_next.return_value = "00002"

        plan_dir = tmp_path / "CLAUDE" / "Plan"
        plan_dir.mkdir(parents=True)

        # Create existing folder with the name we'll try to create
        existing_folder = plan_dir / "00002-my-awesome-plan"
        existing_folder.mkdir()

        result = handler.handle(planning_write_input)

        # Should create folder with -2 suffix (same number, different suffix)
        created_folder = plan_dir / "00002-my-awesome-plan-2"
        assert created_folder.exists()
        assert result.decision == Decision.ALLOW

    @patch(
        "claude_code_hooks_daemon.handlers.pre_tool_use.markdown_organization.get_next_plan_number"
    )
    def test_handle_fails_gracefully_on_file_not_found_error(
        self,
        mock_get_next: MagicMock,
        handler: MarkdownOrganizationHandler,
        planning_write_input: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        """Handler returns DENY with clear message when plan directory doesn't exist."""
        handler._track_plans_in_project = "CLAUDE/Plan"
        # Mock raises FileNotFoundError
        mock_get_next.side_effect = FileNotFoundError("Plan directory does not exist")

        result = handler.handle(planning_write_input)

        # Should return DENY with error message
        assert result.decision == Decision.DENY
        assert "does not exist" in result.reason.lower() or "not found" in result.reason.lower()


class TestMonorepoSupport:
    """Tests for monorepo sub-project markdown organization.

    In a monorepo, sub-projects at paths like packages/frontend/ may have
    their own CLAUDE/Plan/ structures. This requires explicit config to
    designate the repo as a monorepo.
    """

    @pytest.fixture
    def handler(self, tmp_path: Path) -> MarkdownOrganizationHandler:
        """Create handler with monorepo config."""
        handler = MarkdownOrganizationHandler()
        handler._workspace_root = tmp_path
        return handler

    @pytest.fixture
    def write_input(self) -> dict[str, Any]:
        """Create sample Write hook input."""
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": "", "content": "Test content"},
        }

    # ── Sub-project CLAUDE/ paths should be ALLOWED when monorepo enabled ──

    def test_allows_subproject_claude_plan_with_monorepo_config(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Sub-project CLAUDE/Plan/ paths allowed when monorepo patterns configured."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "packages/frontend/CLAUDE/Plan/00001-foo/PLAN.md"
        assert handler.matches(write_input) is False  # Allowed

    def test_allows_subproject_claude_root_with_monorepo_config(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Sub-project CLAUDE/ root files allowed when monorepo patterns configured."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "packages/backend/CLAUDE/ARCHITECTURE.md"
        assert handler.matches(write_input) is False  # Allowed

    def test_allows_subproject_docs_with_monorepo_config(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Sub-project docs/ paths allowed when monorepo patterns configured."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "packages/frontend/docs/setup.md"
        assert handler.matches(write_input) is False  # Allowed

    def test_allows_subproject_untracked_with_monorepo_config(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Sub-project untracked/ paths allowed when monorepo patterns configured."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "packages/frontend/untracked/scratch.md"
        assert handler.matches(write_input) is False  # Allowed

    def test_allows_subproject_releases_with_monorepo_config(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Sub-project RELEASES/ paths allowed when monorepo patterns configured."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "packages/api/RELEASES/v1.0.0.md"
        assert handler.matches(write_input) is False  # Allowed

    # ── Sub-project invalid paths should still be BLOCKED ──

    def test_blocks_subproject_invalid_location_with_monorepo_config(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Sub-project markdown in invalid locations still blocked in monorepo mode."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "packages/frontend/random/notes.md"
        assert handler.matches(write_input) is True  # Blocked

    def test_blocks_subproject_plan_without_number(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Sub-project plans without numeric prefix still blocked in monorepo mode."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "packages/frontend/CLAUDE/Plan/no-number/PLAN.md"
        assert handler.matches(write_input) is True  # Blocked

    # ── Without monorepo config, sub-project paths should be BLOCKED ──

    def test_subproject_without_monorepo_config_falls_through_to_normalize(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Without monorepo config, paths fall through to normalize_path.

        normalize_path strips to the first project marker (CLAUDE/, src/, etc.),
        so paths containing these markers are accidentally allowed. This is
        existing behavior we preserve for backward compatibility. The monorepo
        config is needed for paths that DON'T contain markers (e.g. RELEASES/).
        """
        # No _monorepo_subproject_patterns set (default None)
        # CLAUDE/ marker in path means normalize_path strips to CLAUDE/Plan/...
        write_input["tool_input"]["file_path"] = "packages/frontend/CLAUDE/Plan/00001-foo/PLAN.md"
        assert handler.matches(write_input) is False  # Allowed (via marker stripping)

        # But RELEASES/ is NOT in normalize_path markers, so it's blocked
        write_input["tool_input"]["file_path"] = "packages/api/RELEASES/v1.0.0.md"
        assert handler.matches(write_input) is True  # Blocked (no marker match)

    # ── Multiple patterns ──

    def test_allows_multiple_subproject_patterns(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Multiple monorepo patterns all work."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+", r"apps/[^/]+"]

        write_input["tool_input"]["file_path"] = "packages/frontend/CLAUDE/test.md"
        assert handler.matches(write_input) is False  # Allowed

        write_input["tool_input"]["file_path"] = "apps/web/CLAUDE/test.md"
        assert handler.matches(write_input) is False  # Allowed

    # ── Nested depth patterns ──

    def test_allows_deeper_subproject_patterns(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Deeper monorepo patterns work (e.g. org/team/project)."""
        handler._monorepo_subproject_patterns = [r"org/[^/]+/[^/]+"]
        write_input["tool_input"]["file_path"] = "org/myteam/myapp/CLAUDE/Plan/00001-foo/PLAN.md"
        assert handler.matches(write_input) is False  # Allowed

    # ── Non-matching paths unaffected ──

    def test_monorepo_config_does_not_affect_root_project_paths(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Root-level CLAUDE/ paths still work when monorepo config is set."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "CLAUDE/Plan/00001-foo/PLAN.md"
        assert handler.matches(write_input) is False  # Allowed (root project)

    def test_monorepo_config_does_not_affect_unmatched_paths(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """Paths not matching monorepo patterns still blocked normally."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "other/directory/notes.md"
        assert handler.matches(write_input) is True  # Blocked

    # ── CLAUDE.md and README.md in sub-projects ──

    def test_allows_subproject_claude_md_with_monorepo_config(
        self, handler: MarkdownOrganizationHandler, write_input: dict[str, Any]
    ) -> None:
        """CLAUDE.md in sub-projects allowed (already allowed anywhere via adhoc check)."""
        handler._monorepo_subproject_patterns = [r"packages/[^/]+"]
        write_input["tool_input"]["file_path"] = "packages/frontend/CLAUDE.md"
        assert handler.matches(write_input) is False  # Allowed
