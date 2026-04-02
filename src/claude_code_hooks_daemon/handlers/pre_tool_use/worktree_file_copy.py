"""WorktreeFileCopyHandler - prevents copying files between worktrees and main repo."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command

# Both worktree root prefixes — untracked/ is manually managed, .claude/ is Claude Code managed
_WORKTREE_PREFIXES = (ProjectPath.WORKTREES_DIR, ProjectPath.CLAUDE_WORKTREES_DIR)

# Regex alternation matching either worktree root (used in pattern strings below)
_WORKTREE_RE = r"(?:untracked/worktrees|\.claude/worktrees)"


class WorktreeFileCopyHandler(Handler):
    """Prevent copying files between worktrees and main repo."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.WORKTREE_FILE_COPY,
            priority=Priority.WORKTREE_FILE_COPY,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )

    def _is_same_worktree_operation(self, command: str) -> bool:
        """Return True if both paths in command refer to the same worktree branch."""
        for prefix in _WORKTREE_PREFIXES:
            if command.count(prefix) >= 2:
                escaped = re.escape(prefix)
                branches = re.findall(rf"{escaped}/([^/\s]+)", command)
                if len(branches) >= 2 and branches[0] == branches[1]:
                    return True
        return False

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if copying between worktree and main repo."""
        command = get_bash_command(hook_input)
        if not command:
            return False

        if not any(prefix in command for prefix in _WORKTREE_PREFIXES):
            return False

        # Check for forbidden operations
        if not re.search(r"\b(cp|mv|rsync)\b", command, re.IGNORECASE):
            return False

        # Check patterns
        patterns = [
            rf"{_WORKTREE_RE}/[^/\s]+/\S+\s+.*\b(src/|tests/|config/)",
            rf"rsync.*{_WORKTREE_RE}.*\b(src|tests|config)\b",
        ]

        for pattern in patterns:
            if re.search(pattern, command, re.IGNORECASE):
                if self._is_same_worktree_operation(command):
                    continue
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block worktree file copying."""
        command = get_bash_command(hook_input)

        return HookResult(
            decision=Decision.DENY,
            reason=(
                "❌ BLOCKED: Attempting to copy files from worktree to main repo\n\n"
                f"Command: {command}\n\n"
                "🔥 WHY THIS IS CATASTROPHIC:\n"
                "  1. Defeats entire purpose of worktrees (isolation)\n"
                "  2. Destroys branch isolation\n"
                "  3. Loses git history (bypasses git tracking)\n"
                "  4. Nukes untracked work in target directory\n"
                "  5. Creates merge conflicts\n\n"
                "✅ CORRECT WORKFLOW:\n"
                "  1. cd untracked/worktrees/your-branch\n"
                "  2. git add . && git commit -m 'feat: changes'\n"
                "  3. cd /workspace (main repo)\n"
                "  4. git merge your-branch\n\n"
                "📖 See CLAUDE/Worktree.md for complete guide."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## worktree_file_copy — do not copy files between worktrees and the main repo\n\n"
            "`cp`, `mv`, and `rsync` operations that move files from a worktree directory "
            "(`untracked/worktrees/` or `.claude/worktrees/`) into the main repo "
            "(`src/`, `tests/`, `config/`) — or vice versa — are blocked.\n\n"
            "Worktrees are isolated branches. Cross-copying corrupts that isolation "
            "and can silently overwrite in-progress work.\n\n"
            "**Allowed**: operations within the same worktree branch. "
            "**To merge changes**: use `git merge` or `git cherry-pick` instead."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for worktree file copy handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="cp from worktree to main repo",
                command='echo "cp untracked/worktrees/feature-branch/src/file.py src/"',
                description="Blocks copying files from worktree to main repo (breaks isolation)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"CATASTROPHIC",
                    r"worktree.*isolation",
                    r"git merge",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="rsync from worktree to main repo",
                command='echo "rsync -av untracked/worktrees/feature/src/ src/"',
                description="Blocks rsync from worktree to main repo",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"worktree to main repo",
                    r"git history",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
