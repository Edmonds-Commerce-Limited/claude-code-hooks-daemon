"""Deny writes whose target is named outside the repository root (Plan 00333).

Every other path rule in this daemon is expressed in repo-relative coordinates,
and the absolute-to-relative conversion **is** the containment test. When that
conversion fails the verdict is uniformly *allow*: ``markdown_organization``
catches the ``ValueError`` and returns ``False``, ``sensitive_content`` comments
*"Outside the project root: not ours to judge"*, and six more do the same. So a
markdown file at the repo root is denied for being in the wrong location while
the identical file at ``/tmp/notes.md`` is silently permitted — it left the
coordinate system the rules are defined in, so nothing judges it. Reproducing it
showed ``handlers_matched=[]``: not one handler even considered the write.

The harm is durability, not tidiness. A container's temp directory is ephemeral
while the repository is usually a bind mount, so anything written there is lost
on restart, invisible to git and outside review. The project already held this
position in three places before it was ever a rule -- ``daemon/paths.py`` keeps
runtime files in ``untracked/`` *"not /tmp, to prevent security
vulnerabilities"*, ``scripts/echd-capture`` prefers ``untracked/captures`` and
calls the temp directory a *"last resort"*, and ``worktree_seed_suggestions``
calls ``untracked/`` *"this daemon's own scratch convention"*. The tools obeyed
it; the agent, for whom it was never a rule, did not.

**Two boundaries are deliberate.**

*Named targets only.* A PreToolUse hook receives a command string, not syscalls,
so it cannot see a library's temp file and must not pretend to. Measured on the
container that prompted this plan: of 324 MB in ``/tmp``, 308 MB was pytest's
own ``tmp_path`` tree and 2,415 of 2,834 entries were zero-length ``uv`` lock
files. A guard fighting uv, pytest, pyright, node and semgrep would be switched
off within a day, and a guard that is switched off protects nothing.

*Writes only.* Blocking reads would break diagnosis and gain nothing durable.

This handler does NOT change ``markdown_organization``. That handler's
out-of-root early return is correct for its own premise -- markdown
*organisation* has nothing to say about a file that is not in the project --
and is pinned by its own tests. Containment is a separate premise, so it gets a
separate handler rather than weakening an existing one to make room.
"""

import logging
import os
import shlex
from pathlib import Path
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command, get_bash_write_targets
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted

#: Repo-relative home for scratch, shared with `pipe_blocker` so the handler
#: that DENIES an out-of-repo write and the handler that RECOMMENDS a capture
#: target cannot drift into advising what the other blocks.
SCRATCH_DIR = ProjectPath.SCRATCH_DIR

#: Where Claude Code keeps its own state. Allowed by default: it is not scratch,
#: and it is not ephemeral in the setup this rule was written for -- under ccy
#: the Claude home is mapped back into the bind mount, so it has exactly the
#: durability property this guard exists to protect. An environment that does
#: NOT map it durably can refuse it via ``allow_claude_home: false``.
#:
#: This does not re-open Claude auto-memory: ``markdown_organization`` blocks
#: ``~/.claude/projects/*/memory/*.md`` on a different premise (untracked
#: knowledge bypasses review) through its own raw-string marker rule.
#: Containment asks "is it durable?", that rule asks "is it reviewable?", and a
#: path can fail the second while passing the first.
_CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
_DEFAULT_CLAUDE_HOME = ".claude"

logger = logging.getLogger(__name__)

#: Commands whose ``-o``-style flag genuinely names an OUTPUT FILE, keyed by
#: command. Command-keyed rather than a bare flag list because ``-o`` does not
#: mean "output" everywhere: ``grep -o`` is only-matching and takes no argument
#: at all, so a blind "token after -o" rule would read grep's PATTERN as a
#: destination and deny a command that writes nothing. A wrong path is worse
#: than no path — the same contract ``get_bash_write_targets`` states.
_OUTPUT_FLAG_COMMANDS: dict[str, frozenset[str]] = {
    "curl": frozenset({"-o", "--output"}),
    "wget": frozenset({"-O", "--output-document"}),
}

#: Commands whose LAST positional argument is the destination.
_POSITIONAL_DEST_COMMANDS = frozenset({"rsync", "scp"})

#: Commands where EVERY non-flag argument is a path being created.
_ALL_ARG_DEST_COMMANDS = frozenset({"mkdir"})

#: Shells that take a command string to execute. The quoted inner command is
#: still a command, so it is re-extracted rather than treated as an opaque
#: argument — otherwise `sh -c "echo x > /tmp/y"` walks straight through.
_NESTED_SHELL_COMMANDS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_NESTED_SHELL_FLAG = "-c"
_MAX_NESTED_DEPTH = 2

#: `tar` is the awkward one: the same `-f` names the archive whether reading or
#: writing, so the file is only a DESTINATION when a create flag is present.
#: `tar -xf /tmp/a.tar` extracts FROM that path and is a read.
_ARCHIVE_COMMAND = "tar"
_ARCHIVE_CREATE_FLAGS = frozenset({"-c", "--create"})
_ARCHIVE_FILE_FLAGS = frozenset({"-f", "--file"})

#: Separators that end one command and begin the next.
_SEGMENT_SEPARATORS: tuple[str, ...] = ("&&", "||", ";", "|", "\n")

#: Tool inputs that NAME a write target, and the key each uses. ``get_file_path``
#: covers only Write and Edit, so relying on it alone would leave NotebookEdit
#: as a third open route.
_WRITE_TARGET_KEYS: dict[str, str] = {
    ToolName.WRITE: "file_path",
    ToolName.EDIT: "file_path",
    ToolName.NOTEBOOK_EDIT: "notebook_path",
}

_RULE = Rule(
    rule_id=RuleID.WRITE_OUTSIDE_PROJECT_ROOT,
    blocked="a write whose target is outside the repository root",
    why=(
        "Outside the repo nothing is version-controlled, reviewed or durable — a "
        "container's temp directory is wiped on restart, and every other path rule "
        "is scoped to the repo so none of them judges it"
    ),
    fix=f"Write it inside the repository — `{SCRATCH_DIR}/` is the scratch location",
    verbose=(
        "WHY BLOCKED:\n"
        "The target path is not inside this repository, so it is:\n"
        "  - EPHEMERAL - a container temp directory does not survive a restart\n"
        "  - INVISIBLE - not tracked by git, so it cannot be reviewed or shared\n"
        "  - UNGUARDED - every other path rule is expressed in repo-relative\n"
        "    coordinates, so an out-of-root path escapes all of them at once\n\n"
        f"WRITE IT HERE INSTEAD: {SCRATCH_DIR}/\n"
        "  - inside the working tree, so it survives container restarts\n"
        "  - gitignored, so it never reaches review\n"
        "  - the same convention the daemon's own runtime files already use\n\n"
        "Scratch is not a reason to leave the repository. There is no throwaway\n"
        "location, so nothing is lost by writing it somewhere durable.\n\n"
        "Reading an out-of-repo path is NOT blocked, and neither is a temp file a\n"
        "program creates for itself at runtime — only a path your command names."
    ),
)


class ProjectContainmentHandler(PreToolUseHandlerBase):
    """Deny a write to a path named outside the repository root.

    Priority: 14 (same band as the other handlers guarding content leaving the
    project, and ahead of every repo-relative path rule).
    Terminal: True.
    """

    #: REPO, the default: the boundary is the repository root rather than a
    #: sub-project root. ``untracked/`` lives at the repo root, so in a monorepo
    #: a sub-project writing to the shared scratch directory must not be denied.
    _TOOLS_WITH_NAMED_TARGETS: ClassVar[frozenset[str]] = frozenset(_WRITE_TARGET_KEYS)

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PROJECT_CONTAINMENT,
            priority=Priority.PROJECT_CONTAINMENT,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Configuration attribute (set by registry after instantiation).
        # Empty by default on purpose: a declared exemption is a decision, an
        # assumed one is a hole.
        self._allowed_external_paths: list[str] | None = None
        self._allow_claude_home: bool = True

    @staticmethod
    def _claude_home() -> Path:
        """Claude Code's own state directory.

        ``CLAUDE_CONFIG_DIR`` when set, else the documented default. Read at
        call time rather than cached: the daemon outlives any one session, and
        a cached value would silently follow the environment the daemon
        happened to start in.
        """
        configured = os.environ.get(_CLAUDE_CONFIG_DIR_ENV)
        if configured:
            return Path(configured)
        return Path.home() / _DEFAULT_CLAUDE_HOME

    def _offending_targets(self, hook_input: dict[str, Any]) -> list[str]:
        """Every named write target that lies outside the repository root.

        Args:
            hook_input: The PreToolUse hook input.

        Returns:
            The offending paths in the order they were named, de-duplicated. A
            command that writes two files reports both — naming one would send
            the reader back for a second denial.
        """
        root = self._resolved_root()
        offending: list[str] = []

        for candidate in self._named_targets(hook_input):
            if candidate in offending:
                continue
            if self._is_outside(candidate, root) and not self._is_permitted(candidate):
                offending.append(candidate)

        return offending

    def _named_targets(self, hook_input: dict[str, Any]) -> list[str]:
        """Paths this tool call plainly names as a write target."""
        targets: list[str] = []

        tool_name = hook_input.get("tool_name", "")
        key = _WRITE_TARGET_KEYS.get(tool_name)
        if key is not None:
            named = hook_input.get("tool_input", {}).get(key)
            if named:
                targets.append(str(named))

        # `get_bash_write_targets` returns [] for a non-Bash event, so this is
        # safe to ask unconditionally. It is conservative by contract: a target
        # needing shell expansion yields nothing rather than a guess, because a
        # WRONG path would attribute a write to a file never touched.
        targets.extend(get_bash_write_targets(hook_input))

        # Shapes that accessor deliberately does not resolve. Its premise is
        # "content this command AUTHORED", which is why Plan 00260 excluded
        # cp/mv from the content linters: a copy relocates bytes it did not
        # write, so blaming it would report a defect it did not introduce.
        # Containment has the opposite premise -- a file lands outside the repo
        # just as thoroughly whether the command authored it or fetched it --
        # so the extra destinations are resolved HERE rather than by widening
        # shared infrastructure that 22 other handlers depend on.
        command = get_bash_command(hook_input)
        if command:
            targets.extend(self._destination_targets(command))

        return targets

    def _destination_targets(self, command: str, depth: int = 0) -> list[str]:
        """Paths named as a destination by a flag or a positional argument.

        Args:
            command: The Bash command text.
            depth: Nested-shell recursion depth, bounded by ``_MAX_NESTED_DEPTH``.

        Returns:
            Every destination path this command plainly names. Conservative in
            the same direction as the shared accessor: an unrecognised command
            yields nothing rather than a guess.
        """
        targets: list[str] = []

        for segment in split_unquoted(command, _SEGMENT_SEPARATORS):
            tokens = self._tokenise(segment)
            if not tokens:
                continue

            name = Path(tokens[0]).name
            arguments = tokens[1:]

            if name in _OUTPUT_FLAG_COMMANDS:
                targets.extend(self._flag_targets(arguments, _OUTPUT_FLAG_COMMANDS[name]))
            elif name == _ARCHIVE_COMMAND:
                targets.extend(self._archive_targets(arguments))
            elif name in _ALL_ARG_DEST_COMMANDS:
                targets.extend(argument for argument in arguments if not argument.startswith("-"))
            elif name in _POSITIONAL_DEST_COMMANDS:
                positional = [a for a in arguments if not a.startswith("-")]
                if positional:
                    targets.append(positional[-1])
            elif name in _NESTED_SHELL_COMMANDS and depth < _MAX_NESTED_DEPTH:
                targets.extend(self._nested_shell_targets(arguments, depth))

        return targets

    @staticmethod
    def _tokenise(segment: str) -> list[str]:
        """Shell-tokenise a segment, or return nothing when it cannot be read.

        An unbalanced quote raises rather than tokenising. Returning nothing is
        the conservative answer and matches the accessor's contract: the guard
        would rather miss a write than invent a path. Logged at debug so the
        skip is observable instead of silent.
        """
        try:
            return shlex.split(segment)
        except ValueError as exc:
            logger.debug("Could not tokenise segment for containment check: %s", exc)
            return []

    @staticmethod
    def _flag_targets(arguments: list[str], flags: frozenset[str]) -> list[str]:
        """Values of ``--flag value`` and ``--flag=value`` output options."""
        targets: list[str] = []
        expecting = False

        for argument in arguments:
            if expecting:
                targets.append(argument)
                expecting = False
                continue
            if argument in flags:
                expecting = True
                continue
            for flag in flags:
                if argument.startswith(f"{flag}="):
                    targets.append(argument[len(flag) + 1 :])
                    break

        return targets

    @classmethod
    def _archive_targets(cls, arguments: list[str]) -> list[str]:
        """The archive path, but only when `tar` is CREATING one.

        Short flags bundle (``-cf out.tar``), so membership is tested per
        character rather than against the whole token.
        """
        creating = any(cls._short_flag_has(a, "c") or a in _ARCHIVE_CREATE_FLAGS for a in arguments)
        if not creating:
            return []

        for index, argument in enumerate(arguments):
            names_file = cls._short_flag_has(argument, "f") or argument in _ARCHIVE_FILE_FLAGS
            if names_file and index + 1 < len(arguments):
                return [arguments[index + 1]]
            if argument.startswith("--file="):
                return [argument[len("--file=") :]]

        return []

    @staticmethod
    def _short_flag_has(argument: str, letter: str) -> bool:
        """Is ``letter`` set in a bundled short-flag token such as ``-czf``?"""
        return (
            argument.startswith("-")
            and not argument.startswith("--")
            and letter in argument[1:]
        )

    def _nested_shell_targets(self, arguments: list[str], depth: int) -> list[str]:
        """Re-extract from a shell's ``-c`` command string.

        The inner string is a command, not an opaque argument, so it gets both
        the shared accessor (for redirects and cp/mv) and this extractor again.
        """
        if _NESTED_SHELL_FLAG not in arguments:
            return []

        index = arguments.index(_NESTED_SHELL_FLAG)
        if index + 1 >= len(arguments):
            return []

        inner = arguments[index + 1]
        targets = list(
            get_bash_write_targets({"tool_name": ToolName.BASH, "tool_input": {"command": inner}})
        )
        targets.extend(self._destination_targets(inner, depth + 1))
        return targets

    @staticmethod
    def _resolved_root() -> Path:
        return ProjectContext.project_root().resolve()

    @staticmethod
    def _is_within(candidate: str, container: Path) -> bool:
        """Is ``candidate`` at or under ``container``, comparing PATH COMPONENTS?

        ``relative_to`` is component-wise, which is the point: a string prefix
        test would read ``/repo-backup`` as being inside ``/repo``, and that is
        the usual way a containment check fails.
        """
        try:
            Path(candidate).resolve().relative_to(container)
        except ValueError:
            return False
        return True

    def _is_outside(self, candidate: str, root: Path) -> bool:
        """A relative path is never outside: it resolves against a working
        directory the daemon does not know, so treating it as out-of-root would
        deny writes on a guess."""
        if not Path(candidate).is_absolute():
            return False
        return not self._is_within(candidate, root)

    def _is_permitted(self, candidate: str) -> bool:
        """Is this out-of-root path covered by an allowance?"""
        if self._allow_claude_home and self._is_within(candidate, self._claude_home().resolve()):
            return True
        return any(
            self._is_within(candidate, Path(allowed).resolve())
            for allowed in self._allowed_external_paths or []
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when this call names at least one out-of-root write target."""
        return bool(self._offending_targets(hook_input))

    def get_rules(self) -> list[Rule]:
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, naming every offending path and the sanctioned location."""
        offending = self._offending_targets(hook_input)
        if not offending:
            return GatingResult(decision=Decision.ALLOW)

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        formatter = RuleFormatter()

        if transcript_path and tracker.was_disclosed(
            transcript_path, RuleID.WRITE_OUTSIDE_PROJECT_ROOT
        ):
            message = formatter.terse(_RULE)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.WRITE_OUTSIDE_PROJECT_ROOT)
            message = formatter.verbose(_RULE)

        listed = "\n".join(f"  - {path}" for path in offending)
        message += (
            f"\n\nOUTSIDE THE REPOSITORY:\n{listed}"
            f"\n\nREPOSITORY ROOT: {self._resolved_root()}"
            f"\nWRITE IT HERE INSTEAD: {self._resolved_root() / SCRATCH_DIR}/"
        )

        return GatingResult(decision=Decision.DENY, reason=message, context=[], guidance=None)

    def get_claude_md(self) -> str | None:
        return (
            "## project_containment — nothing is written outside the repository\n\n"
            "A `Write`, `Edit` or `NotebookEdit` whose `file_path` is outside the "
            "repository root is **blocked**, and so is a Bash command that names an "
            "out-of-root destination:\n\n"
            "- redirects and pipes: `>`, `>>`, `tee`\n"
            "- a heredoc target\n"
            "- `cp` / `mv` / `install` / `dd` destinations\n"
            "- `curl -o|--output`, `wget -O|--output-document`\n"
            "- `tar` creating an archive (`-cf`), `mkdir`, `rsync`/`scp` destinations\n"
            "- any of the above inside a nested `sh -c \"...\"` / `bash -c \"...\"`\n\n"
            "**That list is exhaustive, not illustrative — and one gap remains.** An "
            "interpreter one-liner (`python3 -c \"open('/tmp/x','w')\"`) is NOT "
            "caught and cannot be: resolving what it writes means running it, which "
            "a PreToolUse hook must never do. So a clean Bash command is not "
            "evidence the write stayed in the repo; it is evidence that no "
            "*recognised* shape named a path outside it. Put scratch in the right "
            "place because it belongs there, not because you were stopped.\n\n"
            "An output flag is read per COMMAND, never generically: `grep -o` is "
            "only-matching and names no file, so it is untouched.\n\n"
            f"**Write scratch to `{SCRATCH_DIR}/`**: inside the working tree so it "
            "survives a container restart, and gitignored so it never reaches review. "
            "A container's temp directory has neither property — work written there "
            "is gone on the next restart, which is why 'it's only scratch' is not a "
            "reason to leave the repository. There is no throwaway location, so "
            "nothing is lost by writing it somewhere durable.\n\n"
            "**NOT blocked**: reading any path; a temp file a PROGRAM creates for "
            "itself at runtime (pytest's `tmp_path`, a package manager's build dir) — "
            "this rule judges paths your command NAMES, not what a tool does "
            "internally; and a target the daemon cannot resolve without executing "
            "the command (`> \"$OUT\"`), which yields no path rather than a guess.\n\n"
            "**Claude Code's own state directory is allowed** (`$CLAUDE_CONFIG_DIR`, "
            "else `~/.claude`). It is not scratch, and it is not ephemeral where it is "
            "mapped into the bind mount. That does NOT re-open Claude auto-memory: "
            "`markdown_organization` blocks `~/.claude/projects/*/memory/*.md` on a "
            "different premise — this rule asks whether a path is DURABLE, that one "
            "asks whether it is REVIEWABLE, and memory fails the second test while "
            "passing the first.\n\n"
            "**Exemptions** are declarable via "
            "`handlers.pre_tool_use.project_containment.options.allowed_external_paths`, "
            "and the list is empty by default — a declared exemption is a decision, an "
            "assumed one is a hole."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests for the containment guard.

        No setup or cleanup commands: the write is denied before anything is
        created, and a `mkdir` outside the repo would be this handler's own
        business anyway.
        """
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Write to a path outside the repository",
                command=(
                    "Use the Write tool to write to "
                    "/tmp/acceptance-test-containment/probe.md with content '# probe'"
                ),
                description="Blocks a write to an ephemeral location outside the repo",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    r"outside the repository root",
                    r"untracked/scratch",
                ],
                safety_notes="Nothing is created - the write is denied before it happens.",
                test_type=TestType.BLOCKING,
                setup_commands=[],
                cleanup_commands=[],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Bash redirect to a path outside the repository",
                command=(
                    "Run the bash command: echo probe > /tmp/acceptance-test-containment.txt"
                ),
                description="Blocks the Bash side-door as well as the Write tool",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    r"outside the repository root",
                ],
                safety_notes="Nothing is created - the command is denied before it runs.",
                test_type=TestType.BLOCKING,
                setup_commands=[],
                cleanup_commands=[],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="The same scratch write, inside the repository",
                command=(
                    # Absolute, unlike the tracked guidance that names the same
                    # directory relatively (Decision 10): the playbook renders
                    # this verbatim for an agent, and a relative file_path is
                    # denied by AbsolutePathHandler first -- which would turn
                    # this ALLOW case into a pass for entirely the wrong reason.
                    f"Use the Write tool to write to {scratch_path('acceptance-probe.md')} "
                    "with content '# probe'"
                ),
                description=(
                    "The near miss: identical intent and identical content, differing "
                    "only in whether the destination is inside the repo. A guard that "
                    "denied this too would be blocking scratch rather than blocking "
                    "ephemerality, and would be switched off within a day."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Writes one small file into the gitignored scratch directory; "
                    "removed by the cleanup command."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[],
                cleanup_commands=[f"rm -f {SCRATCH_DIR}/acceptance-probe.md"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
