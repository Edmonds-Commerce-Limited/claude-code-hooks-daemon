"""EnforceLlmQaHandler - blocks run_all.sh, requires llm_qa.py.

This project uses LLM-optimised QA output (scripts/qa/llm_qa.py) which
produces ~16 lines instead of 200+. LLM agents should never run the
verbose run_all.sh directly.
"""

import re
import shlex
from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.utils.shell_segmentation import (
    split_unquoted,
    strip_quoted_heredoc_bodies,
)

_BLOCKED_SCRIPT = "run_all.sh"
_LLM_SCRIPT = "./scripts/qa/llm_qa.py all"

# Characters that end one command and begin the next AT THE TOP LEVEL of a
# shell line. A newline is one of them: `a\nb` runs two commands exactly as
# `a; b` does, and omitting it let a real invocation on line 2 inherit line 1's
# leading word. `&` covers both `&&` and backgrounding; splitting on the single
# character handles both without a second rule.
_SEGMENT_SEPARATORS = (";", "|", "&", "\n")

# Commands that hand a following argument to a shell to run, rather than
# treating it as data: `bash scripts/qa/run_all.sh`, `env ./run_all.sh`,
# `timeout 30 ./run_all.sh`. A command whose head is none of these, and whose
# head does not itself name the script, never runs it — no allowlist of
# read-only commands is needed, since anything not on THIS list already
# cannot execute anything (Plan 00466 N6).
_WRAPPER_COMMANDS = ("bash", "sh", "env", "timeout", "nice", "exec")

# The flag that hands a wrapper an entire command LINE as a single argument
# (`sh -c '...'`, `bash -c "..."`) rather than a script path. Its value is
# itself a shell command and must be re-scanned, not treated as a path.
_SUBSHELL_FLAG = "-c"

# `$(...)` and `` `...` `` both run their inner text as a command before the
# rest of the line runs (Plan 00466 N6, `test_still_matches_a_bare_command_substitution`
# and the pre-existing UNQUOTED-heredoc regression). Matched non-greedily and
# with one level of nested parens so `$(echo $(x))` still finds `echo $(x)`.
_SUBSTITUTION_PATTERN = re.compile(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)|`([^`]*)`")


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

    A QUOTED heredoc body is blanked BEFORE splitting, because a newline is a
    separator here: without it the body of ``git commit -F - <<'EOF'`` is cut
    into pseudo-commands and each line judged on its leading word, so a message
    merely MENTIONING the guarded script was denied (Plan 00234 finding H-3 —
    found by hitting it while writing that very commit). The VCS allowlist below
    was meant to prevent exactly that and could not reach this spelling. The
    stripper is shared with ``pipe_blocker`` for the same one-implementation
    reason as the splitter; an UNQUOTED ``<<EOF`` still expands and stays
    scanned.
    """
    return split_unquoted(strip_quoted_heredoc_bodies(command), _SEGMENT_SEPARATORS)


def _tokenise(segment: str) -> list[str] | None:
    """Quote-aware split of one shell segment, or ``None`` if it can't be split safely.

    Mirrors the established pattern in ``project_containment.py``
    (``shlex.split`` wrapped in try/except) rather than hand-rolling a new
    tokeniser — this project already has one way to do this.
    """
    try:
        return shlex.split(segment)
    except ValueError:
        return None


def _word_names_the_script(word: str) -> bool:
    """True when ``word`` — a single already-tokenised shell word — IS the script.

    Matches the bare name or any path ending in it (``./scripts/qa/run_all.sh``,
    ``/workspace/scripts/qa/run_all.sh``). Deliberately NOT a substring test:
    a whole shlex token that merely CONTAINS the name (e.g. an entire quoted
    ``--title "... run_all.sh ..."`` argument, which shlex hands back as one
    token) does not end in ``/run_all.sh`` or equal ``run_all.sh``, so prose
    naming the script in an otherwise-unrelated argument does not match here.
    """
    return word == _BLOCKED_SCRIPT or word.endswith("/" + _BLOCKED_SCRIPT)


def _substitution_inner_segments(text: str) -> list[str]:
    """Every top-level segment inside every ``$(...)``/backtick substitution in ``text``."""
    inner_segments: list[str] = []
    for match in _SUBSTITUTION_PATTERN.finditer(text):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        inner_segments.extend(_split_top_level(inner))
    return inner_segments


def _segment_executes_script(segment: str) -> bool:
    """True when ``segment`` is a REAL invocation of the blocked script.

    A real invocation is: the script named at the segment's command head, or
    named as an argument to a wrapper (``bash``/``sh``/``env``/``timeout``/
    ``nice``/``exec``) that will run it — recursing into a wrapper's ``-c``
    subshell argument, since that argument IS a command line the wrapper
    hands off to a shell, not a path. A substitution's inner text is checked
    first, unconditionally, since bash runs it before running anything else
    on the line regardless of what the surrounding command's head is.

    A segment that can't be tokenised safely (unbalanced quoting) falls back
    to the old conservative substring check — deny rather than silently wave
    a real invocation through because it broke the parser.
    """
    for inner_segment in _substitution_inner_segments(segment):
        if _segment_executes_script(inner_segment):
            return True

    tokens = _tokenise(segment)
    if tokens is None:
        return _BLOCKED_SCRIPT in segment
    if not tokens:
        return False

    if _word_names_the_script(tokens[0]):
        return True

    head = tokens[0].rsplit("/", 1)[-1]
    if head not in _WRAPPER_COMMANDS:
        return False

    for word in tokens[1:]:
        if _word_names_the_script(word):
            return True
        if word == _SUBSHELL_FLAG:
            continue
        for inner_segment in _split_top_level(word):
            if _segment_executes_script(inner_segment):
                return True
    return False


def _has_real_invocation(command: str) -> bool:
    """True when any top-level segment of ``command`` really runs the script."""
    for segment in _split_top_level(command):
        stripped = segment.strip()
        if stripped and _segment_executes_script(stripped):
            return True
    return False


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
        return _has_real_invocation(command)

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
                command="bash -n scripts/qa/run_all.sh",
                description="Blocks verbose QA script, directs to llm_qa.py",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"llm_qa\.py", r"run_all\.sh"],
                safety_notes=(
                    "A genuine invocation shape (bash naming the script), so this "
                    "exercises the real detection path rather than a prose mention "
                    '(Plan 00466 N6: the old `echo "..."` fixture here was denied '
                    "only because echo wasn't on a since-removed allowlist, the "
                    "very false-positive class N6 fixes). `-n` makes bash parse "
                    "the script without running it, so it stays safe to actually "
                    "dispatch even if the block were to fail."
                ),
                test_type=TestType.BLOCKING,
                dispatch_as_bash=True,
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
                dispatch_as_bash=True,
            ),
        ]
