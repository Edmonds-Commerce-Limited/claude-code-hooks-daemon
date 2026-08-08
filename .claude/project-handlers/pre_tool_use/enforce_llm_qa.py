"""EnforceLlmQaHandler - blocks run_all.sh, requires llm_qa.py.

This project uses LLM-optimised QA output (scripts/qa/llm_qa.py) which
produces ~16 lines instead of 200+. LLM agents should never run the
verbose run_all.sh directly.
"""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

_BLOCKED_SCRIPT = "run_all.sh"
_LLM_SCRIPT = "./scripts/qa/llm_qa.py all"

# Commands that read/inspect a file WITHOUT executing it. A path appearing as
# an argument to one of these is a mention, not an invocation — `cat
# scripts/qa/run_all.sh` inspects the script's contents, it never runs it.
# Matched as the first shell word so a compound command's LATER segment can
# still be a real invocation (e.g. `cat run_all.sh; bash run_all.sh`).
#
# Static analysers belong here for the same reason readers do: `shellcheck -x
# scripts/qa/run_all.sh` is the canonical way to VERIFY an edit to that script,
# and denying it with "produces 200+ lines of verbose output" describes an
# execution that never happens.
_INSPECTION_COMMANDS = (
    "cat",
    "less",
    "more",
    "head",
    "tail",
    "grep",
    "rg",
    "wc",
    "bat",
    "shellcheck",
    "shfmt",
    "diff",
    "stat",
    "file",
)

# Version-control commands take the script's path as DATA — a commit message,
# a staged path, a pathspec. None of them executes it.
_VCS_COMMANDS = ("git", "gh")

# Characters that end one command and begin the next AT THE TOP LEVEL of a
# shell line. A newline is one of them: `a\nb` runs two commands exactly as
# `a; b` does, and omitting it let a real invocation on line 2 inherit line 1's
# leading word. `&` covers both `&&` and backgrounding; splitting on the single
# character handles both without a second rule.
_SEGMENT_SEPARATORS = (";", "|", "&", "\n")


def _split_top_level(command: str) -> list[str]:
    """Split ``command`` into segments on UNQUOTED shell separators.

    A separator inside quotes is data, not syntax. The original regex split on
    a bare ``[;|]`` and so cut through a quoted grep alternation
    (``"a\\|b\\|CHECKS="``), stranding a fragment whose apparent leading word
    was the tail of the pattern — which matched no allowlist entry and denied
    an ordinary read of the script.

    Delegates to the shared scanner (Plan 00200 Task 3.7). This function used to
    carry its own, which applied backslash escaping INSIDE single quotes where
    bash treats it as literal — so a trailing ``\\`` in a single-quoted argument
    swallowed the closing quote, nothing split, and the guarded script rode
    through on an allowlisted leading word. The sibling scanner in
    ``pipe_blocker`` had the mirror-image bug. One implementation, one place to
    fix, no way for the two to disagree again.
    """
    return split_unquoted(command, _SEGMENT_SEPARATORS)


def _is_inspection_only(command: str) -> bool:
    """True when every segment referencing the script only inspects it.

    Checks each segment's leading word (the command being run) against the
    inspection and VCS allowlists. A segment whose leading word is NOT in
    either (e.g. `bash`, `./scripts/...`, `sh`) is treated as a potential real
    invocation.

    The VCS exemption is applied PER SEGMENT for the same reason every other
    verdict here is: it used to test ``command.startswith("git ")`` against the
    whole string, so the ubiquitous ``cd /workspace; git commit -m ...`` lost
    it and a commit message mentioning the script was denied.
    """
    allowed = _INSPECTION_COMMANDS + _VCS_COMMANDS
    for segment in _split_top_level(command):
        stripped = segment.strip()
        if not stripped or _BLOCKED_SCRIPT not in stripped:
            continue
        words = stripped.split()
        leading_word = words[0].rsplit("/", 1)[-1] if words else ""  # strip any path prefix
        if leading_word not in allowed:
            return False
    return True


class EnforceLlmQaHandler(Handler):
    """Block run_all.sh and direct LLM agents to llm_qa.py."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="enforce-llm-qa",
            priority=41,
            terminal=True,
            tags=["project", "blocking", "qa"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match Bash commands that actually run run_all.sh (not just mention it)."""
        if hook_input.get("tool_name") != "Bash":
            return False
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if _BLOCKED_SCRIPT not in command:
            return False
        # A path passed to cat/less/grep/shellcheck/git inspects or records the
        # script; none of them executes it, regardless of output volume. The
        # verdict is per segment, so `cat run_all.sh; bash run_all.sh` still
        # matches on the second half.
        return not _is_inspection_only(command)

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block with guidance to use llm_qa.py instead."""
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "USE LLM-OPTIMISED QA SCRIPT\n\n"
                "run_all.sh produces 200+ lines of verbose output.\n"
                "Use the LLM-optimised wrapper instead:\n\n"
                f"  {_LLM_SCRIPT}\n\n"
                "This produces ~16 lines with structured JSON output.\n"
                "Individual scripts (run_tests.sh, run_lint.sh, etc.) are still allowed."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Define acceptance tests."""
        return [
            AcceptanceTest(
                title="Block run_all.sh",
                command='echo "./scripts/qa/run_all.sh"',
                description="Blocks verbose QA script, directs to llm_qa.py",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"llm_qa\.py", r"run_all\.sh"],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.BLOCKING,
            ),
            AcceptanceTest(
                title="Allow inspecting run_all.sh with cat (not an execution)",
                command="cat scripts/qa/run_all.sh",
                description=(
                    "cat reads the script's contents; it never executes it, so "
                    "this must NOT be blocked. Regression test for a real "
                    "dogfooding false positive (Plan 00200)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only inspection of a tracked file",
                test_type=TestType.BLOCKING,
            ),
        ]
