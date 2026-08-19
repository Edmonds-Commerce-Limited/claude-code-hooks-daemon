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


# Command separators that introduce a NEW, separate command (NOT a pure pipe stage).
# When sed appears as a command head after one of these, it is being executed as its
# own command and can modify files on disk.
_SEPARATOR_BEFORE_NEW_COMMAND = ";|&&|\\|\\|"

# Detects sed being EXECUTED as a command head: at the very start of the command, or
# immediately after a command separator (;, &&, ||). This is sed running as its own
# command (e.g. "grep x f; sed -i s/a/b/ f") rather than as a stdout-transforming
# pipe stage, so it can modify files and must be blocked.
_SED_AS_COMMAND_HEAD = re.compile(
    rf"(?:^|{_SEPARATOR_BEFORE_NEW_COMMAND})\s*sed\b",
    re.IGNORECASE,
)

# Detects sed invoked with an in-place / script / quiet flag (-i, -e, -n). These
# flags appear on sed that is editing or executing programs, never on a harmless
# mention, so any occurrence is treated as execution regardless of position.
_SED_WITH_EXECUTION_FLAG = re.compile(
    r"\bsed\s+-[a-z]*[ien]",
    re.IGNORECASE,
)

# Detects sed run via xargs (e.g. "grep -rl X | xargs sed -i ..."). This is mass
# file modification and must be blocked even though a grep precedes it.
_SED_VIA_XARGS = re.compile(
    r"\|\s*xargs\s+.*\bsed\b",
    re.IGNORECASE,
)

# Detects a shell command separator (&&, ||, ;, |). Used to decide whether sed that
# appears after a git commit is part of the commit message (no separator → safe) or a
# separate chained command (separator present → NOT safe).
_COMMAND_SEPARATOR = re.compile(r"[;&|]")


class SedBlockerHandler(Handler):
    """Block sed used for file modification - Claude gets sed wrong and causes file destruction.

    PURPOSE: Prevent the LLM from running dangerous sed updates that cause
    widespread file damage. Read-only sed in pipelines (transforming stdout)
    is acceptable — the danger is sed modifying files on disk.

    Blocks:
    1. Direct sed execution (sed -i, sed -e, bare sed with file args)
    2. Indirect sed via xargs (grep -rl X | xargs sed -i)
    3. Write tool creating .sh/.bash files containing sed commands

    Allows:
    1. Read-only sed in pipelines (cat file | sed 's/x/y/' | grep z)
    2. Markdown files (.md) - documentation can mention sed
    3. Git/gh commands - commit messages and PR bodies can mention sed
    4. grep searching for the word "sed"

    Why sed is dangerous for LLMs:
    - Syntax errors destroy hundreds of files with find -exec
    - In-place editing (-i) is irreversible
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
        git_match = re.search(r"\bgit\s+commit\b", command)
        if git_match:
            git_pos = git_match.start()
            # Find position of 'sed'
            sed_match = self._sed_pattern.search(command)
            if sed_match:
                sed_pos = sed_match.start()
                # sed must come AFTER git commit to be part of the message
                if sed_pos > git_pos:
                    # Reject if a command separator (&&, ||, ;, |) appears between
                    # 'git commit' and sed — that means sed is a SEPARATE command
                    # (e.g. git commit -m "msg" && sed -i s/a/b/ f.py), NOT part of
                    # the commit message. Mirrors _is_gh_command's separator check.
                    text_between = command[git_pos:sed_pos]
                    if _COMMAND_SEPARATOR.search(text_between):
                        return False
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

    def _executes_sed(self, command: str) -> bool:
        """Return True if the command actually EXECUTES sed (vs merely mentioning it).

        sed is treated as executed — and therefore dangerous — when it appears:
        - as a command head (start of command, or after ;, &&, ||), regardless of any
          grep/echo elsewhere in the command (e.g. "grep x f; sed -i s/a/b/ f");
        - with an execution flag (-i / -e / -n) anywhere; or
        - via xargs (e.g. "grep -rl X | xargs sed -i ...").

        sed used purely as a stdout-transforming pipe stage (e.g. "cat f | sed 's/x/y/'")
        is NOT matched here — that read-only case is judged separately.
        """
        return bool(
            _SED_AS_COMMAND_HEAD.search(command)
            or _SED_WITH_EXECUTION_FLAG.search(command)
            or _SED_VIA_XARGS.search(command)
        )

    def _is_safe_readonly_command(self, command: str) -> bool:
        """Check if command is a safe read-only operation mentioning sed.

        Safe commands include:
        - grep (searching for the word 'sed')
        - echo mentioning 'sed' WITHOUT actual sed command patterns
        - read-only pipelines where sed only transforms stdout (cat f | sed 's/x/y/')

        NOT safe (returns False):
        - any command that EXECUTES sed (sed as a command head, sed -i/-e/-n, or
          sed via xargs) — even when a grep or echo also appears in the command;
        - find -exec sed (executing sed)

        The execution check runs FIRST so that destructive sed chained after a grep
        (e.g. "grep x f; sed -i s/a/b/ f") is blocked rather than allowed by the
        presence of grep.
        """
        # FAIL-FAST: if sed is actually being executed, the command is never safe,
        # regardless of any grep/echo that also appears in it.
        if self._executes_sed(command):
            return False

        # Allow grep that searches for the word 'sed' without executing it.
        # Read-only pipelines like `cat file | sed 's/x/y/' | grep z` are safe
        # (the _executes_sed guard above already rejected -i / xargs / chained sed).
        if re.search(r"(^|\s|[;&|])\s*grep\s+", command):
            return True

        # For echo commands, only allow if NOT containing sed command patterns.
        if re.search(r"(^|\s|[;&|])\s*echo\s+", command):
            # Check for sed substitution patterns like 's/.../' inside the echoed text.
            has_sed_substitution = bool(re.search(r"\bsed\s+'s/", command, re.IGNORECASE))
            has_sed_substitution_double = bool(re.search(r'\bsed\s+"s/', command, re.IGNORECASE))

            # If echo contains actual sed command patterns, it's NOT safe.
            if has_sed_substitution or has_sed_substitution_double:
                return False

            # Echo just mentioning the word "sed" is safe.
            return True

        return False

    def _get_block_count(self) -> int:
        """Get number of previous blocks by this handler.

        Falls back to 0 only when the data layer / history is not available
        (AttributeError). Any other error propagates (FAIL FAST) rather than being
        silently swallowed.
        """
        try:
            return get_data_layer().history.count_blocks_by_handler(self.name)
        except AttributeError:
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

    def get_claude_md(self) -> str | None:
        return (
            "## sed_blocker — sed is forbidden for file modification\n\n"
            "`sed` is blocked because Claude gets sed syntax wrong and a single error "
            "can silently destroy hundreds of files with no recovery possible.\n\n"
            "**THE RULE IS DENY-BY-DEFAULT, NOT A LIST OF BAD PATTERNS.** Any Bash "
            "command containing the WORD `sed` is blocked unless it matches one of the "
            "four narrow exemptions below. This framing matters: an earlier version of "
            "this guidance listed specific blocked shapes, which read as though anything "
            "unlisted was fine. It is not — `python3 -c \"print('sed')\"` is blocked, and "
            "so is `xargs sed 's/a/b/'` despite having no `-i`, no command-head position "
            "and no pipe stage.\n\n"
            "**The four exemptions, in the order they are applied**:\n\n"
            "1. **None of them apply if sed is EXECUTED.** sed at a command HEAD (start, "
            "or after `;`, `&&`, `||`), any flag cluster containing `i`, `e` or `n`, or "
            "sed via `xargs`, is blocked no matter what else is in the command. So "
            "`grep x f; sed -i 's/a/b/' f` is still denied — the `grep` does not rescue "
            "it. Note `sed -n '1,20p' file` prints to stdout and cannot write, and is "
            "blocked anyway: `-n` and `-i` differ by one character, and `Read` with "
            "`offset`/`limit` does the same job.\n"
            "2. A `git commit` message mentioning sed (sed must follow `git commit` with "
            "no command separator between).\n"
            "3. A `gh` issue/PR/release body mentioning sed (same separator rule).\n"
            "4. The command contains a `grep`, or an `echo` that does not itself carry a "
            "`sed 's/…'` substitution.\n\n"
            "**Consequence worth internalising**: exemption 4 is a proxy for 'this looks "
            "read-only', and it is the reason two commands that BOTH cannot modify a file "
            "get opposite verdicts — `cat f | sed 's/x/y/' | grep z` is allowed while "
            "`cat f | sed 's/x/y/' | wc -l` is DENIED. Nothing about writing distinguishes "
            "them; only the presence of `grep`.\n\n"
            "**Write/Edit tool (a separate branch, different rule)**: a `.sh`/`.bash` file "
            "whose content contains sed is blocked; a `.md` file is always allowed; any "
            "other path is not examined.\n\n"
            "**The `.md` exemption is Write-tool-only, and this catches people out.** "
            "The Bash branch judges the COMMAND, not the destination, so "
            "`cat > NOTES.md <<'EOF'` whose body mentions sed is DENIED even though "
            "`Write` to that same path is allowed. Only exemption 4 can spare a Bash "
            "write (so `echo 'avoid sed' > NOTES.md` is fine). **Write markdown about sed "
            "with the `Write` tool**, not a heredoc, and this never bites.\n\n"
            "**Use instead**:\n"
            "- `Edit` tool — safe, atomic, verifiable\n"
            "- Parallel Haiku agents with `Edit` tool for bulk changes across many files:\n"
            "  1. Identify all files to update\n"
            "  2. Dispatch one Haiku agent per file\n"
            "  3. Each agent uses the `Edit` tool (never `sed`)"
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
            AcceptanceTest(
                title="Write tool: shell script with sed (strict mode)",
                command="/workspace/untracked/test_sed_acceptance.sh",
                description=(
                    "In strict mode (default), blocks Write tool from creating shell scripts "
                    "containing sed. Use the Write tool to write "
                    "/workspace/untracked/test_sed_acceptance.sh with "
                    "content: '#!/bin/bash\\nsed -i \\'s/foo/bar/g\\' file.txt'. "
                    "The hook should block the Write call before the file is created. "
                    "NOTE: In direct_invocation_only mode this would be allowed."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"(?i)sed.*forbidden",
                    r"Edit tool",
                ],
                safety_notes=(
                    "Test uses Write tool to attempt creating a script - the hook blocks it "
                    "before the file is written. Only applies in default strict mode."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
