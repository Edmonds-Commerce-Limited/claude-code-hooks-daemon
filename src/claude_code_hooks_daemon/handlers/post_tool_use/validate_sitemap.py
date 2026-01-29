"""ValidateSitemapHandler - reminds to validate sitemap files after editing."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path


class ValidateSitemapHandler(Handler):
    """Remind to validate sitemap files after editing."""

    def __init__(self) -> None:
        super().__init__(
            name="validate-sitemap-on-edit",
            priority=Priority.VALIDATE_SITEMAP,
            tags=[HandlerTag.VALIDATION, HandlerTag.EC_SPECIFIC, HandlerTag.PROJECT_SPECIFIC, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if editing sitemap markdown file."""
        tool_name = hook_input.get("tool_name")
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Check if file is in CLAUDE/Sitemap/ directory
        if "CLAUDE/Sitemap" not in file_path:
            return False

        # Ignore CLAUDE/Sitemap/CLAUDE.md itself (documentation file)
        if file_path.endswith("CLAUDE/Sitemap/CLAUDE.md"):
            return False

        # Must be a markdown file
        return file_path.endswith(".md")

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Add reminder to validate sitemap after editing."""
        file_path = get_file_path(hook_input)

        reminder = f"""
⚠️ REMINDER: Sitemap file modified: {file_path}

After completing your edits, you SHOULD validate the sitemap:

Run sitemap-validator agent:
  Task tool:
    subagent_type: sitemap-validator
    prompt: Validate sitemap file: {file_path}
    model: haiku

The validator checks:
  ✓ No content (statistics, prose, descriptions)
  ✓ No hallucinated components (must exist in src/components/CLAUDE.md)
  ✓ No implementation details (props, code, styling)
  ✓ Correct notation (CSI enums, arrow syntax)

Result: ✅ PASS or ❌ FAIL with violation details

If using the sitemap skill, validation runs automatically in the modify→validate→fix loop.
"""

        return HookResult(decision=Decision.ALLOW, context=[reminder])
