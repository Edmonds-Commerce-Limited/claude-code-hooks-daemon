"""MarkdownOrganizationHandler - enforces markdown file organization rules."""

import json
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
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import (
    get_bash_command,
    get_bash_write_targets,
    get_file_path,
)
from claude_code_hooks_daemon.core.workspace import resolve_workspace
from claude_code_hooks_daemon.core.worktree_paths import effective_project_relative_path
from claude_code_hooks_daemon.handlers.utils.plan_numbering import (
    next_plan_number_for_target,
    record_plan_allocation,
)

logger = logging.getLogger(__name__)

# Three Rules (Plan 00116, Decision B) for this handler's three distinct deny
# concepts: a generic wrong-location write, the untracked-Claude-memory
# policy, and a plansDirectory/daemon-config sync failure.
_RULE_WRONG_LOCATION = Rule(
    rule_id=RuleID.MARKDOWN_WRONG_LOCATION,
    blocked="MARKDOWN FILE IN WRONG LOCATION — a new `.md` file written to an unrecognised location",
    why="Markdown files must follow project organization rules",
    fix="Move it into an allowed location, or configure `extra_allowed_markdown_paths`",
    verbose=(
        "This location is NOT allowed. Markdown files can only be written to:\n\n"
        "1. ./CLAUDE/ - All LLM documentation and subdirectories\n"
        "2. ./docs/ - Human-facing documentation\n"
        "3. ./eslint-rules/ - ESLint rule documentation\n"
        "4. ./untracked/ - Ad-hoc temporary docs\n"
        "5. ./RELEASES/ - Release notes\n"
        "6. ./.claude/commands/, ./.claude/agents/, ./.claude/rules/ - "
        "Claude Code command/agent/rules definitions\n"
        "7. ./vendor/, ./node_modules/ - Third-party dependencies\n"
        "8. Standard repo-root files (exact root only): README.md, CHANGELOG.md,\n"
        "   CONTRIBUTING.md, LICENSE.md, SECURITY.md, CODE_OF_CONDUCT.md,\n"
        "   AUTHORS.md, NOTICE.md, MAINTAINERS.md\n\n"
        "CHOOSE THE RIGHT LOCATION:\n"
        "- Is this for LLMs/agents? -> CLAUDE/\n"
        "- Is this for the current plan? -> CLAUDE/Plan/{plan-number}-*/\n"
        "- Is this temporary/ad-hoc? -> untracked/\n"
        "- Is this for humans? -> docs/\n"
        "- Is this a release note? -> RELEASES/\n"
        "- Is this a slash command? -> .claude/commands/\n"
        "- Is this a Claude Code rules file? -> .claude/rules/\n\n"
        "NEED A DIFFERENT LOCATION? Configure in .claude/hooks-daemon.yaml:\n"
        "- allowed_markdown_paths: add regex patterns for extra allowed paths\n"
        "- projects: declare a sub-project (with its own docs/, CLAUDE/, etc.) "
        "as a `projects:` entry (see CLAUDE/Code/WorkspaceResolution.md). This "
        "is the ONLY sub-project mechanism -- monorepo_subproject_patterns was "
        "removed (Plan 00300 hard cutover)."
    ),
)

_RULE_UNTRACKED_MEMORY = Rule(
    rule_id=RuleID.MARKDOWN_UNTRACKED_MEMORY,
    blocked=(
        "UNTRACKED CLAUDE MEMORY IS DISABLED FOR THIS PROJECT — a write to "
        "`~/.claude/projects/*/memory/*.md`"
    ),
    why=(
        "That knowledge is per-checkout, un-reviewed, and invisible to teammates — "
        "it drifts from the repo and bypasses code review"
    ),
    fix="Document it in tracked project docs instead (CLAUDE.md, .claude/rules/*.md, docs/)",
    verbose=(
        "This project does not keep durable knowledge in untracked Claude memory "
        "files (~/.claude/projects/*/memory/).\n\n"
        "READING memory is still allowed — so you can migrate any existing memory "
        "into tracked project docs.\n\n"
        "DOCUMENT IT IN TRACKED PROJECT DOCS INSTEAD (progressive disclosure):\n"
        "- Durable, always-relevant facts -> CLAUDE.md (keep it lean; it is\n"
        "  resident context loaded every session)\n"
        "- Contextual, path-specific guidance -> .claude/rules/*.md with `paths:`\n"
        "  glob frontmatter (loaded on demand only when matching files are touched)\n"
        "- Intent-triggered procedures -> a thin skill under .claude/skills/ that\n"
        "  points at a single-source-of-truth doc body\n"
        "- Reference material humans also read -> docs/\n"
        "- Link between docs with plain markdown links (zero token cost until\n"
        "  followed); AVOID @-imports (they re-inline eagerly rather than defer)\n\n"
        "Keep ONE source of truth per fact and link to it. Put the knowledge where\n"
        "the repo tracks it, not in untracked Claude meta files.\n\n"
        "(Policy: `allow_untracked_claude_memory: false` under markdown_organization\n"
        "in .claude/hooks-daemon.yaml. Set it true to restore default memory writes.)"
    ),
)

_RULE_PLAN_SYNC = Rule(
    rule_id=RuleID.MARKDOWN_PLAN_SYNC,
    blocked=(
        "a `.claude/settings.json` `plansDirectory` out of sync with the daemon's "
        "plan_workflow config"
    ),
    why="Plan workflow requires plansDirectory to match daemon config to redirect writes correctly",
    fix="Fix `.claude/settings.json`'s `plansDirectory` key, then restart your session",
    verbose=(
        "Plan workflow requires `plansDirectory` in `.claude/settings.json` to be "
        "present and to match this daemon's `plan_workflow.directory` config."
    ),
)

# Fallback directory-role truths, used only when no ProjectLayout facade was
# injected (e.g. a handler constructed directly in a unit test rather than
# via the registry). These mirror the Config defaults exactly
# (DocumentationTreesConfig.agent/human, PlanWorkflowConfig.directory,
# PlanWorkflowQaConfig.completed_dir) so behaviour is unchanged either way.
_FALLBACK_AGENT_DOCS_DIR: Final[str] = "CLAUDE"
_FALLBACK_HUMAN_DOCS_DIR: Final[str] = "docs"
_FALLBACK_PLAN_DIR: Final[str] = "CLAUDE/Plan"
_FALLBACK_PLAN_ARCHIVE_DIRS: Final[tuple[str, ...]] = ("Completed",)

# Legacy plan-archive subdirectory names that predate plan_workflow.qa's
# completed_dir/cancelled_dir config and have no config home of their own —
# kept as permanent additive extras alongside the facade's archive dir names.
# 'archive' has no config home at all. 'cancelled' must ALSO be listed here
# even though plan_workflow.qa.cancelled_dir exists: that field defaults to
# None (meaning "no separate dir; cancelled plans archive under
# completed_dir"), so the facade's default plan_archive_dirs is ("Completed",)
# only — yet the pre-facade hardcoded behaviour always recognised a literal
# CLAUDE/Plan/Cancelled/ subdirectory regardless of config. Dropping this
# extra would silently block that folder for every zero-config project.
_LEGACY_PLAN_ARCHIVE_EXTRAS: Final[tuple[str, ...]] = ("archive", "cancelled")

# Files in the plan directory root that are NOT plan files (excluded from interception)
_PLAN_ROOT_EXCLUDED_FILES: Final[frozenset[str]] = frozenset({"readme", "claude"})

# Basename prefixes marking a daemon-owned, non-plan file at the plan root:
# hidden snapshots ('.plan-template-default.md') and template files
# ('_TEMPLATE_.md', '_JOURNAL_TEMPLATE_.md'). A real Claude Code plan-mode save
# is never dot- or underscore-prefixed, so these must never scaffold a plan.
_DAEMON_OWNED_PLAN_FILE_PREFIXES: Final[tuple[str, ...]] = (".", "_")

# Third-party dependency directories that act as implicit monorepos.
# Each top-level package inside these is treated as a sub-project —
# normal markdown organization rules apply within each package root.
_DEPENDENCY_DIRECTORIES: Final[tuple[str, ...]] = ("vendor/", "node_modules/")

# Config option (policy SSoT) that forbids untracked Claude auto-memory writes.
# When False, Claude-memory .md writes are blocked at the daemon layer and durable
# knowledge must live in tracked project docs (progressive disclosure). Plan 00131.
ALLOW_UNTRACKED_CLAUDE_MEMORY_OPTION: Final[str] = "allow_untracked_claude_memory"

# Shipped default for the option above. Flipped True -> False in v3.24.0 (Plan
# 00133): untracked memory is blocked unless a project explicitly opts back in.
# Single source of truth — the handler default AND optimal_config_checker's
# policy-detection fallback both read this so they can never drift.
DEFAULT_ALLOW_UNTRACKED_CLAUDE_MEMORY: Final[bool] = False

# Path markers identifying a Claude Code auto-memory file
# (e.g. ~/.claude/projects/<slug>/memory/MEMORY.md and per-fact files).
_CLAUDE_MEMORY_PATH_MARKERS: Final[tuple[str, str]] = ("/.claude/projects/", "/memory/")

# Shell write-to-file patterns used to close the bash side-door to memory paths.
# Redirect (> / >>) and tee targets are WRITES; reads (cat/grep/less path) have no
# such operator and are intentionally NOT matched (reads stay allowed for migration).
_BASH_REDIRECT_TARGET_RE: Final[re.Pattern[str]] = re.compile(r">>?\s*([^\s|&;<>]+)")
_BASH_TEE_TARGET_RE: Final[re.Pattern[str]] = re.compile(r"\btee\b(?:\s+-[^\s]+)*\s+([^\s|&;<>]+)")

# Industry-standard markdown files that live at the project root.
# These are exact filenames (no path components) — subdirectory copies are blocked.
# README.md and CHANGELOG.md are handled by is_adhoc_instruction_file (allowed anywhere);
# these additional files are root-only.
_STANDARD_ROOT_MARKDOWN_FILES: Final[frozenset[str]] = frozenset(
    {
        "contributing.md",
        "license.md",
        "security.md",
        "code_of_conduct.md",
        "authors.md",
        "notice.md",
        "maintainers.md",
    }
)


class MarkdownOrganizationHandler(PreToolUseHandlerBase):
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
                HandlerTag.PLANNING,
            ],
        )
        # Configuration attributes (set by registry after instantiation)
        self._workspace_root: Path = ProjectContext.project_root()
        self._track_plans_in_project: str | None = None  # Path to plan folder or None
        self._plan_workflow_docs: str | None = None  # Path to workflow doc or None
        self._enforce_claude_code_sync: bool = False  # Enforce plansDirectory sync
        self._allowed_markdown_paths: list[str] | None = None  # Regex patterns for allowed paths
        # Additive allowed paths: layered ON TOP of built-ins OR the legacy override
        self._extra_allowed_markdown_paths: list[str] | None = None
        # Policy: when False, untracked Claude auto-memory writes are BLOCKED at the
        # daemon layer. Default flipped True -> False in v3.24.0 (Plan 00133): durable
        # knowledge belongs in tracked, reviewed project docs, not per-checkout memory.
        # Set allow_untracked_claude_memory: true to opt out and restore the old behaviour.
        self._allow_untracked_claude_memory: bool = DEFAULT_ALLOW_UNTRACKED_CLAUDE_MEMORY

    def _agent_docs_dir(self) -> str:
        """Root of the agent-facing doc tree (facade, or the matching default)."""
        layout = self._project_layout
        return layout.agent_docs_dir if layout is not None else _FALLBACK_AGENT_DOCS_DIR

    def _human_docs_dir(self) -> str:
        """Root of the human-facing doc tree (facade, or the matching default)."""
        layout = self._project_layout
        return layout.human_docs_dir if layout is not None else _FALLBACK_HUMAN_DOCS_DIR

    def _plan_dir(self) -> str:
        """Configured plan directory (facade, or the matching default)."""
        layout = self._project_layout
        return layout.plan_dir if layout is not None else _FALLBACK_PLAN_DIR

    def _plan_archive_dirs_lower(self) -> frozenset[str]:
        """Lower-cased plan archive dir names, plus the legacy 'archive' extra.

        'archive' predates plan_workflow.qa's completed_dir/cancelled_dir and
        has no config home of its own, so it is preserved unconditionally
        rather than only when the facade's archive dirs happen to omit it.
        """
        layout = self._project_layout
        archive_dirs = (
            layout.plan_archive_dirs if layout is not None else _FALLBACK_PLAN_ARCHIVE_DIRS
        )
        return frozenset({name.lower() for name in archive_dirs} | set(_LEGACY_PLAN_ARCHIVE_EXTRAS))

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
        project_markers = [
            f"{self._agent_docs_dir()}/",
            "src/",
            ".claude/",
            f"{self._human_docs_dir()}/",
            "eslint-rules/",
            "untracked/",
        ]
        for marker in project_markers:
            if marker in normalized:
                # Find the marker and strip everything before it
                idx = normalized.find(marker)
                if idx > 0:
                    normalized = normalized[idx:]
                break

        return normalized

    def is_adhoc_instruction_file(self, file_path: str) -> bool:
        """Check if this is CLAUDE.md, README.md, CHANGELOG.md, SKILL.md, agent, command, or rules file (allowed anywhere)."""
        filename = Path(file_path).name.lower()

        # CLAUDE.md, README.md, and CHANGELOG.md allowed anywhere
        if filename in ["claude.md", "readme.md", "changelog.md"]:
            return True

        # Use centralized normalization
        normalized = self.normalize_path(file_path)

        # All markdown inside .claude/skills/ is allowed (SKILL.md plus any
        # supporting reference/usage docs a skill ships alongside it)
        if ".claude/skills/" in normalized and file_path.endswith(".md"):
            return True

        # Agent definitions in .claude/agents/ are allowed
        # Slash command definitions in .claude/commands/ are allowed
        # Rules files in .claude/rules/ are allowed
        if ".claude/commands/" in normalized and file_path.endswith(".md"):
            return True

        if ".claude/rules/" in normalized and file_path.endswith(".md"):
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

    def _declared_subproject_relative(self, normalized_path: str) -> str | None:
        """Strip a DECLARED `projects:` sub-project root from a normalized path.

        Primary resolution mechanism (Plan 00296): a sub-project is
        DECLARED via `projects:` in `.claude/hooks-daemon.yaml` and
        injected onto this handler as `_project_registry` (the same
        `resolve_workspace()` pattern used by `npm_command`/`lint_on_edit`).
        NO inference is performed — an undeclared subdirectory resolves to
        the repository root and this method returns None for it, exactly
        like an unconfigured repository.

        Args:
            normalized_path: Already-normalized file path (no leading slash),
                relative to the repository/workspace root.

        Returns:
            Sub-project-relative path, or None if the path resolves to the
            repository root (nothing declared covers it).
        """
        workspace_root = self._workspace_root.resolve()
        absolute = workspace_root / normalized_path
        workspace = resolve_workspace(self._project_registry, absolute, workspace_root)
        if workspace.root == workspace_root:
            return None

        try:
            declared_relative_root = workspace.root.relative_to(workspace_root)
            return str(Path(normalized_path).relative_to(declared_relative_root))
        except ValueError:
            # Declared root does not actually contain this normalized path
            # (e.g. normalize_path already stripped it to a project marker).
            return None

    @staticmethod
    def _strip_dependency_prefix(lowered_path: str) -> str | None:
        """Strip dependency directory prefix to get package-relative path.

        Treats vendor/ and node_modules/ as implicit monorepos where each
        package is a sub-project. Normal markdown rules apply within each.

        Package root conventions:
        - vendor/{vendor}/{package}/  (PHP Composer — two levels)
        - node_modules/{package}/     (npm — one level)
        - node_modules/@{scope}/{package}/  (npm scoped — two levels)

        Args:
            lowered_path: Lowercased, slash-normalized path (no leading slash)

        Returns:
            Package-relative path, or None if not inside a dependency dir
        """
        for prefix in _DEPENDENCY_DIRECTORIES:
            if not lowered_path.startswith(prefix):
                continue

            after_prefix = lowered_path[len(prefix) :]

            if prefix == "vendor/":
                # Composer: vendor/{vendor}/{package}/{rest}
                match = re.match(r"^[^/]+/[^/]+/(.+)$", after_prefix)
            elif after_prefix.startswith("@"):
                # npm scoped: node_modules/@{scope}/{package}/{rest}
                match = re.match(r"^@[^/]+/[^/]+/(.+)$", after_prefix)
            else:
                # npm unscoped: node_modules/{package}/{rest}
                match = re.match(r"^[^/]+/(.+)$", after_prefix)

            if match:
                return match.group(1)

            # Path is at the package root level (no file inside) — not actionable
            return None

        return None

    @staticmethod
    def _is_daemon_owned_plan_file(filename: str) -> bool:
        """True for a dot-/underscore-prefixed daemon-owned file (never a plan).

        Guards the plan-scaffolding path against the daemon's own template
        snapshot (``.plan-template-default.md``) and template files
        (``_TEMPLATE_.md``, ``_JOURNAL_TEMPLATE_.md``), whose plan-like content
        would otherwise be misread as a user plan-mode save.
        """
        return filename.startswith(_DAEMON_OWNED_PLAN_FILE_PREFIXES)

    def is_planning_mode_write(self, file_path: str) -> bool:
        """Check if this is a planning mode write to intercept.

        Detects two patterns:
        1. Flat file writes to {plan_directory}/*.md (plansDirectory mode)
           e.g., CLAUDE/Plan/my-plan.md — written by Claude Code when plansDirectory is set
        2. Legacy writes to ~/.claude/plans/*.md (backward compatibility)

        Excludes:
        - Files in numbered subfolders (CLAUDE/Plan/00087-name/PLAN.md)
        - Known non-plan files (README.md)

        Args:
            file_path: File path to check

        Returns:
            True if this is a planning mode write
        """
        # Pattern 1: Flat file in plan directory root (plansDirectory mode)
        if self._track_plans_in_project:
            normalized = self.normalize_path(file_path)
            plan_dir = self._track_plans_in_project
            # Match {plan_dir}/{name}.md where {name} has no slashes (flat file)
            pattern = rf"^{re.escape(plan_dir)}/([^/]+)\.md$"
            match = re.match(pattern, normalized, re.IGNORECASE)
            if match:
                filename = match.group(1)
                if self._is_daemon_owned_plan_file(filename):
                    return False
                if filename.lower() not in _PLAN_ROOT_EXCLUDED_FILES:
                    return True

        # Pattern 2: Legacy ~/.claude/plans/*.md (backward compatibility).
        # The dot in '.claude' is escaped so a look-alike directory such as
        # 'Xclaude/plans/' is not misclassified as the legacy planning path.
        return bool(re.search(r"/\.claude/plans/[^/]+\.md$", file_path))

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

    def _find_matching_plan_folder(self, plan_base: Path, flat_file_path: str) -> Path | None:
        """Find the numbered plan folder matching a flat plan filename.

        Searches for folders ending with -{sanitized_name} in the plan directory,
        returning the one with the highest number (most recent).

        Args:
            plan_base: Path to plan directory (e.g., workspace/CLAUDE/Plan/)
            flat_file_path: Path to flat plan file

        Returns:
            Path to matching plan folder, or None if not found
        """
        if not plan_base.exists():
            return None

        sanitized = self.sanitize_folder_name(Path(flat_file_path).name)
        if not sanitized:
            return None

        suffix = f"-{sanitized}"
        matches_found: list[Path] = []
        for entry in plan_base.iterdir():
            if entry.is_dir() and entry.name.endswith(suffix):
                matches_found.append(entry)

        if not matches_found:
            return None

        # Return highest numbered match (most recent)
        return sorted(matches_found, key=lambda p: p.name, reverse=True)[0]

    def _deny_plan_sync(self, detail: str, hook_input: dict[str, Any] | None) -> GatingResult:
        """Deny a plansDirectory sync failure with a verbose-first/terse-after message.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). ``detail`` names the
        SPECIFIC config problem (missing file, parse error, missing key, or
        mismatch) and its fix -- it changes per invocation/scenario, so it is
        appended rather than baked into the static ``Rule.verbose``.
        """
        formatter = RuleFormatter()
        transcript_path = (
            hook_input.get(HookInputField.TRANSCRIPT_PATH) if hook_input is not None else None
        )
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.MARKDOWN_PLAN_SYNC):
            message = formatter.terse(_RULE_PLAN_SYNC)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.MARKDOWN_PLAN_SYNC)
            message = formatter.verbose(_RULE_PLAN_SYNC)

        return GatingResult.deny(reason=f"{message}\n\n{detail}")

    def _check_claude_code_sync(
        self, hook_input: dict[str, Any] | None = None
    ) -> GatingResult | None:
        """Check if plansDirectory in .claude/settings.json matches plan_workflow.directory.

        Args:
            hook_input: The originating hook event, used only to key the
                verbose-first/terse-after disclosure ladder by transcript_path.
                Callers that check config state outside a tool-call context
                (tests, tooling) may omit it -- the result is always verbose.

        Returns:
            GatingResult with DENY if out of sync, None if in sync or enforcement disabled
        """
        if not self._enforce_claude_code_sync or not self._track_plans_in_project:
            return None

        settings_path = self._workspace_root / ".claude" / "settings.json"
        expected_value = f"./{self._track_plans_in_project}"

        if not settings_path.exists():
            return self._deny_plan_sync(
                "settings.json not found.\n\n"
                "Plan workflow requires plansDirectory to be configured.\n\n"
                "Fix: Create .claude/settings.json with:\n"
                f'  "plansDirectory": "{expected_value}"\n\n'
                "Then restart your session.",
                hook_input,
            )

        try:
            settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read .claude/settings.json: {e}")
            return self._deny_plan_sync(
                f"Cannot read .claude/settings.json.\n\nError: {e}\n\n"
                "Fix the file and restart your session.",
                hook_input,
            )

        plans_directory = settings_data.get("plansDirectory")
        if plans_directory is None:
            return self._deny_plan_sync(
                "plansDirectory not set in .claude/settings.json.\n\n"
                "Plan workflow requires plansDirectory to match daemon config.\n\n"
                "Fix: Add to .claude/settings.json:\n"
                f'  "plansDirectory": "{expected_value}"\n\n'
                "Then restart your session.",
                hook_input,
            )

        # Normalise for comparison: strip leading "./" from both
        normalised_actual = plans_directory.lstrip("./")
        normalised_expected = self._track_plans_in_project.lstrip("./")

        if normalised_actual != normalised_expected:
            return self._deny_plan_sync(
                "plansDirectory mismatch.\n\n"
                f'  .claude/settings.json: "{plans_directory}"\n'
                f'  hooks daemon config:   "{self._track_plans_in_project}"\n\n'
                "These must match for plan workflow to work correctly.\n\n"
                "Fix: Update .claude/settings.json:\n"
                f'  "plansDirectory": "{expected_value}"\n\n'
                "Then restart your session.",
                hook_input,
            )

        return None

    def handle_planning_mode_write(self, hook_input: dict[str, Any]) -> GatingResult:
        """Handle planning mode write by creating numbered plan folder.

        For Write tool: Creates CLAUDE/Plan/{number}-{name}/PLAN.md alongside
        the flat file. Returns ALLOW so the flat file is also written (visible
        to ExitPlanMode for user approval).

        For Edit tool: Syncs the edit to the matching numbered folder's PLAN.md.
        Returns ALLOW so the flat file edit proceeds normally.

        Args:
            hook_input: Hook input data

        Returns:
            GatingResult with ALLOW decision and context about plan folder
        """
        file_path = get_file_path(hook_input)
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        if not self._track_plans_in_project or not file_path:
            return GatingResult(decision=Decision.ALLOW)

        # Enforce plansDirectory sync before processing plan writes
        sync_result = self._check_claude_code_sync(hook_input)
        if sync_result is not None:
            return sync_result

        plan_base = self._workspace_root / self._track_plans_in_project

        try:
            if tool_name == ToolName.EDIT:
                return self._handle_plan_edit(hook_input, plan_base, file_path)
            return self._handle_plan_write(hook_input, plan_base, file_path)

        except FileNotFoundError as e:
            logger.error(f"Planning mode write failed - directory not found: {e}")
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"Warning: Could not create plan folder. "
                    f"Ensure {self._track_plans_in_project}/ directory exists."
                ],
            )

        except PermissionError as e:
            logger.error(f"Planning mode write failed - permission error: {e}")
            return GatingResult(
                decision=Decision.ALLOW,
                context=[
                    f"Warning: Permission denied creating plan folder in "
                    f"{self._track_plans_in_project}/."
                ],
            )

        except Exception as e:
            logger.error(f"Planning mode write failed: {e}", exc_info=True)
            return GatingResult(
                decision=Decision.ALLOW,
                context=[f"Warning: Could not create plan folder: {type(e).__name__}: {e}"],
            )

    def _handle_plan_write(
        self, hook_input: dict[str, Any], plan_base: Path, file_path: str
    ) -> GatingResult:
        """Handle Write tool for planning mode — create numbered folder, ALLOW flat file.

        Creates the numbered plan folder with PLAN.md and returns ALLOW so the
        flat file is also written. ExitPlanMode reads the flat file to display
        the full plan content to the user for approval — so the flat write must
        proceed. After ExitPlanMode approval, the agent should rename the
        numbered folder to a semantic name and delete the now-redundant flat
        file.

        Args:
            hook_input: Hook input data
            plan_base: Path to plan directory
            file_path: Path to the flat plan file being written

        Returns:
            GatingResult with ALLOW decision and context describing the numbered folder
        """
        content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("content", "")

        plan_subdir = self._track_plans_in_project or str(plan_base.name)
        next_number = next_plan_number_for_target(plan_base, plan_subdir, self._workspace_root)
        original_filename = Path(file_path).name
        sanitized_name = self.sanitize_folder_name(original_filename)
        folder_name = self.get_unique_folder_name(plan_base, next_number, sanitized_name)

        # Create plan folder and write PLAN.md
        plan_folder = plan_base / folder_name
        plan_folder.mkdir(parents=True, exist_ok=False)

        plan_file = plan_folder / "PLAN.md"
        plan_file.write_text(content, encoding="utf-8")

        # Advance the per-repo high-water mark so the next plan reads counter + 1.
        record_plan_allocation(plan_folder, int(next_number))

        plan_relative = f"{self._track_plans_in_project}/{folder_name}/PLAN.md"
        logger.info(f"Plan folder created: {plan_relative}")

        context_parts = [
            f"Plan also saved to: {plan_relative}",
            "",
            "The flat file is allowed through so ExitPlanMode can display the",
            "full plan content for user approval. After approval, rename the",
            "numbered folder to a semantic name and delete the flat file:",
            "",
            f"  git mv {self._track_plans_in_project}/{folder_name} "
            f"{self._track_plans_in_project}/{next_number}-<descriptive-name>",
            f"  rm {file_path}",
            "",
            "Claude Code generates random three-word folder names by default.",
            "Replace with a short, descriptive kebab-case name for the plan.",
        ]

        if self._plan_workflow_docs:
            workflow_path = self._workspace_root / self._plan_workflow_docs
            if workflow_path.exists():
                context_parts.append(
                    f"See `{self._plan_workflow_docs}` for plan workflow conventions."
                )

        return GatingResult(decision=Decision.ALLOW, context=context_parts)

    def _handle_plan_edit(
        self, hook_input: dict[str, Any], plan_base: Path, file_path: str
    ) -> GatingResult:
        """Handle Edit tool for planning mode — sync edit to numbered folder.

        Args:
            hook_input: Hook input data
            plan_base: Path to plan directory
            file_path: Path to the flat plan file being edited

        Returns:
            GatingResult with ALLOW decision and optional sync context
        """
        old_string = hook_input.get(HookInputField.TOOL_INPUT, {}).get("old_string", "")
        new_string = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        plan_folder = self._find_matching_plan_folder(plan_base, file_path)
        if not plan_folder:
            return GatingResult(decision=Decision.ALLOW)

        plan_file = plan_folder / "PLAN.md"
        if not plan_file.exists():
            return GatingResult(decision=Decision.ALLOW)

        current_content = plan_file.read_text(encoding="utf-8")
        if old_string and old_string in current_content:
            updated = current_content.replace(old_string, new_string, 1)
            plan_file.write_text(updated, encoding="utf-8")

            rel_folder = plan_folder.relative_to(self._workspace_root)
            return GatingResult(
                decision=Decision.ALLOW,
                context=[f"Edit synced to: {rel_folder}/PLAN.md"],
            )

        return GatingResult(decision=Decision.ALLOW)

    @staticmethod
    def _is_claude_memory_path(file_path: str) -> bool:
        """True if file_path is a Claude Code auto-memory file.

        Matches ~/.claude/projects/<slug>/memory/*.md (MEMORY.md index and
        per-fact files). Checked on the RAW path (before resolve()) because a
        ccy symlink (~/.claude -> project/.claude/ccy) can map these back into
        the project root and defeat a resolved-path check.
        """
        marker_projects, marker_memory = _CLAUDE_MEMORY_PATH_MARKERS
        return marker_projects in file_path and marker_memory in file_path

    def _bash_memory_write_target(self, hook_input: dict[str, Any]) -> str | None:
        """Return a Claude-memory path being WRITTEN by a bash command, else None.

        Closes the `cat > ~/.claude/projects/x/memory/y.md` side-door. Reads
        (cat/grep/less with no write operator) are intentionally not matched.

        Two sources, deliberately UNIONED rather than one replacing the other
        (Plan 00260 Task 3.4):

        1. :func:`get_bash_write_targets` — a shlex tokeniser that understands
           `>`, `>>`, `>|`, every `tee` operand, `cp`/`mv`/`install`
           destinations, `dd of=`, and quoted paths containing spaces. Six
           shapes the two regexes below miss outright.
        2. The original raw-string regexes — kept because that accessor is
           CONSERVATIVE by contract and declines any target needing an expansion
           it cannot perform. `cat > $HOME/.claude/projects/x/memory/y.md` is
           exactly that case, and it is a spelling this policy has always
           blocked. Dropping the regexes to "clean up" would have quietly
           reopened it.

        The union is safe from the regexes' known false positive (prose such as
        `echo 'the arrow > file thing'` yields the target `file`) because every
        candidate from either source is filtered through
        :meth:`_is_claude_memory_path` before it can deny anything.

        Heredoc bodies ARE scanned. This is a deny-by-default policy where
        over-blocking is cheap, and the previous raw-string scan already caught
        a heredoc-authored script that would write to a memory path — stripping
        bodies would have been a silent regression.
        """
        for target in get_bash_write_targets(hook_input, include_heredoc_bodies=True):
            if self._is_claude_memory_path(target):
                return target

        command = get_bash_command(hook_input)
        if not command:
            return None
        for pattern in (_BASH_REDIRECT_TARGET_RE, _BASH_TEE_TARGET_RE):
            for match in pattern.finditer(command):
                target = match.group(1).strip("'\"")
                if self._is_claude_memory_path(target):
                    return target
        return None

    def _claude_memory_block_target(self, hook_input: dict[str, Any]) -> str | None:
        """Return the Claude-memory path this call would WRITE, else None.

        Single source of truth shared by matches() and handle() so the block
        decision and the specialist message stay in lock-step. Covers Write/Edit
        tool writes and bash redirect/tee side-doors. Only meaningful when the
        forbid-untracked-memory policy is active (caller gates on the flag).
        """
        file_path = get_file_path(hook_input)
        if file_path and self._is_claude_memory_path(file_path):
            return file_path
        return self._bash_memory_write_target(hook_input)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing markdown to wrong location.

        IMPORTANT: Must match legacy hook behavior exactly using precise patterns.

        Additionally intercepts planning mode writes when feature is enabled.
        """
        # Policy: forbid untracked Claude memory. Close the bash redirect/tee
        # side-door to memory paths BEFORE the Write/Edit tool gate. Only active
        # when the project has opted in (allow_untracked_claude_memory: false).
        if not self._allow_untracked_claude_memory and self._bash_memory_write_target(hook_input):
            return True

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

        # Claude Code auto-memory writes (e.g. ~/.claude/projects/*/memory/*.md).
        # Check the raw path BEFORE resolve() because symlinks (e.g. ~/.claude -> project/.claude/ccy)
        # can cause resolve() to map these paths back into the project root, falsely blocking them.
        # Default policy ALLOWS these (return False). When the project forbids untracked Claude
        # memory (allow_untracked_claude_memory: false), INTERCEPT so handle() can deny with the
        # specialist tracked-docs message. Plan 00131.
        if self._is_claude_memory_path(file_path):
            return not self._allow_untracked_claude_memory

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

            # Worktree-aware re-rooting: a file inside a git worktree subtree
            # (.claude/worktrees/<name>/ or untracked/worktrees/<name>/) must be
            # classified relative to the WORKTREE root, not the main project
            # root — otherwise an allowed location like CLAUDE/LLM-UPDATE.md is
            # seen as .claude/worktrees/<name>/CLAUDE/LLM-UPDATE.md and wrongly
            # blocked. Re-root to a worktree-relative path for all downstream
            # classification (standard-root, normalize, monorepo, adhoc checks).
            effective_relative = effective_project_relative_path(file_path, project_root)
            if effective_relative is not None:
                file_path = effective_relative

        # Standard repo-root files allowed at the project root only.
        # Compute project-relative path accurately:
        # - For absolute paths, resolve() + relative_to() gives the true relative path.
        # - For relative paths, use Path(file_path) directly.
        # We check this BEFORE normalize_path because normalize_path cannot reliably
        # strip arbitrary absolute path prefixes when no project marker is present.
        if Path(file_path).is_absolute():
            _proj_rel = Path(file_path).resolve().relative_to(ProjectContext.project_root())
        else:
            _proj_rel = Path(file_path)
        if _proj_rel.parent == Path() and _proj_rel.name.lower() in _STANDARD_ROOT_MARKDOWN_FILES:
            return False  # Allow — standard repo-root file at project root

        # Use centralized normalization
        normalized = self.normalize_path(file_path)

        # CRITICAL: CLAUDE.md and README.md are allowed ANYWHERE
        if self.is_adhoc_instruction_file(file_path):
            return False

        # Page co-located files (*-research.md, *-rules.md, article-*.md) are allowed
        if self.is_page_colocated_file(file_path):
            return False

        # Third-party dependency directories act as implicit monorepos.
        # Each package inside is a sub-project — apply normal rules within it.
        # Must check the raw path because normalize_path strips to project
        # markers (e.g. vendor/x/docs/y.md → docs/y.md).
        raw_lower = file_path.lstrip("/").lower()
        # Also strip workspace/ prefix for absolute test paths
        for ws_prefix in ("workspace/", "workspace\\"):
            if raw_lower.startswith(ws_prefix):
                raw_lower = raw_lower[len(ws_prefix) :]
                break
        dep_relative = self._strip_dependency_prefix(raw_lower)
        if dep_relative is not None:
            return self._is_invalid_location(dep_relative)

        # Check sub-project paths: declared `projects:` config (Plan 00296)
        # is the ONLY sub-project resolution mechanism (Plan 00300 hard
        # cutover removed the monorepo_subproject_patterns regex alias).
        subproject_relative = self._declared_subproject_relative(normalized)
        if subproject_relative is not None:
            # Path is within a declared or pattern-configured sub-project.
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

        When _extra_allowed_markdown_paths is configured, those regex patterns
        are ADDITIVE: a path the base check (built-in OR override) would block is
        rescued (allowed) if it matches at least one extra pattern. This lets a
        project add locations without redeclaring the entire default set.

        Args:
            normalized: Project-relative normalized path

        Returns:
            True if the location is INVALID (should be blocked)
        """
        # When custom allowed paths are configured, they override ALL built-in logic
        if self._allowed_markdown_paths is not None:
            base_invalid = self._check_custom_paths(normalized)
        else:
            base_invalid = self._check_builtin_paths(normalized)

        # Additive extra paths rescue a blocked location (layered on top of base)
        if base_invalid and self._matches_extra_allowed(normalized):
            return False  # Allowed via extra_allowed_markdown_paths

        return base_invalid

    def _matches_extra_allowed(self, normalized: str) -> bool:
        """Check path against additive extra_allowed_markdown_paths regex patterns.

        Args:
            normalized: Project-relative normalized path

        Returns:
            True if the path matches at least one extra pattern (should be allowed)
        """
        for pattern in self._extra_allowed_markdown_paths or []:
            if re.match(pattern, normalized, re.IGNORECASE):
                return True
        return False

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

    def _check_plan_folder_path(self, normalized: str, plan_dir_prefix: str) -> bool:
        """Validate a path already known to be under the plan directory.

        Args:
            normalized: Project-relative normalized path
            plan_dir_prefix: Lower-cased plan directory prefix with trailing
                slash (e.g. ``"claude/plan/"``)

        Returns:
            True if the location is INVALID (should be blocked)
        """
        escaped_prefix = re.escape(plan_dir_prefix)

        # Extract plan folder pattern: {plan_dir}/{folder}/PLAN.md
        # OR: {plan_dir}/{subdirectory}/{folder}/PLAN.md
        plan_match = re.match(rf"^{escaped_prefix}([^/]+)/", normalized, re.IGNORECASE)
        if not plan_match:
            return False  # File directly in the plan dir root — allow

        folder_name = plan_match.group(1).lower()

        # Check if the first segment is a known archive subdirectory
        # (plan_workflow.qa.completed_dir/cancelled_dir plus the legacy
        # 'archive' extra — see _plan_archive_dirs_lower)
        if folder_name in self._plan_archive_dirs_lower():
            # For subdirectories, validate the SECOND path segment
            subdir_match = re.match(rf"^{escaped_prefix}[^/]+/([^/]+)/", normalized, re.IGNORECASE)
            if subdir_match:
                folder_name = subdir_match.group(1)
            else:
                return False  # Subdirectory without nested plan folder - allow

        # Validate folder name has numeric prefix
        number_match = re.match(r"^(\d+)-", folder_name)
        if not number_match:
            return True  # Block - missing plan number

        # Validate plan number has at least 3 digits
        return len(number_match.group(1)) < 3  # Block - insufficient digits

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

        # 0.1. src/claude_code_hooks_daemon/skills/ - Deployed skill files (packaged with daemon)
        if re.match(r"^src/claude_code_hooks_daemon/skills/.*\.md$", normalized, re.IGNORECASE):
            return False  # Allow

        # 1. Plan directory (facade: plan_workflow.directory) - validate plan
        # number folder format. Checked BEFORE the agent-docs-tree branch
        # below: the plan directory is not guaranteed to be nested under it
        # (a project may configure them independently), though by default
        # ("CLAUDE/Plan" under "CLAUDE") it is.
        plan_dir_prefix = self._plan_dir().strip("/").lower() + "/"
        if normalized.lower().startswith(plan_dir_prefix):
            return self._check_plan_folder_path(normalized, plan_dir_prefix)

        # 2. Agent-facing doc tree (facade: documentation.trees.agent) -
        # allow all files and subdirectories.
        agent_dir_prefix = self._agent_docs_dir().strip("/").lower() + "/"
        if normalized.lower().startswith(agent_dir_prefix):
            return False  # Allow

        # 3. Human-facing doc tree (facade: documentation.trees.human)
        human_dir_prefix = self._human_docs_dir().strip("/").lower() + "/"
        if normalized.lower().startswith(human_dir_prefix):
            return False  # Allow

        # 4. untracked/ - Temporary docs
        if normalized.lower().startswith("untracked/"):
            return False  # Allow

        # 5. RELEASES/ - Release notes
        if normalized.lower().startswith("releases/"):
            return False  # Allow

        # 6. eslint-rules/ - ESLint rule docs
        if re.match(r"^eslint-rules/.*\.md$", normalized, re.IGNORECASE):
            return False  # Allow

        return True  # Block — no rule matched

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Handle markdown write based on location.

        Planning mode writes are redirected to project structure.
        Other invalid locations are denied with guidance.
        """
        # Policy: forbid untracked Claude memory. Emit the SPECIALIST tracked-docs
        # message (distinct from the generic wrong-location one) for any memory
        # write — Write/Edit tool OR bash redirect/tee side-door. Plan 00131.
        if not self._allow_untracked_claude_memory:
            memory_target = self._claude_memory_block_target(hook_input)
            if memory_target is not None:
                return self._deny_untracked_memory(memory_target, hook_input)

        file_path = get_file_path(hook_input)
        if not file_path:
            return GatingResult(decision=Decision.ALLOW)

        # Check if this is a planning mode write to redirect
        if self._track_plans_in_project and self.is_planning_mode_write(file_path):
            return self.handle_planning_mode_write(hook_input)

        # Otherwise, deny with the generic wrong-location message.
        return self._deny_wrong_location(file_path, hook_input)

    def get_rules(self) -> list[Rule]:
        """Return the 3 Rule objects backing this handler's blocking behaviour."""
        return [_RULE_WRONG_LOCATION, _RULE_UNTRACKED_MEMORY, _RULE_PLAN_SYNC]

    def _deny_wrong_location(self, file_path: str, hook_input: dict[str, Any]) -> GatingResult:
        """Deny a write to an unrecognised location, verbose-first/terse-after.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The attempted file path
        is appended on every fire — it changes per invocation.
        """
        formatter = RuleFormatter()
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.MARKDOWN_WRONG_LOCATION
        ):
            message = formatter.terse(_RULE_WRONG_LOCATION)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.MARKDOWN_WRONG_LOCATION)
            message = formatter.verbose(_RULE_WRONG_LOCATION)

        message += f"\n\nAttempted to write: {file_path}"

        return GatingResult(decision=Decision.DENY, reason=message)

    def _deny_untracked_memory(
        self, target: str, hook_input: dict[str, Any] | None = None
    ) -> GatingResult:
        """Specialist DENY for the forbid-untracked-memory policy.

        Distinct from the generic wrong-location message: it explains the policy,
        confirms reads stay allowed (for migration), and routes durable knowledge
        into tracked project docs using progressive disclosure. Plan 00131.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The blocked target path
        is appended on every fire — it changes per invocation.
        """
        formatter = RuleFormatter()
        transcript_path = (
            hook_input.get(HookInputField.TRANSCRIPT_PATH) if hook_input is not None else None
        )
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.MARKDOWN_UNTRACKED_MEMORY
        ):
            message = formatter.terse(_RULE_UNTRACKED_MEMORY)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.MARKDOWN_UNTRACKED_MEMORY)
            message = formatter.verbose(_RULE_UNTRACKED_MEMORY)

        message += f"\n\nBlocked write: {target}"

        return GatingResult(decision=Decision.DENY, reason=message)

    def get_claude_md(self) -> str | None:
        if not self._allow_untracked_claude_memory:
            return (
                "## markdown_organization — tracked-docs policy (untracked Claude memory BLOCKED)\n\n"
                "This project sets `allow_untracked_claude_memory: false`. Writing to Claude\n"
                "auto-memory files (`~/.claude/projects/*/memory/*.md`) is **blocked** — via the\n"
                "Write/Edit tools AND via bash side-doors. **Reading memory is\n"
                "still allowed** so existing memory can be migrated out.\n\n"
                "**The bash coverage is wide but still not every route.** Detected: `>`,\n"
                "`>>`, `>|`, `&>`, `&>>`, every `tee` operand, `cp`/`mv`/`install`\n"
                "destinations, `dd of=`, quoted targets containing spaces, `~` paths, and\n"
                "heredoc bodies. A copy INTO a directory is resolved to the file it really\n"
                "writes, so `cp note.md <memory-dir>` and `cp -t <memory-dir> note.md` are\n"
                "both caught. NOT detected, because no single written path can be named: a\n"
                'target needing an expansion — a variable (`> "$OUT"`) or a glob — and a\n'
                "script that opens the file itself. `$HOME` specifically IS still caught, by\n"
                "a separate raw-string scan. Treat the rule as the policy and honour it — do\n"
                "not read an unblocked command as permission. The markdown-LOCATION rule\n"
                "below is checked on `Write`/`Edit` only, with no bash detection at all.\n\n"
                "**Put durable knowledge in TRACKED project docs (progressive disclosure):**\n\n"
                "- Always-relevant facts → `CLAUDE.md` (keep lean; resident every session)\n"
                "- Path-specific guidance → `.claude/rules/*.md` with `paths:` glob frontmatter "
                "(loads on demand only when matching files are touched)\n"
                "- Intent-triggered procedures → a thin skill under `.claude/skills/` pointing "
                "at a single-source-of-truth doc body\n"
                "- Human-facing reference → `docs/`\n"
                "- Link docs with plain markdown links (zero token cost until followed); "
                "**avoid `@`-imports** (they re-inline eagerly rather than defer)\n\n"
                "Keep ONE source of truth per fact and link to it. Normal markdown-location "
                "rules (below) still apply to every other `.md` file.\n\n"
                "**Allowed locations**: `CLAUDE/`, `docs/`, `RELEASES/`, `CLAUDE/Plan/`, "
                "root-level `README.md`, `.claude/rules/`, or any `extra_allowed_markdown_paths` "
                "pattern."
            )
        return (
            "## markdown_organization — markdown files must go in allowed locations\n\n"
            "Writing a new `.md` file to an unrecognised location is blocked. "
            "Markdown files must be placed in project-configured allowed paths.\n\n"
            "**Common allowed locations**: `CLAUDE/`, `docs/`, `RELEASES/`, `CLAUDE/Plan/`, "
            "root-level `README.md`, or any path matching the `allowed_markdown_paths` config.\n\n"
            "**Dependency directories**: `vendor/` (PHP) and `node_modules/` (JS) are treated "
            "as implicit monorepos — each package is a sub-project where normal markdown rules "
            "apply (e.g. `vendor/acme/lib/docs/guide.md` is allowed, "
            "`vendor/acme/lib/random/notes.md` is blocked).\n\n"
            "**Plan file redirection**: when `track_plans_in_project` is enabled, Claude Code "
            "planning mode writes are automatically redirected to the project's `CLAUDE/Plan/` "
            "directory. Plan folders must follow the `NNNN-description/` naming convention.\n\n"
            "If you need a markdown file in a new location, add a pattern to "
            "`extra_allowed_markdown_paths` in `.claude/hooks-daemon.yaml`. This is ADDITIVE — "
            "it layers your patterns on top of the built-in defaults, so you keep `CLAUDE/`, "
            "`docs/`, `RELEASES/`, etc. without redeclaring them. The older `allowed_markdown_paths` "
            "option REPLACES all built-in locations and is discouraged for simple additions.\n\n"
            "If your project has sub-projects with their own `docs/`, `CLAUDE/`, etc., "
            "declare each one as a `projects:` entry in `.claude/hooks-daemon.yaml` "
            "(see `CLAUDE/Code/WorkspaceResolution.md`) so normal rules apply within "
            "each sub-project. This is the ONLY sub-project mechanism — projects are "
            "DECLARED, never inferred. `monorepo_subproject_patterns` was removed "
            "(Plan 00300 hard cutover) and is now a hard config-validation error."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Markdown Organization."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Block markdown in wrong location",
                command=(
                    "Use the Write tool to write to $CLAUDE_PROJECT_DIR/random-notes.md"
                    " with content '# Some Notes\\n\\nRandom markdown file.'"
                ),
                description="Blocks markdown files written to non-standard locations within the project",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"WRONG LOCATION", r"allowed"],
                safety_notes="Writes to workspace root - handler blocks before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=[],
                cleanup_commands=[],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
