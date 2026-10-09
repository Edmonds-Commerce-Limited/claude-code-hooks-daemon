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
        # filters and viewers; the ones that can write are checked apart
        "sort",
        "uniq",
        "awk",
        "gawk",
        "mawk",
        "xxd",
        "hexdump",
        "column",
        "bat",
        "view",
        "shellcheck",
        "comm",
        "paste",
        "fold",
        "expand",
        "unexpand",
        "rev",
        "base64",
    }
)

#: Options of a command in the read-only set that WRITE the file they are given.
WRITE_OPTIONS: Final[dict[str, frozenset[str]]] = {
    "git": frozenset({"--output"}),
    "less": frozenset({"-o", "-O", "--log-file"}),
    "sort": frozenset({"-o", "--output"}),
}
#: Readers that write their last file operand once they have more than this many.
MAX_READ_OPERANDS: Final[dict[str, int]] = {"xxd": 1, "uniq": 1}
#: ``awk`` options and program text that make it write.
_AWK_VERBS: Final[frozenset[str]] = frozenset({"awk", "gawk", "mawk"})
_AWK_IN_PLACE: Final[str] = "inplace"
_AWK_WRITING_PROGRAM_RE: Final[re.Pattern[str]] = re.compile(r">|\|&?|system\s*\(")

#: Options whose value is a file the command only READS, for any command.
READ_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {"--env-file", "--vault-password-file", "--vault-pass-file"}
)
#: The same, for commands whose ``-f`` / ``--file`` names an input file.
READ_FILE_OPTION_VERBS: Final[frozenset[str]] = frozenset(
    {"docker", "docker-compose", "podman", "podman-compose", "dotenv"}
)
READ_FILE_OPTIONS: Final[frozenset[str]] = frozenset({"-f", "--file"})

#: ``xargs`` options that take a value as the next word.
_XARGS_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {"-I", "-n", "-L", "-P", "-s", "-d", "-E", "-a", "--arg-file", "--max-args", "--max-procs"}
)
_XARGS_REPLACE_OPTION: Final[str] = "-I"
_XARGS: Final[str] = "xargs"
#: Commands that copy their operands out unless the producer's names are the destination.
_COPY_VERBS: Final[frozenset[str]] = frozenset({"cp", "install", "ln"})
#: Commands and their options that copy or move a directory tree.
_TREE_COPY_VERBS: Final[frozenset[str]] = frozenset({"cp", "mv", "install"})
_TREE_COPY_FLAG_LETTERS: Final[str] = "rRaT"
_TREE_COPY_LONG_FLAGS: Final[frozenset[str]] = frozenset(
    {"--recursive", "--archive", "--no-target-directory"}
)

#: ``find`` flags that change or write files, and those that run a command per file.
_FIND: Final[str] = "find"
_FIND_WRITE_FLAGS: Final[frozenset[str]] = frozenset(
    {"-delete", "-fprint", "-fprint0", "-fls", "-fprintf"}
)
_FIND_EXEC_FLAGS: Final[frozenset[str]] = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_FIND_NAME_FLAGS: Final[frozenset[str]] = frozenset({"-name", "-iname"})
_FIND_PATH_FLAGS: Final[frozenset[str]] = frozenset(
    {"-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex"}
)
_FIND_EXPRESSION_START: Final[tuple[str, ...]] = ("-", "(", "!", ")")

_OUTPUT_REDIRECT_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[0-9]*>|&>)")

#: Verbs that read lines into a variable, for a loop whose body writes through it.
_READ_LOOP_VERBS: Final[frozenset[str]] = frozenset({"read", "mapfile", "readarray"})

#: ``export F=P`` and the like set a variable; read as the plain assignment they are.
_DECLARATION_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"(^|[;&|\n(][ \t]*)(?:export|declare|typeset|local|readonly)(?:[ \t]+-[A-Za-z]+)*[ \t]+"
    r"(?=[A-Za-z_][A-Za-z0-9_]*=)"
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
#: How many nested command strings past that depth are read before the rest is
#: judged by name alone.
MAX_DEEP_BODIES: Final[int] = 64
#: How many variables set before a ``cd`` travel with each later part; past it the
#: result is untrusted, so paths are judged by file name as well.
MAX_CARRIED_ASSIGNMENTS: Final[int] = 32

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
        "  Read it with a command known to only read (cat, grep, head, tail, ls, diff,\n"
        "  stat, sort, awk, git diff); any other command that names it is refused\n"
        "  because what it does to the file is unknown. Pipe it instead: cat P | tool."
    ),
)


def _redirects_output(command: SimpleCommand) -> bool:
    """Does the command redirect its output into a file (`> f`, `2>> f`, `&> f`)?"""
    return any(_OUTPUT_REDIRECT_RE.match(word) for word in command.words[1:])


def _copies_a_tree(operand: str) -> bool:
    """Is ``operand`` a ``cp`` / ``mv`` flag that copies or moves a directory tree?"""
    if operand in _TREE_COPY_LONG_FLAGS:
        return True
    if operand.startswith("--") or not operand.startswith("-"):
        return False
    return any(letter in operand[1:] for letter in _TREE_COPY_FLAG_LETTERS)


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
        # The last assignment of each variable, in order of last use: a bounded
        # carry, so a long run of assignments is not re-read by every later part.
        assignments: dict[str, str] = {}
        for part in parts:
            change = _CD_COMMAND_RE.match(_CD_REDIRECT_RE.sub("", part))
            if change is None:
                untrusted = untrusted or _CD_WORD_RE.search(part) is not None
                # Each part is read alone, so the variables set before it travel with it.
                runs.append(("; ".join([*assignments.values(), part]), directory))
                if _ASSIGNMENT_RE.match(part):
                    assignment = _EXPORT_PREFIX_RE.sub("", part)
                    name = assignment.partition("=")[0]
                    assignments.pop(name, None)
                    assignments[name] = assignment
                    if len(assignments) > MAX_CARRIED_ASSIGNMENTS:
                        # The oldest is dropped, so a later `$NAME` may be unresolved.
                        del assignments[next(iter(assignments))]
                        untrusted = True
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
        command = _DECLARATION_PREFIX_RE.sub(r"\1", command)
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
        commands = simple_commands(text, known_verbs=_KNOWN_VERBS)
        for command in commands:
            glob = self._command_verdict(command, commands, where, depth, judged)
            if glob is not None:
                return glob
        return self._read_loop_violation(commands, where)

    def _command_verdict(
        self,
        command: SimpleCommand,
        commands: list[SimpleCommand],
        where: tuple[str, Sequence[str], bool, dict[str, Any]],
        depth: int,
        judged: set[tuple[str, str]],
    ) -> str | None:
        """The glob one simple command breaks; ``commands`` are all of its text's."""
        verb = command.verb
        # A verb the scan judges is re-read from its own text: the scan may not
        # have seen it as written (`time -p rm`, `command rm`, a variable set by `export`).
        if verb in SCAN_JUDGED_VERBS or command.reread:
            glob = self._rescanned(command.text, where)
            if glob is not None:
                return glob
        bodies = nested_command_strings(command)
        for body in bodies:
            glob = self._nested_violation(body, where, depth, judged)
            if glob is not None:
                return glob
        if bodies or verb in SHELL_INTERPRETERS or verb == _EVAL:
            return None
        if verb in SCAN_JUDGED_VERBS:
            return self._tree_copy_violation(command, where)
        if verb == _XARGS:
            return self._xargs_violation(command, commands, where, depth, judged)
        if self._reads_only(command):
            return self._reader_writes_violation(command, where)
        if verb == _FIND:
            acts, glob = self._find_violation(command, where)
            if not acts or glob is not None:
                return glob
        return self._unknown_command_violation(command, where)

    @staticmethod
    def _reads_only(command: SimpleCommand) -> bool:
        """Is the command known to only read the files it is given?"""
        if command.verb == _GIT:
            return git_subcommand(command) in GIT_READ_ONLY_SUBCOMMANDS
        return command.verb in READ_ONLY_VERBS

    def _wide_naming(self, word: str, roots: Sequence[str], base: str) -> str | None:
        """The glob a word names: the file, a directory above it, or a wildcard
        or brace group that could reach it. Used where nothing is known of what
        the command does with it."""
        candidates = [word, *(word.split(":") if ":" in word else [])]
        if "=" in word:
            candidates.append(word.partition("=")[2])
        for candidate in candidates:
            if not candidate:
                continue
            if _WILDCARDS.search(candidate) or any(char in candidate for char in _EXPANSION_CHARS):
                glob = self._token_naming(candidate, roots, [base])
            else:
                glob = self._protecting(str(Path(base) / candidate), roots)
            if glob is not None:
                return glob
        return None

    def _read_loop_violation(
        self,
        commands: list[SimpleCommand],
        where: tuple[str, Sequence[str], bool, dict[str, Any]],
    ) -> str | None:
        """A ``read`` loop whose body changes what it reads, judged by the input.

        The body's operand is a variable (`rm "$f"`), so the file is named by
        whatever feeds the loop: every word of the text counts.
        """
        base, roots, _untrusted, _hook_input = where
        if not any(command.verb in _READ_LOOP_VERBS for command in commands):
            return None
        mutators = [
            command
            for command in commands
            if command.verb not in _READ_LOOP_VERBS
            and (not self._reads_only(command) or _redirects_output(command))
            and command.verb not in SHELL_INTERPRETERS
            and any("$" in operand for operand in command.operands)
        ]
        if not mutators:
            return None
        for command in commands:
            for word in command.operands:
                glob = self._wide_naming(word, roots, base)
                if glob is not None:
                    return glob
        return None

    def _xargs_violation(
        self,
        command: SimpleCommand,
        commands: list[SimpleCommand],
        where: tuple[str, Sequence[str], bool, dict[str, Any]],
        depth: int,
        judged: set[tuple[str, str]],
    ) -> str | None:
        """``xargs`` read as the wrapper it is: the command it runs is judged like any
        other, and when that command does not only read, the names its producer
        prints are its operands."""
        base, roots, _untrusted, _hook_input = where
        operands = command.operands
        position = 0
        replacement = ""
        while position < len(operands):
            operand = operands[position]
            if operand == "--":
                position += 1
                break
            if not operand.startswith("-") or operand == "-":
                break
            if operand == _XARGS_REPLACE_OPTION and position + 1 < len(operands):
                replacement = operands[position + 1]
            elif operand.startswith(_XARGS_REPLACE_OPTION):
                replacement = operand[len(_XARGS_REPLACE_OPTION) :]
            position += 2 if operand in _XARGS_VALUE_OPTIONS else 1
        inner_text = text_from(command.words, 1 + position)
        if not inner_text:
            return None
        glob = self._verbs_violation(inner_text, where, depth, judged)
        if glob is not None:
            return glob
        inner = simple_commands(inner_text, known_verbs=_KNOWN_VERBS)
        if not inner or self._reads_only(inner[0]):
            return None
        args = inner[0].operands
        copies_out = (
            inner[0].verb in _COPY_VERBS
            and bool(replacement)
            and replacement in args
            and args[-1] != replacement
        )
        if copies_out:
            return None
        for other in commands:
            if other.group != command.group or other is command:
                continue
            for word in other.operands:
                glob = self._wide_naming(word, roots, base)
                if glob is not None:
                    return glob
        return None

    def _find_violation(
        self, command: SimpleCommand, where: tuple[str, Sequence[str], bool, dict[str, Any]]
    ) -> tuple[bool, str | None]:
        """Whether ``find`` acts (deletes, writes or runs a changing command), and
        the glob it breaks when it does so over a tree holding a listed file that
        its name filters could select."""
        base, roots, _untrusted, _hook_input = where
        operands = command.operands
        acts = any(operand in _FIND_WRITE_FLAGS for operand in operands) or any(
            operand in _FIND_EXEC_FLAGS
            and position + 1 < len(operands)
            and unquote(operands[position + 1]).rsplit("/", 1)[-1] not in READ_ONLY_VERBS
            for position, operand in enumerate(operands)
        )
        if not acts:
            return False, None
        starts: list[str] = []
        for operand in operands:
            if operand.startswith(_FIND_EXPRESSION_START):
                break
            starts.append(operand)
        names = [
            operands[i + 1]
            for i, operand in enumerate(operands[:-1])
            if operand in _FIND_NAME_FLAGS
        ]
        by_path = any(operand in _FIND_PATH_FLAGS for operand in operands)
        if names and not by_path and not self._could_select(names):
            return True, None
        for start in starts or ["."]:
            glob = self._wide_naming(start, roots, base)
            if glob is not None:
                return True, glob
        return True, None

    def _could_select(self, patterns: list[str]) -> bool:
        """Could a ``-name`` pattern select the file name a listed path ends in?"""
        for glob in self._globs():
            listed = _segments(glob)[-1:]
            if listed and any(_segment_could_match(pattern, listed[0]) for pattern in patterns):
                return True
        return False

    def _tree_copy_violation(
        self, command: SimpleCommand, where: tuple[str, Sequence[str], bool, dict[str, Any]]
    ) -> str | None:
        """``cp -r`` / ``mv -T`` onto the directory that holds a listed file."""
        base, roots, _untrusted, _hook_input = where
        if command.verb not in _TREE_COPY_VERBS:
            return None
        operands = command.operands
        if not any(_copies_a_tree(operand) for operand in operands):
            return None
        for operand in command.file_operands:
            if not operand.startswith("-"):
                glob = self._protecting_parent(str(Path(base) / operand), roots)
                if glob is not None:
                    return glob
        return None

    def _reader_writes_violation(
        self, command: SimpleCommand, where: tuple[str, Sequence[str], bool, dict[str, Any]]
    ) -> str | None:
        """A command in the read-only set, used in a way that writes a file."""
        base, roots, untrusted, _hook_input = where
        verb = command.verb
        operands = command.operands
        options = WRITE_OPTIONS.get(verb, frozenset())
        for position, operand in enumerate(operands):
            name, equals, value = operand.partition("=")
            written = ""
            if name in options:
                written = value if equals else "".join(operands[position + 1 : position + 2])
            else:
                written = next(
                    (
                        operand[len(option) :]
                        for option in options
                        if len(option) == 2 and operand.startswith(option) and len(operand) > 2
                    ),
                    "",
                )
            if written:
                glob = self._operand_naming(written, roots, base, untrusted)
                if glob is not None:
                    return glob
        files = [operand for operand in command.file_operands if not operand.startswith("-")]
        if len(files) > MAX_READ_OPERANDS.get(verb, len(files)):
            return self._operand_naming(files[-1], roots, base, untrusted)
        if verb in _AWK_VERBS:
            if any(_AWK_IN_PLACE in operand for operand in operands):
                return next(
                    (
                        glob
                        for operand in files
                        if (glob := self._operand_naming(operand, roots, base, untrusted))
                    ),
                    None,
                )
            for operand in files:
                if _AWK_WRITING_PROGRAM_RE.search(operand):
                    glob = self._text_naming(operand)
                    if glob is not None:
                        return glob
        return None

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
            return self._deep_violation(body, roots, base)
        return self._spelled_violation(body, hook_input, roots, base, depth + 1, judged)

    def _deep_violation(self, body: str, roots: Sequence[str], base: str) -> str | None:
        """Code nested past the depth bound: no verb is trusted, and any word that
        names a listed path, a directory above it, or could reach it is a denial.

        Linear: each nested string is read once, and at most ``MAX_DEEP_BODIES``
        are read before the rest is judged by whether it names the file.
        """
        queue = [body]
        seen = {body}
        while queue:
            if len(seen) > MAX_DEEP_BODIES:
                return self._text_naming(queue[-1])
            text = queue.pop()
            try:
                variants = list(brace_variants(text))
            except TooManyToEnumerateError:
                return self._text_naming(text)
            for variant in variants:
                for command in simple_commands(variant, known_verbs=_KNOWN_VERBS):
                    for word in (command.verb, *command.operands):
                        glob = self._wide_naming(word, roots, base)
                        if glob is not None:
                            return glob
                    for nested in nested_command_strings(command):
                        if nested not in seen:
                            seen.add(nested)
                            queue.append(nested)
        return None

    def _unknown_command_violation(
        self, command: SimpleCommand, where: tuple[str, Sequence[str], bool, dict[str, Any]]
    ) -> str | None:
        """The glob an unrecognised command names: it may do anything to what it names."""
        base, roots, untrusted, _hook_input = where
        read_options = READ_VALUE_OPTIONS
        if command.verb in READ_FILE_OPTION_VERBS:
            read_options = read_options | READ_FILE_OPTIONS
        skip_value = False
        for operand in command.file_operands:
            if skip_value:
                skip_value = False
                continue
            option, equals, _value = operand.partition("=")
            if option in read_options:
                skip_value = not equals
                continue
            glob = self._operand_naming(operand, roots, base, untrusted, parent=True)
            if glob is not None:
                return glob
        # A verb the scan knows, run by a command this handler does not: the
        # directories it would remove count as well.
        for position, word in enumerate(command.words[1:], start=1):
            if unquote(word) in SCAN_JUDGED_VERBS:
                return self._rescanned(text_from(command.words, position), where)
        return None

    def _operand_naming(
        self,
        operand: str,
        roots: Sequence[str],
        base: str,
        untrusted: bool,
        *,
        parent: bool = False,
    ) -> str | None:
        """The glob an operand of an unrecognised command names: the file itself, a
        wildcard that could expand to it, ``--option=VALUE`` or ``HOST:PATH`` naming
        it, and with ``parent`` the directory that holds it (a destination)."""
        candidates = [operand]
        if "=" in operand:
            candidates.append(operand.partition("=")[2])
        if ":" in operand:
            candidates.extend(operand.split(":"))
        for candidate in candidates:
            if not candidate:
                continue
            if _WILDCARDS.search(candidate) or any(char in candidate for char in _EXPANSION_CHARS):
                glob = self._token_naming(candidate, roots, [base])
            else:
                path = str(Path(base) / candidate)
                glob = self._protecting(path, roots, directories=False)
                if glob is None and parent:
                    glob = self._protecting_parent(path, roots)
                if glob is None and untrusted:
                    glob = self._protecting_by_name(candidate)
            if glob is not None:
                return glob
        return None

    def _protecting_parent(self, path: str, roots: Sequence[str]) -> str | None:
        """The glob whose file sits directly in ``path``, when its directory is spelled out."""
        globs = [glob for glob in self._globs() if _RECURSIVE not in _segments(glob)[:-1]]
        for relative in self._relative(path, roots):
            for glob in globs:
                parts = _segments(glob)
                if len(parts) > 1 and _matches_in_full(relative, parts[:-1]):
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
            "are maintained by infrastructure-as-code or by a human. You may read them "
            "with a command known to only read (below). "
            "`Write`, `Edit` and `NotebookEdit` on one are denied, and so is a Bash command "
            "that redirects into it, `tee`s, `dd`s or `sed -i`s it, copies, moves, "
            "installs or links (`ln`) onto it, or `touch`es, `truncate`s, `rm`s or `unlink`s it "
            "(or removes or moves a directory holding it, as `rm -rf` and `mv` do). A "
            "wildcard is denied when the shell could expand it to the file.\n\n"
            "**Any other command that names the file is denied too**, unless it is known to "
            "only read (`cat`, `grep`, `head`, `tail`, `ls`, `diff`, `stat`, `sort`, `awk`, "
            "`xxd`, `hexdump`, `column`, `shellcheck`, `git diff`, ...): `perl -i`, `rsync` "
            "or `tar -C` into its directory, `find` with `-delete` or `-exec rm` over a tree "
            "holding it, `xargs`, a `read` loop, `flock ... rm` and the like. A reader used "
            "to write (`git diff --output=P`, `sort -o P`, `less -o P`) is a write. Brace "
            "groups (`{a,b}`), `for` loops, `bash -c '...'`, `eval`, `export F=P; rm $F`, a "
            "path to a command (`/bin/rm`) and wrappers (`time`, `command`, `flock`) are read "
            "through to the command they run. Code nested more than three shells deep is "
            "denied when any word in it names the file, the directory above it, or a "
            "wildcard or brace group that could reach it.\n\n"
            "**A tool that is not a known reader is refused even to read the file.** Pipe it "
            "instead: `cat P | tool`. A path given as the value of an input-file option "
            "(`--env-file P`, `docker compose -f P`, `--vault-password-file P`) is a read.\n\n"
            "**Known gaps**: code inside an interpreter (`python -c`/`open()`, `perl -e`) "
            "and a heredoc fed to one reach the file without being seen. Hostile "
            "respellings are out of scope under the careless-agent threat model "
            '(CLAUDE/ARCHITECTURE.md, "Threat model: the agent is careless, not hostile"): '
            "`X=rm; $X P`, bracket globs such as `[l]ocal`, quoted command strings passed "
            "to `ssh`, `watch`, `tmux` or `env -S`, `git -c alias.x=!...`, hard or "
            "symbolic links to the file, a verb hidden in `$(...)`, and code piped or "
            "here-stringed into a shell. The rule is the same whether or not the guard "
            "sees the route. Quote a heredoc delimiter (`<<'EOF'`) when its body only "
            "mentions the path.\n\n"
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
