"""Handler to block chmod 777 and other dangerous permission patterns.

This handler prevents setting overly permissive file permissions that create
security vulnerabilities by allowing anyone to read, write, and execute files.
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command

# Full first-fire teaching content (Plan 00116): reuses the pre-migration
# handler's rich prose verbatim, minus the invocation-specific `COMMAND:`
# interpolation a static Rule.verbose cannot carry (Migration Pattern).
_DANGEROUS_PERMISSIONS_VERBOSE_CONTENT = (
    "Setting 777 (or a+rwx) permissions creates security vulnerabilities:\n"
    "  • Allows anyone to read, write, and execute the file\n"
    "  • Bypasses all file permission security\n"
    "  • Can expose sensitive data\n"
    "  • Violates principle of least privilege\n"
    "  • Often indicates a misunderstanding of permissions\n\n"
    "CORRECT permissions:\n"
    "  • Directories: 755 (owner: rwx, others: r-x)\n"
    "    chmod 755 mydir/\n\n"
    "  • Executable files: 755 (owner: rwx, others: r-x)\n"
    "    chmod 755 script.sh\n\n"
    "  • Regular files: 644 (owner: rw, others: r)\n"
    "    chmod 644 config.json\n\n"
    "  • Private files: 600 (owner: rw, others: none)\n"
    "    chmod 600 secret.key\n\n"
    "If you need broader access, ask the human user for the specific use case.\n"
    "The correct solution is almost never 777."
)

# World-writable OCTAL modes: any mode whose "other" (last) digit has the write bit
# (octal 2) set — digits 2, 3, 6, 7. Covers 666, 777, 757, 002, etc. An optional
# leading special-bits digit (setuid/setgid/sticky) is allowed (e.g. 1777, 2666).
_WORLD_WRITABLE_OCTAL = r"[0-7]?[0-7][0-7][2367]"

# World-writable SYMBOLIC modes: granting write to "others" (o+...) or "all" (a+...).
# Requires '+' so that removals like "go-w" are NOT matched. Matches a+w, o+w, a+rwx,
# o+rw, etc. (any '+' grant for the o/a class that includes 'w').
_WORLD_WRITABLE_SYMBOLIC = r"[ao]\+[rwx]*w[rwx]*"

# Combined dangerous-permission pattern, anchored on chmod. Each alternative is
# wrapped in word boundaries so it matches whole tokens, not substrings of paths.
_DANGEROUS_PERMISSIONS_PATTERN = (
    r"\bchmod\b.*\b(?:" + _WORLD_WRITABLE_OCTAL + r"|" + _WORLD_WRITABLE_SYMBOLIC + r")\b"
)


class DangerousPermissionsHandler(PreToolUseHandlerBase):
    """Block chmod 777 and dangerous permission commands.

    Blocks patterns like:
    - chmod 777
    - chmod -R 777
    - chmod a+rwx
    - chmod -R a+rwx

    These permissions are almost never correct and create severe security issues:
    - Allow anyone to read, write, and execute
    - Bypass all file permission security
    - Expose sensitive data
    - Violate principle of least privilege

    Priority: 15 (safety-critical, slightly lower than pip/sudo)
    Terminal: True (blocks execution)
    """

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            handler_id=HandlerID.DANGEROUS_PERMISSIONS,
            priority=Priority.DANGEROUS_PERMISSIONS,
            terminal=True,
        )
        self._rule = Rule(
            rule_id=RuleID.CHMOD_WORLD_WRITABLE,
            blocked="`chmod 777`/`chmod a+w`/`chmod o+w`",
            why="Allows anyone to read, write, and execute, bypassing all file "
            "permission security",
            fix="Use least-privilege permissions instead (755/644/600)",
            verbose=_DANGEROUS_PERMISSIONS_VERBOSE_CONTENT,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if command sets world-writable (dangerous) permissions.

        Matches any chmod that grants write access to "others"/"all":
        - world-writable octal modes (last digit has the write bit): 777, 666, 757,
          002, etc. (optionally with a leading special-bits digit, e.g. 1777)
        - world-writable symbolic modes: a+w, o+w, a+rwx, o+rw, etc.
        - the -R recursive flag is irrelevant to matching

        Does NOT match permission REMOVALS (e.g. go-w) or non-world-writable modes
        (755, 644, 600, u+x).

        Case-sensitive for file permissions.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command sets dangerous permissions
        """
        # Canonical accessor: non-Bash returns None, and shell line
        # continuations are normalised so a command split across lines is
        # matched in the same form as a one-line one.
        command = get_bash_command(hook_input)
        if not command:
            return False

        return bool(re.search(_DANGEROUS_PERMISSIONS_PATTERN, command))

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [self._rule]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block command with a verbose-first/terse-after explanation.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G): the first fire for a
        given agent is verbose (full teaching content); subsequent fires for
        the SAME agent are terse. An event with no transcript_path fails
        toward verbose every time (unknown disclosure state -> more info)
        since there is no key to track against.

        Args:
            hook_input: Hook input containing the dangerous command

        Returns:
            GatingResult with deny decision and explanation
        """
        # Safety check: if command doesn't match, allow
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.CHMOD_WORLD_WRITABLE):
            message = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.CHMOD_WORLD_WRITABLE)
            message = self._formatter.verbose(self._rule)

        return GatingResult(
            decision=Decision.DENY,
            reason=message,
            context=[],
            guidance=None,
        )

    def get_claude_md(self) -> str | None:
        return (
            "## dangerous_permissions — chmod 777 is blocked\n\n"
            "`chmod 777` and other world-writable permission commands are blocked. "
            "Overly permissive file permissions are a security vulnerability.\n\n"
            "**Blocked**: `chmod 777`, `chmod 666`, `chmod a+w`, `chmod o+w`\n\n"
            "**Use least-privilege permissions instead**:\n"
            "- Executable scripts: `chmod 755` (owner rwx, group/other rx)\n"
            "- Regular files: `chmod 644` (owner rw, group/other r)\n"
            "- Private files: `chmod 600` (owner rw only)"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for dangerous permissions handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="chmod 777",
                command='echo "chmod 777 /tmp/test_file.txt"',
                description="Blocks chmod 777 (security vulnerability)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"chmod 777",
                    r"security vulnerabilities",
                    r"principle of least privilege",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="chmod a+rwx",
                command='echo "chmod a+rwx /tmp/test_script.sh"',
                description="Blocks chmod a+rwx (equivalent to 777)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"dangerous permissions",
                    r"anyone to read, write, and execute",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
