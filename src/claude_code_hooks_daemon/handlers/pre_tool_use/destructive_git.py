"""DestructiveGitHandler - blocks destructive git commands that permanently destroy data."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, get_data_layer
from claude_code_hooks_daemon.core.utils import get_bash_command


class DestructiveGitHandler(Handler):
    """Block destructive git commands that permanently destroy data."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=Priority.DESTRUCTIVE_GIT,
            tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self.destructive_patterns = [
            r"\bgit\s+reset\s+.*--hard\b",
            r"\bgit\s+clean\s+.*-[a-z]*f",
            r"\bgit\s+checkout\s+\.\s*(?:$|;|&&|\|)",
            # SECURITY FIX: Match all variants of checkout with -- and file
            # Matches: git checkout -- file
            # Matches: git checkout HEAD -- file
            # Matches: git checkout main -- file
            # Matches: git checkout @{upstream} -- file
            r"\bgit\s+checkout\s+.*--\s+\S",
            # SECURITY FIX: Match git restore with file paths (discards working tree changes)
            # Matches: git restore file.txt
            # Matches: git restore src/main.py
            # Matches: git restore --worktree file.txt
            # Does NOT match: git restore --staged file.txt (safe - only unstages)
            r"\bgit\s+restore\s+(?!--staged).*\S",
            r"\bgit\s+stash\s+(?:drop|clear)\b",
            # Block force push
            r"\bgit\s+push\s+.*--force\b",
            # Block force branch deletion (bypasses merge check, can lose unmerged work)
            # Uses (?-i:) to match only uppercase -D (lowercase -d is safe, checks merge status)
            r"\bgit\s+branch\s+.*(?-i:-D)\b",
        ]

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a destructive git command."""
        command = get_bash_command(hook_input)
        if not command or "git" not in command.lower():
            return False

        # Check for any destructive git pattern
        for pattern in self.destructive_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True

        return False

    def _get_block_count(self) -> int:
        """Get number of previous blocks by this handler."""
        try:
            return get_data_layer().history.count_blocks_by_handler(self.name)
        except Exception:
            return 0

    def _terse_reason(self, reason: str, command: str) -> str:
        """Generate terse reason message (first block)."""
        return f"BLOCKED: {reason}. Ask the user to run manually."

    def _standard_reason(self, reason: str, command: str) -> str:
        """Generate standard reason message (blocks 2-3)."""
        return (
            f"BLOCKED: {reason}\n\n"
            f"Command: {command}\n\n"
            "SAFE alternatives:\n"
            "  - git stash        (save changes, can recover later)\n"
            "  - git diff         (review changes first)\n"
            "  - git status       (see what would be affected)\n"
            "  - git commit       (save changes permanently first)\n\n"
            "Ask the user to run this manually if needed."
        )

    def _verbose_reason(self, reason: str, command: str) -> str:
        """Generate verbose reason message (blocks 4+)."""
        return (
            f"BLOCKED: Destructive git command detected\n\n"
            f"Reason: {reason}\n\n"
            f"Command: {command}\n\n"
            "This command PERMANENTLY DESTROYS uncommitted changes with NO recovery possible.\n\n"
            "If this operation is truly necessary, you must ask the human user to run it manually.\n\n"
            "SAFE alternatives:\n"
            "  - git stash        (save changes, can recover later)\n"
            "  - git diff         (review changes first)\n"
            "  - git status       (see what would be affected)\n"
            "  - git commit       (save changes permanently first)\n\n"
            "The LLM is NOT ALLOWED to run destructive git commands. Ask the user to do it."
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the destructive command with explanation."""
        command = get_bash_command(hook_input)
        if not command:
            return HookResult(decision=Decision.ALLOW)

        # Determine which pattern matched and provide specific reason
        if re.search(r"\bgit\s+reset\s+.*--hard\b", command, re.IGNORECASE):
            specific_reason = "git reset --hard destroys all uncommitted changes permanently"
        elif re.search(r"\bgit\s+clean\s+.*-[a-z]*f", command, re.IGNORECASE):
            specific_reason = "git clean -f permanently deletes untracked files"
        elif re.search(r"\bgit\s+stash\s+drop\b", command, re.IGNORECASE):
            specific_reason = "git stash drop permanently destroys stashed changes"
        elif re.search(r"\bgit\s+stash\s+clear\b", command, re.IGNORECASE):
            specific_reason = "git stash clear permanently destroys all stashed changes"
        elif re.search(r"\bgit\s+checkout\s+.*--\s+\S", command, re.IGNORECASE):
            specific_reason = (
                "git checkout [REF] -- file discards all local changes to that file permanently"
            )
        elif re.search(r"\bgit\s+restore\s+(?!--staged)", command, re.IGNORECASE):
            specific_reason = "git restore discards all local changes to files permanently"
        elif re.search(r"\bgit\s+push\s+.*--force\b", command, re.IGNORECASE):
            specific_reason = (
                "git push --force can overwrite remote history and destroy team members' work"
            )
        elif re.search(r"\bgit\s+branch\s+.*(?-i:-D)\b", command, re.IGNORECASE):
            specific_reason = (
                "git branch -D force-deletes a branch without checking if it has been merged"
            )
        else:
            specific_reason = "This git command destroys uncommitted changes permanently"

        # Get block count and determine verbosity level
        block_count = self._get_block_count()

        if block_count == 0:
            reason = self._terse_reason(specific_reason, command)
        elif block_count <= 2:
            reason = self._standard_reason(specific_reason, command)
        else:
            reason = self._verbose_reason(specific_reason, command)

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for destructive git handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="git reset --hard",
                command='echo "git reset --hard NONEXISTENT_REF_SAFE_TEST"',
                description="Blocks git reset --hard (destroys uncommitted changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"destroys.*uncommitted changes",
                ],
                safety_notes="Uses non-existent ref - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="git clean -f",
                command='echo "git clean -fd /nonexistent/safe/test/path"',
                description="Blocks git clean -f (permanently deletes untracked files)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"permanently deletes untracked files",
                ],
                safety_notes="Uses non-existent path - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="git push --force",
                command='echo "git push --force NONEXISTENT_REMOTE NONEXISTENT_BRANCH"',
                description="Blocks git push --force (overwrites remote history)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"overwrite remote history",
                    r"destroy.*work",
                ],
                safety_notes="Uses non-existent remote/branch - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="git stash drop",
                command='echo "git stash drop stash@{999}"',
                description="Blocks git stash drop (permanent deletion)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"permanently destroys",
                    r"stash",
                ],
                safety_notes="Uses non-existent stash index - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="git checkout --",
                command='echo "git checkout -- /nonexistent/safe/test/file.py"',
                description="Blocks git checkout -- (discards changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"discards.*local changes",
                    r"permanently",
                ],
                safety_notes="Uses non-existent file path - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="git restore",
                command='echo "git restore /nonexistent/safe/test/file.py"',
                description="Blocks git restore (discards working tree changes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"discards.*local changes",
                    r"permanently",
                ],
                safety_notes="Uses non-existent file path - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="git branch -D",
                command='echo "git branch -D NONEXISTENT_SAFE_TEST_BRANCH"',
                description="Blocks git branch -D (force-deletes branch without merge check)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"force-deletes.*branch",
                    r"merged",
                ],
                safety_notes="Uses non-existent branch - would fail harmlessly if executed",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="git stash clear",
                command='echo "git stash clear"',
                description="Blocks git stash clear (destroys all stashes)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"permanently destroys all",
                    r"stash",
                ],
                safety_notes="Safe to test - only clears stash (recoverable via reflog)",
                test_type=TestType.BLOCKING,
            ),
        ]
