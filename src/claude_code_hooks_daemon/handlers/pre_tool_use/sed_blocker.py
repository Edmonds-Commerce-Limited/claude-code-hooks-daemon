"""SedBlockerHandler - blocks ALL sed command usage to prevent file destruction."""

import re
from typing import Any

from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_content, get_file_path


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
            name="block-sed-command", priority=10, tags=["safety", "bash", "blocking", "terminal"]
        )
        # Word boundary pattern: \bsed\b matches "sed" as whole word
        self._sed_pattern = re.compile(r"\bsed\b", re.IGNORECASE)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if sed appears anywhere in bash commands or shell scripts."""
        tool_name = hook_input.get("tool_name")

        # Case 1: Bash tool - block sed EXCEPT in safe contexts
        if tool_name == "Bash":
            command = get_bash_command(hook_input)
            if command and self._sed_pattern.search(command):
                # ALLOW: git commands (commits, add, etc.)
                if self._is_git_command(command):
                    return False

                # ALLOW: safe read-only commands (grep, echo, cat, etc.)
                # BLOCK: Actual sed execution
                return not self._is_safe_readonly_command(command)

        # Case 2: Write tool - block shell scripts containing sed, allow markdown
        if tool_name == "Write":
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

    def _is_safe_readonly_command(self, command: str) -> bool:
        """Check if command is a safe read-only operation mentioning sed.

        Safe commands include:
        - grep (searching for the word 'sed')
        - echo (printing text mentioning sed)

        NOT safe:
        - cat | sed (piping to sed)
        - find -exec sed (executing sed)
        - command chains with sed (&&, ||, ;)
        """
        # Check for grep or echo (safe - just mentioning sed)
        return bool(re.search(r"(^|\s|[;&|])\s*(grep|echo)\s+", command))

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block the operation with clear explanation."""
        tool_name = hook_input.get("tool_name")

        # Extract the problematic command/content
        if tool_name == "Bash":
            blocked_content = get_bash_command(hook_input)
            context_type = "command"
        else:  # Write tool
            blocked_content = get_file_path(hook_input)
            context_type = "script"

        return HookResult(
            decision=Decision.DENY,
            reason=(
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
            ),
        )
