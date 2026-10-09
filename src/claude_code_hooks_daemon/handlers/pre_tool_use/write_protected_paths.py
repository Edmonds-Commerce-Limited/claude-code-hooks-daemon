"""Handler keeping listed paths read-only for agents (Plan 00499).

Some files are maintained outside the agent: an infrastructure-as-code run
places them, or a human edits them, and the agent only ever READS them. This
handler denies every route by which an agent could create, change, move onto or
delete such a file, and never denies reading one.

It is off by default and does nothing without the ``paths`` option, a list of
repository-relative globs. It covers the file tools (``Write``, ``Edit``,
``NotebookEdit``) and the Bash routes the shared write scan can name: a
redirect, ``tee``, a heredoc redirect, ``sed -i``, ``dd of=``, a copy, move,
install or link onto the path, and a deletion or truncation of it
(``rm``, ``unlink``, ``touch``, ``truncate``, ``: >``). Past those precise routes, a command that
names a listed path and is not known to only read it (:data:`READ_ONLY_VERBS`) is denied: wrappers
(``flock``, ``chronic``), brace groups, ``for`` loops, ``bash -c`` / ``eval`` strings and absolute
command paths are read through to the command they run. It is a guard against an agent's mistake,
not against a human or a process running outside Claude Code.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar, Final

from claude_code_hooks_daemon.constants import HandlerTag, HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import repository_root, scan_bash_write_targets
from claude_code_hooks_daemon.utils.shell_expansion import TooManyToEnumerateError
from claude_code_hooks_daemon.utils.simple_commands import (
    SHELL_INTERPRETERS,
    SimpleCommand,
    brace_variants,
    git_subcommand,
    nested_command_strings,
    simple_commands,
    text_from,
    unquote,
    unroll_for_loops,
)

#: Commands known to only READ the files they are given. A command naming a listed
#: path that is on none of these lists is denied (fail closed): what it does to
#: the file is unknown. A write redirect onto the path is judged apart, by the
#: shared write scan, whatever command carries it.
READ_ONLY_VERBS: Final[frozenset[str]] = frozenset(
    {
        # print or search
        "cat",
        "tac",
        "less",
        "more",
        "head",
        "tail",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "wc",
        "nl",
        "od",
        "strings",
        "cut",
        "jq",
        "cmp",
        "diff",
        # describe
        "ls",
        "stat",
        "file",
        "lsattr",
        "du",
        "readlink",
        "realpath",
        "basename",
        "dirname",
        "sha1sum",
        "sha256sum",
        "sha512sum",
        "md5sum",
        "cksum",
        # test
        "test",
        "[",
        "[[",
        "true",
        "false",
        ":",
        # print text
        "echo",
        "printf",
        # read a file into the shell, or change only shell state
        "source",
        ".",
        "export",
        "unset",
        "declare",
        "readonly",
        "local",
        "set",
        "cd",
        "pushd",
        "popd",
        "type",
        "which",
    }
)

#: Commands whose effect on a file the shared write scan judges precisely
#: (a redirect-free ``cp {p} /tmp/x`` is a read, ``rm {p}`` is not).
SCAN_JUDGED_VERBS: Final[frozenset[str]] = frozenset(
    {"cp", "mv", "install", "ln", "rm", "unlink", "touch", "truncate", "tee", "dd", "sed"}
)

#: ``git`` subcommands that never change a working-tree file's content.
GIT_READ_ONLY_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {
        "diff",
        "log",
        "show",
        "status",
        "blame",
        "annotate",
        "ls-files",
        "ls-tree",
        "grep",
        "add",
        "commit",
        "rev-parse",
        "check-ignore",
        "cat-file",
        "diff-tree",
        "shortlog",
    }
)
#: ``git`` subcommands the shared write scan judges (``git rm``, ``git mv``).
GIT_SCAN_JUDGED_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"rm", "mv"})
_GIT: Final[str] = "git"
_EVAL: Final[str] = "eval"

#: Every command this handler has a rule for; behind a wrapper it does not
#: know, the first later word naming one of these is the command the wrapper runs.
_KNOWN_VERBS: Final[frozenset[str]] = (
    READ_ONLY_VERBS | SCAN_JUDGED_VERBS | SHELL_INTERPRETERS | {_GIT, _EVAL}
)

#: How many levels of ``bash -c '...'`` / ``eval`` are read as commands; past it
#: the code is judged by whether it visibly names a listed path.
MAX_SHELL_DEPTH: Final[int] = 3

#: The tool-input field each file tool names its target in.
_FILE_TOOL_TARGET_KEYS: Final[dict[str, str]] = {
    ToolName.WRITE: "file_path",
    ToolName.EDIT: "file_path",
    ToolName.NOTEBOOK_EDIT: "notebook_path",
}

PATHS_OPTION: Final[str] = "paths"

_RECURSIVE: Final[str] = "**"
_WILDCARDS: Final[re.Pattern[str]] = re.compile(r"[*?\[]")
_EXPANSION_CHARS: Final[str] = "$`"

#: A command that builds a path from a substitution the scan reads as separate
#: words. Such a path is judged by its file name as well.
_SUBSTITUTION_RE: Final[re.Pattern[str]] = re.compile(r"\$\(|`")

#: `xargs` running a verb that changes the files it is handed.
_XARGS_MUTATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\bxargs\b[^|;&]*?\b(?:rm|unlink|touch|truncate|mv)\b"
)

#: Shell syntax whose scope a plain cut at the separators would get wrong.
_NOT_SEQUENTIAL_RE: Final[re.Pattern[str]] = re.compile(r"[(){}`]|<<")
#: A part that sets a variable (`F=value`, `export F=value`).
_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(r"^(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*=")
_EXPORT_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^export\s+")
#: A part that is nothing but a directory change.
_CD_COMMAND_RE: Final[re.Pattern[str]] = re.compile(
    r"^(cd|pushd|popd)(?:\s+(?:-[LP]\s+)?(?:--\s+)?(\"[^\"]*\"|'[^']*'|\S+))?\s*$"
)

#: A redirection on a `cd` (`2>/dev/null`, `>/dev/null 2>&1`, `&> log`): it does
#: not stop the `cd` changing the directory.
_CD_REDIRECT_RE: Final[re.Pattern[str]] = re.compile(r"\s+[0-9]*(?:&>>?|>>?|<)&?\s*[^\s;&|<>]+")

_CD_WORD_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:cd|pushd|popd)\b")
_CD_ARGUMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:cd|pushd)\s+(?:-[LP]\s+)?(?:--\s+)?(\"[^\"]*\"|'[^']*'|[^\s;&|()]+)"
)
#: A `cd` argument the handler cannot follow to a directory.
_UNFOLLOWABLE_CD: Final[re.Pattern[str]] = re.compile(r"[$`*?~]|^-$")
#: Characters that make a name part of a longer one (`.env` inside `.envrc`).
_NAME_CHARACTER: Final[str] = r"[\w.-]"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.WRITE_PROTECTED_PATH,
    blocked="a write, move onto, deletion or truncation of a path the project keeps read-only",
    why="The file is maintained outside the agent (infrastructure-as-code or a human); an agent's change is overwritten or breaks that process",
    fix="Do not change it; ask the human for any change to the file",
    verbose=(
        "WHY BLOCKED:\n"
        "This project lists the path below as maintained OUTSIDE the agent: an\n"
        "infrastructure-as-code (IaC) run places it, or a human edits it. Agents may\n"
        "read it and must never create, change, overwrite, move onto, link over,\n"
        "truncate or delete it, by any tool or any shell command.\n\n"
        "DO INSTEAD:\n"
        "  Leave the file alone and ask the human for the change you need.\n"
        "  Reading it is always allowed with a command known to only read (cat, grep,\n"
        "  head, tail, ls, diff, stat, git diff); any other command that names it is\n"
        "  refused because what it does to the file is unknown."
    ),
)


def _segments(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _matches_in_full(path: Sequence[str], glob: Sequence[str]) -> bool:
    """Do the components of ``path`` match those of ``glob``? ``**`` spans directories."""
    if not glob:
        return not path
    head, rest = glob[0], glob[1:]
    if head == _RECURSIVE:
        return any(_matches_in_full(path[skip:], rest) for skip in range(len(path) + 1))
    return bool(path) and fnmatch.fnmatchcase(path[0], head) and _matches_in_full(path[1:], rest)


def _is_ancestor(path: Sequence[str], glob: Sequence[str]) -> bool:
    """Could ``path`` be a directory that holds a file ``glob`` names?

    Removing or moving such a directory removes the protected file with it.
    Below a recursive ``**`` no particular directory is singled out, so only
    the directories above it count.
    """
    if not path:
        return bool(glob)
    if not glob or glob[0] == _RECURSIVE:
        return False
    return fnmatch.fnmatchcase(path[0], glob[0]) and _is_ancestor(path[1:], glob[1:])


def _segment_could_match(token: str, listed: str) -> bool:
    """Could a path component written as ``token`` be one ``listed`` describes?

    Wildcards follow the shell: a wildcard component never matches a name that
    starts with a dot unless it starts with one itself.
    """
    token_wild = _WILDCARDS.search(token) is not None
    listed_wild = _WILDCARDS.search(listed) is not None
    if not token_wild and not listed_wild:
        return token == listed
    if token_wild and listed.startswith(".") and not token.startswith("."):
        return False
    if token_wild and not listed_wild:
        return fnmatch.fnmatchcase(listed, token)
    if listed_wild and not token_wild:
        return fnmatch.fnmatchcase(token, listed)
    return True


def _could_match(token: Sequence[str], listed: Sequence[str]) -> bool:
    """Could a shell wildcard path, as components, expand to a listed path or to a
    directory that holds one? ``token`` may stop early: that is a directory."""
    if not token:
        return True
    if not listed:
        return False
    if listed[0] == _RECURSIVE:
        return _could_match(token, listed[1:]) or _could_match(token[1:], listed)
    return _segment_could_match(token[0], listed[0]) and _could_match(token[1:], listed[1:])


def _names_chain(written: Sequence[str], glob: str) -> bool:
    """Do the last components of ``written`` name ``glob``'s file, or a directory above
    it together with the whole chain of directories that leads to it?

    A bare directory name (`.claude`, `ccy`) is not enough: it is the name of
    unrelated directories everywhere.
    """
    parts = [part for part in _segments(glob) if part != _RECURSIVE]
    if not written or not parts:
        return False
    if fnmatch.fnmatchcase(written[-1], parts[-1]):
        return True
    for last in range(1, len(parts) - 1):
        if _is_all_wildcard(parts[last]) or len(written) < last + 1:
            continue
        tail = written[len(written) - last - 1 :]
        if all(fnmatch.fnmatchcase(name, part) for name, part in zip(tail, parts, strict=False)):
            return True
    return False


def _is_all_wildcard(part: str) -> bool:
    return not part.strip("*?")


def _name_pattern(glob: str) -> re.Pattern[str] | None:
    """A pattern finding the literal part of ``glob``'s file name in free text,
    only as a whole name; ``None`` when the name has no literal part."""
    parts = _segments(glob)
    last = parts[-1] if parts else ""
    fragments = [fragment for fragment in _WILDCARDS.split(last) if fragment]
    if not fragments:
        return None
    fragment = max(fragments, key=len)
    start = last.find(fragment)
    before = f"(?<!{_NAME_CHARACTER})" if start == 0 else ""
    after = f"(?!{_NAME_CHARACTER})" if start + len(fragment) == len(last) else ""
    return re.compile(f"{before}{re.escape(fragment)}{after}")


def _split_sequence(command: str) -> list[str] | None:
    """``command`` cut at the separators that run its parts one after another
    (`;`, `&&`, `||`, a newline), outside quotes; ``None`` if a quote never closes."""
    parts: list[str] = []
    current: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        pair = command[index : index + 2]
        if quote:
            if char == "\\" and quote == '"':
                current.append(command[index : index + 2])
                index += 2
                continue
            quote = "" if char == quote else quote
        elif char == "\\":
            current.append(command[index : index + 2])
            index += 2
            continue
        elif char in "'\"":
            quote = char
        elif char in ";\n" or pair in ("&&", "||"):
            parts.append("".join(current))
            current = []
            index += 1 if char in ";\n" else 2
            continue
        current.append(char)
        index += 1
    if quote:
        return None
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _option_problem(options: Mapping[str, Any]) -> str | None:
    """Why the ``paths`` option is unusable, or None."""
    if PATHS_OPTION not in options:
        return None
    value = options[PATHS_OPTION]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return f"{PATHS_OPTION} must be a list of repository-relative path globs"
    for item in value:
        if not item.strip():
            return f"{PATHS_OPTION} must not hold an empty path"
        if item.startswith("/") or ".." in _segments(item):
            return f"{PATHS_OPTION} entries are relative to the repository root: {item!r}"
    return None


class WriteProtectedPathsHandler(PreToolUseHandlerBase):
    """Deny any agent write to a configured path; reading is never denied.

    Opt-in: ships disabled, and without ``paths`` it matches nothing.
    """

    default_enabled = False

    #: Injected by the registry from the handler's options (``self._<key>``).
    _paths: list[str] | None = None

    _TOOLS: ClassVar[frozenset[str]] = frozenset({*_FILE_TOOL_TARGET_KEYS, ToolName.BASH})

    def __init__(self, project_root: Path | None = None) -> None:
        super().__init__(
            handler_id=HandlerID.WRITE_PROTECTED_PATHS,
            priority=Priority.WRITE_PROTECTED_PATHS,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._project_root = project_root
        self._last: tuple[str, str | None] | None = None

    def get_default_enabled(self) -> bool:
        """Off until a project lists the paths it keeps read-only."""
        return False

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed ``paths`` value; the handler then protects nothing."""
        problem = _option_problem(options)
        return {PATHS_OPTION: problem} if problem is not None else {}

    # ------------------------------------------------------------------
    # Where is a path, relative to the project?
    # ------------------------------------------------------------------

    def _root(self) -> Path:
        return self._project_root or ProjectContext.project_root()

    def _roots(self, cwd: str) -> list[str]:
        """The project root and the repository root the call runs in (a worktree
        is a separate checkout of the same project), as written and resolved."""
        found = [str(self._root())]
        enclosing = repository_root(cwd)
        if enclosing is not None:
            found.append(enclosing)
        return list(dict.fromkeys([*found, *(os.path.realpath(root) for root in found)]))

    @staticmethod
    def _relative(path: str, roots: Sequence[str]) -> Iterator[list[str]]:
        """``path`` below each root it sits under, as components."""
        for form in dict.fromkeys((os.path.normpath(path), os.path.realpath(path))):
            for root in roots:
                if form == root or form.startswith(root.rstrip("/") + "/"):
                    yield _segments(form[len(root) :])

    def _globs(self) -> list[str]:
        # `validate_options` withholds a malformed value, so this is a list of strings.
        return [glob for glob in (self._paths or []) if glob.strip()]

    def _protecting(
        self, path: str, roots: Sequence[str], *, directories: bool = True
    ) -> str | None:
        """The glob keeping ``path`` (or, with ``directories``, a file inside it) read-only."""
        globs = self._globs()
        for relative in self._relative(path, roots):
            for glob in globs:
                parts = _segments(glob)
                if _matches_in_full(relative, parts) or (
                    directories and _is_ancestor(relative, parts)
                ):
                    return glob
        return None

    def _protecting_by_name(self, path: str) -> str | None:
        """The glob whose file name, or directory chain, ``path`` ends with."""
        written = _segments(path)
        return next((glob for glob in self._globs() if _names_chain(written, glob)), None)

    def _token_naming(self, token: str, roots: Sequence[str], bases: Sequence[str]) -> str | None:
        """The glob an unresolved destination ``token`` visibly names, else None.

        Where the token writes is unknown, so it is judged by what it SAYS. A
        token built from an expansion (`$DIR/name`) has an unknown directory, so
        only its final component is judged, whole. A plain wildcard is expanded
        the way the shell would from each directory the command may be in: a
        `*` stays inside one component and never matches a leading dot.
        """
        if any(char in token for char in _EXPANSION_CHARS):
            written = _segments(token)
            if not written or any(char in written[-1] for char in _EXPANSION_CHARS):
                return None
            return next((glob for glob in self._globs() if _names_chain(written, glob)), None)
        for base in bases:
            written = _segments(os.path.normpath(str(Path(base) / token)))
            for root in roots:
                for glob in self._globs():
                    if _could_match(written, [*_segments(root), *_segments(glob)]):
                        return glob
        return None

    def _text_naming(self, text: str) -> str | None:
        """The glob that command text we could not read visibly names, else None."""
        for glob in self._globs():
            pattern = _name_pattern(glob)
            if pattern is None or pattern.search(text):
                return glob
        return None

    @staticmethod
    def _runs(command: str, working: str) -> tuple[list[tuple[str | None, str]], bool]:
        """Where each part of a command runs, and whether that is only a guess.

        Returns ``(text, directory)`` pairs, ``text`` being ``None`` for the whole
        command. Without a ``cd`` that is the whole command in the hook's
        directory. A plain sequence of commands is cut at its separators and
        each part is placed in the directory a literal ``cd`` left it in. Anything
        the cut cannot be trusted with (subshells, groups, substitutions,
        heredocs) is judged whole from every directory the command names, which
        over-claims rather than misses. A ``cd`` it cannot follow (`cd "$D"`,
        `cd -`, `popd`) or a path built by a substitution makes the result
        untrusted, so paths are also judged by file name.
        """
        untrusted = _SUBSTITUTION_RE.search(command) is not None
        if _CD_WORD_RE.search(command) is None:
            return [(None, working)], untrusted
        parts = None if _NOT_SEQUENTIAL_RE.search(command) else _split_sequence(command)
        if parts is None:
            bases = [working]
            for raw in _CD_ARGUMENT_RE.findall(command):
                argument = raw.strip("\"'")
                if _UNFOLLOWABLE_CD.search(argument):
                    untrusted = True
                else:
                    bases.append(os.path.normpath(str(Path(bases[-1]) / argument)))
            unfollowed = len(_CD_WORD_RE.findall(command)) != len(bases) - 1
            return [(None, base) for base in bases], untrusted or unfollowed
        runs: list[tuple[str | None, str]] = []
        directory = working
        assignments: list[str] = []
        for part in parts:
            change = _CD_COMMAND_RE.match(_CD_REDIRECT_RE.sub("", part))
            if change is None:
                untrusted = untrusted or _CD_WORD_RE.search(part) is not None
                # Each part is read alone, so the variables set before it travel with it.
                runs.append(("; ".join([*assignments, part]), directory))
                if _ASSIGNMENT_RE.match(part):
                    assignments.append(_EXPORT_PREFIX_RE.sub("", part))
                continue
            argument = (change.group(2) or "").strip("\"'")
            if change.group(1) == "popd" or not argument or _UNFOLLOWABLE_CD.search(argument):
                untrusted = True
            else:
                directory = os.path.normpath(str(Path(directory) / argument))
        return runs, untrusted

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _violation(self, hook_input: dict[str, Any]) -> str | None:
        """The glob this call breaks, or None when it leaves every listed path alone.

        ``matches`` and ``handle`` ask about the same call back to back, so the
        last answer is kept and the command is read once.
        """
        key = repr(
            (
                hook_input.get(HookInputField.TOOL_NAME),
                hook_input.get(HookInputField.TOOL_INPUT),
                hook_input.get(HookInputField.CWD),
            )
        )
        if self._last is not None and self._last[0] == key:
            return self._last[1]
        glob = self._judge(hook_input)
        self._last = (key, glob)
        return glob

    def _judge(self, hook_input: dict[str, Any]) -> str | None:
        if not self._globs():
            return None
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        cwd = hook_input.get(HookInputField.CWD)
        working = cwd if isinstance(cwd, str) and cwd else str(self._root())
        roots = self._roots(working)

        key = _FILE_TOOL_TARGET_KEYS.get(str(tool_name))
        if key is not None:
            named = hook_input.get(HookInputField.TOOL_INPUT, {}).get(key)
            if not isinstance(named, str) or not named:
                return None
            return self._protecting(str(Path(working) / named), roots)
        if tool_name != ToolName.BASH:
            return None
        return self._bash_violation({**hook_input, HookInputField.CWD: working}, roots, working)

    def _bash_violation(
        self, hook_input: dict[str, Any], roots: Sequence[str], working: str
    ) -> str | None:
        """The glob a shell command breaks, judged from every directory it may run in."""
        raw = hook_input[HookInputField.TOOL_INPUT].get("command", "")
        command = raw if isinstance(raw, str) else ""
        return self._spelled_violation(command, hook_input, roots, working, 0, set())

    def _spelled_violation(
        self,
        command: str,
        hook_input: dict[str, Any],
        roots: Sequence[str],
        working: str,
        depth: int,
        judged: set[tuple[str, str]],
    ) -> str | None:
        """The glob ``command`` breaks once its brace groups and ``for`` loops are spelled out.

        ``judged`` holds the nested command strings already judged from a
        directory, so a body repeated by each spelling of an outer group is
        read once.
        """
        try:
            variants = list(brace_variants(command))
        except TooManyToEnumerateError:
            # Too many spellings to list: the command is judged by whether it
            # visibly names a listed path.
            return self._text_naming(command)
        for variant in variants:
            glob = self._command_violation(
                unroll_for_loops(variant), hook_input, roots, working, depth, judged
            )
            if glob is not None:
                return glob
        return None

    def _scan_text(
        self,
        text: str,
        base: str,
        hook_input: dict[str, Any],
        roots: Sequence[str],
        untrusted: bool,
    ) -> tuple[str | None, list[str], str | None]:
        """What the shared write scan makes of ``text`` run in ``base``: the glob
        it breaks, the destinations it could not place and the text it could not read."""
        tool_input = hook_input[HookInputField.TOOL_INPUT]
        part = {**hook_input, HookInputField.TOOL_INPUT: {**tool_input, "command": text}}
        scan = scan_bash_write_targets({**part, HookInputField.CWD: base}, include_mutations=True)
        for path in scan.paths:
            glob = self._protecting(path, roots)
            if glob is None and untrusted:
                glob = self._protecting_by_name(path)
            if glob is not None:
                return glob, [], None
        return None, list(scan.unresolved), scan.unreadable

    def _command_violation(
        self,
        command: str,
        hook_input: dict[str, Any],
        roots: Sequence[str],
        working: str,
        depth: int,
        judged: set[tuple[str, str]],
    ) -> str | None:
        """The glob a command, its braces already spelled out, breaks."""
        runs, untrusted = self._runs(command, working)
        bases = list(dict.fromkeys(directory for _, directory in runs))
        unresolved: list[str] = []
        unreadable: str | None = None
        for run, base in runs:
            text = command if run is None else run
            glob, tokens, unread = self._scan_text(text, base, hook_input, roots, untrusted)
            if glob is not None:
                return glob
            unresolved.extend(token for token in tokens if token not in unresolved)
            unreadable = unreadable if unreadable is not None else unread
            glob = self._verbs_violation(text, (base, roots, untrusted, hook_input), depth, judged)
            if glob is not None:
                return glob
        # `xargs rm` takes its operands from the pipe, so none are visible to
        # the scan: the command text is what can name the file.
        for pipeline in _split_sequence(command) or [command]:
            if _XARGS_MUTATION_RE.search(pipeline):
                glob = self._text_naming(pipeline)
                if glob is not None:
                    return glob
        # What the scan could not place is unknown, not nothing: it is denied
        # only when it visibly names a listed path.
        for token in unresolved:
            glob = self._token_naming(token, roots, bases)
            if glob is not None:
                return glob
        return self._text_naming(unreadable) if unreadable is not None else None

    # ------------------------------------------------------------------
    # Judging the verb each simple command runs (Plan 00499 Phase 1b)
    # ------------------------------------------------------------------

    def _verbs_violation(
        self,
        text: str,
        where: tuple[str, Sequence[str], bool, dict[str, Any]],
        depth: int,
        judged: set[tuple[str, str]],
    ) -> str | None:
        """The glob a simple command of ``text`` breaks, judged by its verb.

        The shared scan names the routes it knows; this reads what the command
        IS. A command that names a listed path and is not known to only read is
        denied, whatever wraps it. Code handed to a shell is read as commands.
        """
        for command in simple_commands(text, known_verbs=_KNOWN_VERBS):
            if command.reread:
                glob = self._rescanned(command.text, where)
                if glob is not None:
                    return glob
            bodies = nested_command_strings(command)
            for body in bodies:
                glob = self._nested_violation(body, where, depth, judged)
                if glob is not None:
                    return glob
            if bodies or self._only_reads_or_is_scanned(command):
                continue
            glob = self._unknown_command_violation(command, where)
            if glob is not None:
                return glob
        return None

    @staticmethod
    def _only_reads_or_is_scanned(command: SimpleCommand) -> bool:
        """Is the command's effect on a file known: a read, or a verb the scan judges?"""
        verb = command.verb
        if verb in READ_ONLY_VERBS or verb in SCAN_JUDGED_VERBS or verb in SHELL_INTERPRETERS:
            return True
        if verb == _EVAL:
            return True
        if verb == _GIT:
            subcommand = git_subcommand(command)
            return subcommand in GIT_READ_ONLY_SUBCOMMANDS | GIT_SCAN_JUDGED_SUBCOMMANDS
        return False

    def _rescanned(
        self, text: str, where: tuple[str, Sequence[str], bool, dict[str, Any]]
    ) -> str | None:
        """The glob the shared scan finds in a command it did not see as written:
        its verb sat behind an absolute path or a wrapper."""
        base, roots, untrusted, hook_input = where
        glob, unresolved, unreadable = self._scan_text(text, base, hook_input, roots, untrusted)
        if glob is not None:
            return glob
        for token in unresolved:
            glob = self._token_naming(token, roots, [base])
            if glob is not None:
                return glob
        return self._text_naming(unreadable) if unreadable is not None else None

    def _nested_violation(
        self,
        body: str,
        where: tuple[str, Sequence[str], bool, dict[str, Any]],
        depth: int,
        judged: set[tuple[str, str]],
    ) -> str | None:
        """The glob code handed to a shell (``bash -c BODY``) breaks."""
        base, roots, _untrusted, hook_input = where
        if (body, base) in judged:
            return None
        judged.add((body, base))
        if depth >= MAX_SHELL_DEPTH:
            return self._text_naming(body)
        return self._spelled_violation(body, hook_input, roots, base, depth + 1, judged)

    def _unknown_command_violation(
        self, command: SimpleCommand, where: tuple[str, Sequence[str], bool, dict[str, Any]]
    ) -> str | None:
        """The glob an unrecognised command names: it may do anything to what it names."""
        base, roots, untrusted, _hook_input = where
        for operand in command.file_operands:
            glob = self._operand_naming(operand, roots, base, untrusted)
            if glob is not None:
                return glob
        # A verb the scan knows, run by a command this handler does not: the
        # directories it would remove count as well.
        for position, word in enumerate(command.words[1:], start=1):
            if unquote(word) in SCAN_JUDGED_VERBS:
                return self._rescanned(text_from(command.words, position), where)
        return None

    def _operand_naming(
        self, operand: str, roots: Sequence[str], base: str, untrusted: bool
    ) -> str | None:
        """The glob an operand of an unrecognised command names: the file itself, a
        wildcard that could expand to it, or ``--option=VALUE`` naming it."""
        candidates = [operand, operand.partition("=")[2]] if "=" in operand else [operand]
        for candidate in candidates:
            if not candidate:
                continue
            if _WILDCARDS.search(candidate) or any(char in candidate for char in _EXPANSION_CHARS):
                glob = self._token_naming(candidate, roots, [base])
            else:
                glob = self._protecting(str(Path(base) / candidate), roots, directories=False)
                if glob is None and untrusted:
                    glob = self._protecting_by_name(candidate)
            if glob is not None:
                return glob
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True when the call would change a listed path."""
        # A verdict is kept only between `matches` and the `handle` that follows
        # it, so an earlier answer is never reused for a later call.
        self._last = None
        if hook_input.get(HookInputField.TOOL_NAME) not in self._TOOLS:
            return False
        return self._violation(hook_input) is not None

    def get_rules(self) -> list[Rule]:
        """The Rule backing this handler's denial."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, saying the file is maintained outside the agent."""
        glob = self._violation(hook_input)
        self._last = None
        if glob is None:
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult.deny(f"{RuleFormatter().verbose(_RULE)}\n\nPROTECTED PATH: {glob}")

    # ------------------------------------------------------------------
    # Guidance and acceptance
    # ------------------------------------------------------------------

    def get_claude_md(self) -> str | None:
        """Resident guidance: what is protected and who to ask."""
        return (
            "## write_protected_paths — files maintained outside the agent are read-only\n\n"
            "Paths listed under `handlers.pre_tool_use.write_protected_paths.options.paths` "
            "are maintained by infrastructure-as-code or by a human. You may read them. "
            "`Write`, `Edit` and `NotebookEdit` on one are denied, and so is a Bash command "
            "that redirects into it, `tee`s, `dd`s or `sed -i`s it, copies, moves, "
            "installs or links (`ln`) onto it, or `touch`es, `truncate`s, `rm`s or `unlink`s it "
            "(or removes or moves a directory holding it, as `rm -rf` and `mv` do). A "
            "wildcard is denied when the shell could expand it to the file.\n\n"
            "**Any other command that names the file is denied too**, unless it is known to "
            "only read (`cat`, `grep`, `head`, `tail`, `ls`, `diff`, `stat`, `git diff`, ...): "
            "`perl -i`, `rsync`, `find -delete`, `flock ... rm` and the like. Brace groups "
            "(`{a,b}`), `for` loops, `bash -c '...'`, `eval`, a path to a command "
            "(`/bin/rm`) and wrappers are read through to the command they run.\n\n"
            "**Known gaps, still not for you to use**: code inside an interpreter "
            "(`python -c`/`open()`, `perl -e`), a heredoc fed to one, and a directory "
            "removed by a tool the guard does not know that names only the directory "
            "(`find .claude -delete`) reach the file without being seen. The rule is the "
            "same whether or not the guard sees the route. Quote a heredoc delimiter "
            "(`<<'EOF'`) when its body only mentions the path.\n\n"
            "**When it is denied, do not look for another route to the same file.** Ask the "
            "human for the change you need; the file is theirs (or the IaC's) to place."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """A near-miss that must allow, and the deny declared as undrivable."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="write protected paths - echo that only names a file",
                command='echo "ccy.env.local is maintained by IaC"',
                dispatch_as_bash=True,
                description=(
                    "Mentioning a file name in text is not writing it: nothing is "
                    "redirected, copied, moved or deleted."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to execute; touches no file.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="write protected paths - write to a listed path",
                command="Write, or run `echo x > <a listed path>` / `rm <a listed path>`",
                description=(
                    "Denied with the message that the file is maintained outside the "
                    "agent (IaC or a human) and the human is the one to ask."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"IaC", r"human", r"PROTECTED PATH"],
                safety_notes=(
                    "A probe that fires only if the handler is loaded would WRITE the "
                    "real protected file when it is not. Never probe it live."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "The protected paths are the project's own configuration, and a probe "
                    "against one would create or destroy the real file if the handler were "
                    "not loaded. Covered by "
                    "tests/unit/handlers/pre_tool_use/test_write_protected_paths.py over "
                    "temporary files."
                ),
            ),
        ]
