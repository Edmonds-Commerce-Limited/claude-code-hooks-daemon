"""ValidatePlanNumberHandler - validates plan folder numbering BEFORE directory creation."""

import logging
import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ProjectPath,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, ProjectContext
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path
from claude_code_hooks_daemon.handlers.utils.plan_numbering import (
    PLAN_NUMBER_WIDTH,
    next_plan_number_for_target,
    record_plan_allocation,
)

logger = logging.getLogger(__name__)


class ValidatePlanNumberHandler(Handler):
    """
    Validate plan folder numbering to ensure sequential plans.

    IMPORTANT: This runs as PreToolUse (BEFORE directory creation) to avoid
    the timing bug where PostToolUse sees the just-created directory as existing.

    The bug scenario (PostToolUse - WRONG):
    1. User finds highest plan: 060
    2. User creates CLAUDE/Plan/061-new/ (correct: 060 + 1)
    3. PostToolUse runs AFTER directory exists
    4. Handler sees 061 as existing, says "use 062" (FALSE WARNING!)

    The fix (PreToolUse - CORRECT):
    1. User finds highest plan: 060
    2. PreToolUse runs BEFORE mkdir/write
    3. Handler sees highest as 060, validates 061 is correct
    4. No false warning - operation proceeds

    SKIP VALIDATION FOR:
    - Files in .claude/commands/ (slash command documentation)
    - Files in .claude/hooks/ (hook documentation)
    - Bash heredoc content (documentation examples)
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.VALIDATE_PLAN_NUMBER,
            priority=Priority.VALIDATE_PLAN_NUMBER,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self.workspace_root = ProjectContext.project_root()
        self._track_plans_in_project: str | None = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if creating a NEW plan folder.

        Only genuinely-new plan folders are number-validated. A Write/Edit to a
        file inside an ALREADY-EXISTING plan folder (an edit/rewrite of an
        existing plan), or an ``mkdir`` of a folder that already exists, is NOT
        a creation — the handler must not fire (Plan 00138).
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Check Write operations
        if tool_name == ToolName.WRITE:
            file_path = get_file_path(hook_input)
            if file_path:
                # Skip documentation/command files
                if self._is_documentation_file(file_path):
                    return False

                # Match plan folder creation (direct children of Plan/ only)
                # CLAUDE/Plan/NNN-name/ matches, CLAUDE/Plan/Subfolder/NNN-name/ does not
                match = re.search(r"(.*CLAUDE/Plans?/\d+-[^/]+)/", file_path)
                if match:
                    # Editing a file inside an existing plan folder is not creation.
                    return not self._plan_folder_exists(match.group(1))

        # Check Bash mkdir commands
        if tool_name == ToolName.BASH:
            command = get_bash_command(hook_input)
            if command:
                # Skip heredoc commands (documentation)
                if self._is_heredoc_command(command):
                    return False

                # Match mkdir for plan folders (direct children of Plan/ only)
                # Use [^&;]* instead of .*? to prevent spanning across && or ;
                # command boundaries into unrelated git mv arguments
                match = re.search(r"mkdir[^&;]*?(\S*CLAUDE/Plans?/\d+-[^\s/]+)", command)
                if match:
                    # mkdir of an already-existing plan folder is a no-op re-create.
                    return not self._plan_folder_exists(match.group(1))

        return False

    def _plan_folder_exists(self, plan_path: str) -> bool:
        """Whether the plan folder at ``plan_path`` already exists on disk."""
        return self._resolve_target(plan_path).is_dir()

    def _is_documentation_file(self, file_path: str) -> bool:
        """Check if file is documentation (skip validation for these)."""
        # Normalize path
        path_lower = file_path.lower()

        # Skip slash command files
        if "/.claude/commands/" in path_lower:
            return True

        # Skip hook documentation
        return bool(
            "/.claude/hooks/" in path_lower
            and (path_lower.endswith(".md") or path_lower.endswith("readme"))
        )

    def _is_heredoc_command(self, command: str) -> bool:
        """Check if bash command is a heredoc (cat > file << EOF)."""
        # Match heredoc patterns: cat > file << 'EOF' or cat > file << EOF
        return bool(re.search(r'<<\s*["\']?\w+["\']?', command))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Validate plan number is sequential (git-anchored, per-repo)."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        plan_path: str | None = None
        plan_number: int | None = None
        plan_number_str: str | None = None  # original digits as typed (zero-padding preserved)
        plan_name: str | None = None

        # Extract the full plan-folder path, number and name.
        if tool_name == ToolName.WRITE:
            file_path = get_file_path(hook_input)
            if file_path:
                match = re.search(r"(.*CLAUDE/Plans?/(\d+)-([^/]+))/", file_path)
                if match:
                    plan_path = match.group(1)
                    plan_number_str = match.group(2)
                    plan_number = int(plan_number_str)
                    plan_name = match.group(3)

        elif tool_name == ToolName.BASH:
            command = get_bash_command(hook_input)
            if command:
                match = re.search(r"mkdir[^&;]*?(\S*CLAUDE/Plans?/(\d+)-([^\s/]+))", command)
                if match:
                    plan_path = match.group(1)
                    plan_number_str = match.group(2)
                    plan_number = int(plan_number_str)
                    plan_name = match.group(3)

        if plan_number is None or plan_path is None or plan_number_str is None:
            return HookResult(decision=Decision.ALLOW)

        plan_dir = self._track_plans_in_project or ProjectPath.PLAN_DIR
        target = self._resolve_target(plan_path)
        expected_number = int(next_plan_number_for_target(target, plan_dir, self.workspace_root))

        # Allow ``expected`` (normal: dir not yet created) and ``expected - 1``
        # (TOCTOU: mkdir already created the dir, so a bootstrap scan counted it
        # as the high-water mark and expected jumped one ahead).
        if plan_number not in (expected_number, expected_number - 1):
            # Echo the actual folder name back VERBATIM (zero-padding preserved):
            # int() would strip leading zeros, rendering ``00135-x`` as ``135-x``
            # (Plan 00138). The corrected example uses the zero-padded convention.
            expected_padded = f"{expected_number:0{PLAN_NUMBER_WIDTH}d}"
            error_message = f"""
PLAN NUMBER INCORRECT

You are creating: {plan_dir}/{plan_number_str}-{plan_name}/
Expected next number: {expected_number}

The next plan number is tracked per-repository in git config
(`hooksdaemon.latestPlanNumber`), so it is stable across branches and
correct even inside nested/vendor repos. You do NOT need to scan the
filesystem — use the expected number directly.

YOU MUST FIX THIS NOW:

Use the correct plan number: {expected_number}

Example:
```bash
mkdir -p {plan_dir}/{expected_padded}-{plan_name}
```

See: {plan_dir}/CLAUDE.md for full instructions
"""
            return HookResult(decision=Decision.ALLOW, context=[error_message])

        # Valid number — advance the per-repo high-water mark to record the
        # creation so the next plan reads ``counter + 1``.
        self._record_allocation(target, plan_number)

        return HookResult(decision=Decision.ALLOW)

    def _record_allocation(self, target: Path, plan_number: int) -> None:
        """Advance the per-repo plan high-water mark, tolerating git failures.

        This handler is advisory: a counter-write failure must not block the
        plan creation. The failure is logged with a full traceback and
        execution continues — the next read re-bootstraps from a filesystem
        scan, so the counter self-heals rather than silently going stale.
        """
        try:
            record_plan_allocation(target, plan_number)
        except Exception:
            logger.warning(
                "validate_plan_number: failed to record plan allocation for %s",
                target,
                exc_info=True,
            )

    def _resolve_target(self, plan_path: str) -> Path:
        """Absolute path to the plan folder, for repo resolution.

        Bash ``mkdir`` paths may be relative to the project root; Write
        ``file_path`` values are absolute (enforced by the absolute_path
        handler). Relative paths are anchored to the workspace root.
        """
        path = Path(plan_path)
        if not path.is_absolute():
            path = self.workspace_root / path
        return path

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Validate Plan Number."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Plan number validation - wrong number",
                command=(
                    "Use the Write tool to write to /workspace/CLAUDE/Plan/999-wrong-number/PLAN.md"
                    " with content '# Plan 999: Wrong Number\\n\\n**Status**: Not Started'"
                ),
                description="Warns when plan number is not sequential (advisory, non-blocking)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"PLAN NUMBER", r"[Ee]xpected"],
                safety_notes="Advisory handler - warns about wrong plan number but allows operation.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
