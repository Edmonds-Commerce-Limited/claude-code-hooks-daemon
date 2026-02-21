"""SedBlockerHandler - blocks sed command usage to prevent file destruction."""

import re
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult, get_data_layer
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_content, get_file_path


class SedBlockingMode:
    """Blocking mode options for SedBlockerHandler.

    Controls which tool invocations trigger the sed block:

    STRICT (default):
        Block both Bash direct invocation and Write tool creating shell scripts with sed.
        Safest option - prevents any sed from being written or executed.

    DIRECT_INVOCATION_ONLY:
        Only block Bash tool direct invocation of sed.
        Allows Write tool to create shell scripts that contain sed commands.
        Use when scripts that wrap sed are acceptable, but direct Claude sed calls are not.
    """

    STRICT = "strict"
    DIRECT_INVOCATION_ONLY = "direct_invocation_only"


class SedBlockerHandler(Handler):
    """Block ALL sed command usage - Claude gets sed wrong and causes file destruction.

    Blocks:
    1. Bash tool with sed command (direct execution)
    2. Write tool creating .sh/.bash files containing sed commands

    Allows:
    1. Markdown files (.md) - documentation can mention sed
    2. Git commands - commit messages can mention sed
    3. Read operations - already allowed (doesn't match Write/Bash)

    sed causes large-scale file corruption when:
    - Syntax errors destroy hundreds of files with find -exec
    - In-place editing is irreversible
    - Regular expressions are error-prone
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SED_BLOCKER,
            priority=Priority.SED_BLOCKER,
            tags=[HandlerTag.SAFETY, HandlerTag.BASH, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Word boundary pattern: \bsed\b matches "sed" as whole word
        self._sed_pattern = re.compile(r"\bsed\b", re.IGNORECASE)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if sed appears anywhere in bash commands or shell scripts."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Case 1: Bash tool - block sed EXCEPT in safe contexts
        if tool_name == ToolName.BASH:
            command = get_bash_command(hook_input)
            if command and self._sed_pattern.search(command):
                # ALLOW: git commands (commits, add, etc.)
                if self._is_git_command(command):
                    return False

                # ALLOW: GitHub CLI (gh) commands with sed in text content
                if self._is_gh_command(command):
                    return False

                # ALLOW: safe read-only commands (grep, echo, cat, etc.)
                # BLOCK: Actual sed execution
                return not self._is_safe_readonly_command(command)

        # Case 2: Write tool - block shell scripts containing sed, allow markdown
        # Only applies in strict mode; direct_invocation_only skips this check
        blocking_mode = getattr(self, "_blocking_mode", SedBlockingMode.STRICT)
        if blocking_mode != SedBlockingMode.DIRECT_INVOCATION_ONLY:
            if tool_name == ToolName.WRITE:
                file_path = get_file_path(hook_input)
                if not file_path:
                    return False

                # ALLOW: Markdown files (documentation for humans)
                if file_path.endswith(".md"):
                    return False

                # BLOCK: Shell scripts with sed
                if file_path.endswith(".sh") or file_path.endswith(".bash"):
                    content = get_file_content(hook_input)
                    if content and self._sed_pattern.search(content):
                        return True

        return False

    def _is_git_command(self, command: str) -> bool:
        """Check if command is a git operation with sed in its arguments.

        Git commands are allowed to mention sed in commit messages, heredocs, etc.

        SAFE:
        - git commit -m "Fix sed blocker"
        - git commit -m "$(cat <<'EOF'\nBlock sed\nEOF\n)"
        - git add . && git commit -m "sed blocker"

        NOT SAFE (sed is separate command):
        - git diff && sed -i 's/foo/bar/g' file.txt
        - sed -i 's/foo/bar/g' file.txt && git commit

        Key: sed must appear AFTER 'git commit' in the command string.
        """
        # Check if this is a git commit command with sed appearing after it
        # This handles: git commit -m "...sed..." and heredocs
        if re.search(r"\bgit\s+commit\b", command):
            # Find position of 'git commit'
            git_match = re.search(r"\bgit\s+commit\b", command)
            if git_match:
                git_pos = git_match.start()
                # Find position of 'sed'
                sed_match = self._sed_pattern.search(command)
                if sed_match:
                    sed_pos = sed_match.start()
                    # sed must come AFTER git commit to be part of the message
                    if sed_pos > git_pos:
                        return True

        # Check for git add followed by git commit (command chains)
        # git add . && git commit -m "sed" - SAFE
        if re.search(r"\bgit\s+add\b.*&&.*\bgit\s+commit\b", command):
            # Check if sed appears after 'git commit' in the chain
            commit_match = re.search(r"\bgit\s+commit\b", command)
            if commit_match:
                command_after_commit = command[commit_match.end() :]
                if self._sed_pattern.search(command_after_commit):
                    return True

        return False

    def _is_gh_command(self, command: str) -> bool:
        """Check if command is a GitHub CLI (gh) operation with sed in text content.

        GitHub CLI commands are allowed to mention sed in their text arguments (issue bodies,
        PR descriptions, comments, etc.) because they're just creating documentation/text
        content, not executing sed.

        SAFE:
        - gh issue create --title "Block sed" --body "sed is dangerous"
        - gh pr create --title "Fix" --body "Blocks sed usage"
        - gh issue comment 123 --body "Do not use sed"
        - gh pr comment 456 --body "$(cat <<'EOF'\nPackage.resolved\nEOF\n)"

        NOT SAFE (sed is separate command):
        - gh issue list && sed -i 's/foo/bar/g' file.txt
        - sed -i 's/foo/bar/g' file.txt && gh pr create

        Key: sed must appear AFTER 'gh' command in the command string, not as a separate
        command chained with && or || or ;
        """
        # Check if this is a gh command (issue, pr, release, etc.)
        if re.search(r"\bgh\s+(issue|pr|release|gist|repo)\b", command):
            # Find position of 'gh' command
            gh_match = re.search(r"\bgh\s+(issue|pr|release|gist|repo)\b", command)
            if gh_match:
                gh_pos = gh_match.start()
                # Find position of 'sed'
                sed_match = self._sed_pattern.search(command)
                if sed_match:
                    sed_pos = sed_match.start()
                    # sed must come AFTER gh command to be part of the text content
                    if sed_pos > gh_pos:
                        # Check that sed is not a separate command (not after &&, ||, ;)
                        # Extract text between gh command and sed
                        text_between = command[gh_pos:sed_pos]
                        # If there's a command separator, sed is separate (NOT safe)
                        if re.search(r"[;&|]{1,2}\s*$", text_between):
                            return False
                        # sed is part of gh command arguments (SAFE)
                        return True

        return False

    def _is_safe_readonly_command(self, command: str) -> bool:
        """Check if command is a safe read-only operation mentioning sed.

        Safe commands include:
        - grep (searching for the word 'sed')
        - echo mentioning 'sed' WITHOUT actual sed command patterns

        NOT safe:
        - echo containing sed command patterns (e.g., "echo \"sed -i 's/foo/bar/g' file\"")
        - cat | sed (piping to sed)
        - find -exec sed (executing sed)
        - command chains with sed (&&, ||, ;)
        """
        # Always allow grep (safe - just searching)
        if re.search(r"(^|\s|[;&|])\s*grep\s+", command):
            return True

        # For echo commands, only allow if NOT containing sed command patterns
        if re.search(r"(^|\s|[;&|])\s*echo\s+", command):
            # Check if echo contains actual sed command patterns (flags like -i, -e, -n)
            # or sed substitution patterns like 's/.../'
            has_sed_flags = bool(re.search(r"\bsed\s+-[ien]", command, re.IGNORECASE))
            has_sed_substitution = bool(re.search(r"\bsed\s+'s/", command, re.IGNORECASE))
            has_sed_substitution_double = bool(re.search(r'\bsed\s+"s/', command, re.IGNORECASE))

            # If echo contains actual sed command patterns, it's NOT safe
            if has_sed_flags or has_sed_substitution or has_sed_substitution_double:
                return False

            # Echo just mentioning the word "sed" is safe
            return True

        return False

    def _get_block_count(self) -> int:
        """Get number of previous blocks by this handler."""
        try:
            return get_data_layer().history.count_blocks_by_handler(self.name)
        except Exception:
            return 0

    def _terse_reason(self, context_type: str, blocked_content: str | None) -> str:
        """Return terse message for first block."""
        return (
            f"BLOCKED: sed is forbidden. Use Edit tool (or parallel Haiku agents for bulk).\n\n"
            f"BLOCKED {context_type}: {blocked_content}"
        )

    def _standard_reason(self, context_type: str, blocked_content: str | None) -> str:
        """Return standard message for blocks 2-3."""
        return (
            f"🚫 BLOCKED: sed command detected\n\n"
            f"sed is FORBIDDEN - causes large-scale file corruption.\n\n"
            f"BLOCKED {context_type}: {blocked_content}\n\n"
            f"WHY BANNED:\n"
            f"  • Claude gets sed syntax wrong regularly\n"
            f"  • Single error destroys hundreds of files\n"
            f"  • In-place editing is irreversible\n\n"
            f"✅ USE PARALLEL HAIKU AGENTS:\n"
            f"  1. List files to update\n"
            f"  2. Dispatch haiku agents (one per file)\n"
            f"  3. Use Edit tool (safe, atomic, git-trackable)"
        )

    def _verbose_reason(self, context_type: str, blocked_content: str | None) -> str:
        """Return verbose message with example for blocks 4+."""
        return (
            f"🚫 BLOCKED: sed command detected\n\n"
            f"sed is FORBIDDEN - causes large-scale file corruption.\n\n"
            f"BLOCKED {context_type}: {blocked_content}\n\n"
            f"WHY BANNED:\n"
            f"  • Claude gets sed syntax wrong regularly\n"
            f"  • Single error destroys hundreds of files\n"
            f"  • In-place editing is irreversible\n\n"
            f"✅ USE PARALLEL HAIKU AGENTS:\n"
            f"  1. List files to update\n"
            f"  2. Dispatch haiku agents (one per file)\n"
            f"  3. Use Edit tool (safe, atomic, git-trackable)\n\n"
            f"EXAMPLE:\n"
            f"  Bad:  find . -name \"*.ts\" -exec sed -i 's/foo/bar/g' {{}} \\;\n"
            f"  Good: Dispatch 10 haiku agents with Edit tool"
        )

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the operation with clear explanation."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)

        # Extract the problematic command/content
        if tool_name == ToolName.BASH:
            blocked_content = get_bash_command(hook_input)
            context_type = "command"
        else:  # Write tool
            blocked_content = get_file_path(hook_input)
            context_type = "script"

        # Get block count and determine verbosity level
        block_count = self._get_block_count()

        # Progressive verbosity: terse -> standard -> verbose
        if block_count == 0:
            reason = self._terse_reason(context_type, blocked_content)
        elif block_count <= 2:
            reason = self._standard_reason(context_type, blocked_content)
        else:
            reason = self._verbose_reason(context_type, blocked_content)

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for sed blocker handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="sed -i with substitution",
                command='sed -i "s/foo/bar/g" /tmp/sed_test.txt',
                description="Blocks sed -i (in-place editing) to prevent file destruction",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"(?i)sed.*forbidden",
                    r"Edit tool",
                ],
                setup_commands=['echo "test content" > /tmp/sed_test.txt'],
                cleanup_commands=["rm -f /tmp/sed_test.txt"],
                safety_notes="Uses test file in /tmp - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="sed -e command",
                command='sed -e "s/old/new/" /tmp/sed_test.txt',
                description="Blocks sed -e commands",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"(?i)sed.*forbidden",
                    r"Edit tool",
                ],
                safety_notes="Uses test file in /tmp - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
