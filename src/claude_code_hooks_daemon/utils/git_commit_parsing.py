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

import shlex
from typing import Final

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


def extract_commit_pathspecs(tokens: list[str]) -> list[str]:
    """Trailing pathspec arguments to ``git commit`` (paths, not flags/values).

    A ``git commit <pathspec>...`` form commits the CURRENT WORKING TREE
    content of exactly those paths, regardless of what is (or isn't)
    staged for them — different semantics from a bare ``git commit``, which
    commits the index. Empty when the invocation has no trailing paths (a
    bare commit, or ``-a``).
    """
    try:
        commit_index = tokens.index(_COMMIT_TOKEN)
    except ValueError:
        return []

    pathspecs: list[str] = []
    seen_separator = False
    index = commit_index + 1
    while index < len(tokens):
        token = tokens[index]
        if not seen_separator and token == _PATHSPEC_SEPARATOR:
            seen_separator = True
            index += 1
            continue
        if not seen_separator and token.startswith("-"):
            flag = token.split("=", 1)[0]
            if flag in VALUE_FLAGS and "=" not in token:
                index += 2  # skip the flag AND its separate value token
                continue
            if "=" not in token:
                cluster = _short_cluster_value_letter(token)
                if cluster is not None:
                    _, attached = cluster
                    # Attached value stays in this token; an unattached one
                    # (value is the FOLLOWING token) must be skipped too.
                    index += 1 if attached is not None else 2
                    continue
            index += 1  # boolean flag, or `flag=value` (no separate token)
            continue
        pathspecs.append(token)
        index += 1
    return pathspecs
