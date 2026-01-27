"""MarkdownOrganizationHandler - enforces markdown file organization rules."""

import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path


class MarkdownOrganizationHandler(Handler):
    """Enforce markdown file organization rules.

    CRITICAL: This handler must match legacy hook behavior EXACTLY.
    Cannot use simple 'in' checks - must use precise pattern matching.
    """

    def __init__(self) -> None:
        super().__init__(
            name="enforce-markdown-organization",
            priority=35,
            tags=["workflow", "markdown", "ec-specific", "blocking", "terminal"],
        )

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
        """Check if this is CLAUDE.md, README.md, SKILL.md, agent file, or command file (allowed anywhere)."""
        filename = Path(file_path).name.lower()

        # CLAUDE.md and README.md allowed anywhere
        if filename in ["claude.md", "readme.md"]:
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

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing markdown to wrong location.

        IMPORTANT: Must match legacy hook behavior exactly using precise patterns.
        """
        tool_name = hook_input.get("tool_name")
        if tool_name not in ["Write", "Edit"]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path or not file_path.endswith(".md"):
            return False

        # Use centralized normalization
        normalized = self.normalize_path(file_path)

        # CRITICAL: CLAUDE.md and README.md are allowed ANYWHERE
        if self.is_adhoc_instruction_file(file_path):
            return False

        # Page co-located files (*-research.md, *-rules.md, article-*.md) are allowed
        if self.is_page_colocated_file(file_path):
            return False

        # Check allowed locations with PRECISE pattern matching (not simple 'in' checks)

        # 1. CLAUDE/Plan/NNN-*/ - Requires numbered subdirectory
        if re.match(r"^CLAUDE/Plan/\d{3}-[^/]+/.+\.md$", normalized, re.IGNORECASE):
            return False  # Allow

        # 2. CLAUDE/ root level ONLY (no subdirs except known ones)
        if normalized.lower().startswith("claude/") and "/" not in normalized[7:]:
            return False  # Allow

        # 3. CLAUDE/research/ - Structured research data
        if re.match(r"^CLAUDE/research/", normalized, re.IGNORECASE):
            return False  # Allow

        # 4. CLAUDE/Sitemap/ - Site architecture
        if re.match(r"^CLAUDE/Sitemap/", normalized, re.IGNORECASE):
            return False  # Allow

        # 5. docs/ - Human-facing documentation
        if normalized.lower().startswith("docs/"):
            return False  # Allow

        # 6. untracked/ - Temporary docs
        if normalized.lower().startswith("untracked/"):
            return False  # Allow

        # 7. eslint-rules/ - ESLint rule docs
        # Not in allowed location - block (negated condition returns True)
        return not re.match(r"^eslint-rules/.*\.md$", normalized, re.IGNORECASE)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block markdown in wrong location."""
        file_path = get_file_path(hook_input)

        return HookResult(
            decision=Decision.DENY,
            reason=(
                "MARKDOWN FILE IN WRONG LOCATION\n\n"
                "Markdown files must follow project organization rules.\n\n"
                f"Attempted to write: {file_path}\n\n"
                "This location is NOT allowed. Markdown files can only be written to:\n\n"
                "1. ./CLAUDE/Plan/XXX-plan-name/ - Docs for current plan\n"
                "2. ./CLAUDE/ (root only) - Generic LLM docs\n"
                "3. ./CLAUDE/research/ - Structured research data\n"
                "4. ./docs/ - Human-facing documentation\n"
                "5. ./eslint-rules/ - ESLint rule documentation\n"
                "6. ./untracked/ - Ad-hoc temporary docs\n"
                "7. ./.claude/commands/ - Slash command definitions\n\n"
                "CHOOSE THE RIGHT LOCATION:\n"
                "- Is this for the current plan? -> CLAUDE/Plan/{plan-number}-*/\n"
                "- Is this temporary/ad-hoc? -> untracked/\n"
                "- Is this for humans? -> docs/\n"
                "- Is this a slash command? -> .claude/commands/\n"
                "- Is this generic LLM context? -> CLAUDE/ (very rare!)"
            ),
        )
