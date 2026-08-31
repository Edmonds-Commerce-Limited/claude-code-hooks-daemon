"""Plan Number Helper Handler.

Prevents Claude from using broken bash commands to discover plan numbers.
Instead of letting Claude use commands like:
    ls -d CLAUDE/Plan/0* 2>/dev/null | sort -V | tail -1

Which are broken (wrong glob patterns, ignore Completed/, etc.), this handler
detects these attempts and injects the correct next plan number into context.

TERMINAL: a matched command is DENIED, not merely annotated. The handler is
tagged ``advisory`` because what it injects is guidance rather than a safety
veto, but that tag describes the CONTENT of the response, never its force -- it
must not be read as an inability to block, or the denials this handler issues
become inexplicable to whoever hits one.

Matching is deliberately scoped to what the shell will EXECUTE. Quoted literals
are blanked first (see ``utils.quoted_spans.blank_shell_literal_spans``), so
prose or a regex that merely NAMES the plan directory is not mistaken for a
scan of it.
"""

import os.path
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.handlers.utils.plan_numbering import (
    PLAN_NUMBER_WIDTH,
    next_plan_number_for_target,
)
from claude_code_hooks_daemon.install.plan_workflow import MKPLAN_SCRIPT_NAME
from claude_code_hooks_daemon.utils.quoted_spans import blank_shell_literal_spans
from claude_code_hooks_daemon.utils.shell_segmentation import strip_quoted_heredoc_bodies

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

# The sort-and-truncate discovery idiom, named rather than inlined so the two
# halves of the rule read as one intent: order the listing, keep the last line.
_SORT_COMMAND: Final[str] = "sort"
_TRUNCATE_TO_LAST_PATTERN: Final[str] = r"tail\s+(-n\s*)?-?\d+"

# The hand-rolled plan-folder creation path (Plan 00234 Task 4.10). `mkdir`
# claims a number the moment the folder appears, but nothing records that claim
# until PLAN.md is written -- so a concurrent agent reading the git counter in
# between is handed the SAME number. `mkplan.bash` takes a lock and allocates
# atomically, so the gap is closed by redirecting to it rather than by adding
# bookkeeping to a path that was never synchronised.
_MKDIR_COMMAND: Final[str] = "mkdir"


class PlanNumberHelperHandler(PreToolUseHandlerBase):
    """Detect bash commands attempting to discover plan numbers and provide correct answer."""

    def __init__(self) -> None:
        """Initialize handler."""
        super().__init__(
            handler_id=HandlerID.PLAN_NUMBER_HELPER,
            priority=Priority.PLAN_NUMBER_HELPER,  # Run before markdown_organization (35)
            terminal=True,  # Block broken commands that return incorrect plan numbers
            # BLOCKING, not ADVISORY: this handler is already `terminal=True`
            # and denies a hand-rolled plan-folder mkdir. `_detect_behavior`
            # checks the advisory tag BEFORE falling back to the terminal flag,
            # so the ADVISORY tag actively overrode the truth the flag stated.
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.PLANNING],
        )

        # Configuration attributes (set by registry after instantiation)
        self._workspace_root: Path = ProjectContext.project_root()
        self._track_plans_in_project: str | None = None  # Path to plan folder or None
        self._plan_workflow_docs: str | None = None  # Path to workflow doc or None

        self._rule_discovery = Rule(
            rule_id=RuleID.PLAN_NUMBER_DISCOVERY,
            blocked="a bash discovery scan (ls/find/sort+tail) for the next plan number",
            why="Misses subdirectories like Completed/ and disagrees across branches",
            fix="Use the printed next plan number, or the git counter directly",
            verbose=(
                "Folder scans miss plans archived in Completed/ (and other "
                "subdirectories), and different branches can disagree about "
                "which plans exist -- so a scan-derived number is not "
                "trustworthy. The daemon tracks the next plan number in a "
                "per-repo git config counter (hooksdaemon.latestPlanNumber) "
                "instead, which stays correct across branches."
            ),
        )
        self._rule_mkdir = Rule(
            rule_id=RuleID.PLAN_FOLDER_MKDIR,
            blocked="`mkdir <plan-dir>/NNNNN-name` (hand-creating a plan folder)",
            why="Claims a plan number the moment the folder appears, but "
            "nothing records the claim until PLAN.md is written",
            fix="Use the mkplan.bash scaffolder instead",
            verbose=(
                "The number is claimed the moment the folder appears, but "
                "nothing records the claim until PLAN.md is written. A "
                "concurrent agent reading the git counter in between is "
                "handed the SAME number, and nothing catches the collision "
                "until the commit gate -- by which point both folders exist.\n\n"
                "The scaffolder takes a lock, allocates atomically from "
                "hooksdaemon.latestPlanNumber, creates the folder, scaffolds "
                "PLAN.md and advances the counter -- so concurrent runs can "
                "never collide on a number."
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the 2 Rule objects backing this handler's deny paths."""
        return [self._rule_discovery, self._rule_mkdir]

    def _render(self, rule: Rule, hook_input: dict[str, Any]) -> str:
        """Render `rule` via the verbose-first/terse-after disclosure ladder.

        Keyed on (transcript_path, rule_id) via the shared DisclosureTracker
        (Plan 00116, Decision G). A missing transcript_path fails toward
        verbose every time (no key to track against).
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            return self._formatter.terse(rule)

        if transcript_path:
            tracker.mark_disclosed(transcript_path, rule.rule_id)
        return self._formatter.verbose(rule)

    def _new_plan_folder_in_mkdir(self, command: str) -> str | None:
        """The plan folder a ``mkdir`` in ``command`` would CREATE, else ``None``.

        Narrow on purpose -- five conditions must all hold, and each one rules
        out a legitimate command that looks superficially the same:

        * the path is a direct ``NNNNN-name`` child of the configured plan dir,
          so ``mkdir -p CLAUDE/Plan/Completed`` (an archive directory) is not it;
        * the ``mkdir`` is not inside a heredoc body, which is written rather
          than executed;
        * the folder does NOT already exist, so ``mkdir -p <plan>/JOURNAL`` --
          adding a journal to a plan that exists -- is not it, and neither is a
          ``-p`` re-create of a folder already on disk;
        * the target resolves INSIDE the workspace, because the counter being
          protected is per-repo and acceptance-test setup commands build
          plan-shaped fixture trees under /tmp;
        * ``mkplan.bash`` is deployed, because denying the only available
          creation path would leave the agent unable to create a plan at all
          and would name a script that is not there.
        """
        plan_dir = self._track_plans_in_project
        if plan_dir is None or _MKDIR_COMMAND not in command:
            return None

        # Blank what the shell will not execute, and ONLY that: the body of a
        # quoted-delimiter heredoc (content being written) and quoted literals.
        # Scoping matters -- exempting the whole command because a heredoc
        # appears anywhere in it is an evasion, since appending a throwaway
        # heredoc would then wave the creation through.
        scannable = blank_shell_literal_spans(strip_quoted_heredoc_bodies(command))

        match = re.search(
            rf"{_MKDIR_COMMAND}[^{_COMMAND_SEPARATORS}]*?"
            rf"(\S*{re.escape(plan_dir)}/\d{{1,{PLAN_NUMBER_WIDTH}}}-[^\s/]+)",
            scannable,
        )
        if match is None:
            return None

        candidate = match.group(1)
        # An ABSOLUTE candidate replaces the base under pathlib's `/`, so this
        # single expression resolves both the relative and absolute spellings.
        # `normpath` is then required, not cosmetic: pathlib joins LEXICALLY and
        # keeps `..` as a literal segment, so `workspace/../sibling/...` still
        # tests as "inside the workspace" and a plan folder in a neighbouring
        # checkout would be denied with THIS project's scaffolder named as the
        # remedy. Purely lexical (no filesystem, no symlink resolution), which
        # is what the containment question actually needs.
        target = Path(os.path.normpath(self._workspace_root / candidate))
        if not target.is_relative_to(self._workspace_root):
            return None
        if target.is_dir():
            return None
        if not (self._workspace_root / plan_dir / MKPLAN_SCRIPT_NAME).exists():
            return None

        return candidate

    def _deny_hand_rolled_creation(
        self, plan_folder: str, hook_input: dict[str, Any]
    ) -> GatingResult:
        """Redirect a hand-rolled plan-folder creation to the scaffolder."""
        folder_name = plan_folder.rsplit("/", 1)[-1]
        name_match = re.match(rf"\d{{1,{PLAN_NUMBER_WIDTH}}}-(.+)$", folder_name)
        kebab_name = name_match.group(1) if name_match else folder_name

        message = self._render(self._rule_mkdir, hook_input)
        # The exact command and scaffolder invocation are invocation-specific
        # and always shown, regardless of disclosure state.
        message += (
            f"\n\nCommand: `{_MKDIR_COMMAND} {plan_folder}`\n\n"
            f'    {self._track_plans_in_project}/{MKPLAN_SCRIPT_NAME} "{kebab_name}"\n\n'
            "It prints the new folder path on stdout. You still add the README "
            "index row yourself."
        )
        return GatingResult.deny(reason=message)

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
    def _sweeps_the_plan_directory(command: str, plan_dir: str) -> bool:
        """True when the command references the plan dir as a DIRECTORY TO LIST.

        A reference that names one specific plan -- ``CLAUDE/Plan/00163-x`` --
        is not a sweep, so a command operating inside a known plan folder does
        not arm the sort-and-truncate rule. The discovery globs ``0*`` and
        ``[0-9]*`` carry fewer than ``_SPECIFIC_PLAN_NUMBER_DIGITS`` literal
        digits, so they are still treated as sweeps.

        Args:
            command: The command text, already stripped of quoted literals.
            plan_dir: Configured plan directory, relative to the workspace.

        Returns:
            True when at least one reference to the plan dir is not a specific
            plan folder.
        """
        if plan_dir not in command:
            return False

        specific_reference = rf"{re.escape(plan_dir)}/\d{{{_SPECIFIC_PLAN_NUMBER_DIGITS},}}"
        without_specific_references = re.sub(specific_reference, "", command)
        return plan_dir in without_specific_references

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
        # An optional `(` admits a regex ALTERNATION naming the archive dirs --
        # `CLAUDE/Plan/(Completed/|Cancelled/)` -- which reaches them just as
        # plainly as a literal path does. Without it the very command that
        # enumerates both archives is denied with a reason claiming it "misses
        # subdirectories like Completed/", which is untrue of that command.
        # The trailing anchor is unchanged, so a letter-led FILE in the plan
        # root (`CLAUDE/Plan/README.md`) still does not qualify.
        if re.search(rf"{re.escape(plan_dir)}/\(?[A-Za-z][\w-]*(/|\s|$)", command):
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

        # A copy with non-executing quoted literals blanked, used ONLY by the
        # two rules that would otherwise read a literal as shell syntax: the
        # echo/printf glob rule (a single-quoted grep regex `[0-9]` is not a
        # glob) and the sort-and-truncate rule (an `echo` of English prose is
        # not a directory scan).
        #
        # Deliberately NOT applied to every rule. This handler inspects quoted
        # arguments on purpose elsewhere -- the numeric grep pattern in
        # `ls CLAUDE/Plan | grep '[0-9]'`, and the `-name "00036-*"` that tells
        # a targeted find from a sweep. Blanking those blinds rules that are
        # working correctly, so the exemption is placed where a misread costs a
        # false positive and withheld where a literal IS the signal.
        executable_text = blank_shell_literal_spans(command)

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

        # 0. CREATION, not discovery. `mkdir CLAUDE/Plan/NNNNN-name` does not ask
        # for a number, it CLAIMS one -- unsynchronised, and unrecorded until
        # PLAN.md lands. Checked before the discovery rules because it is the
        # most specific shape and the only one that changes the plan tree.
        if self._new_plan_folder_in_mkdir(command) is not None:
            return True

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
            if re.search(pattern, executable_text):
                return True

        # 4. Sort-and-truncate over a listing OF THE PLAN DIRECTORY.
        #
        # The reduction must consume a listing of the directory itself. Mere
        # co-occurrence is not enough: this rule once required only that the
        # plan dir, `sort` and `tail` each appear somewhere in the string, which
        # fires on text that is not a command at all and on a command scoped to
        # ONE named plan. Both are legitimate:
        #
        #   git ls-files CLAUDE/Plan/00163-x/JOURNAL | sort | tail -1
        #
        # reads the newest journal day-file of a KNOWN plan -- the operation the
        # plan-workflow guidance recommends -- and discovers no plan number.
        #
        # So a reference that names a specific plan (two or more literal digits
        # after the plan dir) does not arm this rule. `CLAUDE/Plan/0*` and
        # `CLAUDE/Plan/[0-9]*` carry at most one literal digit before their glob
        # metacharacter, so the real discovery idiom still arms it.
        if _SORT_COMMAND in executable_text and self._sweeps_the_plan_directory(
            executable_text, plan_dir
        ):
            if re.search(_TRUNCATE_TO_LAST_PATTERN, executable_text):
                return True

        # 5. ls on plan directory piped to grep with number patterns
        # This catches: ls CLAUDE/Plan/ | grep -E '^[0-9]+' or similar
        if re.search(rf"ls\s+.*{re.escape(plan_dir)}", command) and "grep" in command:
            # Check if grep is filtering for numbers (common pattern)
            if re.search(r"grep.*['\"]?\^?\[?0-9\]?", command):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block broken command and provide correct next plan number.

        Args:
            hook_input: Hook input data

        Returns:
            GatingResult with DENY decision and helpful reason
        """
        # Precondition: matches() ensures _track_plans_in_project is not None
        assert self._track_plans_in_project is not None, "Handler called without matches check"

        # A hand-rolled creation needs the scaffolder, not a number: handing back
        # "the next number is N" would answer a question that was not asked and
        # leave the caller on the very path that loses the allocation.
        command = hook_input.get(HookInputField.TOOL_INPUT, {}).get("command", "")
        hand_rolled_folder = self._new_plan_folder_in_mkdir(command)
        if hand_rolled_folder is not None:
            return self._deny_hand_rolled_creation(hand_rolled_folder, hook_input)

        # Get next plan number (git-anchored: per-repo counter, trusted when
        # present, bootstrapped from a filesystem scan when absent).
        message = self._render(self._rule_discovery, hook_input)

        try:
            plan_base = self._workspace_root / self._track_plans_in_project
            next_number = next_plan_number_for_target(
                plan_base, self._track_plans_in_project, self._workspace_root
            )

            # The next plan number is invocation-specific and is always shown,
            # regardless of disclosure state -- it is the concrete answer, not
            # teaching content.
            message += f"\n\nNext plan number is {next_number}. Use this instead of bash commands to discover plan numbers."

            # Add workflow docs reference if configured
            if self._plan_workflow_docs:
                workflow_path = self._workspace_root / self._plan_workflow_docs
                if workflow_path.exists():
                    message += (
                        f"\n📖 See `{self._plan_workflow_docs}` for plan structure and conventions."
                    )

            return GatingResult.deny(reason=message)

        except Exception as e:
            # Gracefully handle errors - still block the broken command
            message += f"\n\n⚠️ Could not determine next plan number ({e}). Starting from 00001 if this is a new project."

            return GatingResult.deny(reason=message)

    def get_claude_md(self) -> str | None:
        return (
            "## plan_number_helper — use `mkplan.bash` to create a plan\n\n"
            "**Before creating one, check nothing already covers it.** Dispatch the "
            "`hooks-daemon-plan-dedupe-scout` agent with a sentence describing the "
            "intended work; it "
            "reads the still-live plans and names any that already cover it, so you can "
            "merge or supersede instead of filing alongside. This is a SUGGESTION — it "
            "never blocks, it is a judgement call rather than a rule, and it can be "
            "wrong. It is worth the few seconds because the alternative failure is "
            "expensive and silent: a duplicate plan is usually discovered only after an "
            "agent has spent a lot of context re-deriving conclusions that already "
            "existed on disk.\n\n"
            "**To create a new plan, run the deployed scaffolding script:**\n\n"
            "```\n"
            'CLAUDE/Plan/mkplan.bash "descriptive-kebab-name"\n'
            "```\n\n"
            "**Hand-creating the folder is BLOCKED.** `mkdir <plan-dir>/NNNNN-name` "
            "is denied when the scaffolder is deployed: `mkdir` claims a number the "
            "moment the folder appears, but nothing records the claim until PLAN.md "
            "is written, so a concurrent agent reading the counter in between gets the "
            "SAME number and the collision surfaces only at the commit gate. This is "
            "narrow — `mkdir <plan-dir>/Completed`, a `JOURNAL/` inside a plan that "
            "already exists, and a `-p` re-create of an existing folder are all "
            "allowed, as is any path outside this workspace.\n\n"
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
                title="Block hand-creating a plan folder with mkdir",
                command="mkdir -p CLAUDE/Plan/99999-acceptance-probe",
                description=(
                    "`mkdir` claims a plan number without recording it, so a "
                    "concurrent agent reading the git counter is handed the same "
                    "number. The block redirects to mkplan.bash, which takes a "
                    "lock and allocates atomically (Plan 00234 Task 4.10)."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"mkplan\.bash"],
                safety_notes=(
                    "Denied before execution, so no folder is created. The number "
                    "is deliberately outside any real plan range."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Allow mkdir of a plan archive directory",
                command="mkdir -p CLAUDE/Plan/Completed",
                description=(
                    "The creation block is narrow: an archive directory is not a "
                    "numbered plan folder and must not be denied."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Idempotent mkdir of a directory that already exists.",
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
