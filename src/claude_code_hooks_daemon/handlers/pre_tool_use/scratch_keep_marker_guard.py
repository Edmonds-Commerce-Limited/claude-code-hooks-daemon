"""Deny an agent writing a `.scratch-keep` marker (Plan 00627, R-SCRATCH-KEEP-MARKER).

A scratch entry holding `.scratch-keep` is KEPT for ever by the sweep (DESIGN
R15), so the marker is a human's decision. An agent that could write it could
pin its own clutter past every TTL; one that could remove it could unpin a
human's keep. So every write route is judged on the file NAME: `Write`/`Edit`,
and a Bash command's redirects, `tee`, `cp`/`mv`/`install`/`dd`, `ln`, `touch`
and `rm`, read by the shared write scan. Past that scan: a copy whose SOURCE
is the marker into a directory (`cp .scratch-keep DIR/`), a shell `-c` body
(scanned as a command of its own), and an interpreter (`python3 -c`, `perl -e`
...) whose code names the marker, which fails closed.

A destination the scan cannot resolve (`> "$DIR/.scratch-keep"`) or command
text it cannot read fails CLOSED when it names the marker: where it writes is
unknown, and the name is the whole rule.
"""

import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.scratch_verdict import KEEP_MARKER
from claude_code_hooks_daemon.core.utils import (
    get_bash_command,
    get_file_path,
    scan_bash_write_targets,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_predicates import path_is_dir
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path
from claude_code_hooks_daemon.utils.scratch_dir_creation import (
    UnparseableCommand,
    copy_operands,
    peeled_statements,
)
from claude_code_hooks_daemon.utils.simple_commands import SimpleCommand, nested_command_strings

logger = logging.getLogger(__name__)

#: Acceptance-test fixture directory, below the gitignored acceptance root.
_FIXTURE_DIR: Final[str] = "acceptance-test-scratch-keep"
_COPY_VERBS: Final[frozenset[str]] = frozenset({"cp", "mv", "install", "ln"})
_INTERPRETER: Final[re.Pattern[str]] = re.compile(
    r"(?:python|pypy)[0-9.]*|perl|ruby|node|nodejs|deno|bun|php|lua|Rscript|osascript"
)
_MAX_NESTING: Final[int] = 3

_RULE = Rule(
    rule_id=RuleID.SCRATCH_KEEP_MARKER,
    blocked="an agent creating, changing or removing a `.scratch-keep` marker",
    why=(
        "The marker keeps a scratch entry for ever, so it is a human's decision; "
        "an agent's own keep would outlive every TTL"
    ),
    fix=(
        "Pause the entry instead (`hooks-daemon scratch-sweep keep <entry> --reason ...`, "
        "bounded), file what is worth keeping where git carries it, or ask the human "
        "to add the marker"
    ),
    verbose=(
        "WHY BLOCKED:\n"
        "A scratch entry holding `.scratch-keep` is KEPT by the sweep for ever.\n"
        "Pinning an entry for ever is a human's decision (Plan 00627 R15): an\n"
        "agent's keep would outlive every TTL, and an agent's removal would undo\n"
        "a human's keep. Every write route naming the file is denied, including\n"
        "Bash redirects, tee, cp/mv/install, ln, touch and rm."
    ),
)


def _names_marker(path: str) -> bool:
    """Whether ``path``'s final component is the keep marker."""
    return PurePosixPath(path.rstrip("/") or "/").name == KEEP_MARKER


def _copies_marker_into_directory(words: list[str], cwd: str | None) -> bool:
    """``cp .scratch-keep DIR/``: the copy is named after its source."""
    if words[0] not in _COPY_VERBS:
        return False
    sources, destination, into_directory = copy_operands(words[1:])
    if not any(_names_marker(source) for source in sources) or destination is None:
        return False
    if into_directory or "$" in destination or "`" in destination:
        return True
    # An unreadable destination may be a directory: fail closed.
    return path_is_dir(Path(cwd or "/") / destination, unreadable_means=True)


def _interpreter_names_marker(words: list[str]) -> bool:
    """An interpreter whose code or arguments name the marker fails closed:
    what its code writes cannot be read."""
    return bool(_INTERPRETER.fullmatch(words[0])) and any(KEEP_MARKER in w for w in words[1:])


def _bash_writes_marker(hook_input: dict[str, Any], *, depth: int) -> bool:
    """The shared write scan, then the routes it does not follow: a copy into
    a directory, an interpreter's code, and a shell ``-c`` body (scanned whole)."""
    scan = scan_bash_write_targets(hook_input, include_mutations=True)
    if any(_names_marker(path) for path in scan.paths):
        return True
    if any(_names_marker(token) for token in scan.unresolved):
        return True
    if scan.unreadable is not None and KEEP_MARKER in scan.unreadable:
        return True
    command = get_bash_command(hook_input) or ""
    if KEEP_MARKER not in command:
        return False
    cwd = hook_input.get(HookInputField.CWD)
    try:
        return _statement_routes_write_marker(hook_input, command, cwd, depth=depth)
    except UnparseableCommand as exc:
        log_and_continue(
            logger,
            exc,
            reason=(
                "keep-marker guard: the copy/interpreter/shell-body routes cannot read "
                "unlexable text, so only the shared write scan above judged this command"
            ),
        )
    return False


def _statement_routes_write_marker(
    hook_input: dict[str, Any], command: str, cwd: Any, *, depth: int
) -> bool:
    """The routes the shared write scan does not follow, statement by statement.

    Raises :class:`UnparseableCommand` where the command cannot be lexed.
    """
    for words in peeled_statements(command):
        if _copies_marker_into_directory(words, cwd) or _interpreter_names_marker(words):
            return True
        bodies = nested_command_strings(
            SimpleCommand(
                verb=words[0], words=tuple(words), operands=tuple(words[1:]), reread=False
            )
        )
        for body in bodies:
            if KEEP_MARKER not in body:
                continue
            if depth >= _MAX_NESTING:
                return True
            nested = {**hook_input, HookInputField.TOOL_INPUT: {"command": body}}
            if _bash_writes_marker(nested, depth=depth + 1):
                return True
    return False


class ScratchKeepMarkerGuardHandler(PreToolUseHandlerBase):
    """Block every agent write route onto a file named `.scratch-keep`.

    Priority: 18 (safety band, beside write_protected_paths)
    Terminal: True
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SCRATCH_KEEP_MARKER_GUARD,
            priority=Priority.SCRATCH_KEEP_MARKER_GUARD,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when a Write/Edit path or a Bash write names the marker."""
        file_path = get_file_path(hook_input)
        if file_path is not None:
            return bool(file_path) and _names_marker(file_path)
        return _bash_writes_marker(hook_input, depth=0)

    def get_rules(self) -> list[Rule]:
        """Return the single Rule this handler denies under."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny the write, naming the bounded alternative."""
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult(
            decision=Decision.DENY,
            reason=(
                f"{RuleFormatter().verbose(_RULE)}\n\n"
                "Only a human may pin a scratch entry for ever. An agent may pause "
                "one for a bounded time, with a reason."
            ),
        )

    def get_claude_md(self) -> str | None:
        return (
            "## scratch_keep_marker_guard — `.scratch-keep` is a human's mark\n\n"
            "A scratch entry holding a `.scratch-keep` file is never swept, so an agent "
            "may not create, change or remove that file: `Write`/`Edit`, and a Bash "
            "redirect, `tee`, `cp`/`mv`/`install`, `ln`, `touch` or `rm` naming it, are "
            "denied (R-SCRATCH-KEEP-MARKER). A destination built from a variable that "
            "names the marker is denied too, as are `cp .scratch-keep DIR/`, a `sh -c` "
            "body that writes it, and any `python3 -c`/`perl -e`/`node -e` code naming it. "
            "A script on disk that writes the marker, or a name assembled at run time, "
            "is not followed.\n\n"
            "**Instead**: file the work where git carries it (a plan folder, a test, "
            "docs), pause the entry for a bounded time with a reason "
            "(`hooks-daemon scratch-sweep keep`), or ask the human to add the marker."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests: a Write and a Bash touch of the marker are denied."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        marker = acceptance_path(_FIXTURE_DIR, KEEP_MARKER)
        write_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={"file_path": marker, "content": "keep: agent says so\n"},
        )
        setup = [f"mkdir -p untracked/acceptance/{_FIXTURE_DIR}"]
        cleanup = [f"rm -rf untracked/acceptance/{_FIXTURE_DIR}"]
        return [
            AcceptanceTest(
                title="Write a .scratch-keep marker",
                command=write_probe.as_instruction(),
                tool_payload=write_probe,
                description="Blocks an agent pinning a scratch entry with Write",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-SCRATCH-KEEP-MARKER", r"human"],
                safety_notes="Inside the gitignored acceptance directory; denied before the write.",
                test_type=TestType.BLOCKING,
                setup_commands=setup,
                cleanup_commands=cleanup,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="touch a .scratch-keep marker",
                command=f"touch {marker}",
                dispatch_as_bash=True,
                description="Blocks an agent pinning a scratch entry with a Bash touch",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-SCRATCH-KEEP-MARKER", r"human"],
                safety_notes="Inside the gitignored acceptance directory; denied before it runs.",
                test_type=TestType.BLOCKING,
                setup_commands=setup,
                cleanup_commands=cleanup,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="read a .scratch-keep marker (near miss)",
                command=f"cat {marker}",
                dispatch_as_bash=True,
                description="Reading the marker names it but writes nothing, so it is allowed",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="A read inside the gitignored acceptance directory; a missing file only errors.",
                test_type=TestType.BLOCKING,
                setup_commands=setup,
                cleanup_commands=cleanup,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
