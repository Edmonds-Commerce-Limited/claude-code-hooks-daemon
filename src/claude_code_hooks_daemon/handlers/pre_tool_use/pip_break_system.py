"""Handler to block pip install --break-system-packages flag.

This handler prevents the use of pip's --break-system-packages flag, which
disables the system package manager conflict detection and can corrupt
Python installations managed by the OS package manager.
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
_PIP_BREAK_SYSTEM_VERBOSE_CONTENT = (
    "The --break-system-packages flag disables pip's protection against\n"
    "conflicting with your system package manager (apt, dnf, pacman, etc.).\n\n"
    "Using this flag can:\n"
    "  • Corrupt your system Python installation\n"
    "  • Break OS tools that depend on Python\n"
    "  • Cause conflicts with system package manager\n"
    "  • Create difficult-to-debug environment issues\n\n"
    "SAFE alternatives:\n"
    "  1. Use a virtual environment (RECOMMENDED):\n"
    "     python -m venv myenv\n"
    "     source myenv/bin/activate\n"
    "     pip install <package>\n\n"
    "  2. Use --user flag for user-local install:\n"
    "     pip install --user <package>\n\n"
    "  3. If in a container/isolated environment, ask the human user\n"
    "     whether it's safe to proceed (they can override if truly needed)\n\n"
    "NEVER use --break-system-packages as default behavior."
)


class PipBreakSystemHandler(PreToolUseHandlerBase):
    """Block pip install --break-system-packages commands.

    This flag was introduced in pip 22.1 to bypass PEP 668 externally-managed
    environment protections. Using it can:
    - Conflict with system package manager (apt, dnf, etc.)
    - Break OS tools that depend on Python
    - Corrupt system Python installation
    - Cause difficult-to-debug issues

    Priority: 10 (safety-critical)
    Terminal: True (blocks execution)
    """

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            handler_id=HandlerID.PIP_BREAK_SYSTEM,
            priority=Priority.PIP_BREAK_SYSTEM,
            terminal=True,
        )
        self._rule = Rule(
            rule_id=RuleID.PIP_BREAK_SYSTEM_PACKAGES,
            blocked="`pip install --break-system-packages`",
            why="Bypasses PEP 668 protection and can corrupt the system Python installation",
            fix="Use a virtual environment or `pip install --user` instead",
            verbose=_PIP_BREAK_SYSTEM_VERBOSE_CONTENT,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if command contains pip install --break-system-packages.

        Matches:
        - pip install --break-system-packages
        - pip3 install --break-system-packages
        - python -m pip install --break-system-packages
        - python3 -m pip install --break-system-packages

        Case-insensitive matching.

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if command uses --break-system-packages flag
        """
        # Canonical accessor: non-Bash returns None, and shell line
        # continuations are normalised so a command split across lines is
        # matched in the same form as a one-line one.
        command = get_bash_command(hook_input)
        if not command:
            return False

        # Pattern: Any form of pip install with --break-system-packages
        # Matches: pip/pip3/python -m pip/python3 -m pip + install + --break-system-packages
        pattern = r"\b(pip3?|python3?\s+-m\s+pip)\s+install\s+.*--break-system-packages"

        return bool(re.search(pattern, command, re.IGNORECASE))

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

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.PIP_BREAK_SYSTEM_PACKAGES
        ):
            message = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.PIP_BREAK_SYSTEM_PACKAGES)
            message = self._formatter.verbose(self._rule)

        return GatingResult(
            decision=Decision.DENY,
            reason=message,
            context=[],
            guidance=None,
        )

    def get_claude_md(self) -> str | None:
        return (
            "## pip_break_system — --break-system-packages is blocked\n\n"
            "`pip install --break-system-packages` (and the `pip3` / `python -m pip` / "
            "`python3 -m pip` variants) is blocked. The flag bypasses PEP 668 system-package "
            "protection and corrupts the system Python environment in containers and on "
            "modern Linux distros.\n\n"
            "**Use a virtualenv or `--user` install instead**:\n\n"
            "```\n"
            "python3 -m venv /tmp/venv && /tmp/venv/bin/pip install <package>\n"
            "# or\n"
            "pip install --user <package>\n"
            "```\n\n"
            "If a tool's installer insists on `--break-system-packages` (some quick-start "
            "scripts do), download it first, inspect, and run it inside a venv — do not "
            "shortcut by adding the flag."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for pip break system handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="pip install --break-system-packages",
                command='echo "pip install --break-system-packages requests"',
                description="Blocks pip --break-system-packages flag (system corruption risk)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"--break-system-packages",
                    r"system Python installation",
                    r"virtual environment",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="python3 -m pip install --break-system-packages",
                command='echo "python3 -m pip install --break-system-packages numpy"',
                description="Blocks python3 -m pip with --break-system-packages",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"--break-system-packages",
                    r"Corrupt.*system Python",
                ],
                safety_notes="Uses echo - safe to test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
