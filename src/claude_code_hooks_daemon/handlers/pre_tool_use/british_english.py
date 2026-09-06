"""BritishEnglishHandler - warns about American English spellings in content files."""

import re
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Fallback doc-tree dirs, used only when no ProjectLayout facade was
# injected. Mirror the Config defaults exactly (DocumentationTreesConfig
# agent/human), same convention as markdown_organization's fallbacks.
_FALLBACK_AGENT_DOCS_DIR: Final[str] = "CLAUDE"
_FALLBACK_HUMAN_DOCS_DIR: Final[str] = "docs"

#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR: Final[str] = "acceptance-test-british"

# Non-layout extra: a directory this project checks that is NOT a
# documentation-tree truth (it is a handler BEHAVIOUR default, Plan 00288
# Task 4.5/C7), so it stays a handler option rather than moving into the
# facade.
_DEFAULT_EXTRA_CHECK_DIRECTORIES: Final[tuple[str, ...]] = ("private_html",)


class BritishEnglishHandler(PreToolUseHandlerBase):
    """Warn about American English spellings in content files (non-blocking)."""

    # REPO-scoped (Plan 00301 follow-up): agent_docs_dir/human_docs_dir are
    # sourced from the ROOT project's `documentation.trees` config even when
    # composing a declared sub-project's ProjectLayout (see
    # ProjectLayout.for_project / CLAUDE/Code/WorkspaceResolution.md) --
    # there is no per-project override, so per-file resolution would be a
    # no-op. The doc-tree axis is repository-singular by design.
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.REPO

    # Common American -> British spelling patterns
    SPELLING_CHECKS: ClassVar[dict[str, str]] = {
        r"\bcolor\b": "colour",
        r"\bfavor\b": "favour",
        r"\bbehavior\b": "behaviour",
        r"\borganize\b": "organise",
        r"\brecognize\b": "recognise",
        r"\banalyze\b": "analyse",
        r"\bcenter\b": "centre",
        r"\bmeter\b": "metre",
        r"\bliter\b": "litre",
    }

    CHECK_EXTENSIONS: ClassVar[list[str]] = [".md", ".ejs", ".html", ".txt"]

    def __init__(self) -> None:
        # Non-terminal (terminal=False) - allows operation but adds warning context
        super().__init__(
            handler_id=HandlerID.BRITISH_ENGLISH,
            priority=Priority.BRITISH_ENGLISH,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.CONTENT_QUALITY,
                HandlerTag.EC_PREFERENCE,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Config option: extra directories to check, additive on top of the
        # ProjectLayout facade's agent/human docs trees (Plan 00288 Task 4.5).
        # Set via setattr after __init__ from handler options.
        self._extra_check_directories: list[str] = list(_DEFAULT_EXTRA_CHECK_DIRECTORIES)

    @property
    def CHECK_DIRECTORIES(self) -> list[str]:
        """Effective directories to check: facade docs trees + extras.

        Reads the ProjectLayout facade's agent_docs_dir/human_docs_dir
        instead of hardcoding CLAUDE/docs; falls back to the matching Config
        defaults when no facade was injected, so zero-config behaviour is
        unchanged.
        """
        layout = self._project_layout
        agent_dir = layout.agent_docs_dir if layout is not None else _FALLBACK_AGENT_DOCS_DIR
        human_dir = layout.human_docs_dir if layout is not None else _FALLBACK_HUMAN_DOCS_DIR
        return [*self._extra_check_directories, human_dir, agent_dir]

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing content files with potential American spellings."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Only check content files
        if not any(file_path.endswith(ext) for ext in self.CHECK_EXTENSIONS):
            return False

        # Only check certain directories
        if not any(dir in file_path for dir in self.CHECK_DIRECTORIES):
            return False

        content = get_file_content(hook_input)
        if tool_name == ToolName.EDIT:
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return False

        # Check for American spellings (skip code blocks in markdown)
        issues = self._check_british_english(content)
        return len(issues) > 0

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Warn about American spellings but allow operation."""
        file_path = get_file_path(hook_input)
        content = get_file_content(hook_input)
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        if tool_name == ToolName.EDIT:
            content = hook_input.get(HookInputField.TOOL_INPUT, {}).get("new_string", "")

        if not content:
            return GatingResult(decision=Decision.ALLOW)

        issues = self._check_british_english(content)

        # WARNING: We allow the operation but print a warning
        warning_parts = [f"⚠️  American English detected in {file_path}:\n"]

        for issue in issues[:5]:  # Show max 5 issues
            warning_parts.append(
                f"  Line {issue['line']}: '{issue['american']}' → use '{issue['british']}'\n"
                f"    {issue['text']}\n"
            )

        if len(issues) > 5:
            warning_parts.append(f"  ... and {len(issues) - 5} more issue(s)\n")

        warning_parts.append(
            "\n✅ CORRECT SPELLING: Please use British English.\n"
            "If this is intentional (e.g., in a quote), you can ignore this warning.\n"
        )

        # Return allow with warning in context (advisory messages use context, not reason)
        return GatingResult(decision=Decision.ALLOW, context=["".join(warning_parts)])

    def _check_british_english(self, content: str) -> list[dict[str, Any]]:
        """Check content for American spellings, skipping code blocks.

        Deprecated alias for :meth:`find_american_spellings`, kept because the
        handler's own tests call it by this name.
        """
        return self.find_american_spellings(content)

    def find_american_spellings(self, content: str) -> list[dict[str, Any]]:
        """Find American spellings in ``content``, skipping fenced code blocks.

        Public so the batch equivalent of this rule
        (``scripts/qa/check_british_english.py``) can share the implementation
        rather than reimplement it. The word list lives in
        :attr:`SPELLING_CHECKS`, which that checker imports by identity — one
        definition of the rule, two surfaces enforcing it.

        Returns:
            One dict per finding with ``line``, ``american``, ``british`` and a
            truncated ``text`` excerpt.
        """
        issues = []
        lines = content.split("\n")
        in_code_block = False

        for line_num, line in enumerate(lines, 1):
            # Toggle code block state
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue

            # Skip lines in code blocks
            if in_code_block:
                continue

            # Check for American spellings
            for american_pattern, british in self.SPELLING_CHECKS.items():
                match = re.search(american_pattern, line, re.IGNORECASE)
                if match:
                    issues.append(
                        {
                            "line": line_num,
                            "american": match.group(),
                            "british": british,
                            "text": line.strip()[:80],  # Truncate long lines
                        }
                    )

        return issues

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for British English."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="American spellings in markdown",
                command=(
                    "Use the Write tool to write to "
                    f"{scratch_path(_FIXTURE_DIR, 'docs', 'style-guide.md')}"
                    " with content 'The color of the organization logo should favor readability.'"
                ),
                description="Advises British spellings but allows operation (advisory)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"colour", r"British"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Advisory handler "
                    "allows write but warns."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p untracked/scratch/{_FIXTURE_DIR}/docs"],
                cleanup_commands=[f"rm -rf untracked/scratch/{_FIXTURE_DIR}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
