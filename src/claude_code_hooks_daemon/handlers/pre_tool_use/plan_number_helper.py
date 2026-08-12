"""Plan Number Helper Handler.

Prevents Claude from using broken bash commands to discover plan numbers.
Instead of letting Claude use commands like:
    ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1

Which are broken (wrong glob patterns, ignore Completed/, etc.), this handler
detects these attempts and injects the correct next plan number into context.

Non-blocking (advisory only) - provides context but doesn't prevent execution.
"""

import re
from typing import TYPE_CHECKING, Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.utils.plan_numbering import next_plan_number_for_target

if TYPE_CHECKING:
    from pathlib import Path

# Shell metacharacters that terminate one command and begin another. Used inside a
# NEGATED regex character class so a pattern anchored on `echo`/`printf` cannot run
# past the end of its own command into an unrelated one. A newline is a command
# separator just as much as `;`, `&` and `|` are, and must be listed explicitly:
# a negated class matches "\n" unless told otherwise.
_COMMAND_SEPARATORS: Final[str] = r";&|\n\r"

# A `-name` pattern carrying this many consecutive literal digits is naming ONE
# specific plan (e.g. `00036-*`), not sweeping for whichever plans happen to
# exist. A single digit is not enough: `0*` is the generic "any plan folder"
# glob that the discovery idiom uses.
_SPECIFIC_PLAN_NUMBER_DIGITS: Final[int] = 2


class PlanNumberHelperHandler(Handler):
    """Detect bash commands attempting to discover plan numbers and provide correct answer."""

    def __init__(self) -> None:
        """Initialize handler."""
        super().__init__(
            handler_id=HandlerID.PLAN_NUMBER_HELPER,
            priority=Priority.PLAN_NUMBER_HELPER,  # Run before markdown_organization (35)
            terminal=True,  # Block broken commands that return incorrect plan numbers
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.PLANNING],
        )

        # Configuration attributes (set by registry after instantiation)
        self._workspace_root: Path = ProjectContext.project_root()
        self._track_plans_in_project: str | None = None  # Path to plan folder or None
        self._plan_workflow_docs: str | None = None  # Path to workflow doc or None

    @staticmethod
    def _extracts_latest(command: str) -> bool:
        """True when the command reduces its output to the single highest entry.

        This is the signature of "what is the next plan number?" -- sorting the
        folder list and taking the last one. It is what the git counter exists
        to replace, so it stays blocked regardless of how thorough the scan
        feeding it happens to be.
        """
        return bool(re.search(r"tail\s+(-n\s*)?-?\d+", command))

    @staticmethod
    def _covers_archive_subdirectories(command: str, plan_dir: str) -> bool:
        """True when the command demonstrably reaches the plan dir's archives.

        Two shapes qualify:

        1. An explicit path into a NAMED subdirectory of the plan dir --
           ``CLAUDE/Plan/Completed/...``. The check is for a letter rather than
           the literal names ``Completed``/``Cancelled`` because the archive
           directory names are configurable; a numbered plan folder always
           starts with a digit, so "letter follows the plan dir" cleanly
           separates a named subdirectory from a specific plan. The segment
           must then END (at a slash, whitespace, or the end of the string) so
           that a letter-led FILE in the plan root -- ``CLAUDE/Plan/README.md``
           -- cannot masquerade as a subdirectory and exempt a compound command
           whose other half really is a discovery scan.
        2. A ``find`` rooted at the plan dir whose ``-name`` pattern is not a
           generic plan-number sweep -- either it names ONE specific plan
           (``00036-*``) or it is not about plan numbers at all (``PLAN.md``).
           A bare ``find`` with no ``-name``, or one globbing ``0*`` /
           ``[0-9]*``, stays ambiguous: an agent hunting the next number
           plausibly runs exactly that and reads the tail of the output, so it
           is left to the handler's normal detection.
        """
        if re.search(rf"{re.escape(plan_dir)}/[A-Za-z][\w-]*(/|\s|$)", command):
            return True

        if not re.search(rf"find\s+{re.escape(plan_dir)}/?(\s|$)", command):
            return False

        name_pattern = re.search(r"-name\s+['\"]?([^'\"\s]+)", command)
        if name_pattern is None:
            return False

        target = name_pattern.group(1)
        if re.search(rf"\d{{{_SPECIFIC_PLAN_NUMBER_DIGITS},}}", target):
            return True
        # No digit and no digit character-class => not a plan-number search.
        return not re.search(r"\d|\[0-9\]", target)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match bash commands attempting to discover plan numbers.

        Args:
            hook_input: Hook input data

        Returns:
            True if this is a bash command trying to discover plan numbers
        """
        # Only active when planning mode is enabled
        if not self._track_plans_in_project:
            return False

        # Only match Bash tool
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False

        command = hook_input.get(HookInputField.TOOL_INPUT, {}).get("command", "")
        if not command:
            return False

        # Get the plan directory path (relative to workspace)
        plan_dir = self._track_plans_in_project

        # A command piped to `wc` COUNTS lines/words/bytes; it can never be
        # part of a "find the latest/highest plan number" idiom (which needs
        # sort+tail or similar to extract ONE value, not a count). A count
        # of how many plans exist (e.g. for a statistics line) is a
        # different, legitimate operation this handler must not misfire on,
        # regardless of which other discovery-shaped pattern it also matches.
        if plan_dir in command and re.search(r"\|\s*wc\b", command):
            return False

        # RECONCILIATION, not discovery. This handler's whole justification --
        # stated verbatim in its own deny reason -- is that a folder scan
        # "misses subdirectories like Completed/". A command that demonstrably
        # DOES reach those subdirectories cannot be denied on that ground
        # without telling the caller something untrue about their own command.
        #
        # The carve-out is deliberately narrow: it applies only while the
        # command is NOT also extracting a single highest value. Auditing which
        # numbers exist (statistics, collision hunting, absent-number
        # reconciliation) is a different operation from asking "what is the next
        # number", and only the latter is what the git counter replaces --
        # folder scans still disagree across branches, so the discovery idiom
        # stays blocked even when it happens to cover the archives.
        if self._covers_archive_subdirectories(command, plan_dir) and not self._extracts_latest(
            command
        ):
            return False

        # Pattern detection: Commands trying to discover plan numbers
        # These patterns indicate Claude is trying to find the latest plan

        # 1. ls with glob patterns on plan directory
        ls_patterns = [
            rf"ls\s+.*{re.escape(plan_dir)}/\*",  # ls CLAUDE/Plan/*
            rf"ls\s+.*{re.escape(plan_dir)}/0\*",  # ls CLAUDE/Plan/0*
            rf"ls\s+.*{re.escape(plan_dir)}/\[0-9\]",  # ls CLAUDE/Plan/[0-9]*
        ]

        for pattern in ls_patterns:
            if re.search(pattern, command):
                return True

        # 2. find commands on the plan directory ITSELF (discovery), NOT a find scoped to a
        # specific numbered plan folder. The trailing `/?(\s|$)` anchors the path token to
        # END at the plan dir (optionally with a slash): it matches `find CLAUDE/Plan`,
        # `find CLAUDE/Plan/ -name ...`, `find CLAUDE/Plan -maxdepth 1`, but NOT
        # `find CLAUDE/Plan/00135-feature ...` (a find operating on a known plan folder).
        find_patterns = [
            rf"find\s+{re.escape(plan_dir)}/?(\s|$)",
        ]

        for pattern in find_patterns:
            if re.search(pattern, command):
                return True

        # 3. Glob expansion (echo, printf with plan directory globs)
        # Match patterns like: echo CLAUDE/Plan/0*, echo CLAUDE/Plan/*, echo CLAUDE/Plan/[0-9]*
        # Use _COMMAND_SEPARATORS instead of .* to avoid matching across command separators,
        # which would cause false positives when echo and CLAUDE/Plan appear in different
        # subcommands. A NEWLINE separates commands exactly as `;`/`&`/`|` do, so it belongs
        # in the class too — a negated class matches "\n" by default, which previously let an
        # `echo` on one line reach forward and borrow a glob character from an unrelated
        # command on the next line.
        # The referenced path segment MUST contain a real glob metacharacter (*, [, ?) — a bare
        # digit is NOT enough, otherwise `echo CLAUDE/Plan/00135-feature/PLAN.md` (a reference to
        # a specific numbered folder) would falsely match as a discovery glob.
        glob_patterns = [
            rf"echo\s+[^{_COMMAND_SEPARATORS}]*{re.escape(plan_dir)}"
            rf"/[^\s{_COMMAND_SEPARATORS}]*[\*\[?]",  # echo with glob chars
            rf"printf\s+[^{_COMMAND_SEPARATORS}]*{re.escape(plan_dir)}"
            rf"/[^\s{_COMMAND_SEPARATORS}]*[\*\[?]",  # printf with glob chars
        ]

        for pattern in glob_patterns:
            if re.search(pattern, command):
                return True

        # 4. Commands with sort and tail on plan directory output
        # This catches complex pipelines like: ls ... | sort -V | tail -1
        if plan_dir in command and "sort" in command and "tail" in command:
            # Additional check: make sure it's actually trying to get latest
            if re.search(r"tail\s+-\d+", command) or "tail -1" in command:
                return True

        # 5. ls on plan directory piped to grep with number patterns
        # This catches: ls CLAUDE/Plan/ | grep -E '^[0-9]+' or similar
        if re.search(rf"ls\s+.*{re.escape(plan_dir)}", command) and "grep" in command:
            # Check if grep is filtering for numbers (common pattern)
            if re.search(r"grep.*['\"]?\^?\[?0-9\]?", command):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block broken command and provide correct next plan number.

        Args:
            hook_input: Hook input data

        Returns:
            HookResult with DENY decision and helpful reason
        """
        # Precondition: matches() ensures _track_plans_in_project is not None
        assert self._track_plans_in_project is not None, "Handler called without matches check"

        # Get next plan number (git-anchored: per-repo counter, trusted when
        # present, bootstrapped from a filesystem scan when absent).
        try:
            plan_base = self._workspace_root / self._track_plans_in_project
            next_number = next_plan_number_for_target(
                plan_base, self._track_plans_in_project, self._workspace_root
            )

            reason_message = (
                f"🚫 BLOCKED: This command won't find all plans (misses subdirectories like Completed/).\n\n"
                f"💡 Next plan number is {next_number}. "
                f"Use this instead of bash commands to discover plan numbers."
            )

            # Add workflow docs reference if configured
            if self._plan_workflow_docs:
                workflow_path = self._workspace_root / self._plan_workflow_docs
                if workflow_path.exists():
                    reason_message += (
                        f"\n📖 See `{self._plan_workflow_docs}` for plan structure and conventions."
                    )

            return HookResult.deny(reason=reason_message)

        except Exception as e:
            # Gracefully handle errors - still block the broken command
            reason_message = (
                f"🚫 BLOCKED: This command won't find all plans.\n\n"
                f"⚠️ Could not determine next plan number ({e}). "
                f"Starting from 00001 if this is a new project."
            )

            return HookResult.deny(reason=reason_message)

    def get_claude_md(self) -> str | None:
        return (
            "## plan_number_helper — use `mkplan.bash` to create a plan\n\n"
            "**To create a new plan, run the deployed scaffolding script:**\n\n"
            "```\n"
            'CLAUDE/Plan/mkplan.bash "descriptive-kebab-name"\n'
            "```\n\n"
            "(Use the project's configured plan directory if it is not `CLAUDE/Plan/`.) "
            "The script takes a lock, reads the same authoritative git counter "
            "(`hooksdaemon.latestPlanNumber`), assigns the next number atomically, creates the "
            "`NNNNN-name/` folder, scaffolds `PLAN.md`, and advances the counter — so concurrent "
            "runs can never collide on a number. It prints the new folder path on stdout. "
            "You still add the README index row yourself (the script reminds you).\n\n"
            "**If you only need the *number* (not a folder)**, read the counter and add 1 — "
            "this is the fallback, not the primary path:\n\n"
            "```\n"
            "git config --local hooksdaemon.latestPlanNumber\n"
            "```\n\n"
            "Add 1 to that value (zero-pad to 5 digits, e.g. counter `117` → next plan `00118`). "
            "The git counter is the source of truth; the daemon keeps it correct across branches.\n\n"
            "**Do NOT** scan `CLAUDE/Plan/` with `ls`/`find`/glob pipelines to discover the "
            "next number. Folder scans miss plans in `Completed/` and other subdirectories, "
            "and disagree across branches. The folder scan is only used to bootstrap the "
            "counter when the git key is unset (which `mkplan.bash` and the daemon both handle)."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Plan Number Helper."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block broken plan number discovery",
                command="ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1",
                description="Blocks broken bash commands that try to discover plan numbers and provides correct next number",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"plan number"],
                safety_notes="Handler blocks broken command and provides correct plan number instead.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Allow counting plans with wc (not number discovery)",
                command="find CLAUDE/Plan -maxdepth 1 -type d -name '[0-9]*' | wc -l",
                description=(
                    "A count of how many plans exist (e.g. for a statistics "
                    "line) is not an attempt to discover the NEXT plan number "
                    "and must NOT be blocked — 'wc' counts, it never extracts "
                    "a single latest value. Regression test for a dogfooding "
                    "false positive (Plan 00200)."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only count of tracked directories",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
