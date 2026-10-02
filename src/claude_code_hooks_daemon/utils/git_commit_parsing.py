"""Shared ``git commit`` command-line tokenising helpers.

ONE home for the tokeniser both ``docs_qa_commit_gate`` and
``plan_qa_commit_gate`` need to read a staged-commit-gate's Bash `command`
string into a commit message and pathspec list (Plan 00293). The two gates
previously carried byte-identical copies of this ~60-line helper table — DRY
forbids that, and the duplication is exactly how a bug shipped twice: neither
copy recognised a combined short-flag cluster (``git commit -am "msg"``) as
message-taking, so the tokeniser filed the commit MESSAGE as a pathspec, the
STAGED diff was built against a nonexistent path, and every STAGED check
silently passed on a commit it never actually examined.

git's own short-flag cluster rule (git-commit(1)): a cluster is read
letter-by-letter; a VALUE-taking letter (``m``, ``F``, ``c``, ``C``, ``u``)
ends the cluster — anything AFTER it in the same token is that flag's
attached value (``-mFOO`` means message "FOO"), and with nothing left in the
token the value is the FOLLOWING token instead (``-am "msg"`` means message
"msg"). Earlier letters in the cluster are read as independent boolean flags
(``-a`` in both examples above).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Final

from claude_code_hooks_daemon.utils.command_evasion import (
    SHELL_RESERVED_COMMAND_PREFIXES,
    git_subcommand_index,
    normalise_line_continuations,
)
from claude_code_hooks_daemon.utils.shell_segmentation import command_word

#: The commit message flags recognised as a WHOLE token (own token). The
#: `-m` attached-value spelling (`-mFOO`, `-am`) is not listed here -- it is
#: recognised by the short-flag cluster reader below, per git's own
#: cluster-parsing rule.
MESSAGE_FLAGS: Final[frozenset[str]] = frozenset({"-m", "--message"})
#: The `--message=` attached-value spelling's prefix (its own whole token,
#: unlike `-mFOO` which the cluster reader below handles).
MESSAGE_LONGFORM_PREFIX: Final[str] = "--message="
MESSAGE_JOINER: Final[str] = "\n\n"

#: git-commit flags that take a SEPARATE value token (not a pathspec) when
#: spelled as their own whole token. Kept narrow to the flags realistically
#: seen on a commit line — sufficient to stop e.g. the -m message text or an
#: --author value from being mistaken for a path, without attempting a full
#: git-commit(1) CLI parse.
VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-m",
        "--message",
        "-F",
        "--file",
        "-c",
        "-C",
        "--reuse-message",
        "--reedit-message",
        "--fixup",
        "--squash",
        "--author",
        "--date",
        "-u",
        "--untracked-files",
    }
)

#: The short-flag LETTERS (no leading dash) that take a value, per git's own
#: cluster-parsing rule — the single-letter forms of a subset of VALUE_FLAGS.
_SHORT_VALUE_LETTERS: Final[frozenset[str]] = frozenset({"m", "F", "c", "C", "u"})

_MESSAGE_LETTER: Final[str] = "m"
_PATHSPEC_SEPARATOR: Final[str] = "--"
_GIT_TOKEN: Final[str] = "git"
_COMMIT_TOKEN: Final[str] = "commit"

#: The ``-a``/``--all`` flag, which makes a commit record the WORKING TREE
#: rather than the index.
_ALL_LONG_FLAG: Final[str] = "--all"
_ALL_SHORT_LETTER: Final[str] = "a"

#: Short-flag letters taking a REQUIRED value: with nothing after them in the
#: token, the value is the FOLLOWING token. A superset of _SHORT_VALUE_LETTERS
#: above -- it also carries ``t`` (--template) -- and the two are deliberately
#: not merged: widening the set used by :func:`extract_commit_message` and
#: :func:`extract_commit_pathspecs` would change what two live commit gates
#: parse, which is not a side effect class 2a should have.
_REQUIRED_VALUE_LETTERS: Final[str] = "mcCFt"
#: Short-flag letters taking an OPTIONAL value (``-S``, ``-Skeyid``). They end
#: the cluster like any other value letter, but NEVER consume the following
#: token -- treating ``-S -a`` as "sign with key -a" would lose the ``-a``.
_OPTIONAL_VALUE_LETTERS: Final[str] = "Su"

#: Long options whose value is a SEPARATE token -- the only places a leading
#: dash can appear without being a flag of its own. Distinct from VALUE_FLAGS,
#: which mixes long and short forms and does not record whether the value is
#: required.
_LONG_FLAGS_WITH_VALUE: Final[frozenset[str]] = frozenset(
    {
        "--message",
        "--file",
        "--template",
        "--author",
        "--date",
        "--cleanup",
        "--reuse-message",
        "--reedit-message",
        "--fixup",
        "--squash",
        "--trailer",
        "--pathspec-from-file",
    }
)


def tokenise_command(command: str) -> list[str]:
    """Shell-tokenise ``command``; empty list when unparseable."""
    try:
        return shlex.split(command)
    except ValueError:
        return []


def is_git_commit(tokens: list[str]) -> bool:
    """True when a ``commit`` token follows a ``git`` token.

    Tokenisation keeps quoted strings whole, so prose like
    ``echo 'git commit is fun'`` does not match.
    """
    for index, token in enumerate(tokens):
        if token == _GIT_TOKEN and _COMMIT_TOKEN in tokens[index + 1 :]:
            return True
    return False


def _short_cluster_value_letter(token: str) -> tuple[str, str | None] | None:
    """The value-taking letter in a short-flag CLUSTER, and its attached value.

    ``token`` must be a single-dash cluster of two or more alphabetic
    characters (``-am``, ``-ma``) — a lone ``-m``/other whole-token flag is
    handled by the callers before this is ever reached. Returns ``None`` when
    ``token`` isn't such a cluster, or none of its letters take a value (pure
    boolean cluster, e.g. ``-an``).

    When the value-taking letter is found, everything AFTER it in the same
    token is its attached value (``-mFOO`` -> ("m", "FOO")); with nothing
    left in the token the attached value is ``None`` and the caller must
    consume the FOLLOWING token instead (``-am`` -> ("m", None)).
    """
    if not token.startswith("-") or token.startswith("--") or len(token) < 3:
        return None
    letters = token[1:]
    if not letters.isalpha():
        return None
    for position, letter in enumerate(letters):
        if letter in _SHORT_VALUE_LETTERS:
            remainder = letters[position + 1 :]
            return letter, (remainder if remainder else None)
    return None


def extract_commit_message(tokens: list[str]) -> str | None:
    """The ``-m``/``--message`` payload(s), joined; None when absent.

    Recognises the whole-token forms (``-m x``, ``--message=x``), and a
    combined short-flag cluster ending or carrying ``m`` (``-am x`` -> "x";
    ``-mx``/``-amx`` -> "x" attached) per git's own cluster-parsing rule.
    """
    parts: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in MESSAGE_FLAGS and index + 1 < len(tokens):
            parts.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith(MESSAGE_LONGFORM_PREFIX):
            parts.append(token[len(MESSAGE_LONGFORM_PREFIX) :])
            index += 1
            continue
        cluster = _short_cluster_value_letter(token)
        if cluster is not None:
            letter, attached = cluster
            if letter == _MESSAGE_LETTER:
                if attached is not None:
                    parts.append(attached)
                    index += 1
                    continue
                if index + 1 < len(tokens):
                    parts.append(tokens[index + 1])
                    index += 2
                    continue
            index += 1
            continue
        index += 1
    return MESSAGE_JOINER.join(parts) if parts else None


def commits_working_tree(options: list[str]) -> bool:
    """True when this ``git commit`` option run carries ``-a``/``--all``.

    ``options`` are the tokens AFTER the ``commit`` subcommand. Locating the
    subcommand is left to the caller so it can use the rigorous
    ``git_subcommand_index`` (which reads ``git -C path commit``); taking a
    whole command here would invite a weaker locator instead.

    Walks the options rather than testing each token independently, because
    whether a token IS an option depends on what came before it: an option's
    value, and anything after ``--``, are operands. ``git commit -m 'fix the
    -a flag handling'`` must not be read as committing the working tree.

    Why it matters to a caller: ``-a`` means the commit records the working
    tree, so a gate that inspects only the INDEX examines something the commit
    will not contain.
    """
    index = 0
    while index < len(options):
        option = options[index]
        index += 1
        if option == _PATHSPEC_SEPARATOR:
            return False
        if option == _ALL_LONG_FLAG:
            return True
        if not option.startswith("-") or len(option) < 2:
            continue
        if option.startswith("--"):
            # A value token is never scanned for flags: it is data, and the
            # `-a` inside a commit message is prose.
            if option in _LONG_FLAGS_WITH_VALUE:
                index += 1
            continue
        carries_all, consumes_next = _read_all_cluster(option[1:])
        if carries_all:
            return True
        if consumes_next:
            index += 1
    return False


def _read_all_cluster(letters: str) -> tuple[bool, bool]:
    """``(cluster carries -a, cluster consumes the next token)``.

    A short cluster ends at the first letter that takes a value: everything
    after it is that value. Reading straight through instead is how a
    ``-m``-attached message gets mined for flags -- and how ``-ta`` (template
    "a") and ``-Skeya`` (key id "keya") are misread as carrying ``-a``.
    """
    for position, letter in enumerate(letters):
        if letter == _ALL_SHORT_LETTER:
            return True, False
        if letter in _OPTIONAL_VALUE_LETTERS:
            return False, False
        if letter in _REQUIRED_VALUE_LETTERS:
            return False, position == len(letters) - 1
    return False, False


#: git-commit's long options, from git's own table (``git commit
#: --git-completion-helper-all``), mapped to whether each takes a REQUIRED
#: value that may be the following token. ``--gpg-sign`` and
#: ``--untracked-files`` take an OPTIONAL value, which git only ever reads
#: attached (``--gpg-sign=KEY``), so the following token stays an operand.
#: git accepts any unambiguous prefix of these names, so a caller must
#: resolve an abbreviation against the whole table, not only the value-takers.
_COMMIT_LONG_OPTIONS: Final[dict[str, bool]] = {
    "quiet": False,
    "verbose": False,
    "file": True,
    "author": True,
    "date": True,
    "message": True,
    "reedit-message": True,
    "reuse-message": True,
    "fixup": True,
    "squash": True,
    "reset-author": False,
    "trailer": True,
    "signoff": False,
    "template": True,
    "edit": False,
    "cleanup": True,
    "status": False,
    "gpg-sign": False,
    "all": False,
    "include": False,
    "interactive": False,
    "patch": False,
    "only": False,
    "no-verify": False,
    "dry-run": False,
    "short": False,
    "branch": False,
    "ahead-behind": False,
    "porcelain": False,
    "long": False,
    "null": False,
    "amend": False,
    "no-post-rewrite": False,
    "untracked-files": False,
    "pathspec-from-file": True,
    "pathspec-file-nul": False,
    "allow-empty": False,
    "allow-empty-message": False,
    "verify": False,
    "post-rewrite": False,
}
_LONG_PREFIX: Final[str] = "--"
_NEGATION_PREFIX: Final[str] = "no-"
_ASSIGNMENT_SIGN: Final[str] = "="

#: The shell's operator characters: ``shlex``'s ``punctuation_chars`` set.
#: A word made only of these is an operator, never an argument.
_OPERATOR_CHARS: Final[frozenset[str]] = frozenset("();<>|&")
#: An operator carrying one of these is a REDIRECTION, whose next word is its
#: target (or, for ``<<``, the heredoc delimiter); every other operator ends
#: the simple command.
_REDIRECT_CHARS: Final[frozenset[str]] = frozenset("<>")
_SUBSHELL_OPEN: Final[str] = "("
_SUBSHELL_CLOSE: Final[str] = ")"
_STATEMENT_SEPARATOR: Final[str] = " ; "

#: A heredoc operator and its delimiter, in any of the quoting forms bash
#: accepts. ``<<<`` (a here-string) is excluded by the lookbehind and lookahead.
_HEREDOC_OPERATOR: Final[re.Pattern[str]] = re.compile(
    r"(?<!<)<<(?!<)(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([^\s;&|()<>'\"]+))"
)
_HEREDOC_STRIP_TABS: Final[str] = "-"
#: A file-descriptor prefix on a redirection: ``2>``, ``10>&1``, ``{fd}>``.
#: Only at the start of a word, which the scanner guarantees.
_IO_NUMBER: Final[re.Pattern[str]] = re.compile(r"(?:\d+|\{[A-Za-z_]\w*\})(?=[<>])")
_WORD_BREAK_CHARS: Final[frozenset[str]] = frozenset(" \t;&|()<>")
_SINGLE_QUOTE: Final[str] = "'"
_DOUBLE_QUOTE: Final[str] = '"'
_BACKSLASH: Final[str] = "\\"
_NEWLINE: Final[str] = "\n"


def _skip_heredoc_bodies(command: str, start: int, pending: list[tuple[str, bool]]) -> int:
    """Index just past the bodies of ``pending`` heredocs, which begin at ``start``."""
    position = start
    for delimiter, strip_tabs in pending:
        while position < len(command):
            end = command.find(_NEWLINE, position)
            line = command[position:] if end < 0 else command[position:end]
            position = len(command) if end < 0 else end + 1
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
    return position


def _lexable_text(command: str) -> str:
    """``command`` rewritten so a punctuation-aware ``shlex`` reads it as bash does.

    Three things bash knows that ``shlex`` does not are applied first, each
    outside quotes only: a heredoc BODY is data, so it is removed and the
    operator is left with its bare delimiter; a file-descriptor number before a
    redirection belongs to the operator, not the argument list (``2>&1``); and
    a newline ends a statement, so it becomes ``;``.
    """
    text = normalise_line_continuations(command)
    out: list[str] = []
    quote: str | None = None
    pending: list[tuple[str, bool]] = []
    word_start = True
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == _BACKSLASH and quote == _DOUBLE_QUOTE and index + 1 < len(text):
                out.append(text[index : index + 2])
                index += 2
                continue
            out.append(char)
            index += 1
            if char == quote:
                quote = None
            continue
        if char == _NEWLINE:
            out.append(_STATEMENT_SEPARATOR)
            index = _skip_heredoc_bodies(text, index + 1, pending)
            pending = []
            word_start = True
            continue
        if char == _BACKSLASH and index + 1 < len(text):
            out.append(text[index : index + 2])
            index += 2
            word_start = False
            continue
        if word_start:
            io_number = _IO_NUMBER.match(text, index)
            if io_number is not None:
                index = io_number.end()
                word_start = False
                continue
        heredoc = _HEREDOC_OPERATOR.match(text, index)
        if heredoc is not None:
            delimiter = next(group for group in heredoc.groups()[1:] if group is not None)
            pending.append((delimiter, heredoc.group(1) == _HEREDOC_STRIP_TABS))
            out.append(f" << {shlex.quote(delimiter)} ")
            index = heredoc.end()
            word_start = True
            continue
        if char in (_SINGLE_QUOTE, _DOUBLE_QUOTE):
            quote = char
        out.append(char)
        word_start = char in _WORD_BREAK_CHARS
        index += 1
    return "".join(out)


def command_words(command: str) -> list[str]:
    """``command`` as the words and operators bash reads, or ``[]`` when unparseable.

    The shared lexer for reading a commit line. Unlike :func:`tokenise_command`,
    an operator is its own word (``2>&1`` is ``>&``, ``1``; ``x;`` is ``x``,
    ``;``), a heredoc body is gone, and a newline is a ``;`` -- so a redirection
    or the next command can never be read as a commit's pathspec.
    """
    text = _lexable_text(command)
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        # Unbalanced quoting: bash would not run it either, but a guard must
        # still see the words, so they are read on whitespace alone.
        return text.split()


def is_operator(word: str) -> bool:
    """True when ``word`` is a shell operator rather than an argument."""
    return bool(word) and all(char in _OPERATOR_CHARS for char in word)


def is_redirection(word: str) -> bool:
    """True for a redirection operator, whose next word is its target."""
    return is_operator(word) and not _REDIRECT_CHARS.isdisjoint(word)


def _long_option_takes_value(option: str) -> bool:
    """Whether the long ``option`` (no ``=``) consumes the following word.

    git resolves an unambiguous prefix (``--mess``) to its option; an
    ambiguous one is an error and the commit never runs, so it consumes
    nothing here.
    """
    name = option[len(_LONG_PREFIX) :]
    if name in _COMMIT_LONG_OPTIONS:
        return _COMMIT_LONG_OPTIONS[name]
    candidates = [known for known in _COMMIT_LONG_OPTIONS if known.startswith(name)]
    if not candidates and name.startswith(_NEGATION_PREFIX):
        return False
    return len(candidates) == 1 and _COMMIT_LONG_OPTIONS[candidates[0]]


def _short_cluster_consumes_next(letters: str) -> bool:
    """Whether a short-option cluster's value is the following word.

    git reads a cluster letter by letter and the first value-taking letter
    ends it: a REQUIRED one with nothing after it takes the next word, an
    OPTIONAL one (``-S``, ``-u``) never does.
    """
    for position, letter in enumerate(letters):
        if letter in _OPTIONAL_VALUE_LETTERS:
            return False
        if letter in _REQUIRED_VALUE_LETTERS:
            return position == len(letters) - 1
    return False


def commit_option_words(words: list[str], start: int) -> list[str]:
    """The arguments of one git subcommand, from ``words[start]`` to its end.

    Stops at the operator that ends the simple command and drops every
    redirection with its target, so ``git commit -m x 2>&1 | tee log`` has the
    arguments ``-m x`` and nothing else.
    """
    arguments: list[str] = []
    index = start
    while index < len(words):
        word = words[index]
        if is_redirection(word):
            index += 2
            continue
        if is_operator(word):
            break
        arguments.append(word)
        index += 1
    return arguments


def extract_commit_pathspecs(command: str) -> list[str]:
    """The pathspecs of the first ``git commit`` in ``command``.

    A ``git commit <pathspec>...`` form commits the CURRENT WORKING TREE
    content of exactly those paths, regardless of what is (or isn't)
    staged for them — different semantics from a bare ``git commit``, which
    commits the index. Empty when the invocation has no trailing paths (a
    bare commit, or ``-a``).

    Read with :func:`command_words`, so a redirection, a heredoc, a trailing
    ``&`` or the next command is never a pathspec, and with git's own option
    table, so the value of ``-t``, ``--cleanup`` or ``--author`` is never one
    either.
    """
    words = command_words(command)
    subcommand = commit_subcommand_index(words)
    if subcommand is None:
        return []
    return commit_pathspecs(commit_option_words(words, subcommand + 1))


def commit_pathspecs(options: list[str]) -> list[str]:
    """The pathspecs among ``options``, the arguments after ``commit``."""
    pathspecs: list[str] = []
    index = 0
    while index < len(options):
        option = options[index]
        index += 1
        if option == _PATHSPEC_SEPARATOR:
            pathspecs.extend(options[index:])
            break
        if not option.startswith("-") or len(option) < 2:
            pathspecs.append(option)
            continue
        if _ASSIGNMENT_SIGN in option:
            continue
        if option.startswith(_LONG_PREFIX):
            if _long_option_takes_value(option):
                index += 1
            continue
        if _short_cluster_consumes_next(option[1:]):
            index += 1
    return pathspecs


#: ``--include`` and ``--pathspec-from-file`` as git accepts them: any
#: unambiguous prefix. ``--in`` is also ``--interactive`` and ``--pathspec-f``
#: is also ``--pathspec-file-nul``, so each has a shortest accepted spelling.
_INCLUDE_LONG_NAME: Final[str] = "include"
_INCLUDE_MIN_PREFIX: Final[int] = len("inc")
_INCLUDE_SHORT_LETTER: Final[str] = "i"
_PATHSPEC_FILE_LONG_NAME: Final[str] = "pathspec-from-file"
_PATHSPEC_FILE_MIN_PREFIX: Final[int] = len("pathspec-fr")


@dataclass(frozen=True)
class CommitForm:
    """The part of a ``git commit`` command line that decides which tree it records.

    * no ``pathspecs``: the index (``-a`` is read separately, by
      :func:`commits_working_tree`);
    * ``pathspecs``: HEAD's tree with those paths' WORKING-TREE content (the
      default ``--only``), the index ignored for them and every other staged
      change left out of the commit;
    * ``pathspecs`` with ``include``: the index, with those paths' working-tree
      content laid over it.

    ``pathspec_from_file`` means the named paths are in a file the command line
    does not carry, so the recorded tree cannot be stated from it.
    """

    pathspecs: tuple[str, ...] = ()
    include: bool = False
    pathspec_from_file: bool = False


def _long_option_is(option: str, name: str, minimum_prefix: int) -> bool:
    """Whether the long ``option`` (``--name`` or ``--name=value``) spells ``name``."""
    spelled = option[len(_LONG_PREFIX) :].partition(_ASSIGNMENT_SIGN)[0]
    return len(spelled) >= minimum_prefix and name.startswith(spelled)


def commit_includes_index(options: list[str]) -> bool:
    """True when this ``git commit`` option run carries ``-i``/``--include``.

    Walked like :func:`commits_working_tree`: an option's value, and anything
    after ``--``, is an operand, so ``-m 'about -i'`` and a file called ``-i``
    after the separator are not the flag.
    """
    index = 0
    while index < len(options):
        option = options[index]
        index += 1
        if option == _PATHSPEC_SEPARATOR:
            return False
        if not option.startswith("-") or len(option) < 2:
            continue
        if option.startswith(_LONG_PREFIX):
            if _long_option_is(option, _INCLUDE_LONG_NAME, _INCLUDE_MIN_PREFIX):
                return True
            if _ASSIGNMENT_SIGN not in option and _long_option_takes_value(option):
                index += 1
            continue
        letters = option[1:]
        for position, letter in enumerate(letters):
            if letter == _INCLUDE_SHORT_LETTER:
                return True
            if letter in _OPTIONAL_VALUE_LETTERS or letter in _REQUIRED_VALUE_LETTERS:
                if letter in _REQUIRED_VALUE_LETTERS and position == len(letters) - 1:
                    index += 1
                break
    return False


def _names_a_pathspec_file(options: list[str]) -> bool:
    """Whether an option before ``--`` is ``--pathspec-from-file``."""
    for option in options:
        if option == _PATHSPEC_SEPARATOR:
            return False
        if option.startswith(_LONG_PREFIX) and _long_option_is(
            option, _PATHSPEC_FILE_LONG_NAME, _PATHSPEC_FILE_MIN_PREFIX
        ):
            return True
    return False


def extract_commit_form(command: str) -> CommitForm:
    """The :class:`CommitForm` of the first ``git commit`` in ``command``.

    The bare form (what a commit with no path named records) when the command
    holds no commit or cannot be read.
    """
    words = command_words(command)
    subcommand = commit_subcommand_index(words)
    if subcommand is None:
        return CommitForm()
    options = commit_option_words(words, subcommand + 1)
    return CommitForm(
        pathspecs=tuple(commit_pathspecs(options)),
        include=commit_includes_index(options),
        pathspec_from_file=_names_a_pathspec_file(options),
    )


#: Characters that make a pathspec word something the shell, not git, resolves.
#: ``$`` covers a variable and ``$( )``; the rest are a backtick substitution,
#: a brace expansion and a home directory. A word carrying any of them names a
#: path this reading cannot state.
_SHELL_RESOLVED_CHARS: Final[str] = "$`{~"
#: Global options that point git at a different repository or work tree.
_REPOSITORY_MOVING_OPTIONS: Final[tuple[str, ...]] = ("-C", "--git-dir", "--work-tree")
_GIT_ENVIRONMENT_PREFIX: Final[str] = "GIT_"
_CHANGE_DIRECTORY_OPTION: Final[str] = "-C"
#: The repository-moving options a directory cannot stand for.
_UNSTATABLE_REPOSITORY_OPTIONS: Final[tuple[str, ...]] = ("--git-dir", "--work-tree")


@dataclass(frozen=True)
class CommitReading:
    """A command's :class:`CommitForm` and whether it can be taken at its word.

    ``certain`` is True only for the plain shape a careless agent types: ONE
    ``git commit``, run where the hook runs, in the repository the hook is in,
    naming literal paths. Only then may a gate narrow what the commit records to
    the named paths; any other shape is judged as the index with the named paths'
    working tree laid over it, which is never less than the index alone.
    """

    form: CommitForm
    certain: bool
    moves: tuple[str | None, ...] = ()


def _commit_moves(run: GitInvocation) -> tuple[str | None, ...]:
    """Where ``run`` goes from its starting directory, oldest move first.

    The ``cd``/``pushd`` chain, then the ``-C`` operands. An entry of None is a
    move this reading cannot state: an unreadable ``cd``, a word the shell
    resolves, or an option (``--git-dir``, ``--work-tree``, ``GIT_*``) that
    points git somewhere a directory cannot express.
    """
    moves: list[str | None] = [
        None if move is None or any(char in _SHELL_RESOLVED_CHARS for char in move) else move
        for move in run.directory
    ]
    options = run.global_options
    for position, option in enumerate(options):
        if option == _CHANGE_DIRECTORY_OPTION:
            operand = options[position + 1] if position + 1 < len(options) else None
        elif option.startswith(_CHANGE_DIRECTORY_OPTION):
            operand = option[len(_CHANGE_DIRECTORY_OPTION) :]
        elif option.startswith(_UNSTATABLE_REPOSITORY_OPTIONS):
            operand = None
        else:
            continue
        if operand is not None and any(char in _SHELL_RESOLVED_CHARS for char in operand):
            operand = None
        moves.append(operand)
    if any(assignment.startswith(_GIT_ENVIRONMENT_PREFIX) for assignment in run.assignments):
        moves.append(None)
    return tuple(moves)


def read_commit_form(command: str) -> CommitReading:
    """The :class:`CommitReading` of ``command``."""
    form = extract_commit_form(command)
    commits = [run for run in git_invocations(command) if run.subcommand == _COMMIT_TOKEN]
    moves = _commit_moves(commits[0]) if len(commits) == 1 else ()
    if not form.pathspecs:
        return CommitReading(form=form, certain=True, moves=moves)
    if len(commits) != 1:
        return CommitReading(form=form, certain=False)
    run = commits[0]
    moves_repository = any(
        option.startswith(_REPOSITORY_MOVING_OPTIONS) for option in run.global_options
    ) or any(assignment.startswith(_GIT_ENVIRONMENT_PREFIX) for assignment in run.assignments)
    shell_resolved = any(
        any(char in _SHELL_RESOLVED_CHARS for char in pathspec) for pathspec in form.pathspecs
    )
    return CommitReading(
        form=form,
        certain=not (run.directory or moves_repository or shell_resolved),
        moves=moves,
    )


def commit_subcommand_index(words: list[str]) -> int | None:
    """Index of the first ``commit`` subcommand of a ``git`` word, else None."""
    for position, word in enumerate(words):
        if command_word(word) != _GIT_TOKEN:
            continue
        index = git_subcommand_index(words, position)
        if index is not None and words[index] == _COMMIT_TOKEN:
            return index
    return None


#: Commands that run a string argument as shell: ``eval STRING`` and
#: ``sh -c STRING`` (any option cluster carrying ``c``).
_EVAL: Final[str] = "eval"
_SHELLS: Final[frozenset[str]] = frozenset({"sh", "bash", "dash", "zsh", "ksh"})
_SHELL_COMMAND_LETTER: Final[str] = "c"
_DIRECTORY_CHANGERS: Final[frozenset[str]] = frozenset({"cd", "pushd"})
_DIRECTORY_POPPER: Final[str] = "popd"
_CD_OPTIONS: Final[frozenset[str]] = frozenset({"-P", "-L", "-e", "-@"})
_HOME: Final[str] = "~"
_BUILTIN: Final[str] = "builtin"
_ASSIGNMENT_WORD: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class GitInvocation:
    """One ``git`` run found in a command, and where it runs.

    ``directory`` is the chain of ``cd``/``pushd`` targets in effect, oldest
    first, relative to the command's starting directory. An entry of None is
    a change this reading cannot state (``cd -``, ``popd``, ``cd a b``).
    ``assignments`` are the ``NAME=value`` words the simple command carries.
    """

    subcommand: str
    global_options: tuple[str, ...]
    arguments: tuple[str, ...]
    assignments: tuple[str, ...]
    directory: tuple[str | None, ...]


def git_invocations(command: str) -> list[GitInvocation]:
    """Every ``git <subcommand>`` ``command`` runs, with its directory.

    ``git`` counts wherever it is a word (``sudo git``, ``command git``,
    ``xargs git``, ``env -i git``, ``(git``), located with the same
    :func:`~claude_code_hooks_daemon.utils.command_evasion.git_subcommand_index`
    the sibling commit gates use. A string run by ``eval`` or ``sh -c`` is
    read as a command of its own, in the directory in effect. A subshell's
    ``cd`` ends with the subshell.
    """
    return _invocations(command_words(command), ())


def _invocations(words: list[str], directory: tuple[str | None, ...]) -> list[GitInvocation]:
    found: list[GitInvocation] = []
    stack: list[tuple[str | None, ...]] = []
    index = 0
    while index < len(words):
        if is_operator(words[index]) and not is_redirection(words[index]):
            # The lexer joins adjacent operators (`);`), so each is read in turn.
            for char in words[index]:
                if char == _SUBSHELL_OPEN:
                    stack.append(directory)
                elif char == _SUBSHELL_CLOSE:
                    directory = stack.pop() if stack else directory
            index += 1
            continue
        end = index
        while end < len(words) and not (is_operator(words[end]) and not is_redirection(words[end])):
            end += 2 if is_redirection(words[end]) else 1
        segment = [word for word in commit_option_words(words, index) if word]
        directory = _after_directory_change(segment, directory)
        found.extend(_segment_invocations(segment, directory))
        index = end
    return found


def _segment_invocations(
    segment: list[str], directory: tuple[str | None, ...]
) -> list[GitInvocation]:
    """The git runs of one simple command, including an ``eval``/``sh -c`` string."""
    body = _evaluated_string(segment)
    if body is not None:
        return _invocations(command_words(body), directory)
    for position, word in enumerate(segment):
        if command_word(word) != _GIT_TOKEN:
            continue
        subcommand = git_subcommand_index(segment, position)
        if subcommand is None:
            return []
        return [
            GitInvocation(
                subcommand=segment[subcommand],
                global_options=tuple(segment[position + 1 : subcommand]),
                arguments=tuple(segment[subcommand + 1 :]),
                assignments=tuple(
                    word for word in segment[:position] if _ASSIGNMENT_WORD.match(word)
                ),
                directory=directory,
            )
        ]
    return []


def _evaluated_string(segment: list[str]) -> str | None:
    """The string ``eval``/``sh -c`` runs as shell, or None when there is none."""
    for position, word in enumerate(segment):
        name = command_word(word)
        if name == _EVAL:
            return " ".join(segment[position + 1 :])
        if name in _SHELLS:
            for offset, option in enumerate(segment[position + 1 :], start=position + 1):
                if not option.startswith("-"):
                    return None
                if option.startswith(_LONG_PREFIX):
                    continue
                if _SHELL_COMMAND_LETTER in option[1:] and offset + 1 < len(segment):
                    return segment[offset + 1]
            return None
    return None


def _after_directory_change(
    segment: list[str], directory: tuple[str | None, ...]
) -> tuple[str | None, ...]:
    """``directory`` after ``segment`` when it is a ``cd``/``pushd``/``popd``."""
    words = segment
    while words and (words[0] in SHELL_RESERVED_COMMAND_PREFIXES or words[0] == _BUILTIN):
        words = words[1:]
    if not words:
        return directory
    name = command_word(words[0])
    if name == _DIRECTORY_POPPER:
        return (*directory, None)
    if name not in _DIRECTORY_CHANGERS:
        return directory
    operands = list(words[1:])
    while operands and operands[0] in _CD_OPTIONS:
        operands = operands[1:]
    if operands and operands[0] == _PATHSPEC_SEPARATOR:
        operands = operands[1:]
    if not operands:
        return (*directory, _HOME)
    if len(operands) > 1 or operands[0].startswith("-") or operands[0].startswith("+"):
        return (*directory, None)
    return (*directory, operands[0])
