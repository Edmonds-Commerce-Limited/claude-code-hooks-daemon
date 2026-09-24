"""PlanJournalGuardHandler - a journal entry reaches a day-file only through the tool.

Plan 00461. ``mkplan.bash --journal <plan> <category> <body-file>`` reads the
real UTC clock and writes the entry heading itself, so the timestamp cannot be
guessed. In one session a coordinator and five sub-agents still appended every
entry by hand, and one heredoc entry was stamped 40 minutes ahead of the clock.
Because the journal is append-only, that entry could only be corrected once
the clock had passed the wrong time (ledger 00422 N3 and N21). An advisory, in
effect, already existed and changed nothing, so this handler DENIES and names
the exact command for the plan in question.

Every checkout is guarded, not just this one. A worktree under
``untracked/worktrees/`` or ``.claude/worktrees/`` sends its sub-agents' hooks
to the MAIN daemon, so a day-file is located with
``core.worktree_paths.enclosing_checkout`` and the command printed is THAT
checkout's ``mkplan.bash``, as an absolute path.

Two surfaces, both keyed on the day-file a call would write:

* ``Write``/``Edit``: denied when the would-be content has more non-blank lines
  or more entry headings than the file does now, or when a ``Write`` creates a
  day-file. Any added line is denied, not only an added heading, because text
  appended under the last entry inherits that entry's stamp. Headings come from
  ``plan_qa.model.journal_entry_headings``, the parser the journal checks use.
  An Edit that adds no line passes: a deletion (conflict markers after two
  branches each appended an entry), a reordering, a same-line redaction.
  Whether it rewrites history is ``journal-append-only``'s question.
* ``Bash``: denied when the command writes into a day-file by any route
  ``handlers.utils.bash_file_writes`` finds: a redirect, ``tee``, a heredoc, a
  copy, an in-place editor, a program handed to an interpreter (inline, on a
  heredoc, or behind a wrapper), a patch, a link. ``git`` relocations are never
  judged (``git mv`` of a plan folder into ``Completed/``).

Fails CLOSED on a destination it cannot place: one built at run time
(``$(date …)``, a variable, a glob), or a relative one after a ``cd``. Such a
destination is denied when it visibly names a day-file (``NNNNN-Journal-``), or
when its file name is built at run time inside a ``JOURNAL/`` directory.

Gated as ``plan_number_helper`` is: the plan workflow is on and the checkout's
scaffolder is deployed. That scaffolder must also offer ``--journal``, and the
journal template it needs must be present, so no client is told to use a tool
it lacks. Journalling switched off, or kept in a directory other than
``JOURNAL/``, also stands the guard down. Each of those is logged once at INFO,
because a guard that turns itself off must say so.
"""

import logging
import os.path
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
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
from claude_code_hooks_daemon.core.utils import expand_home, get_bash_command, get_file_path
from claude_code_hooks_daemon.core.worktree_paths import enclosing_checkout
from claude_code_hooks_daemon.handlers.utils.bash_file_writes import bash_file_writes
from claude_code_hooks_daemon.handlers.utils.would_be_content import would_be_content
from claude_code_hooks_daemon.install.plan_workflow import JOURNAL_TEMPLATE_NAME
from claude_code_hooks_daemon.plan_qa.checks.common import plan_number_for_folder
from claude_code_hooks_daemon.plan_qa.model import (
    JOURNAL_CATEGORIES,
    MKPLAN_SCRIPT_NAME,
    journal_entry_headings,
    parse_journal_dayfile_name,
)
from claude_code_hooks_daemon.plan_qa.types import DEFAULT_JOURNAL_DIR_NAME, JOURNAL_MODE_OFF
from claude_code_hooks_daemon.utils.path_predicates import (
    TextOrReason,
    path_is_file,
    read_text_or_reason,
)

logger = logging.getLogger(__name__)

#: The scaffolder's journal mode. Its presence in the deployed script is the
#: proof that the remedy this handler prints actually exists there.
_JOURNAL_FLAG: Final[str] = "--journal"

#: Decode policy for the files this handler reads: it looks only for ASCII
#: markers and headings, so a replaced byte can neither create nor hide one.
_DECODE_REPLACE: Final[str] = "replace"

#: A Bash command without one of these cannot write a day-file. A cheap
#: prefilter run on every Bash call; the patch words let a patch file that
#: names a day-file be read.
_BASH_PREFILTER_RE: Final[re.Pattern[str]] = re.compile(
    r"-Journal-|" + DEFAULT_JOURNAL_DIR_NAME + r"|\bpatch\b|\bapply\b"
)

#: A day-file named in a token, wherever the rest of the token came from.
_DAYFILE_MENTION_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|/)(\d{1,5})-Journal-")
#: The plan folder above a `JOURNAL/` directory named in a token.
_PLAN_FOLDER_MENTION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|/)(\d{1,5})-[A-Za-z][^/]*/" + DEFAULT_JOURNAL_DIR_NAME + r"(?:/|$)"
)

#: Characters meaning the shell builds the token at run time.
_EXPANSION_CHARACTERS: Final[tuple[str, ...]] = ("$", "*", "?", "`", "{", "[")
_HOME_PREFIX: Final[str] = "~"
_PATH_SEPARATOR: Final[str] = "/"

#: Shown in place of a number the command did not reveal.
_PLAN_NUMBER_PLACEHOLDER: Final[str] = "<plan-number>"

#: Fresh body-file name per deny (UTC stamp plus a random suffix), so a second
#: entry is never written over the first one's file (ledger 00422 N29).
_BODY_FILE_STAMP: Final[str] = "%y%m%d-%H%M%S"
_BODY_FILE_SUFFIX_BYTES: Final[int] = 2


@dataclass(frozen=True)
class _JournalTarget:
    """A day-file a call would write, and the checkout whose tool appends to it."""

    display: str
    plan_number: int | None
    checkout: Path
    placed: bool = True


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
        self._inert_logged: set[str] = set()

        self._rule = Rule(
            rule_id=RuleID.JOURNAL_HAND_WRITTEN_ENTRY,
            blocked="a plan journal entry written by hand (Edit/Write/Bash into a JOURNAL/ day-file)",
            why="Only `mkplan.bash --journal` stamps the real UTC time; hand-typed "
            "stamps have landed 40 minutes in the future",
            fix="Write the entry body to a fresh file under untracked/scratch/, then run "
            "`mkplan.bash --journal <plan> <category> <body-file>`",
            verbose=(
                "`mkplan.bash --journal` reads the real UTC clock and writes the "
                "`## HH:MM · category · REF` heading itself, so a guessed time "
                "cannot get in. A hand-typed one did: a heredoc entry was stamped "
                "09:50 when the clock read 09:11, 40 minutes in the future. The "
                "journal is append-only, so a wrong stamp can only be corrected "
                "by a later entry, and only once the clock has passed the wrong "
                "time. This applies to every agent and every sub-agent, in every "
                "worktree, and to archived plans too."
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's deny path."""
        return [self._rule]

    # ------------------------------------------------------------------
    # I/O seams
    # ------------------------------------------------------------------

    def _read_text(self, path: Path) -> TextOrReason:
        """Every read this handler makes (a day-file, a scaffolder, a patch)."""
        return read_text_or_reason(path, errors=_DECODE_REPLACE)

    def _file_state(self, path: Path) -> bool | None:
        """Whether ``path`` is a file; None when it cannot be stat'ed."""
        return path_is_file(path, unreadable_means=None)

    # ------------------------------------------------------------------
    # Gate
    # ------------------------------------------------------------------

    def _log_inert(self, condition: str) -> None:
        """Say once why the guard is off, so its silence can be explained."""
        if condition in self._inert_logged:
            return
        self._inert_logged.add(condition)
        logger.info(
            "plan_journal_guard: inert (%s); a hand-written journal entry is not denied",
            condition,
        )

    def _plan_dir(self) -> str | None:
        """The plan directory guarded, or None when journalling policy is off.

        The scaffolder writes into a directory named `JOURNAL`. A project that
        configures another name keeps its journals somewhere `--journal` never
        writes, so naming the tool there would move entries to a different
        folder than the one being written. The handler stands down instead.
        """
        plan_dir = self._track_plans_in_project
        if plan_dir is None:
            return None
        journal = getattr(self._plan_qa, "journal", None)
        if journal is None:
            return plan_dir
        if not journal.enabled:
            self._log_inert("plan_workflow.qa.journal.enabled is false")
            return None
        if journal.mode == JOURNAL_MODE_OFF:
            self._log_inert(f"plan_workflow.qa.journal.mode is {JOURNAL_MODE_OFF}")
            return None
        if journal.dir_name != DEFAULT_JOURNAL_DIR_NAME:
            self._log_inert(
                f"plan_workflow.qa.journal.dir_name is {journal.dir_name!r}, and "
                f"`mkplan.bash {_JOURNAL_FLAG}` writes only into {DEFAULT_JOURNAL_DIR_NAME}/"
            )
            return None
        return plan_dir

    def _remedy_is_deployed(self, plan_root: Path) -> bool:
        """Whether `mkplan.bash --journal` exists in this checkout and can run.

        Read only once a call has already been found to target a day-file, so
        the cost falls on the rare matching call and never on ordinary traffic.
        """
        template = plan_root / JOURNAL_TEMPLATE_NAME
        if self._file_state(template) is not True:
            self._log_inert(f"{template} is missing, so `mkplan.bash {_JOURNAL_FLAG}` cannot run")
            return False
        script = plan_root / MKPLAN_SCRIPT_NAME
        if self._file_state(script) is not True:
            self._log_inert(f"{script} is missing")
            return False
        read = self._read_text(script)
        if read.text is None:
            logger.warning(
                "plan_journal_guard: cannot read %s (%s); standing down rather "
                "than naming a remedy that may not exist",
                script,
                read.reason,
            )
            return False
        if _JOURNAL_FLAG not in read.text:
            self._log_inert(f"{script} has no {_JOURNAL_FLAG} mode")
            return False
        return True

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------

    def _dayfile_target(self, raw: str, cwd: Any, plan_dir: str) -> _JournalTarget | None:
        """``raw`` as a day-file under some checkout's plan tree, else None."""
        if raw.startswith(_HOME_PREFIX):
            expanded = expand_home(raw)
            if expanded is None:
                return None
            raw = expanded
        candidate = Path(raw)
        if not candidate.is_absolute():
            if not isinstance(cwd, str) or not cwd:
                return None
            candidate = Path(cwd) / candidate
        located = enclosing_checkout(os.path.normpath(candidate), self._workspace_root)
        if located is None:
            return None
        checkout, relative = located

        plan_parts = Path(plan_dir).parts
        if relative.parts[: len(plan_parts)] != plan_parts:
            return None
        if relative.parent.name != DEFAULT_JOURNAL_DIR_NAME:
            return None
        if parse_journal_dayfile_name(relative.name) is None:
            return None
        plan_number = plan_number_for_folder(relative.parent.parent.name)
        if plan_number is None:
            return None
        return _JournalTarget(display=str(relative), plan_number=plan_number, checkout=checkout)

    def _file_tool_target(self, hook_input: dict[str, Any], plan_dir: str) -> _JournalTarget | None:
        """The day-file a Write/Edit would add a line to, else None."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return None
        target = self._dayfile_target(file_path, hook_input.get(HookInputField.CWD), plan_dir)
        if target is None:
            return None

        path = target.checkout / target.display
        exists = self._file_state(path)
        if exists is None:
            # Nothing to count against, and the tool call will meet the same
            # permission error itself.
            return None
        is_write = hook_input.get(HookInputField.TOOL_NAME) == ToolName.WRITE
        if not exists:
            # Creating a day-file is `--journal`'s job: it seeds the file from
            # the template and stamps the first entry in one step.
            return target if is_write else None

        read = self._read_text(path)
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
        if _non_blank_lines(after) > _non_blank_lines(before) or len(
            journal_entry_headings(after)
        ) > len(journal_entry_headings(before)):
            return target
        return None

    def _bash_target(self, hook_input: dict[str, Any], plan_dir: str) -> _JournalTarget | None:
        """The first day-file a Bash command would write into, else None."""
        command = get_bash_command(hook_input)
        if not command or not _BASH_PREFILTER_RE.search(command):
            return None
        raw_cwd = hook_input.get(HookInputField.CWD)
        cwd = raw_cwd if isinstance(raw_cwd, str) and raw_cwd else None

        writes = bash_file_writes(command, cwd, self._read_text)
        for raw in writes.destinations:
            if _needs_expansion(raw) or (writes.directories and not _is_anchored(raw)):
                if _could_name_dayfile(raw, writes.directories):
                    return self._unplaced_target(raw, writes.directories, cwd, plan_dir)
                continue
            target = self._dayfile_target(raw, cwd, plan_dir)
            if target is not None:
                return target
        return None

    def _unplaced_target(
        self, raw: str, directories: tuple[str, ...], cwd: str | None, plan_dir: str
    ) -> _JournalTarget:
        """A destination that names a day-file but cannot be placed exactly."""
        plan_number: int | None = None
        for text in (raw, *directories):
            match = _DAYFILE_MENTION_RE.search(text) or _PLAN_FOLDER_MENTION_RE.search(text)
            if match is not None:
                plan_number = int(match.group(1))
                break
        return _JournalTarget(
            display=raw,
            plan_number=plan_number,
            checkout=self._checkout_for(directories, cwd, plan_dir),
            placed=False,
        )

    def _checkout_for(self, directories: tuple[str, ...], cwd: str | None, plan_dir: str) -> Path:
        """The checkout a command works in: an absolute `cd`, else its cwd."""
        anchors = [d for d in directories if Path(d).is_absolute() and not _needs_expansion(d)]
        if cwd is not None:
            anchors.append(cwd)
        for anchor in anchors:
            located = enclosing_checkout(
                str(Path(anchor) / plan_dir / MKPLAN_SCRIPT_NAME), self._workspace_root
            )
            if located is not None:
                return located[0]
        return self._workspace_root

    # ------------------------------------------------------------------
    # Handler API
    # ------------------------------------------------------------------

    def _target(self, hook_input: dict[str, Any]) -> tuple[_JournalTarget, str] | None:
        """The day-file this call would write an entry into, with the plan dir."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT, ToolName.BASH):
            return None
        plan_dir = self._plan_dir()
        if plan_dir is None:
            return None
        if tool_name == ToolName.BASH:
            target = self._bash_target(hook_input, plan_dir)
        else:
            target = self._file_tool_target(hook_input, plan_dir)
        if target is None or not self._remedy_is_deployed(target.checkout / plan_dir):
            return None
        return target, plan_dir

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match a call that would write a journal entry by hand."""
        return self._target(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, naming the exact `--journal` command for that plan and checkout."""
        resolved = self._target(hook_input)
        # Precondition: matches() found a target on this same input.
        assert resolved is not None, "Handler called without matches check"
        target, plan_dir = resolved

        number = _PLAN_NUMBER_PLACEHOLDER if target.plan_number is None else str(target.plan_number)
        script = target.checkout / plan_dir / MKPLAN_SCRIPT_NAME
        stamp = datetime.now(UTC).strftime(_BODY_FILE_STAMP)
        suffix = secrets.token_hex(_BODY_FILE_SUFFIX_BYTES)
        body_file = (
            target.checkout / ProjectPath.SCRATCH_DIR / f"journal-{number}-{stamp}-{suffix}.md"
        )
        unplaced_note = (
            ""
            if target.placed
            else "  (built by the shell at run time; it names a journal day-file, "
            "so it is treated as one)"
        )
        message = self._render(hook_input)
        # The target and the command are invocation-specific, so they are shown
        # on every fire, terse or verbose.
        message += (
            f"\n\nTarget: `{target.display}`{unplaced_note}\n\n"
            "Append the entry through the stamping tool, in two steps:\n\n"
            f"  1. Write the entry BODY with the Write tool to {body_file}\n"
            "     (body only: the tool writes the `## HH:MM · category · REF` heading;\n"
            "     use a fresh file name for every entry).\n"
            "  2. Run:\n\n"
            f'       {script} {_JOURNAL_FLAG} {number} <category> {body_file} --title "short title"\n\n'
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
            "# 1. Write the entry BODY (no heading) with the Write tool to a FRESH file, e.g.\n"
            f"#    {ProjectPath.SCRATCH_DIR}/journal-<plan-number>-<yymmdd-hhmmss>.md\n"
            "# 2. Append it (category: "
            f"{' | '.join(JOURNAL_CATEGORIES)}):\n"
            "CLAUDE/Plan/mkplan.bash --journal <plan-number> <category> "
            f"{ProjectPath.SCRATCH_DIR}/journal-<plan-number>-<yymmdd-hhmmss>.md "
            '--title "short title"\n'
            "```\n\n"
            "(Use the project's configured plan directory if it is not `CLAUDE/Plan/`, "
            "and the `mkplan.bash` of the checkout you are in — a worktree has its "
            "own.) The deny message prints the exact command, with absolute paths.\n\n"
            "**DENIED**: an `Edit`/`Write` that adds any line to a day-file or creates "
            "one, and a Bash command that writes into a day-file by any route — `>`, "
            "`>>`, `tee`, a heredoc, `cp`/`mv`/`dd`/`ln`/`rsync`, an in-place editor, "
            "a patch, an interpreter program (inline, on a heredoc, or behind "
            "`timeout`/`uv run`/…). A destination the shell builds at run time "
            "(`$(date …)`, a variable, a glob, a relative name after `cd`) is denied "
            "when it names a day-file. Every worktree and archived plan included. "
            "**Allowed**: the tool itself, `git` (moving a plan folder into "
            "`Completed/`), reading a journal, and an Edit that adds no line (removing "
            "conflict markers, reordering, a same-line redaction).\n\n"
            "**Active only when** the plan workflow is on, journalling is on with its "
            "directory named `JOURNAL`, and the checkout's plan directory holds "
            "`_JOURNAL_TEMPLATE_.md` and a `mkplan.bash` that offers `--journal`. "
            "Otherwise it is inert, and says so once in the daemon log. Put the "
            "`--journal` pattern into every sub-agent brief that asks for journalling."
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


def _non_blank_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _needs_expansion(token: str) -> bool:
    return any(character in token for character in _EXPANSION_CHARACTERS)


def _is_anchored(token: str) -> bool:
    """Absolute or home-relative: placed the same wherever the shell stands."""
    return token.startswith((_PATH_SEPARATOR, _HOME_PREFIX))


def _names_journal_dir(text: str) -> bool:
    return DEFAULT_JOURNAL_DIR_NAME in text.split(_PATH_SEPARATOR)


def _could_name_dayfile(token: str, directories: tuple[str, ...]) -> bool:
    """Whether an unplaceable destination could be a journal day-file.

    Yes when it names one outright, or when its file name is built at run time
    inside a `JOURNAL/` directory: named in the token itself, or entered with
    `cd` before a relative token.
    """
    if _DAYFILE_MENTION_RE.search(token):
        return True
    directory, _, name = token.rpartition(_PATH_SEPARATOR)
    if not _needs_expansion(name):
        return False
    if _names_journal_dir(directory):
        return True
    return not _is_anchored(token) and any(_names_journal_dir(d) for d in directories)
