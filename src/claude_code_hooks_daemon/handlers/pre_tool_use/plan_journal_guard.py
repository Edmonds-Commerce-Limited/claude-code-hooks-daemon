"""PlanJournalGuardHandler - a journal entry reaches a day-file only through the tool.

Plan 00461. ``mkplan.bash --journal <plan> <category> <body-file>`` reads the
real UTC clock and writes the entry heading itself, so the timestamp cannot be
guessed. In one session a coordinator and five sub-agents still appended every
entry by hand, and one heredoc entry was stamped 40 minutes ahead of the clock.
Because the journal is append-only, that entry could only be corrected once
the clock had passed the wrong time (ledger 00422 N3 and N21). An advisory, in
effect, already existed and changed nothing, so this handler DENIES and names
the exact command for the plan in question.

Two surfaces, both keyed on the day-file a call would write:

* ``Write``/``Edit``: denied when the would-be content carries MORE entry
  headings than the file does now, or when a ``Write`` creates a day-file. The
  count comes from the same parser the journal checks use
  (``plan_qa.model.journal_entry_headings``), so the three cannot disagree
  about what an entry is. A deletion-only Edit adds no heading and passes: for
  example, removing merge conflict markers after two branches each appended
  an entry. Whether an edit rewrites history is ``journal-append-only``'s
  question, not this one.
* ``Bash``: denied when the command writes into a day-file. The targets come
  from ``core.utils.get_bash_write_targets`` (redirects, ``tee``, heredocs,
  ``cp``/``mv``/``install``/``dd``) rather than a parser of this handler's own.
  Two additions cover what that detector cannot see. A quoted program is one
  shlex token, so an interpreter one-liner (``python3 -c``, ``perl -e``,
  ``bash -c``, an awk program) is judged by the day-file its PROGRAM names
  plus a write signal inside that program. An in-place editor flag (``-i``) on
  ``sed``/``perl``/``ruby`` is also judged. A ``git`` stage's RELOCATIONS are
  never judged (``git mv`` of a plan folder into ``Completed/``), but a
  redirect riding on a git stage still is.

Known limit: a script fed to an interpreter on stdin (``python3 <<'EOF'``) is
not read. A heredoc into the day-file itself is caught, because that is a
redirect.

Gated exactly as ``plan_number_helper`` is: only when the plan workflow is on
and the scaffolder is deployed. That scaffolder must also offer ``--journal``,
and the journal template it needs must be present. A client without them is
never told to use a tool it lacks.
"""

import logging
import os.path
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import (
    expand_home,
    get_bash_command,
    get_bash_write_targets,
    get_file_path,
)
from claude_code_hooks_daemon.handlers.utils.would_be_content import would_be_content
from claude_code_hooks_daemon.install.plan_workflow import (
    JOURNAL_TEMPLATE_NAME,
    MKPLAN_SCRIPT_NAME,
)
from claude_code_hooks_daemon.plan_qa.checks.common import plan_number_for_folder
from claude_code_hooks_daemon.plan_qa.model import (
    JOURNAL_CATEGORIES,
    journal_entry_headings,
    parse_journal_dayfile_name,
)
from claude_code_hooks_daemon.plan_qa.types import DEFAULT_JOURNAL_DIR_NAME
from claude_code_hooks_daemon.utils.path_predicates import path_is_file, read_text_or_reason
from claude_code_hooks_daemon.utils.shell_segmentation import (
    command_word,
    split_unquoted,
    strip_message_bodies,
    strip_quoted_heredoc_bodies,
)

logger = logging.getLogger(__name__)

#: The scaffolder's journal mode. Its presence in the deployed script is the
#: proof that the remedy this handler prints actually exists there.
_JOURNAL_FLAG: Final[str] = "--journal"

#: `plan_workflow.qa.journal.mode` token that switches journalling off.
_JOURNAL_MODE_OFF: Final[str] = "off"

#: Decode policy for the files this handler only searches for ASCII markers.
_DECODE_REPLACE: Final[str] = "replace"

#: Every day-file name carries this, so a command without it cannot name one.
#: A cheap prefilter run on every Bash call, never a coverage decision.
_DAYFILE_MARKER: Final[str] = "-Journal-"

#: Stage separators for the per-stage checks. Longest first, so `&&` and `||`
#: are not read as `&` and `|`.
_STAGE_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "\n")

#: The one command word whose relocations are never judged. See the module
#: docstring.
_GIT: Final[str] = "git"

#: Words that precede the real command without being it.
_COMMAND_PREFIXES: Final[frozenset[str]] = frozenset({"sudo", "env", "command", "exec"})

#: `NAME=value` before a command is an environment assignment, not the command.
_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: Runs of text that could be a path to a markdown file. Deliberately wide:
#: every candidate is then filtered by `parse_journal_dayfile_name` and the
#: plan-tree location test, so this only has to over-collect.
_MARKDOWN_PATH_RE: Final[re.Pattern[str]] = re.compile(r"[^\s'\"`;|&()<>=,\[\]{}]+\.md\b")

#: Interpreters whose inline program flag carries the code to run, by name.
#: A name matching `_PYTHON_RE` uses `-c`.
_PROGRAM_FLAGS: Final[dict[str, frozenset[str]]] = {
    "perl": frozenset({"-e", "-E"}),
    "ruby": frozenset({"-e"}),
    "node": frozenset({"-e", "-p", "--eval", "--print"}),
    "bash": frozenset({"-c"}),
    "sh": frozenset({"-c"}),
    "zsh": frozenset({"-c"}),
    "dash": frozenset({"-c"}),
}
_PYTHON_RE: Final[re.Pattern[str]] = re.compile(r"^python[\d.]*$")
_PYTHON_PROGRAM_FLAGS: Final[frozenset[str]] = frozenset({"-c"})

#: awk takes its program as the first operand rather than after a flag.
_AWK_NAMES: Final[frozenset[str]] = frozenset({"awk", "gawk", "mawk", "nawk"})

#: Editors whose `-i` rewrites the named file in place.
_IN_PLACE_EDITORS: Final[frozenset[str]] = frozenset({"sed", "perl", "ruby"})
_IN_PLACE_FLAG_RE: Final[re.Pattern[str]] = re.compile(r"^(?:-[A-Za-z]*i|--in-place)")

#: Something inside a program that writes: a write/append mode string, a
#: write call, or a redirect. Judged only together with a day-file named in
#: the SAME program, so a read-only one-liner never matches.
_WRITE_SIGNAL_RE: Final[re.Pattern[str]] = re.compile(
    r"""['"](?:[wax]|r\+)[bt+]*['"]|\bwrite|\bappend|>"""
)

_FLAG_PREFIX: Final[str] = "-"
_LONG_FLAG_PREFIX: Final[str] = "--"


@dataclass(frozen=True)
class _Layout:
    """Where this project's day-files live, resolved once per call."""

    plan_dir: str
    plan_root: Path
    journal_dir: str


@dataclass(frozen=True)
class _JournalTarget:
    """A day-file a call would write, resolved against the plan tree."""

    rel_path: str
    plan_number: int


class PlanJournalGuardHandler(PreToolUseHandlerBase):
    """Deny a journal entry written by hand rather than through `mkplan.bash --journal`."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_JOURNAL_GUARD,
            priority=Priority.PLAN_JOURNAL_GUARD,
            terminal=True,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.PLANNING],
        )
        self._workspace_root: Path = ProjectContext.project_root()
        # Injected by the registry for PLANNING-tagged handlers.
        self._track_plans_in_project: str | None = None
        self._plan_qa: Any = None

        self._rule = Rule(
            rule_id=RuleID.JOURNAL_HAND_WRITTEN_ENTRY,
            blocked="a plan journal entry written by hand (Edit/Write/Bash into a JOURNAL/ day-file)",
            why="Only `mkplan.bash --journal` stamps the real UTC time; hand-typed "
            "stamps have landed 40 minutes in the future",
            fix="Write the entry body to untracked/scratch/, then run "
            "`mkplan.bash --journal <plan> <category> <body-file>`",
            verbose=(
                "`mkplan.bash --journal` reads the real UTC clock and writes the "
                "`## HH:MM · category · REF` heading itself, so a guessed time "
                "cannot get in. A hand-typed one did: a heredoc entry was stamped "
                "09:50 when the clock read 09:11, 40 minutes in the future. The "
                "journal is append-only, so a wrong stamp can only be corrected "
                "by a later entry, and only once the clock has passed the wrong "
                "time. This applies to every agent and every sub-agent, and to "
                "archived plans too."
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's deny path."""
        return [self._rule]

    # ------------------------------------------------------------------
    # Gate
    # ------------------------------------------------------------------

    def _layout(self) -> _Layout | None:
        """The plan tree this handler guards, or None when it is inactive.

        The scaffolder writes into a directory named `JOURNAL`. A project that
        configures another name keeps its journals somewhere `--journal` never
        writes, so naming the tool there would move entries to a different
        folder than the one being written. The handler stands down instead.
        """
        plan_dir = self._track_plans_in_project
        if plan_dir is None:
            return None
        journal = getattr(self._plan_qa, "journal", None)
        if journal is not None and (
            not journal.enabled
            or journal.mode == _JOURNAL_MODE_OFF
            or journal.dir_name != DEFAULT_JOURNAL_DIR_NAME
        ):
            return None
        return _Layout(
            plan_dir=plan_dir,
            plan_root=Path(os.path.normpath(self._workspace_root / plan_dir)),
            journal_dir=DEFAULT_JOURNAL_DIR_NAME,
        )

    @staticmethod
    def _remedy_is_deployed(layout: _Layout) -> bool:
        """Whether `mkplan.bash --journal` exists here and can run.

        Read only once a call has already been found to target a day-file, so
        the cost falls on the rare matching call and never on ordinary traffic.
        """
        if not path_is_file(layout.plan_root / JOURNAL_TEMPLATE_NAME, unreadable_means=False):
            return False
        script = layout.plan_root / MKPLAN_SCRIPT_NAME
        if not path_is_file(script, unreadable_means=False):
            return False
        read = read_text_or_reason(script, errors=_DECODE_REPLACE)
        if read.text is None:
            logger.warning(
                "plan_journal_guard: cannot read %s (%s); standing down rather "
                "than naming a remedy that may not exist",
                script,
                read.reason,
            )
            return False
        return _JOURNAL_FLAG in read.text

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    def _dayfile_target(self, raw: str, cwd: Any, layout: _Layout) -> _JournalTarget | None:
        """``raw`` as a day-file under this project's plan tree, else None.

        Lexical only (`normpath`, no symlink resolution). A day-file in another
        checkout is not this project's: the printed command would append to
        THIS checkout's plan, which is the wrong file.
        """
        if raw.startswith("~"):
            expanded = expand_home(raw)
            if expanded is None:
                return None
            raw = expanded
        candidate = Path(raw)
        if not candidate.is_absolute():
            if not isinstance(cwd, str) or not cwd:
                return None
            candidate = Path(cwd) / candidate
        path = Path(os.path.normpath(candidate))

        if not path.is_relative_to(layout.plan_root):
            return None
        if path.parent.name != layout.journal_dir:
            return None
        if parse_journal_dayfile_name(path.name) is None:
            return None
        plan_number = plan_number_for_folder(path.parent.parent.name)
        if plan_number is None:
            return None
        return _JournalTarget(
            rel_path=str(path.relative_to(self._workspace_root)),
            plan_number=plan_number,
        )

    def _file_tool_target(
        self, hook_input: dict[str, Any], layout: _Layout
    ) -> _JournalTarget | None:
        """The day-file a Write/Edit would add an entry to, else None."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return None
        target = self._dayfile_target(file_path, hook_input.get(HookInputField.CWD), layout)
        if target is None:
            return None

        path = self._workspace_root / target.rel_path
        exists = path_is_file(path, unreadable_means=None)
        if exists is None:
            # Nothing to count against, and the tool call will meet the same
            # permission error itself.
            return None
        is_write = hook_input.get(HookInputField.TOOL_NAME) == ToolName.WRITE
        if not exists:
            # Creating a day-file is `--journal`'s job: it seeds the file from
            # the template and stamps the first entry in one step.
            return target if is_write else None

        # Headings are ASCII plus a middot, so a replaced byte can neither
        # create nor hide one; a strict decode would only blind the guard.
        read = read_text_or_reason(path, errors=_DECODE_REPLACE)
        if read.text is None:
            logger.warning(
                "plan_journal_guard: cannot read %s (%s); the tool call will meet "
                "the same error",
                path,
                read.reason,
            )
            return None
        before = read.text
        after = would_be_content(hook_input, current=before)
        if after is None:
            # An Edit whose old_string is absent fails with its own error.
            return None
        if len(journal_entry_headings(after)) > len(journal_entry_headings(before)):
            return target
        return None

    def _bash_target(self, hook_input: dict[str, Any], layout: _Layout) -> _JournalTarget | None:
        """The first day-file a Bash command would write into, else None."""
        command = get_bash_command(hook_input)
        if not command or _DAYFILE_MARKER not in command:
            return None
        cwd = hook_input.get(HookInputField.CWD)

        # Authored writes over the WHOLE command: a redirect, `tee`, a heredoc.
        # Judged even on a git stage (`git show HEAD:f > f` is a shell write).
        written = get_bash_write_targets(hook_input, authored_only=True)
        for stage in self._stages(command):
            words = _words(stage)
            head_index = _head_index(words)
            if head_index is None:
                continue
            head = command_word(words[head_index])
            if head == MKPLAN_SCRIPT_NAME:
                continue
            if head != _GIT:
                written.extend(self._relocations(hook_input, stage))
            written.extend(self._program_mentions(head, words[head_index + 1 :]))

        for raw in written:
            target = self._dayfile_target(raw, cwd, layout)
            if target is not None:
                return target
        return None

    @staticmethod
    def _stages(command: str) -> list[str]:
        """The command's stages, with text the shell does not execute blanked.

        A heredoc body fed to a data sink and a commit message are prose; a
        line of either that happens to read like `python3 -c "..."` must not
        be judged as a command.
        """
        executable = strip_message_bodies(strip_quoted_heredoc_bodies(command))
        return split_unquoted(executable, _STAGE_SEPARATORS)

    @staticmethod
    def _relocations(hook_input: dict[str, Any], stage: str) -> list[str]:
        """Paths ONE stage writes by relocating bytes (`cp`/`mv`/`install`/`dd`).

        Per stage, because the git exemption is per stage: a `git mv` must not
        excuse a `cp` onto the same file elsewhere in the chain.
        """
        stage_input = {**hook_input, HookInputField.TOOL_INPUT: {"command": stage}}
        authored = set(get_bash_write_targets(stage_input, authored_only=True))
        return [path for path in get_bash_write_targets(stage_input) if path not in authored]

    @staticmethod
    def _program_mentions(head: str, arguments: list[str]) -> list[str]:
        """Markdown paths an interpreter or in-place editor would write.

        Two shapes the write-target detector cannot see, because the write is
        not shell syntax: an in-place flag on an editor (every path operand is
        rewritten), and a write inside an inline program (a path named in the
        program, when the program also carries a write signal).
        """
        if head in _IN_PLACE_EDITORS and any(_IN_PLACE_FLAG_RE.match(arg) for arg in arguments):
            return [
                path
                for arg in arguments
                if not arg.startswith(_FLAG_PREFIX)
                for path in _MARKDOWN_PATH_RE.findall(arg)
            ]
        program = _inline_program(head, arguments)
        if program is None or not _WRITE_SIGNAL_RE.search(program):
            return []
        return list(_MARKDOWN_PATH_RE.findall(program))

    # ------------------------------------------------------------------
    # Handler API
    # ------------------------------------------------------------------

    def _target(self, hook_input: dict[str, Any]) -> tuple[_JournalTarget, _Layout] | None:
        """The day-file this call would write an entry into, with its layout."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT, ToolName.BASH):
            return None
        layout = self._layout()
        if layout is None:
            return None
        if tool_name == ToolName.BASH:
            target = self._bash_target(hook_input, layout)
        else:
            target = self._file_tool_target(hook_input, layout)
        if target is None or not self._remedy_is_deployed(layout):
            return None
        return target, layout

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match a call that would write a journal entry by hand."""
        return self._target(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, naming the exact `--journal` command for that plan."""
        resolved = self._target(hook_input)
        # Precondition: matches() found a target on this same input.
        assert resolved is not None, "Handler called without matches check"
        target, layout = resolved

        script = f"{layout.plan_dir}/{MKPLAN_SCRIPT_NAME}"
        body_file = f"{ProjectPath.SCRATCH_DIR}/journal-{target.plan_number}-entry.md"
        message = self._render(hook_input)
        # The target and the command are invocation-specific, so they are shown
        # on every fire, terse or verbose.
        message += (
            f"\n\nTarget: `{target.rel_path}`\n\n"
            "Append the entry through the stamping tool, in two steps:\n\n"
            f"  1. Write the entry BODY with the Write tool to {body_file}\n"
            "     (body only: the tool writes the `## HH:MM · category · REF` heading).\n"
            "  2. Run:\n\n"
            f'       {script} {_JOURNAL_FLAG} {target.plan_number} <category> {body_file} --title "short title"\n\n'
            f"     <category> is one of: {', '.join(JOURNAL_CATEGORIES)}. "
            "Add `--ref T1.2` for a task reference.\n\n"
            "It creates today's day-file from the template when there is none."
        )
        return GatingResult.deny(reason=message)

    def _render(self, hook_input: dict[str, Any]) -> str:
        """Verbose on first fire per transcript, terse after (Plan 00116)."""
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        if transcript_path and tracker.was_disclosed(transcript_path, self._rule.rule_id):
            return self._formatter.terse(self._rule)
        if transcript_path:
            tracker.mark_disclosed(transcript_path, self._rule.rule_id)
        return self._formatter.verbose(self._rule)

    def get_claude_md(self) -> str | None:
        return (
            "## plan_journal_guard — journal entries go through `mkplan.bash --journal`\n\n"
            "A plan `JOURNAL/` entry is appended with the stamping tool and nothing "
            "else. It reads the real UTC clock and writes the "
            "`## HH:MM · category · REF` heading itself. Hand-typed stamps have landed "
            "40 minutes in the future, and an append-only journal cannot correct one "
            "until the clock passes it.\n\n"
            "```\n"
            "# 1. Write the entry BODY (no heading) with the Write tool, e.g.\n"
            f"#    {ProjectPath.SCRATCH_DIR}/journal-<plan-number>-entry.md\n"
            "# 2. Append it (category: "
            f"{' | '.join(JOURNAL_CATEGORIES)}):\n"
            "CLAUDE/Plan/mkplan.bash --journal <plan-number> <category> "
            f'{ProjectPath.SCRATCH_DIR}/journal-<plan-number>-entry.md --title "short title"\n'
            "```\n\n"
            "(Use the project's configured plan directory if it is not `CLAUDE/Plan/`.) "
            "The deny message prints the exact command for the plan in question.\n\n"
            "**DENIED**: an `Edit`/`Write` that adds an entry heading to a day-file "
            "or creates one, and a Bash command that names a day-file as what it "
            "writes — `>`, `>>`, `tee`, a heredoc, `cp`/`mv`/`dd` onto it, an in-place "
            "editor, an interpreter one-liner. Archived plans' journals included. A "
            "path built from a variable is not seen; that is not a loophole to use. "
            "**Allowed**: the tool "
            "itself, `git` (moving a plan folder into `Completed/`), reading a "
            "journal, and an Edit that only DELETES (such as removing conflict "
            "markers after a merge). Put the `--journal` pattern into every "
            "sub-agent brief that asks for journalling."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the plan journal guard."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        probe_dayfile = "CLAUDE/Plan/99999-acceptance-probe/JOURNAL/99999-Journal-26-01-01.md"
        probe_body = f"{ProjectPath.SCRATCH_DIR}/journal-99999-acceptance-probe.md"
        return [
            AcceptanceTest(
                title="Block a hand-appended journal entry",
                command=f"echo '## 00:00 · action · —' >> {probe_dayfile}",
                dispatch_as_bash=True,
                description=(
                    "A redirect that appends an entry heading to a plan JOURNAL/ "
                    "day-file is denied, naming `mkplan.bash --journal` with that "
                    "plan's number (Plan 00461)."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"mkplan\.bash --journal 99999"],
                safety_notes=(
                    "Denied before execution. The plan number is outside any real "
                    "plan range and the folder does not exist, so even a regressed "
                    "handler lets the shell fail on a missing directory."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Allow appending a journal entry through mkplan.bash --journal",
                command=f"CLAUDE/Plan/mkplan.bash --journal 99999 action {probe_body}",
                dispatch_as_bash=True,
                description=(
                    "The stamping tool is the remedy the deny names, so invoking "
                    "it must never be blocked."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "If executed, mkplan.bash validates before it writes: the "
                    "body file does not exist, so it exits with an error and "
                    "writes nothing."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]


def _words(stage: str) -> list[str]:
    """Shell words of one stage; whitespace words when it cannot be parsed."""
    try:
        return shlex.split(stage)
    except ValueError as exc:
        # shlex also rejects text bash accepts (an ANSI-C `$'it\'s'` escape),
        # so whitespace words keep the command name and any path visible.
        logger.debug("plan_journal_guard: shlex could not parse %r (%s)", stage, exc)
        return stage.split()


def _head_index(words: list[str]) -> int | None:
    """Index of the word naming the command a stage runs, else None."""
    for index, word in enumerate(words):
        if _ASSIGNMENT_RE.match(word):
            continue
        if command_word(word) in _COMMAND_PREFIXES:
            continue
        if word.startswith(_FLAG_PREFIX):
            continue
        return index
    return None


def _inline_program(head: str, arguments: list[str]) -> str | None:
    """The program text an interpreter was handed inline, else None."""
    if head in _AWK_NAMES:
        return next((arg for arg in arguments if not arg.startswith(_FLAG_PREFIX)), None)
    flags = _PYTHON_PROGRAM_FLAGS if _PYTHON_RE.match(head) else _PROGRAM_FLAGS.get(head)
    if flags is None:
        return None
    for index, arg in enumerate(arguments[:-1]):
        if arg in flags:
            return arguments[index + 1]
        # A short-flag cluster ending in the program flag: `perl -ne '...'`.
        if not arg.startswith(_LONG_FLAG_PREFIX) and any(
            len(flag) == 2 and arg.startswith(_FLAG_PREFIX) and arg.endswith(flag[1])
            for flag in flags
        ):
            return arguments[index + 1]
    return None
