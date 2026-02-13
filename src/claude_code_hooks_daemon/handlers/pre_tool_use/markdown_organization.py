"""MarkdownOrganizationHandler - enforces markdown file organization rules."""

import logging
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.handlers.utils.plan_numbering import get_next_plan_number

logger = logging.getLogger(__name__)

# Known CLAUDE/Plan/ subdirectories that should allow nested plan folders
_PLAN_SUBDIRECTORIES: Final[tuple[str, ...]] = ("completed", "cancelled", "archive")


class MarkdownOrganizationHandler(Handler):
    """Enforce markdown file organization rules.

    CRITICAL: This handler must match legacy hook behavior EXACTLY.
    Cannot use simple 'in' checks - must use precise pattern matching.

    Additionally intercepts Claude Code planning mode writes (~/.claude/plans/)
    and redirects them to project CLAUDE/Plan/ structure when enabled.
    """

    def __init__(self) -> None:
        """Initialize handler.

        Configuration is read from handler options:
        - track_plans_in_project: str | None - Path to plan folder (e.g., "CLAUDE/Plan") or null to disable
        - plan_workflow_docs: str | None (optional) - Path to workflow doc file (e.g., "CLAUDE/PlanWorkflow.md")
        """
        super().__init__(
            handler_id=HandlerID.MARKDOWN_ORGANIZATION,
            priority=Priority.MARKDOWN_ORGANIZATION,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.MARKDOWN,
                HandlerTag.EC_SPECIFIC,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )
        # Configuration attributes (set by registry after instantiation)
        self._workspace_root: Path = ProjectContext.project_root()
        self._track_plans_in_project: str | None = None  # Path to plan folder or None
        self._plan_workflow_docs: str | None = None  # Path to workflow doc or None
        self._monorepo_subproject_patterns: list[str] | None = (
            None  # Regex patterns for sub-projects
        )
        self._allowed_markdown_paths: list[str] | None = None  # Regex patterns for allowed paths

    def normalize_path(self, file_path: str) -> str:
        """Normalize file path to project-relative format.

        Handles both test paths and real absolute paths.
        Strips everything before known project markers.
        """
        if not file_path:
            return ""

        # Strip leading slash first
        normalized = file_path.lstrip("/")

        # Remove test environment prefix patterns
        workspace_patterns = ["workspace/", "workspace\\"]
        for pattern in workspace_patterns:
            if normalized.startswith(pattern):
                normalized = normalized[len(pattern) :]
                return normalized

        # For absolute paths, find first occurrence of project markers
        # and strip everything before it
        project_markers = ["CLAUDE/", "src/", ".claude/", "docs/", "eslint-rules/", "untracked/"]
        for marker in project_markers:
            if marker in normalized:
                # Find the marker and strip everything before it
                idx = normalized.find(marker)
                if idx > 0:
                    normalized = normalized[idx:]
                break

        return normalized

    def is_adhoc_instruction_file(self, file_path: str) -> bool:
        """Check if this is CLAUDE.md, README.md, CHANGELOG.md, SKILL.md, agent file, or command file (allowed anywhere)."""
        filename = Path(file_path).name.lower()

        # CLAUDE.md, README.md, and CHANGELOG.md allowed anywhere
        if filename in ["claude.md", "readme.md", "changelog.md"]:
            return True

        # Use centralized normalization
        normalized = self.normalize_path(file_path)

        # SKILL.md files in .claude/skills/*/ are allowed
        if filename == "skill.md" and ".claude/skills/" in normalized:
            return True

        # Agent definitions in .claude/agents/ are allowed
        # Slash command definitions in .claude/commands/ are allowed
        if ".claude/commands/" in normalized and file_path.endswith(".md"):
            return True

        return bool(".claude/agents/" in normalized and file_path.endswith(".md"))

    def is_page_colocated_file(self, file_path: str) -> bool:
        """Check if this is a *-research.md, *-rules.md, or article-*.md file co-located with pages.

        Article workflow (Plan 102):
        1. article-research-writer creates outline.md and sources.md
        2. article-content-writer creates article-{slug}.md (raw markdown)
        3. article-converter transforms article-{slug}.md into page.tsx
        """
        # Use centralized normalization
        normalized = self.normalize_path(file_path)

        # Check for page research files: src/pages/**/*-research.md
        if re.match(r"^src/pages/.*-research\.md$", normalized, re.IGNORECASE):
            return True

        # Check for page rules files: src/pages/**/*-rules.md
        if re.match(r"^src/pages/.*-rules\.md$", normalized, re.IGNORECASE):
            return True

        # Check for article content files: src/pages/articles/**/article-*.md
        return bool(
            re.match(r"^src/pages/articles/.*/article-[^/]+\.md$", normalized, re.IGNORECASE)
        )

    def strip_monorepo_prefix(self, normalized_path: str) -> str | None:
        """Strip monorepo sub-project prefix from a normalized path.

        If the path matches a configured monorepo sub-project pattern,
        returns the path relative to the sub-project root. Otherwise
        returns None (no match).

        Args:
            normalized_path: Already-normalized file path (no leading slash)

        Returns:
            Sub-project-relative path, or None if no pattern matches
        """
        if not self._monorepo_subproject_patterns:
            return None

        for pattern in self._monorepo_subproject_patterns:
            # Pattern must match at the start of the path followed by /
            match = re.match(rf"^({pattern})/(.+)$", normalized_path)
            if match:
                return match.group(2)

        return None

    def is_planning_mode_write(self, file_path: str) -> bool:
        """Check if this is a Claude Code planning mode write.

        Planning mode writes go to ~/.claude/plans/*.md (user home directory).

        Args:
            file_path: File path to check

        Returns:
            True if this is a planning mode write
        """
        # Pattern: ~/.claude/plans/*.md (anywhere in user home)
        # Examples:
        # - /home/user/.claude/plans/my-plan.md
        # - /Users/bob/.claude/plans/plan.md
        # - ~/.claude/plans/test.md
        return bool(re.search(r"/.claude/plans/[^/]+\.md$", file_path))

    def sanitize_folder_name(self, filename: str) -> str:
        """Sanitize plan filename for use as folder name.

        Removes .md extension, converts to lowercase, replaces special chars
        with hyphens, and collapses multiple hyphens.

        Args:
            filename: Original filename (e.g., "My Plan.md")

        Returns:
            Sanitized folder name (e.g., "my-plan")
        """
        # Remove .md extension
        name = filename.replace(".md", "")

        # Convert to lowercase
        name = name.lower()

        # Replace special characters with hyphens
        name = re.sub(r"[^a-z0-9]+", "-", name)

        # Remove leading/trailing hyphens
        name = name.strip("-")

        # Collapse multiple hyphens
        name = re.sub(r"-+", "-", name)

        return name

    def get_unique_folder_name(self, base_folder: Path, plan_number: str, plan_name: str) -> str:
        """Get unique folder name, adding suffix if collision exists.

        Args:
            base_folder: Base folder (e.g., CLAUDE/Plan/)
            plan_number: Plan number (e.g., "00001")
            plan_name: Sanitized plan name (e.g., "my-plan")

        Returns:
            Unique folder name (e.g., "00001-my-plan" or "00001-my-plan-2")
        """
        folder_name = f"{plan_number}-{plan_name}"
        folder_path = base_folder / folder_name

        # If no collision, return immediately
        if not folder_path.exists():
            return folder_name

        # Try with suffix -2, -3, etc.
        suffix = 2
        while True:
            folder_name_with_suffix = f"{plan_number}-{plan_name}-{suffix}"
            folder_path_with_suffix = base_folder / folder_name_with_suffix
            if not folder_path_with_suffix.exists():
                return folder_name_with_suffix
            suffix += 1

    def handle_planning_mode_write(self, hook_input: dict[str, Any]) -> HookResult:
        """Handle planning mode write by redirecting to project structure.

        Creates:
        1. CLAUDE/Plan/{number}-{name}/PLAN.md (actual plan content)
        2. ~/.claude/plans/{original-name}.md (stub redirect file)

        Args:
            hook_input: Hook input data

        Returns:
            HookResult with ALLOW decision and context about redirect
        """
        file_path = get_file_path(hook_input)
        content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("content", "")

        try:
            # Get plan directory from config (track_plans_in_project is the path)
            if not self._track_plans_in_project:
                # Should not reach here - matches() should have filtered this
                return HookResult(decision=Decision.ALLOW)

            plan_base = self._workspace_root / self._track_plans_in_project

            # Get next plan number
            next_number = get_next_plan_number(plan_base)

            # Sanitize filename to create folder name
            if not file_path:
                return HookResult(decision=Decision.ALLOW)  # Should not happen
            original_filename = Path(file_path).name
            sanitized_name = self.sanitize_folder_name(original_filename)

            # Get unique folder name (handle collisions)
            folder_name = self.get_unique_folder_name(plan_base, next_number, sanitized_name)

            # Create plan folder (don't use exist_ok to catch unexpected collisions)
            plan_folder = plan_base / folder_name
            plan_folder.mkdir(parents=True, exist_ok=False)

            # Write PLAN.md
            plan_file = plan_folder / "PLAN.md"
            plan_file.write_text(content, encoding="utf-8")

            # Create stub redirect file at original location
            original_path = Path(file_path).expanduser()
            original_path.parent.mkdir(parents=True, exist_ok=True)

            stub_content = (
                f"# Plan Redirect\n\n"
                f"This plan has been moved to the project:\n\n"
                f"**Location**: `{self._track_plans_in_project}/{folder_name}/PLAN.md`\n\n"
                f"The hooks daemon automatically redirects planning mode writes "
                f"to keep plans in version control.\n\n"
                f"**IMPORTANT**: The plan folder currently has a temporary name: `{folder_name}`\n\n"
                f"**You MUST rename this folder** to a descriptive name based on the plan content:\n"
                f"1. Read the plan to understand what it's about\n"
                f"2. Choose a clear, descriptive kebab-case name\n"
                f"3. Rename: `{self._track_plans_in_project}/{folder_name}/` → "
                f"`{self._track_plans_in_project}/{next_number}-descriptive-name/`\n"
                f"4. Keep the plan number prefix ({next_number}-) intact\n\n"
                f"Example: `{next_number}-floofy-growing-moth` → `{next_number}-implement-tdd-validation`\n"
            )
            original_path.write_text(stub_content, encoding="utf-8")

            logger.info(f"Planning mode write redirected: {file_path} -> {plan_folder}/PLAN.md")

            # Build context with workflow docs reference if configured
            context_parts = [
                f"Planning mode write successfully redirected.\n\n"
                f"Your plan has been saved to: `{self._track_plans_in_project}/{folder_name}/PLAN.md`\n\n"
                f"A redirect stub was created at: `{file_path}`\n\n"
                f"**ACTION REQUIRED**: The plan folder has a temporary name.\n"
                f"Please rename `{folder_name}/` to `{next_number}-descriptive-name/` "
                f"based on the plan content. Keep the number prefix intact."
            ]

            # Phase 4: Inject workflow docs guidance if configured
            if self._plan_workflow_docs:
                workflow_path = self._workspace_root / self._plan_workflow_docs
                if workflow_path.exists():
                    context_parts.append(
                        f"\n\n**Workflow Documentation**: See `{self._plan_workflow_docs}` "
                        f"for plan structure and conventions."
                    )

            return HookResult(
                decision=Decision.ALLOW,
                context=context_parts,
            )

        except FileNotFoundError as e:
            logger.error(f"Planning mode write failed - directory not found: {e}")
            return HookResult(
                decision=Decision.DENY,
                reason=(
                    "Failed to redirect planning mode write.\n\n"
                    f"Error: Plan directory does not exist: {plan_base}\n\n"
                    f"Please ensure {self._track_plans_in_project}/ directory exists in your project."
                ),
            )

        except PermissionError as e:
            logger.error(f"Planning mode write failed - permission error: {e}")
            return HookResult(
                decision=Decision.DENY,
                reason=(
                    "Failed to redirect planning mode write.\n\n"
                    "Error: Permission denied when creating plan folder.\n\n"
                    f"Please check file permissions for {self._track_plans_in_project}/ directory."
                ),
            )

        except Exception as e:
            logger.error(f"Planning mode write failed - unexpected error: {e}", exc_info=True)
            return HookResult(
                decision=Decision.DENY,
                reason=(
                    "Failed to redirect planning mode write.\n\n"
                    f"Error: {type(e).__name__}: {e}\n\n"
                    "Please check daemon logs for details."
                ),
            )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing markdown to wrong location.

        IMPORTANT: Must match legacy hook behavior exactly using precise patterns.

        Additionally intercepts planning mode writes when feature is enabled.
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path or not file_path.endswith(".md"):
            return False

        # Check for planning mode write FIRST (takes precedence when enabled)
        # Planning mode writes are intentionally outside project but should be intercepted
        if self._track_plans_in_project and self.is_planning_mode_write(file_path):
            return True  # Intercept to redirect

        # Allow Claude Code auto-memory writes (e.g. ~/.claude/projects/*/memory/*.md)
        # Check the raw path BEFORE resolve() because symlinks (e.g. ~/.claude -> project/.claude/ccy)
        # can cause resolve() to map these paths back into the project root, falsely blocking them.
        if "/.claude/projects/" in file_path and "/memory/" in file_path:
            return False

        # CRITICAL: Only enforce rules for files WITHIN the project root
        # Files outside project root (like Claude Code auto memory) should be allowed
        # Only check absolute paths - relative paths are always within project
        if Path(file_path).is_absolute():
            file_path_obj = Path(file_path).resolve()
            project_root = ProjectContext.project_root()
            try:
                # Check if file_path is under project_root
                file_path_obj.relative_to(project_root)
            except ValueError:
                # File is outside project root - allow it (don't match)
                return False

        # Use centralized normalization
        normalized = self.normalize_path(file_path)

        # CRITICAL: CLAUDE.md and README.md are allowed ANYWHERE
        if self.is_adhoc_instruction_file(file_path):
            return False

        # Page co-located files (*-research.md, *-rules.md, article-*.md) are allowed
        if self.is_page_colocated_file(file_path):
            return False

        # Check monorepo sub-project paths: strip prefix and validate remainder
        subproject_relative = self.strip_monorepo_prefix(normalized)
        if subproject_relative is not None:
            # Path is within a configured monorepo sub-project.
            # Apply the same organization rules to the sub-project-relative path.
            return self._is_invalid_location(subproject_relative)

        # For root-level paths, apply organization rules directly
        return self._is_invalid_location(normalized)

    def _is_invalid_location(self, normalized: str) -> bool:
        """Check if a normalized path is in an invalid markdown location.

        Applies organization rules to a path that is already relative to
        a project root (either the repo root or a monorepo sub-project).

        When _allowed_markdown_paths is configured, those regex patterns
        OVERRIDE all built-in path checks. Any path matching at least one
        pattern is allowed; everything else is blocked.

        Args:
            normalized: Project-relative normalized path

        Returns:
            True if the location is INVALID (should be blocked)
        """
        # When custom allowed paths are configured, they override ALL built-in logic
        if self._allowed_markdown_paths is not None:
            return self._check_custom_paths(normalized)

        return self._check_builtin_paths(normalized)

    def _check_custom_paths(self, normalized: str) -> bool:
        """Check path against custom allowed_markdown_paths regex patterns.

        Args:
            normalized: Project-relative normalized path

        Returns:
            True if the location is INVALID (no pattern matches)
        """
        for pattern in self._allowed_markdown_paths or []:
            if re.match(pattern, normalized, re.IGNORECASE):
                return False  # Allowed - matches a custom pattern
        return True  # Blocked - no pattern matched

    def _check_builtin_paths(self, normalized: str) -> bool:
        """Check path against built-in allowed locations.

        Args:
            normalized: Project-relative normalized path

        Returns:
            True if the location is INVALID (should be blocked)
        """
        # 0. src/claude_code_hooks_daemon/guides/ - Shipped guide files (part of daemon package)
        if re.match(r"^src/claude_code_hooks_daemon/guides/.*\.md$", normalized, re.IGNORECASE):
            return False  # Allow

        # 1. CLAUDE/ - Allow all files and subdirectories, BUT validate plan number format
        if normalized.lower().startswith("claude/"):
            # Special validation for CLAUDE/Plan/ directories
            if normalized.lower().startswith("claude/plan/"):
                # Extract plan folder pattern: CLAUDE/Plan/{folder}/PLAN.md
                # OR: CLAUDE/Plan/{subdirectory}/{folder}/PLAN.md
                plan_match = re.match(r"^claude/plan/([^/]+)/", normalized, re.IGNORECASE)
                if plan_match:
                    folder_name = plan_match.group(1).lower()

                    # Check if first segment is a known subdirectory (Completed, Cancelled, Archive)
                    if folder_name in _PLAN_SUBDIRECTORIES:
                        # For subdirectories, validate the SECOND path segment
                        subdir_match = re.match(
                            r"^claude/plan/[^/]+/([^/]+)/", normalized, re.IGNORECASE
                        )
                        if subdir_match:
                            folder_name = subdir_match.group(1)
                        else:
                            # Subdirectory without nested plan folder - allow
                            return False

                    # Validate folder name has numeric prefix
                    number_match = re.match(r"^(\d+)-", folder_name)
                    if number_match:
                        # Validate plan number has at least 3 digits
                        plan_number = number_match.group(1)
                        if len(plan_number) < 3:
                            return True  # Block - insufficient digits
                        # Plan number is valid (3+ digits) - allow
                        return False
                    else:
                        # No numeric prefix - block
                        return True  # Block - missing plan number
            return False  # Allow all other CLAUDE/ files

        # 5. docs/ - Human-facing documentation
        if normalized.lower().startswith("docs/"):
            return False  # Allow

        # 6. untracked/ - Temporary docs
        if normalized.lower().startswith("untracked/"):
            return False  # Allow

        # 7. RELEASES/ - Release notes
        if normalized.lower().startswith("releases/"):
            return False  # Allow

        # 8. eslint-rules/ - ESLint rule docs
        # Not in allowed location - block (negated condition returns True)
        return not re.match(r"^eslint-rules/.*\.md$", normalized, re.IGNORECASE)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Handle markdown write based on location.

        Planning mode writes are redirected to project structure.
        Other invalid locations are denied with guidance.
        """
        file_path = get_file_path(hook_input)
        if not file_path:
            return HookResult(decision=Decision.ALLOW)

        # Check if this is a planning mode write to redirect
        if self._track_plans_in_project and self.is_planning_mode_write(file_path):
            return self.handle_planning_mode_write(hook_input)

        # Otherwise, deny with standard message
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "MARKDOWN FILE IN WRONG LOCATION\n\n"
                "Markdown files must follow project organization rules.\n\n"
                f"Attempted to write: {file_path}\n\n"
                "This location is NOT allowed. Markdown files can only be written to:\n\n"
                "1. ./CLAUDE/ - All LLM documentation and subdirectories\n"
                "2. ./docs/ - Human-facing documentation\n"
                "3. ./eslint-rules/ - ESLint rule documentation\n"
                "4. ./untracked/ - Ad-hoc temporary docs\n"
                "5. ./RELEASES/ - Release notes\n"
                "6. ./.claude/commands/ - Slash command definitions\n\n"
                "CHOOSE THE RIGHT LOCATION:\n"
                "- Is this for LLMs/agents? -> CLAUDE/\n"
                "- Is this for the current plan? -> CLAUDE/Plan/{plan-number}-*/\n"
                "- Is this temporary/ad-hoc? -> untracked/\n"
                "- Is this for humans? -> docs/\n"
                "- Is this a release note? -> RELEASES/\n"
                "- Is this a slash command? -> .claude/commands/"
            ),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Markdown Organization."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="Block markdown in wrong location",
                command=(
                    "Use the Write tool to write to /tmp/acceptance-test-mdorg/random-notes.md"
                    " with content '# Some Notes\\n\\nRandom markdown file.'"
                ),
                description="Blocks markdown files written to non-standard locations",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"WRONG LOCATION", r"allowed"],
                safety_notes="Uses /tmp path - safe. Handler blocks non-standard markdown locations.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-mdorg"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-mdorg"],
            ),
        ]
