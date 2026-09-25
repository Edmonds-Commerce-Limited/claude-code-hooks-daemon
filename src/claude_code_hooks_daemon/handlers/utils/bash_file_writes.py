"""Every path a Bash command writes, including the writes shell grammar cannot show.

Plan 00461. ``core.utils.bash_write_destinations`` reads the shell grammar:
redirects, ``tee``, heredocs, ``cp``/``mv``/``install``/``dd``. A guard that
must hold a file against EVERY hand-written change also needs the writes that
grammar cannot show, because in each of them the path is an ordinary argument
or sits inside a program:

* an in-place editor (``sed -i``, ``perl -pi``, ``ruby -i``, ``gawk -i inplace``);
* a program handed to an interpreter inline (``python3 -c``, ``node -e``), on a
  heredoc (``python3 - <<'PY'``), or behind a wrapper (``timeout``, ``nohup``,
  ``uv run``). A shell program (``bash -c``) is analysed as a command in turn;
* ``ln``, ``rsync``, ``sponge``, and a patch (``git apply``, ``patch``), whose
  target paths are inside the patch file.

A program counts as writing a path only when the path is the TARGET of a write
call (``open(p, 'a')``, ``Path(p).write_text``, ``File.write(p``,
``appendFileSync(p``, perl's ``open(F, ">>", p)``, awk's ``print > "p"``). A
read that merely mentions the path is not a write. When a write call's target
is not a string literal (a variable), every path-like literal in the program
is reported: a caller that denies then fails closed rather than open.

Destinations are returned RAW, as written. Placing them is the caller's
decision, and so are the ``cd``/``pushd`` directories reported beside them: a
relative destination after a ``cd`` cannot be placed from the payload's ``cwd``.
``git`` relocations (``git mv``) are never reported; moving a file is not
writing into it.
"""

import logging
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.core.utils import (
    HeredocBody,
    bash_write_destinations,
    split_heredocs,
)
from claude_code_hooks_daemon.utils.command_evasion import strip_reserved_word_prefix
from claude_code_hooks_daemon.utils.path_predicates import TextOrReason
from claude_code_hooks_daemon.utils.shell_segmentation import (
    command_word,
    split_unquoted,
    strip_message_bodies,
)

logger = logging.getLogger(__name__)

#: Reads a file for the analysis (a patch), reporting failure rather than raising.
ReadText = Callable[[Path], TextOrReason]


@dataclass(frozen=True)
class BashFileWrites:
    """What a command writes, and where it changes directory first."""

    destinations: tuple[str, ...]
    directories: tuple[str, ...]


@dataclass(frozen=True)
class _FlagSyntax:
    """How one program's short and long flags take values.

    ``value_chars``: a short flag whose value is the rest of its cluster, or
    the next word when the cluster ends there (``-e prog``, ``-eprog``).
    ``suffix_chars``: a short flag whose value can only be attached
    (``sed -i.bak``); the next word is never consumed.
    """

    value_chars: str = ""
    suffix_chars: str = ""
    value_longs: frozenset[str] = frozenset()


@dataclass
class _Parsed:
    operands: list[str] = field(default_factory=list)
    flags: dict[str, list[str]] = field(default_factory=dict)

    def has(self, *names: str) -> bool:
        return any(name in self.flags for name in names)

    def values(self, *names: str) -> list[str]:
        return [value for name in names for value in self.flags.get(name, [])]


_NO_FLAG_VALUES: Final[_FlagSyntax] = _FlagSyntax()

_PYTHON: Final[str] = "python"
_PERL: Final[str] = "perl"
_RUBY: Final[str] = "ruby"
_NODE: Final[str] = "node"
_AWK: Final[str] = "awk"
_SHELL: Final[str] = "shell"

_PYTHON_RE: Final[re.Pattern[str]] = re.compile(r"^python[\d.]*$")
_LANGUAGES: Final[dict[str, str]] = {
    "perl": _PERL,
    "ruby": _RUBY,
    "node": _NODE,
    "awk": _AWK,
    "gawk": _AWK,
    "mawk": _AWK,
    "nawk": _AWK,
    "bash": _SHELL,
    "sh": _SHELL,
    "zsh": _SHELL,
    "dash": _SHELL,
    "ksh": _SHELL,
}

_SYNTAX: Final[dict[str, _FlagSyntax]] = {
    _PYTHON: _FlagSyntax(value_chars="cmWX"),
    _PERL: _FlagSyntax(value_chars="eEI", suffix_chars="iMmlxdDC0V"),
    _RUBY: _FlagSyntax(value_chars="eIrC", suffix_chars="iEFx0KTW"),
    _NODE: _FlagSyntax(
        value_chars="epr", value_longs=frozenset({"--eval", "--print", "--require"})
    ),
    _AWK: _FlagSyntax(
        value_chars="vfFie",
        value_longs=frozenset({"--assign", "--file", "--field-separator", "--include", "--source"}),
    ),
    _SHELL: _FlagSyntax(value_chars="coO"),
    "sed": _FlagSyntax(
        value_chars="efl",
        suffix_chars="i",
        value_longs=frozenset({"--expression", "--file", "--line-length"}),
    ),
    "git": _FlagSyntax(
        value_chars="Cc", value_longs=frozenset({"--git-dir", "--work-tree", "--namespace"})
    ),
    "patch": _FlagSyntax(
        value_chars="pioDdFBrVYzg",
        value_longs=frozenset({"--input", "--output", "--directory", "--strip"}),
    ),
    "ln": _FlagSyntax(value_chars="tS", value_longs=frozenset({"--target-directory", "--suffix"})),
    "rsync": _FlagSyntax(value_chars="eT", value_longs=frozenset({"--rsh", "--temp-dir"})),
}

#: The short flag an interpreter takes its inline program on, per language.
_PROGRAM_FLAGS: Final[dict[str, tuple[str, ...]]] = {
    _PYTHON: ("-c",),
    _PERL: ("-e", "-E"),
    _RUBY: ("-e",),
    _NODE: ("-e", "-p", "--eval", "--print"),
    _SHELL: ("-c",),
}
_PYTHON_MODULE_FLAG: Final[str] = "-m"

#: Words that run the command after them. Their own flags are skipped, and so
#: are the values listed here and a bare duration (`timeout 5`, `timeout 5m`).
_COMMAND_PREFIXES: Final[dict[str, frozenset[str]]] = {
    "sudo": frozenset({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U"}),
    "env": frozenset({"-u", "-C", "-S"}),
    "command": frozenset(),
    "exec": frozenset({"-a"}),
    "timeout": frozenset({"-s", "-k", "--signal", "--kill-after"}),
    "nohup": frozenset(),
    "nice": frozenset({"-n"}),
    "ionice": frozenset({"-c", "-n", "-p"}),
    "time": frozenset(),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "xargs": frozenset({"-n", "-I", "-L", "-P", "-d", "-a", "-E", "-s"}),
}
#: Two-word runners: `uv run python ...`, `poetry run python ...`.
_TWO_WORD_PREFIXES: Final[dict[str, str]] = {"uv": "run", "poetry": "run"}
_TWO_WORD_PREFIX_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {"--with", "--python", "-p", "--project", "--directory", "--extra", "--group", "--env-file"}
)
_DURATION_RE: Final[re.Pattern[str]] = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: Command separators, and the pipe that joins a pipeline's stages.
_COMMAND_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "\n")
_STAGE_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "\n")
_PIPE: Final[tuple[str, ...]] = ("|",)

#: Words that are shell grouping, not arguments.
_GROUPING_WORDS: Final[frozenset[str]] = frozenset({"(", ")", "{", "}"})

#: A redirection operator on its own (its operand is the next word) and one
#: with its operand attached.
_REDIRECT_OPERATOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^\d*(?:<<<|<<-?|<>|<|>>|>\||>|&>>|&>)$"
)
_REDIRECT_ATTACHED_RE: Final[re.Pattern[str]] = re.compile(r"^\d*(?:<|>|&>)")
_STDIN_REDIRECT: Final[str] = "<"

_DIRECTORY_CHANGERS: Final[frozenset[str]] = frozenset({"cd", "pushd"})
_GIT: Final[str] = "git"
_GIT_APPLY: Final[str] = "apply"
_PATCH: Final[str] = "patch"
_SED: Final[str] = "sed"
_LAST_OPERAND_WRITERS: Final[frozenset[str]] = frozenset({"ln", "rsync"})
_SPONGE: Final[str] = "sponge"
_STDIN_PASSTHROUGH: Final[str] = "cat"
_STDIN_OPERAND: Final[str] = "-"
_TARGET_DIRECTORY_FLAGS: Final[tuple[str, ...]] = ("-t", "--target-directory")
_MIN_LINK_OPERANDS: Final[int] = 2

_SED_IN_PLACE_FLAGS: Final[tuple[str, ...]] = ("-i", "--in-place")
_SED_SCRIPT_FLAGS: Final[tuple[str, ...]] = ("-e", "-f", "--expression", "--file")
_SCRIPT_FLAGS: Final[tuple[str, ...]] = ("-e", "-E")
_IN_PLACE_FLAG: Final[str] = "-i"
_AWK_INPLACE: Final[str] = "inplace"
_AWK_INCLUDE_FLAGS: Final[tuple[str, ...]] = ("-i", "--include")
_AWK_FILE_FLAGS: Final[tuple[str, ...]] = ("-f", "--file")
_AWK_SOURCE_FLAGS: Final[tuple[str, ...]] = ("-e", "--source")
_PATCH_INPUT_FLAGS: Final[tuple[str, ...]] = ("-i", "--input")
_PATCH_OUTPUT_FLAGS: Final[tuple[str, ...]] = ("-o", "--output")

#: Heredocs and shell programs nest; past this depth the text is not followed.
_MAX_DEPTH: Final[int] = 4

#: Patch headers naming the file a hunk writes.
_PATCH_TARGET_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:\+\+\+ (?P<plus>\S+)|diff --git \S+ (?P<git>\S+)|rename to (?P<rename>\S+))",
    re.MULTILINE,
)
_PATCH_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^[ab]/")
_NULL_DEVICE: Final[str] = "/dev/null"
_UNEXPANDABLE: Final[tuple[str, ...]] = ("$", "*", "?", "`", "{", "[")

# --- program sinks ---------------------------------------------------------
_MODE: Final[str] = r"""(?P<q>['"])(?P<mode>[rwaxbtU+]{1,5})(?P=q)"""
#: `open(p, 'a')`, `open(p, mode='w')`, `File.open(p, 'a')`, `fs.openSync(p, 'a')`.
_OPEN_SINK_RE: Final[re.Pattern[str]] = re.compile(
    r"\bopen(?:Sync)?\(\s*(?P<target>[^,()]+?)\s*,\s*(?:mode\s*=\s*)?" + _MODE
)
#: `Path(p).open('a')`.
_PATH_OPEN_SINK_RE: Final[re.Pattern[str]] = re.compile(
    r"\bPath\(\s*(?P<target>[^()]+?)\s*\)\s*\.\s*open\(\s*(?:mode\s*=\s*)?" + _MODE
)
_WRITE_MODE_RE: Final[re.Pattern[str]] = re.compile(r"[wax+]")
#: Calls that write their target whatever else they are passed.
_WRITE_SINK_RES: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bPath\(\s*(?P<target>[^()]+?)\s*\)\s*\.\s*write_(?:text|bytes)\b"),
    re.compile(r"\b(?:appendFile|writeFile|createWriteStream)(?:Sync)?\(\s*(?P<target>[^,()]+)"),
    re.compile(r"\b(?:File|IO)\.(?:bin)?write\(\s*(?P<target>[^,()]+)"),
    re.compile(
        r"\b(?:shutil\.(?:copy\w*|move)|os\.(?:rename|replace))\(\s*[^,()]+,\s*(?P<target>[^,()]+)"
    ),
    # perl's three-argument open: `open(my $f, ">>", "p")`.
    re.compile(r"""\bopen\s*\(?\s*[^,;()]+,\s*(['"])(?:\+<|\+?>>?)\1\s*,\s*(?P<target>[^),;]+)"""),
)
#: perl's two-argument open, where the path follows the mode inside the string.
_PERL_TWO_ARG_OPEN_RE: Final[re.Pattern[str]] = re.compile(
    r"""\bopen\s*\(?\s*[^,;()]+,\s*(['"])\s*(?:\+<|\+?>>?)\s*(?P<path>[^'"\s<>][^'"\s]*)\1"""
)
#: awk's output redirection: `print > "p"`, `printf ... >> p`.
_AWK_SINK_RE: Final[re.Pattern[str]] = re.compile(
    r"""\bprintf?\b[^;}]*?>>?\s*(?P<target>"[^"]*"|[A-Za-z_]\w*)"""
)
#: A string literal, with an optional Python prefix (`f'...'`, `rb"..."`).
_LITERAL_RE: Final[re.Pattern[str]] = re.compile(
    r"""^\s*[rRbBuUfF]{0,2}(['"])(?P<path>[^'"]*)\1\s*$"""
)
#: Every string literal in a program, for the fail-closed report.
_ANY_LITERAL_RE: Final[re.Pattern[str]] = re.compile(r"""(['"])(?P<text>[^'"\s]+)\1""")
_PATH_CHARACTERS: Final[tuple[str, ...]] = ("/", ".")


def bash_file_writes(command: str, cwd: str | None, read_text: ReadText) -> BashFileWrites:
    """Every destination ``command`` writes, raw, and the directories it enters.

    Args:
        command: The Bash command.
        cwd: The directory it runs in, used only to find a patch file to read.
        read_text: Reads a patch file; a failure there names no destination.

    Returns:
        Destinations in command order, de-duplicated; ``cd``/``pushd`` operands.
    """
    analysis = _Analysis(cwd, read_text)
    analysis.command(command, depth=0)
    return BashFileWrites(
        destinations=tuple(dict.fromkeys(analysis.destinations)),
        directories=tuple(dict.fromkeys(analysis.directories)),
    )


class _Analysis:
    """Accumulates writes across nested commands, programs and heredocs."""

    def __init__(self, cwd: str | None, read_text: ReadText) -> None:
        self._cwd = cwd
        self._read_text = read_text
        self.destinations: list[str] = []
        self.directories: list[str] = []

    def command(self, command: str, depth: int) -> None:
        """Analyse shell text: its grammar, each stage, each heredoc it feeds."""
        if depth > _MAX_DEPTH:
            logger.debug("bash_file_writes: nesting past %d not followed", _MAX_DEPTH)
            return
        # Authored writes over the WHOLE command, a git stage included:
        # `git show HEAD:f > f` is a shell write.
        self.destinations.extend(
            candidate.destination
            for candidate in bash_write_destinations(command)
            if candidate.authored
        )
        outside, heredocs = split_heredocs(command)
        for stage in split_unquoted(strip_message_bodies(outside), _STAGE_SEPARATORS):
            self._stage(stage, depth)
        for heredoc in heredocs:
            self._heredoc(heredoc, depth)

    def _stage(self, stage: str, depth: int) -> None:
        words = _words(stage)
        located = _head(words)
        if located is None:
            return
        head, args = located
        if head in _DIRECTORY_CHANGERS:
            self.directories.extend(_parse(args, _NO_FLAG_VALUES).operands[:1])
            return
        if head == _GIT:
            self._git(args)
            return
        # One line of the command, so no heredoc body can follow it here.
        self.destinations.extend(
            candidate.destination
            for candidate in bash_write_destinations(stage)
            if not candidate.authored
        )
        self.destinations.extend(_verb_writes(head, args))
        if head == _PATCH:
            self._patch(stage, args)
        if head == _SED:
            self.destinations.extend(_sed_in_place_writes(_parse(args, _SYNTAX[_SED])))
        language = _language(head)
        if language is None:
            return
        parsed = _parse(args, _SYNTAX[language])
        self.destinations.extend(_in_place_writes(language, parsed))
        program = _inline_program(language, parsed)
        if program is not None:
            self._program(language, program, depth)

    def _program(self, language: str, program: str, depth: int) -> None:
        if language == _SHELL:
            self.command(program, depth + 1)
        else:
            self.destinations.extend(_program_writes(language, program))

    def _heredoc(self, heredoc: HeredocBody, depth: int) -> None:
        """Analyse a body fed to an interpreter as a program; skip one fed to data."""
        marker = re.compile(r"<<-?\s*['\"]?" + re.escape(heredoc.delimiter) + r"\b")
        for command in split_unquoted(heredoc.opener_line, _COMMAND_SEPARATORS):
            if not marker.search(command):
                continue
            stages = split_unquoted(command, _PIPE)
            start = next(
                (index for index, stage in enumerate(stages) if marker.search(stage)), len(stages)
            )
            for stage in stages[start:]:
                located = _head(_words(stage))
                if located is None:
                    return
                head, args = located
                language = _language(head)
                if language is not None:
                    parsed = _parse(args, _SYNTAX[language])
                    if _reads_program_from_stdin(language, parsed):
                        self._program(language, heredoc.body, depth)
                    return
                if head != _STDIN_PASSTHROUGH or _parse(args, _NO_FLAG_VALUES).operands:
                    return
            return

    def _git(self, args: list[str]) -> None:
        parsed = _parse(args, _SYNTAX[_GIT])
        if parsed.operands[:1] != [_GIT_APPLY]:
            return
        patch_args = _parse(parsed.operands[1:], _NO_FLAG_VALUES).operands
        for patch in patch_args:
            self.destinations.extend(self._patch_targets(patch))

    def _patch(self, stage: str, args: list[str]) -> None:
        parsed = _parse(args, _SYNTAX[_PATCH])
        outputs = parsed.values(*_PATCH_OUTPUT_FLAGS)
        if outputs:
            self.destinations.extend(outputs)
            return
        if parsed.operands:
            # `patch ORIGINAL [PATCHFILE]` writes ORIGINAL whatever the patch names.
            self.destinations.append(parsed.operands[0])
            return
        sources = parsed.values(*_PATCH_INPUT_FLAGS) or _stdin_sources(stage)
        for source in sources:
            self.destinations.extend(self._patch_targets(source))

    def _patch_targets(self, patch: str) -> list[str]:
        """The files a patch file's headers name as written."""
        if any(character in patch for character in _UNEXPANDABLE):
            return []
        path = Path(patch)
        if not path.is_absolute():
            if not self._cwd:
                return []
            path = Path(self._cwd) / path
        read = self._read_text(path)
        if read.text is None:
            logger.debug("bash_file_writes: patch %s unreadable (%s)", path, read.reason)
            return []
        targets: list[str] = []
        for match in _PATCH_TARGET_RE.finditer(read.text):
            named = match.group("plus") or match.group("git") or match.group("rename")
            if named and named != _NULL_DEVICE:
                targets.append(_PATCH_PREFIX_RE.sub("", named))
        return targets


def _words(stage: str) -> list[str]:
    """Shell words of one stage, without grouping or leading reserved words.

    Whitespace words if unparseable. `do python3 -c ...` runs python3, so the
    reserved word goes before anything reads the head (Plan 00422 N25).
    """
    stage = strip_reserved_word_prefix(stage)
    try:
        words = shlex.split(stage)
    except ValueError as exc:
        # shlex also rejects text bash accepts (an ANSI-C `$'it\'s'` escape),
        # so whitespace words keep the command name and any path visible.
        logger.debug("bash_file_writes: shlex could not parse %r (%s)", stage, exc)
        words = stage.split()
    words = [word for word in words if word not in _GROUPING_WORDS]
    if words and words[-1].endswith(")") and "(" not in words[-1]:
        words[-1] = words[-1].rstrip(")")
    return words


def _head(words: list[str]) -> tuple[str, list[str]] | None:
    """The command a stage runs, past assignments and wrappers, with its arguments."""
    words = _without_redirections(words)
    index = 0
    while index < len(words):
        word = words[index]
        name = command_word(word)
        if _ASSIGNMENT_RE.match(word) or word.startswith("-"):
            index += 1
        elif name in _TWO_WORD_PREFIXES and words[index + 1 : index + 2] == [
            _TWO_WORD_PREFIXES[name]
        ]:
            index = _skip_prefix_options(words, index + 2, _TWO_WORD_PREFIX_VALUE_FLAGS)
        elif name in _COMMAND_PREFIXES:
            index = _skip_prefix_options(words, index + 1, _COMMAND_PREFIXES[name])
        else:
            return name, words[index + 1 :]
    return None


def _skip_prefix_options(words: list[str], index: int, value_flags: frozenset[str]) -> int:
    while index < len(words):
        word = words[index]
        if word in value_flags:
            index += 2
        elif word.startswith("-") or _DURATION_RE.match(word):
            index += 1
        else:
            break
    return index


def _parse(args: list[str], syntax: _FlagSyntax) -> _Parsed:
    """Operands and flags of one invocation, with redirections removed."""
    parsed = _Parsed()
    words = _without_redirections(args)
    index = 0
    while index < len(words):
        word = words[index]
        index += 1
        if word == "--":
            parsed.operands.extend(words[index:])
            break
        if word.startswith("--"):
            name, separator, value = word.partition("=")
            if not separator and name in syntax.value_longs and index < len(words):
                value = words[index]
                index += 1
            parsed.flags.setdefault(name, []).append(value)
        elif word.startswith("-") and word != _STDIN_OPERAND:
            index = _parse_cluster(word, words, index, syntax, parsed)
        else:
            parsed.operands.append(word)
    return parsed


def _parse_cluster(
    word: str, words: list[str], index: int, syntax: _FlagSyntax, parsed: _Parsed
) -> int:
    """Record one short-flag cluster (`-pi`, `-ne`, `-i.bak`); return the next index."""
    for position, character in enumerate(word[1:], start=1):
        rest = word[position + 1 :]
        name = f"-{character}"
        if character in syntax.value_chars:
            if not rest and index < len(words):
                rest = words[index]
                index += 1
            parsed.flags.setdefault(name, []).append(rest)
            return index
        if character in syntax.suffix_chars:
            parsed.flags.setdefault(name, []).append(rest)
            return index
        parsed.flags.setdefault(name, []).append("")
    return index


def _without_redirections(args: list[str]) -> list[str]:
    kept: list[str] = []
    skip_next = False
    for word in args:
        if skip_next:
            skip_next = False
        elif _REDIRECT_OPERATOR_RE.match(word):
            skip_next = True
        elif not _REDIRECT_ATTACHED_RE.match(word):
            kept.append(word)
    return kept


def _stdin_sources(stage: str) -> list[str]:
    """Files a stage reads on stdin (`< file`)."""
    words = _words(stage)
    sources: list[str] = []
    for index, word in enumerate(words):
        if word == _STDIN_REDIRECT and index + 1 < len(words):
            sources.append(words[index + 1])
        elif word.startswith(_STDIN_REDIRECT) and not word.startswith("<<") and len(word) > 1:
            sources.append(word[1:])
    return sources


def _language(head: str) -> str | None:
    if _PYTHON_RE.match(head):
        return _PYTHON
    return _LANGUAGES.get(head)


def _verb_writes(head: str, args: list[str]) -> list[str]:
    """`ln`/`rsync` write their last operand; `sponge` writes its operands."""
    if head == _SPONGE:
        return _parse(args, _NO_FLAG_VALUES).operands
    if head not in _LAST_OPERAND_WRITERS:
        return []
    parsed = _parse(args, _SYNTAX[head])
    if parsed.has(*_TARGET_DIRECTORY_FLAGS) or len(parsed.operands) < _MIN_LINK_OPERANDS:
        return []
    return parsed.operands[-1:]


def _in_place_writes(language: str, parsed: _Parsed) -> list[str]:
    """The files an in-place edit rewrites: every operand but the script."""
    if language == _AWK:
        included = parsed.values(*_AWK_INCLUDE_FLAGS)
        if _AWK_INPLACE not in included:
            return []
        if parsed.has(*_AWK_FILE_FLAGS, *_AWK_SOURCE_FLAGS):
            return parsed.operands
        return parsed.operands[1:]
    if language not in (_PERL, _RUBY) or not parsed.has(_IN_PLACE_FLAG):
        return []
    return parsed.operands if parsed.has(*_SCRIPT_FLAGS) else parsed.operands[1:]


def _sed_in_place_writes(parsed: _Parsed) -> list[str]:
    if not parsed.has(*_SED_IN_PLACE_FLAGS):
        return []
    return parsed.operands if parsed.has(*_SED_SCRIPT_FLAGS) else parsed.operands[1:]


def _inline_program(language: str, parsed: _Parsed) -> str | None:
    """The program text an interpreter was handed as an argument, else None."""
    if language == _AWK:
        sources = parsed.values(*_AWK_SOURCE_FLAGS)
        if sources:
            return sources[0]
        if parsed.has(*_AWK_FILE_FLAGS) or not parsed.operands:
            return None
        return parsed.operands[0]
    programs = parsed.values(*_PROGRAM_FLAGS[language])
    return programs[0] if programs else None


def _reads_program_from_stdin(language: str, parsed: _Parsed) -> bool:
    """Whether the interpreter takes its program from stdin (a heredoc body)."""
    if language == _AWK or _inline_program(language, parsed) is not None:
        return False
    if language == _PYTHON and parsed.has(_PYTHON_MODULE_FLAG):
        return False
    return not parsed.operands or parsed.operands[0] == _STDIN_OPERAND


def _program_writes(language: str, program: str) -> list[str]:
    """Paths a program writes, tied to a write call; see the module docstring."""
    targets: list[str] = []
    untied = False

    def record(target: str) -> None:
        nonlocal untied
        literal = _LITERAL_RE.match(target)
        if literal is None:
            untied = True
        else:
            targets.append(literal.group("path"))

    for match in _OPEN_SINK_RE.finditer(program):
        if _WRITE_MODE_RE.search(match.group("mode")):
            record(match.group("target"))
    for match in _PATH_OPEN_SINK_RE.finditer(program):
        if _WRITE_MODE_RE.search(match.group("mode")):
            record(match.group("target"))
    for pattern in _WRITE_SINK_RES:
        for match in pattern.finditer(program):
            record(match.group("target"))
    targets.extend(match.group("path") for match in _PERL_TWO_ARG_OPEN_RE.finditer(program))
    if language == _AWK:
        for match in _AWK_SINK_RE.finditer(program):
            record(match.group("target"))

    if untied:
        # A write whose target is a variable: report every path-like literal.
        targets.extend(
            match.group("text")
            for match in _ANY_LITERAL_RE.finditer(program)
            if any(character in match.group("text") for character in _PATH_CHARACTERS)
        )
    return targets
