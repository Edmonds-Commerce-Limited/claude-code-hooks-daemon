"""Split a Bash command string into top-level segments.

Handlers that decide *what command is actually being run* need to know where one
command ends and the next begins, and must treat a separator inside a quoted
argument as DATA rather than syntax. Getting that wrong in either direction is a
real defect:

- split too eagerly and a quoted ``;`` cuts the producer in half, so a
  legitimate command is denied because its resolved name is a fragment;
- split too lazily and a separator is missed, so the guarded command inherits
  the leading word of a harmless one and the handler is bypassed.

This module exists because two handlers grew their own scanner and each got the
opposite half of the escape rule, producing the same bypass from opposite causes
(Plan 00200 Task 3.7). One scanner, one set of rules, one place to fix.

Deliberately a scanner, not a shell parser. Callers need boundaries and a
yes/no answer on whether a span can execute — never a full expansion.

Plan 00222 added the second of those, for the same reason the module exists at
all. ``git_message_backtick`` already encoded "bash substitutes inside DOUBLE
quotes"; ``pipe_blocker`` independently assumed the opposite, treating any
message value as inert prose, and so let a real pipe through inside
``git commit -m "$(pytest ... | tail -1)"``. Two handlers, one codebase,
contradicting each other about the shell. ``value_can_substitute`` is where
that fact now lives, once.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from claude_code_hooks_daemon.utils.ansi_c import ansi_c_string
from claude_code_hooks_daemon.utils.command_evasion import (
    git_subcommand_index,
    strip_reserved_word_prefix,
)
from claude_code_hooks_daemon.utils.heredoc_operators import (
    COMMENT_PRECEDERS,
    Heredoc,
    scan_heredocs,
)

# Bash quoting characters. Inside single quotes NOTHING is special except the
# closing quote -- in particular a backslash is a literal backslash, which is
# the rule a scanner that escapes everywhere gets wrong.
_SINGLE_QUOTE = "'"
_DOUBLE_QUOTE = '"'

# A backslash escapes exactly the next character, everywhere EXCEPT inside
# single quotes. A scanner blind to it flips its quote state on an escaped quote
# and never leaves quoted mode.
_ESCAPE_CHAR = "\\"

# ANSI-C quoting: inside `$'...'` a backslash DOES escape, so `$'it\'s'` is one
# word. `$$` is the pid, and the quote after it is a plain one.
_ANSI_C_OPEN = "$'"
_PID = "$$"
_NEWLINE = "\n"

# Spans that make bash RUN something and substitute its output. Backticks are
# listed separately because the same character opens and closes them.
_SUBSTITUTION_OPENERS: tuple[str, ...] = ("$(", "<(", ">(")
_BACKTICK = "`"

# ``"$(cat <<'EOF' ... EOF)"`` -- the canonical multi-line message idiom.
#
# It contains ``$(``, so the opener test alone would call it executable. What
# makes it inert is the QUOTED delimiter: bash performs no expansion at all
# inside ``<<'EOF'``, so the body is literal text and the only thing that runs
# is ``cat``. An UNQUOTED ``<<EOF`` does expand and is deliberately unmatched.
#
# Scanning the body instead of recognising the idiom is not a safe fallback:
# newlines are segment separators, so the "command" before a pipe in the body
# resolves to a line of English prose (Plan 00200's false positive, rediscovered
# by Plan 00222's tests before it shipped).
#
# The heredoc must be the WHOLE substitution (Plan 00466 N120): a regex ending
# in ``.*\)"`` let ``)$(cmd)`` after the closer, or ``; cmd`` on the opener
# line, ride inside a value blanked as prose. So the value is split into these
# fixed parts and the heredoc between them is read by the shared scanner.
_MESSAGE_SUBSTITUTION_OPEN = '"$('
_MESSAGE_SUBSTITUTION_CLOSE = ')"'
_MESSAGE_HEREDOC_HEAD_PATTERN = re.compile(r"\s*cat\s+")

# The same bash fact as above, for a heredoc fed straight to a command's stdin
# rather than wrapped in an argument value: `git commit -F - <<'EOF' ... EOF`.
# Quoting the delimiter disables every expansion, so bash hands the body over
# verbatim and never parses it as shell syntax. The delimiter MUST be quoted: a
# bare `<<EOF` still expands `$(...)` and backticks, so its body can genuinely
# run a command and is deliberately left alone.
#
# Where a heredoc starts, what its delimiter is and which line closes it are
# read by `scan_heredocs`, bash's grammar in one place (Plan 00466 N120). An
# unrecognised heredoc is not a near miss: its body is scanned as shell, so a
# paragraph of prose is split on newlines and judged command by command.

# What a blanked body is replaced with: a single inert token that keeps the
# heredoc's shape (opener, one body line, closer) so a caller splitting on
# newlines still sees a well-formed command.
_INERT_BODY_PLACEHOLDER = "HEREDOC_BODY"

# Separators that end one command and start the next, used to find which
# command a heredoc opener actually belongs to. Longest-first: `||` must be
# matched whole before the single `|` can claim its first character.
_RECEIVER_SEPARATORS: tuple[str, ...] = ("&&", "||", ";", "|", "&")

#: A receiving segment that OPENS with a command substitution. `$(cat <<'EOF'
#: ... )` and its backtick spelling put the body's TEXT into command position:
#: bash substitutes the output and then runs it. The heredoc's receiver really
#: is `cat`, and nothing is piped on, so the other two checks both answer
#: "prose" -- this is the third way a sink stops being one.
#:
#: Deliberately NOT matching a bare `(` or `{`. Those GROUP rather than
#: substitute, so `( cat <<'EOF' ) > notes.md` sends the body to a redirect and
#: never to command position; withholding there would scan every grouped prose
#: write for nothing.
_SUBSTITUTION_OPENER_PATTERN = re.compile(r"^(?:\$\(|`)")

#: A file-descriptor redirect, whose `&` is punctuation rather than a command
#: separator: `2>&1`, `>&2`, `1>&2`, `&>log`, `&>>log`, `2>&-`.
#:
#: These are blanked out of a segment BEFORE it is split, because
#: `_RECEIVER_SEPARATORS` contains a lone `&` and would otherwise cut
#: `cat 2>&1 <<'EOF'` into `cat 2>` and `1 `, resolving the receiver to `1`.
#: That is on no allowlist, so the exemption is withheld and ordinary prose is
#: scanned -- which re-opens the false positive Plan 00377 N7 closed, for
#: `git commit -F - 2>&1 <<'EOF'`.
_FD_REDIRECT_PATTERN = re.compile(r"[0-9]*[<>]&[0-9]*-?|&>>?")

#: Separators that END the pipeline a heredoc feeds, as opposed to extending
#: it. `|` is deliberately absent: it hands the body's bytes to another
#: command, so that command is a consumer and must be judged too. `||` and `&&`
#: hand over nothing, so a fallback branch on the opener line must not cause
#: the body to be scanned. Longest-first, so `||` is matched whole.
#:
#: A LONE `&` is deliberately absent too, and that is a correction rather than
#: an omission. It was here, and a stderr redirect contains one: `2>&1` cut
#: `cat <<'EOF' 2>&1 | bash` before the pipe was ever seen, so a body bash runs
#: was blanked. Dropping it costs only over-withholding -- a `|` belonging to
#: something after a background `&` is read as downstream, which scans a body
#: rather than exempting one -- and that is the safe direction.
_PIPELINE_TERMINATORS: tuple[str, ...] = ("&&", "||", ";")

#: Grouping and escaping characters bash strips off the front of a command
#: word while deciding what command it names. `(` and `{` open a subshell or
#: brace group, `` ` `` and `$` open a substitution, `\` escapes the next
#: character -- in none of these does the punctuation belong to the command's
#: name.
_WORD_GROUPING_PREFIXES = "(){}`\\$"


@dataclass(frozen=True)
class _WrapperGrammar:
    """The option syntax of a command that runs another command.

    Short letters that take no value, short letters whose value is the rest
    of the cluster or the next word, long options without and with a value
    (``--name value`` or ``--name=value``), long options whose value may
    only be glued (``--name[=value]``), operands before the command
    (``timeout``'s DURATION), and whether ``NAME=value`` words may precede
    the command (``env``).
    """

    flags: frozenset[str] = frozenset()
    value_flags: frozenset[str] = frozenset()
    long_flags: frozenset[str] = frozenset()
    long_value_flags: frozenset[str] = frozenset()
    long_optional_value_flags: frozenset[str] = frozenset()
    operand: re.Pattern[str] | None = None
    assignments: bool = False
    numeric_flags: bool = False


#: Words that PREFIX a command without being it, so the command word sits
#: further along: `sudo -u root tee f` names tee. Each is parsed with its
#: own option grammar, because an option's VALUE is not the command:
#: `sudo -p cat bash` runs bash (Plan 00466 N101, D-SEC F2). An option not
#: in the grammar, and each option refused below, resolves to NO command,
#: which every allowlist caller treats as unknown. Only consulted by the
#: allowlist callers (`quoted_heredoc_command_words`, the data-sink
#: exemption, `brace_expansion_view`'s inert heads);
#: `quoted_heredoc_receivers` must NOT use this: its caller matches against
#: DANGEROUS names, where reporting only `sudo` would hide the interpreter.
#:
#: A deliberate WIDENING of the data-sink exemption (Plan 00466 N101 D-RULE
#: m1): main skipped only `sudo`, so `env cat <<'EOF'` kept its body. Each
#: wrapper here is sound to see through because it execs the named command
#: with the same stdin and adds no execution of its own, and the name it
#: runs resolves as it would on its own: `sudo` runs it as another user
#: with a reset environment, `env` sets only the variables it names, `nice`
#: and `nohup` change only scheduling and signals, `timeout` only bounds
#: its run time, and `command` only bypasses shell functions (so it trusts
#: a sink name LESS than a bare one, N89).
#:
#: Refused, so they resolve to no command: a mode that runs a shell
#: (`sudo -s`/`-i`, `env -S`); a PATH change; a new root or working
#: directory (`sudo -R`/`--chroot`, `sudo -D`/`--chdir`, `env -C`/
#: `--chdir`), under which the name need not reach the same binary; and
#: `sudo -E`/`--preserve-env`, which carries the caller's environment
#: across sudo's reset (N101 round 4, D-RULE minor 1).
_WRAPPER_GRAMMARS: dict[str, _WrapperGrammar] = {
    "sudo": _WrapperGrammar(
        flags=frozenset("AbBHknNPS"),
        value_flags=frozenset("CgpTtUu"),
        long_flags=frozenset(
            {
                "askpass",
                "background",
                "bell",
                "set-home",
                "reset-timestamp",
                "non-interactive",
                "preserve-groups",
                "stdin",
            }
        ),
        long_value_flags=frozenset(
            {
                "close-from",
                "group",
                "prompt",
                "role",
                "type",
                "command-timeout",
                "other-user",
                "user",
            }
        ),
    ),
    "env": _WrapperGrammar(
        flags=frozenset("i0v"),
        value_flags=frozenset("u"),
        long_flags=frozenset({"ignore-environment", "null", "debug"}),
        long_value_flags=frozenset({"unset"}),
        long_optional_value_flags=frozenset({"block-signal", "default-signal", "ignore-signal"}),
        assignments=True,
    ),
    "nice": _WrapperGrammar(
        value_flags=frozenset("n"),
        long_value_flags=frozenset({"adjustment"}),
        numeric_flags=True,
    ),
    "timeout": _WrapperGrammar(
        flags=frozenset("v"),
        value_flags=frozenset("sk"),
        long_flags=frozenset({"foreground", "preserve-status", "verbose"}),
        long_value_flags=frozenset({"signal", "kill-after"}),
        operand=re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)[smhd]?"),
    ),
    "nohup": _WrapperGrammar(),
    "command": _WrapperGrammar(flags=frozenset("p")),
}

#: An `env` operand that sets a variable rather than naming the command.
_ENV_ASSIGNMENT_PATTERN = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)=")

#: Commands that consume a heredoc body as DATA rather than executing it, and
#: so are the only receivers for which blanking the body is sound.
#:
#: An ALLOWLIST, deliberately, per Plan 00335 Decision 1. The opposite shape --
#: a list of interpreters to withhold from -- makes every name nobody thought
#: of default to "safe to blank", and that failed four separate times in
#: `curl_pipe_shell` before the direction was flipped: `eval "$(cat <<'EOF')"`,
#: `. /dev/stdin`, seven punctuation spellings, six word-expansion spellings,
#: and `ssh host <<'EOF'`, which runs the body on another machine entirely.
#: Asking "is this a recognised sink?" makes the same unknown default to "scan
#: the body", which costs a false positive rather than a guard.
#:
#: Lives here rather than in a handler because every caller that blanks a body
#: needs it: `curl_pipe_shell` reached this conclusion alone and the other
#: eight consumers did not inherit it, which is how `bash <<'EOF'` walked past
#: five data-loss rules (Plan 00409).
#:
#: An omission here costs a FALSE POSITIVE, not a bypass: withholding the
#: exemption scans the body rather than denying the command, so a denial
#: follows only if that body independently trips a guard. Add names as they
#: prove legitimate.
#:
#: Deliberately EXCLUDED despite looking like ordinary filters or clients:
#:   sed  -- `sed -f -` runs the body as a script, and the `e` flag reaches a shell
#:   awk  -- `awk -f /dev/stdin` runs the body as a program
#:   ssh  -- executes the body on the remote host
#:   crontab -- `crontab -` installs commands that execute later
#:   sqlite3 -- the `.shell` / `.system` dot-commands run a shell command
#:   psql -- the `\!` meta-command runs a shell command
#:   mysql -- the `system` / `\!` client command runs a shell command
#:
#: The three database clients were on this list until a release review probed
#: them: each reads its body from stdin and each offers a shell escape, so a
#: body naming one was blanked before any scan. They are the same shape as
#: `ssh` -- a client that looks like a data consumer and is also an executor --
#: which is why the test that pins them names the escape rather than the
#: command.
DATA_SINKS: frozenset[str] = frozenset(
    {
        # Version control and text output
        "git",
        "cat",
        "tee",
        "sort",
        "uniq",
        "tr",
        "cut",
        "column",
        "head",
        "tail",
        "wc",
        "grep",
        "diff",
        "patch",
        "less",
        "more",
        "base64",
        "md5sum",
        "sha1sum",
        "sha256sum",
        # Structured data
        "jq",
        "yq",
        # Network and mail sinks that transfer rather than execute
        "mail",
        "mailx",
        "sendmail",
        "ftp",
    }
)


#: Matches a `-m`/`--message`/`-F`/`--file` flag immediately followed by its
#: VALUE, so the value can be excluded from a command scan. Three value shapes,
#: tried in order (DOTALL so `.` spans newlines, needed for the heredoc
#: alternative's body):
#:   1. The canonical heredoc-embedded message idiom: -m "$(cat <<'EOF' … EOF)"
#:      (leading whitespace before the closing delimiter is tolerated — messages
#:      are often re-indented). Any delimiter word, quoted or not, as bash
#:      allows; whether the value is inert is `value_can_substitute`'s call.
#:   2. A single- or double-quoted string (may span literal newlines).
#:   3. A bare word (e.g. `-F commit-msg.txt`) as a fallback.
#:
#: The bare-word alternative stops at a shell METACHARACTER rather than at the
#: next space, and that boundary is load-bearing. It was `\S+`, and `\S` matches
#: `&`, `;` and `|` -- so an unquoted value ran straight through the separator
#: and ate the head word of the command after it: `git commit -m x&&git reset
#: --hard` had `x&&git` blanked as prose, leaving every downstream guard looking
#: at `reset --hard` with no `git` in front of it while bash ran both commands.
#: Quoting the value was enough to avoid it, which is why the bypass survived
#: the suite -- every test quoted.
_MESSAGE_BODY_PATTERN = re.compile(
    r"(?P<flag>(?<![\w-])(?:-m|--message|-F|--file))"
    r"(?P<sep>=|\s+)"
    r"(?P<value>"
    r"\"\$\(cat\s+<<-?\s*(?P<dq>['\"]?)(?P<delim>[^\s'\"\\;&|<>()]+)(?P=dq)"
    r"\s*\n.*?\n[ \t]*(?P=delim)[ \t]*\n?\s*\)\""
    r"|'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r"|[^\s;&|<>()`]+"
    r")",
    re.DOTALL,
)

#: What an inert message value is replaced with.
_MESSAGE_BODY_PLACEHOLDER = "<REDACTED>"

#: Commands whose `-m`/`--message`/`-F`/`--file` argument is human-authored
#: PROSE rather than an operand (Plan 00222). Scoping is required because the
#: same spelling means something else elsewhere: `python -m <module>` names a
#: MODULE, and blanking it reported the producer of `python -m pytest … | tail`
#: as the redaction placeholder — a remediation the caller cannot run.
_MESSAGE_TAKING_COMMANDS: tuple[str, ...] = ("git", "hg", "svn", "jj")

#: Scoping to the BINARY is not enough, and the gap was a live bypass of
#: R-GIT-CHECKOUT-DISCARD (Plan 00407 N7). `-m` means "message" only where the
#: SUBCOMMAND takes one: for `git checkout` it selects merge-conflict style and
#: takes NO value, so the next token -- the `--` that makes the checkout
#: destructive -- was blanked as though it were commit prose, and the guard
#: stopped matching. Inserting two characters was enough, and the loss is
#: silent and permanent.
#:
#: An ALLOWLIST, because the safe error is withholding an exemption: an
#: unlisted subcommand keeps its operands visible to every scanner, which at
#: worst costs a false positive on a message nobody quoted.
#:
#: Deliberately absent, each because `-m` there is NOT prose: `checkout` and
#: `branch` (rename / conflict style), `cherry-pick` and `revert` (mainline
#: parent NUMBER), `rebase` (`--merge`, valueless).
_MESSAGE_TAKING_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "git": frozenset({"commit", "tag", "merge", "notes", "stash"}),
}

#: Separators that end one command and start the next, for attributing a flag
#: to the command word that owns it.
_CHAIN_SEPARATORS: tuple[str, ...] = ("&&", "||", ";", "\n")

#: Path separator, for reducing `/usr/bin/git` to `git` before comparison.
_PATH_SEPARATOR = "/"

#: Where a top-level scan starts when no earlier separator is found.
_SEGMENT_START = 0

#: Combined alternation of `_CHAIN_SEPARATORS`, longest-first so `&&`/`||`
#: match whole (there is no bare `&`/`|` in the list, so no other ordering
#: risk). Used by `_SegmentTracker` to find every separator in a gap with one
#: scan instead of one `rfind` per separator per query.
_CHAIN_SEPARATOR_PATTERN = re.compile("|".join(re.escape(sep) for sep in _CHAIN_SEPARATORS))

#: How far into a segment `_SegmentTracker` looks for the binary and
#: subcommand. Generous for any real invocation (`git -C /path -c x=y
#: commit`), and a bound here is what keeps a single-segment command with
#: thousands of matches (Plan 00466 N25's repro: 40000 `-m x` flags, no chain
#: separator anywhere) from re-splitting an ever-growing prefix for every
#: match. A segment whose subcommand sits further out than this resolves to
#: "" (unknown), which is the FAIL-SAFE direction here: the flag is left
#: unblanked and scanned normally, never silently treated as prose.
_SEGMENT_WORD_SCAN_BOUND = 4096


class _SegmentTracker:
    """Resolves, and caches, which top-level command segment owns each match.

    `strip_message_bodies` used to answer "what segment owns this `-m`/`-F`
    flag?" by re-deriving it from scratch for every match: `rfind` each chain
    separator over `command[:index]`, then `command[start:index].split()`.
    Both costs grow with `index`, and Plan 00466 N25's repro -- a single 200
    KB `git commit` carrying 40000 repeated `-m x` flags, with NO chain
    separator anywhere -- made every one of those 40000 matches re-split an
    ever-growing prefix: 99s where a linear scan takes milliseconds.

    A segment's identity cannot change between two matches unless a chain
    separator sits between them, and `re.sub`/`re.finditer` visit matches in
    strictly ascending position order. So this resolves a segment once and
    reuses it for every later match in the same segment, and the separator
    search that decides whether a NEW segment started is bounded to the GAP
    since the previous match rather than restarted from the beginning --
    those gaps are disjoint and sum to at most `len(command)` over the whole
    scan.

    Leading reserved words are dropped from the window before splitting, so
    the segment of `if x; then git commit -m m; fi` starts at `git` (Plan
    00422 N25) -- merged in alongside the N25 performance fix above (Plan
    00466 N40 review 2 MA4).
    """

    __slots__ = ("_binary", "_command", "_scanned_to", "_segment_start", "_subcommand")

    def __init__(self, command: str) -> None:
        self._command = command
        self._scanned_to = _SEGMENT_START
        self._segment_start = _SEGMENT_START
        self._binary = ""
        self._subcommand = ""
        self._resolve(_SEGMENT_START)

    def _resolve(self, start: int) -> None:
        """(Re)compute the binary/subcommand for the segment beginning at ``start``."""
        window_text = strip_reserved_word_prefix(
            self._command[start : start + _SEGMENT_WORD_SCAN_BOUND]
        )
        window = window_text.split()
        self._binary = window[0].rpartition(_PATH_SEPARATOR)[2] if window else ""
        position = git_subcommand_index(window, 0) if window else None
        self._subcommand = window[position] if position is not None else ""

    def binary_and_subcommand(self, index: int) -> tuple[str, str]:
        """``(binary, subcommand)`` of the segment owning the flag at ``index``."""
        last_separator_end = None
        for match in _CHAIN_SEPARATOR_PATTERN.finditer(self._command, self._scanned_to, index):
            last_separator_end = match.end()
        if last_separator_end is not None:
            self._segment_start = last_separator_end
            self._resolve(self._segment_start)
        self._scanned_to = index
        return self._binary, self._subcommand


def command_word(word: str) -> str:
    """The command name bash would resolve ``word`` to.

    Public because a second handler now needs it (Plan 00401's reference-repo
    gate, which compares a segment's head against ``git``). That handler shipped
    a private copy first, and the copy was weaker in exactly the way this
    docstring warns about -- it reduced only the basename, so ``(cd`` stayed
    ``(cd`` and a subshell escaped the comparison.

    Quoting is a property of the SHELL SYNTAX, not of the command being named:
    ``"bash"``, ``'bash'``, ``ba"sh"``, ``\\bash`` and ``(bash`` all invoke
    bash. A caller comparing a receiver against a list of interpreter names has
    to compare what bash resolves, or the list is defeated by punctuation that
    changes nothing about what runs.

    Reducing only the basename -- the previous behaviour -- made this helper
    UNDER-report, which grants an exemption. That inverts the safe direction
    its own contract promises: over-reporting withholds an exemption, and
    withholding is the cheap error.
    """
    unquoted = word.replace('"', "").replace("'", "")
    return unquoted.lstrip(_WORD_GROUPING_PREFIXES).rsplit("/", 1)[-1]


#: Unquoted characters whose word bash changes by more than quote removal:
#: parameter and command substitution, pathname globbing, brace expansion.
_EXPANDING_CHARS = "$`*?[{}"

#: Whitespace that ends an unquoted shell word.
_WORD_BREAK_CHARS = " \t\n"


def iter_shell_words(text: str) -> Iterator[str | None]:
    """Each whitespace-delimited shell word of ``text``, quotes kept.

    Quote-aware, so ``sudo -p 'x cat' bash`` is four words, not five
    (Plan 00466 N101 round 3, D-SEC minor 3). A word's extent is certain
    only while no substitution can hide whitespace inside it, so an
    unterminated quote, ``$(``, ``${`` or a backtick yields ``None`` and
    ends the stream: every word before it is exact, and nothing after it is
    guessed at.
    """
    index = 0
    length = len(text)
    while True:
        while index < length and text[index] in _WORD_BREAK_CHARS:
            index += 1
        if index >= length:
            return
        start = index
        while index < length and text[index] not in _WORD_BREAK_CHARS:
            end = _quoted_span_end(text, index)
            if end is None:
                yield None
                return
            index = end
        yield text[start:index]


def _quoted_span_end(text: str, index: int) -> int | None:
    """Index past the escape, quoted span or plain character at ``index``;
    ``None`` when its extent cannot be known without running the shell."""
    char = text[index]
    if char == "\\":
        return min(index + 2, len(text))
    if char == "`" or text.startswith(("$(", "${"), index):
        return None
    if char == "'":
        end = text.find("'", index + 1)
        return None if end == -1 else end + 1
    if text.startswith("$'", index):
        cursor = index + 2
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
            elif text[cursor] == "'":
                return cursor + 1
            else:
                cursor += 1
        return None
    if char == '"':
        cursor = index + 1
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
            elif text[cursor] == '"':
                return cursor + 1
            elif text[cursor] == "`" or text.startswith(("$(", "${"), cursor):
                return None
            else:
                cursor += 1
        return None
    return index + 1


def resolve_shell_word(word: str) -> str | None:
    """The text bash makes of ``word`` by quote and backslash removal alone.

    ``'exec'``, ``"exec"``, ``\\exec`` and ``e\\xec`` all resolve to
    ``exec``: bash removes quotes before it looks a name up, so a name list
    compared against the word as written is defeated by punctuation
    (Plan 00466 N101 round 3, D-RULE B1 and M1). ``None`` when anything but
    quote removal could change the word -- an expansion, a glob, a brace
    group, ANSI-C quoting or an unterminated quote -- because a caller
    comparing names must treat a word it cannot resolve as any name at all.
    """
    out: list[str] = []
    index = 0
    length = len(word)
    while index < length:
        char = word[index]
        if char == "\\":
            if index + 1 >= length:
                return None
            if word[index + 1] != "\n":
                out.append(word[index + 1])
            index += 2
        elif char == "'":
            end = word.find("'", index + 1)
            if end == -1:
                return None
            out.append(word[index + 1 : end])
            index = end + 1
        elif char == '"':
            closed = _resolve_double_quoted(word, index + 1, out)
            if closed is None:
                return None
            index = closed
        elif char in _EXPANDING_CHARS:
            return None
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _resolve_double_quoted(word: str, index: int, out: list[str]) -> int | None:
    """Append the double-quoted span starting at ``index`` to ``out``;
    return the index past its closing quote, or ``None`` when it expands
    something or never closes."""
    while index < len(word):
        char = word[index]
        if char == '"':
            return index + 1
        if char in "$`":
            return None
        if char == "\\" and index + 1 < len(word) and word[index + 1] in '$`"\\\n':
            if word[index + 1] != "\n":
                out.append(word[index + 1])
            index += 2
            continue
        out.append(char)
        index += 1
    return None


def value_can_substitute(value: str) -> bool:
    """Whether bash will EXECUTE something inside this quoted argument value.

    The question a handler actually needs before deciding that an argument is
    inert data. Quote class alone is the wrong test in both directions:

    * DOUBLE quotes do not stop substitution -- they stop word splitting. So
      ``"$(pytest ...)"`` runs pytest, and treating it as prose hides it.
    * SINGLE quotes stop substitution entirely, so a ``$(`` between them is
      literal text however executable it reads.

    What separates the cases is whether a substitution is present at all, which
    is why a rule phrased on quote class was tried and rejected: it re-breaks
    the deliberate allowance for double-quoted PROSE that merely mentions a
    pipe (Plan 00200).

    Args:
        value: The argument value INCLUDING its surrounding quotes, exactly as
            it appeared in the command. The quotes are the evidence.

    Returns:
        True if bash would run something inside ``value``.
    """
    if value.startswith(_SINGLE_QUOTE) and value.endswith(_SINGLE_QUOTE):
        return False
    if _is_message_heredoc_idiom(value):
        return False
    return _BACKTICK in value or any(opener in value for opener in _SUBSTITUTION_OPENERS)


def _is_message_heredoc_idiom(value: str) -> bool:
    """Is ``value`` exactly ``"$(cat <<'D'`` + body + ``D)"``, with blanks only
    around the heredoc and nothing else anywhere in the substitution?"""
    if not (
        value.startswith(_MESSAGE_SUBSTITUTION_OPEN)
        and value.endswith(_MESSAGE_SUBSTITUTION_CLOSE)
        and len(value) >= len(_MESSAGE_SUBSTITUTION_OPEN) + len(_MESSAGE_SUBSTITUTION_CLOSE)
    ):
        return False
    inner = value[len(_MESSAGE_SUBSTITUTION_OPEN) : -len(_MESSAGE_SUBSTITUTION_CLOSE)]
    heredocs = scan_heredocs(inner).heredocs
    if len(heredocs) != 1:
        return False
    heredoc = heredocs[0]
    operator = heredoc.operator
    if not (operator.quoted and heredoc.terminated):
        return False
    if not _MESSAGE_HEREDOC_HEAD_PATTERN.fullmatch(inner[: operator.start]):
        return False
    return (
        not inner[operator.end : heredoc.body_start].strip()
        and not inner[heredoc.closer_end :].strip()
    )


def strip_message_bodies(command: str) -> str:
    """Blank every ``-m``/``--message``/``-F``/``--file`` VALUE bash cannot run.

    These flags carry human-authored prose — a commit/tag message, or a path to
    one — never shell syntax to execute. A guarded construct sitting in that
    prose is DATA, and a handler that scans the raw string reads it as a
    command: the field report for Plan 00377 N7 is a commit message describing
    a ``--force`` flag, denied as though it were a force push.

    Two conditions gate the blanking, both from Plan 00222, each added after the
    unconditional form was measured to be wrong in the opposite direction:

    * the owning command must actually TAKE a message, so ``python -m
      <module>`` keeps naming a module rather than a redaction placeholder, and
    * the value must not be able to execute — bash substitutes inside double
      quotes, so blanking ``"$(...)"`` would CONCEAL a live command.

    A value failing either test is returned untouched and scanned normally.

    Args:
        command: The raw Bash command string.

    Returns:
        ``command`` with each inert message value replaced by a placeholder.
        Everything else, including a real command beside the message, is
        untouched.
    """

    tracker = _SegmentTracker(command)

    def _blank_if_inert(match: re.Match[str]) -> str:
        binary, subcommand = tracker.binary_and_subcommand(match.start())
        if binary not in _MESSAGE_TAKING_COMMANDS:
            return match.group(0)
        allowed = _MESSAGE_TAKING_SUBCOMMANDS.get(binary)
        if allowed is not None and subcommand not in allowed:
            return match.group(0)
        if value_can_substitute(match.group("value")):
            return match.group(0)
        return f"{match.group('flag')}{match.group('sep')}{_MESSAGE_BODY_PLACEHOLDER}"

    return _MESSAGE_BODY_PATTERN.sub(_blank_if_inert, command)


def strip_inert_spans(command: str) -> str:
    """Blank every span bash will hand over as data rather than execute.

    The composition of :func:`strip_message_bodies` and
    :func:`strip_quoted_heredoc_bodies` — the scan target a handler should
    judge when it is asking "what command is being run?".

    Both halves are required, and that is measured rather than assumed: for
    Plan 00377 N7, blanking only the heredoc cleared the reported command while
    leaving an ordinary one-line ``git commit -m 'document --amend'`` still
    denied, because the single-line patterns match inside the message value.

    "Hand over as data" is the load-bearing phrase, and the heredoc half reads
    it strictly: a body is blanked only when its RECEIVER treats it as data.
    ``bash <<'EOF'`` does not, so its body survives here and is judged like any
    other command.

    Args:
        command: The raw Bash command string.

    Returns:
        ``command`` with inert message values and sink-fed quoted-heredoc
        bodies blanked.
    """
    return strip_quoted_heredoc_bodies(strip_message_bodies(command))


def strip_quoted_heredoc_bodies(command: str) -> str:
    """Blank the body of every quoted-delimiter heredoc fed to a DATA SINK.

    ``<<'EOF'`` and ``<<"EOF"`` disable every expansion, so bash hands the body
    to the receiving command verbatim and never parses it as shell syntax.
    Anything in that body — a pipe, a script name, a command that reads as
    dangerous — is DATA *to bash*.

    That last qualifier is the whole contract, and omitting it shipped a
    bypass. Bash not parsing the body says nothing about what the RECEIVER
    does with it: ``bash <<'EOF'`` executes it, and the quoting governs only
    what the outer shell expands on the way in. Blanking on the strength of the
    delimiter alone therefore handed every caller an empty command while the
    interpreter ran the real one — five data-loss rules in ``destructive_git``
    among them (Plan 00409).

    So the exemption is granted by receiver, from :data:`DATA_SINKS`. An
    unrecognised receiver — an interpreter, ``ssh host``, or simply a name the
    list does not carry — keeps its body, which is then scanned like any other
    command.

    Call this BEFORE splitting a command into segments. Newlines are segment
    separators, so a caller that splits first will chop the body into lines and
    judge each one as a command; the "command" before a pipe then resolves to a
    line of English prose. That is not hypothetical, it is the false positive
    this module's docstring already records for ``value_can_substitute``, and it
    recurred in ``enforce_llm_qa`` for the one heredoc shape that function does
    not cover (Plan 00234 finding H-3): a ``git commit -F - <<'EOF'`` message
    body that merely MENTIONED a guarded script was denied.

    An UNQUOTED ``<<EOF`` is deliberately NOT blanked: bash expands ``$(...)``
    and backticks inside it, so its body really can run something.

    Args:
        command: The raw Bash command string.

    Returns:
        ``command`` with each sink-fed quoted-delimiter heredoc body replaced by
        a single inert placeholder line. The opener and closing delimiter are
        preserved, so the result still splits into well-formed segments. A body
        fed to anything else is returned untouched.

    Examples:
        >>> strip_quoted_heredoc_bodies("git commit -F - <<'EOF'\\nrm -rf /\\nEOF")
        "git commit -F - <<'EOF'\\nHEREDOC_BODY\\nEOF"
        >>> strip_quoted_heredoc_bodies("bash <<'EOF'\\nrm -rf /\\nEOF")
        "bash <<'EOF'\\nrm -rf /\\nEOF"
        >>> strip_quoted_heredoc_bodies("echo hi")
        'echo hi'
    """

    depth_tracker = _SubstitutionDepthTracker(command)
    newline_tracker = _LastNewlineTracker(command)
    pieces: list[str] = []
    copied_to = 0
    for heredoc in _quoted_heredocs(command):
        opener_start = heredoc.operator.start
        # Three questions, because each was separately a real hole: who
        # RECEIVES the body, what it is PIPED ON to, and whether the whole
        # command sits in a SUBSTITUTION whose output lands in command
        # position. Any one of them failing keeps the body.
        if not _receiver_is_data_sink(command, opener_start, depth_tracker, newline_tracker):
            continue
        if not _downstream_is_all_data_sinks(_opener_tail(command, heredoc)):
            continue
        # Only the body lines are replaced. Everything else on the opener
        # line is kept, and that is usually a REDIRECT (`cat <<'EOF' > doc.md`):
        # blanking a body must remove no evidence but the body.
        pieces.append(command[copied_to : heredoc.body_start])
        pieces.append(f"{_INERT_BODY_PLACEHOLDER}\n")
        copied_to = heredoc.closer_start
    pieces.append(command[copied_to:])
    return "".join(pieces)


def _quoted_heredocs(command: str) -> list[Heredoc]:
    """Every terminated quoted-delimiter heredoc, in opener order: the order
    the incremental trackers require."""
    heredocs = (
        heredoc
        for heredoc in scan_heredocs(command).heredocs
        if heredoc.operator.quoted and heredoc.terminated
    )
    return sorted(heredocs, key=lambda heredoc: heredoc.operator.start)


def _opener_tail(command: str, heredoc: Heredoc) -> str:
    """What the opener line carries after the heredoc's delimiter word."""
    line_end = command.find("\n", heredoc.operator.end)
    return command[heredoc.operator.end : len(command) if line_end < 0 else line_end]


def _receiver_is_data_sink(
    command: str,
    opener_start: int,
    depth_tracker: _SubstitutionDepthTracker,
    newline_tracker: _LastNewlineTracker,
) -> bool:
    """Does the command feeding the heredoc at ``opener_start`` only READ it?

    Decided per heredoc rather than per command: ``cat > a <<'A' … bash <<'B'``
    has one of each, and blanking is sound for the first and unsound for the
    second.

    A receiver that names no command word at all (bash allows a bare
    ``<<'EOF'`` redirection) resolves to ``None`` and is treated as unknown,
    so the body is scanned. Unknown means scan, always — that is the direction
    the allowlist exists to fix.

    A segment OPENING with a command substitution is refused before the
    receiver is even resolved, because there the receiver is not the whole
    story: ``$(cat <<'EOF' … )`` really is fed to ``cat``, and bash then runs
    what ``cat`` emitted. See :data:`_SUBSTITUTION_OPENER_PATTERN`.

    ``depth_tracker``/``newline_tracker`` carry state ACROSS calls for the
    same top-level scan (Plan 00466 N25) — see their own docstrings. Callers
    querying `opener_start` values in ascending order (every caller here
    does, via `re.sub`/`re.finditer`) get each character of `command`
    inspected at most once between them, however many heredocs it contains.
    """
    if depth_tracker.inside_substitution_at(opener_start):
        return False
    segment = _receiving_segment(command, opener_start, newline_tracker)
    if _SUBSTITUTION_OPENER_PATTERN.match(segment.lstrip()):
        return False
    word = _segment_command_word(segment)
    return word is not None and word in DATA_SINKS


class _SubstitutionDepthTracker:
    """Incrementally answers "is this position inside an open substitution?".

    The stateless check this replaces -- walk the command from index 0,
    tracking quote state and ``$(...)``/backtick depth -- is correct but
    O(position) per call. Called once per heredoc match, in a command with
    many heredocs and no separator between them (Plan 00466 N25's repro: 5000
    quoted heredocs in 200 KB), that made the whole scan O(n^2): 98s where a
    single linear pass takes milliseconds.

    Relies on the SAME ordering guarantee `_SegmentTracker` does: callers
    query strictly ascending positions (true for every caller here, via
    `re.sub`/`re.finditer` over one command), so resuming from where the
    previous query left off, rather than restarting at 0, inspects each
    character of the command at most once across the whole scan.
    """

    __slots__ = ("_command", "_depth", "_in_backtick", "_in_double", "_in_single", "_index")

    def __init__(self, command: str) -> None:
        self._command = command
        self._index = 0
        self._depth = 0
        self._in_single = False
        self._in_double = False
        self._in_backtick = False

    def inside_substitution_at(self, position: int) -> bool:
        """True if ``position`` sits inside an OPEN ``$(...)``/backtick span.

        Quotes are tracked because they decide whether an opener is one:
        ``$(`` is literal inside single quotes and live inside double
        quotes, and an apostrophe inside double quotes (``"don't"``) is not
        a quote opener. Over-reporting containment is the safe error here --
        it withholds the exemption and the body is scanned, costing a false
        positive. Under-reporting hands a live command to every caller as
        blanked prose.
        """
        command = self._command
        index = self._index
        depth = self._depth
        in_single = self._in_single
        in_double = self._in_double
        in_backtick = self._in_backtick

        while index < position:
            char = command[index]
            if char == "\\" and not in_single:
                index += 2
                continue
            if char == "'" and not in_double and not in_backtick:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif not in_single:
                if char == "`":
                    in_backtick = not in_backtick
                elif command.startswith("$(", index):
                    depth += 1
                    index += 2
                    continue
                elif char == ")" and depth > 0:
                    depth -= 1
            index += 1

        self._index = index
        self._depth = depth
        self._in_single = in_single
        self._in_double = in_double
        self._in_backtick = in_backtick
        return depth > 0 or in_backtick


class _LastNewlineTracker:
    """Incrementally finds the most recent newline strictly before a position.

    ``_receiving_segment`` used to compute this as
    ``command[:opener_start].rsplit("\\n", 1)[-1]``: a full copy of the
    command's PREFIX, made fresh for every heredoc match. The copy's cost
    grows with `opener_start`, so many heredocs in one command (Plan 00466
    N25's repro) made it O(n^2) even though the segments it returns are
    individually short.

    Bounding the search to the GAP since the previous query (`opener_start`
    values arrive in ascending order, the same guarantee
    `_SubstitutionDepthTracker` relies on) keeps each call's cost
    proportional to that gap rather than to the absolute position, and the
    gaps are disjoint and sum to at most `len(command)`.
    """

    __slots__ = ("_command", "_last_newline", "_scanned_to")

    def __init__(self, command: str) -> None:
        self._command = command
        self._scanned_to = 0
        self._last_newline = -1

    def line_start_before(self, position: int) -> int:
        """Index right after the most recent literal ``\\n`` before ``position``.

        Deliberately naive about quoting/escaping, matching the ``rsplit``
        behaviour it replaces exactly: every literal newline is a line
        boundary here, full stop.
        """
        found = self._command.rfind("\n", self._scanned_to, position)
        if found != -1:
            self._last_newline = found
        self._scanned_to = position
        return self._last_newline + 1


def _downstream_is_all_data_sinks(opener_tail: str) -> bool:
    """Does every command the body is PIPED ON to also just read it?

    ``cat <<'EOF' | bash`` passes :func:`_receiver_is_data_sink` — the receiver
    really is ``cat`` — and then hands the body straight to an interpreter. The
    exemption has to survive the whole pipeline, not merely its first stage, or
    a sink becomes a way to smuggle one.

    Only ``|`` extends the pipeline. ``&&``, ``||``, ``;`` and ``&`` end it and
    everything after them is a separate command that never sees the body, so a
    fallback branch on the opener line (``cat <<'EOF' > f || echo failed``)
    must not cause the body to be scanned.

    Args:
        opener_tail: Whatever the opener line carried after the delimiter.

    Returns:
        True when there are no downstream stages, or every one of them names a
        recognised data sink. An unrecognised or unnameable stage returns
        False, which withholds the exemption and scans the body.
    """
    pipeline = split_unquoted(opener_tail, _PIPELINE_TERMINATORS)[0]
    for stage in split_unquoted(pipeline, ("|",))[1:]:
        word = _segment_command_word(stage)
        if word is None or word not in DATA_SINKS:
            return False
    return True


def quoted_heredoc_receivers(command: str) -> list[str]:
    """Return the command words each quoted-delimiter heredoc is fed to.

    ``strip_quoted_heredoc_bodies`` blanks a body because bash never PARSES
    it. That is the whole truth when the receiver treats the bytes as data —
    ``git commit -F -``, ``cat > file`` — but NOT when the receiver is an
    interpreter: ``bash <<'EOF'`` executes the body regardless of the quoting,
    which only governs what the OUTER shell expands on the way in. A caller
    blanking bodies for a safety decision would otherwise hand out a clean
    bypass, so it needs to know who is on the receiving end.

    The interpreter policy deliberately stays with the caller; different
    handlers guard different interpreter sets, and this module judges nothing.

    Every word of the receiving command is returned, not just the first,
    because ``sudo -E bash <<'EOF'`` genuinely feeds bash and reporting only
    ``sudo`` would hide it. Words are reduced to their basename so ``/bin/sh``
    and ``sh`` compare equal. The consequence is intentional over-reporting: a
    redirect target that happens to be named like an interpreter is reported
    too. For a caller deciding whether to WITHHOLD an exemption that is the
    safe direction — it withholds one, it never grants one.

    An UNQUOTED ``<<EOF`` is not reported: it is not blanked either, so there
    is no exemption to guard.

    Args:
        command: The raw Bash command string.

    Returns:
        Basenames of the words making up each quoted heredoc's receiving
        command, in the order the heredocs appear. Empty if there are none.

    Examples:
        >>> quoted_heredoc_receivers("git commit -F - <<'MSG'\\nbody\\nMSG")
        ['git']
        >>> quoted_heredoc_receivers("/bin/sh <<'EOF'\\nbody\\nEOF")
        ['sh']
    """
    receivers: list[str] = []
    for segment in _heredoc_receiving_segments(command):
        receivers.extend(
            command_word(word) for word in segment.split() if word and not word.startswith("-")
        )
    return receivers


def _heredoc_receiving_segments(command: str) -> list[str]:
    """Return the command segment feeding each quoted heredoc, in order.

    The receiving command is what sits between the previous separator and the
    ``<<`` opener -- a pipe stage or an ``&&`` branch, not the whole line, so
    ``echo x | bash <<'EOF'`` resolves to bash rather than echo.
    """
    newline_tracker = _LastNewlineTracker(command)
    return [
        _receiving_segment(command, heredoc.operator.start, newline_tracker)
        for heredoc in _quoted_heredocs(command)
    ]


def _receiving_segment(
    command: str, opener_start: int, newline_tracker: _LastNewlineTracker
) -> str:
    """Return the command segment feeding the heredoc opening at ``opener_start``.

    ``newline_tracker`` carries state across calls for the same top-level
    scan (Plan 00466 N25) -- see its own docstring. Callers must query
    ``opener_start`` values in ascending order, which every caller here does.
    """
    line_start = newline_tracker.line_start_before(opener_start)
    last_line = command[line_start:opener_start]
    # Blanked, not removed: an fd redirect's `&` is punctuation, and leaving it
    # in lets `_RECEIVER_SEPARATORS`' lone `&` cut `cat 2>&1 ` at the redirect.
    without_redirects = _FD_REDIRECT_PATTERN.sub(" ", last_line)
    return split_unquoted(without_redirects, _RECEIVER_SEPARATORS)[-1]


def quoted_heredoc_command_words(command: str) -> list[str]:
    """Return the single command word feeding each quoted heredoc.

    The allowlist counterpart to ``quoted_heredoc_receivers``. That function
    reports EVERY word so a caller matching against a list of DANGEROUS names
    cannot be fooled by ``sudo -E bash`` hiding the interpreter behind sudo.
    A caller matching against a list of SAFE names needs the opposite shape:
    the one word that names the command, because an argument is not the
    receiver and must not be asked to satisfy the allowlist. ``git commit -F -``
    would otherwise fail on ``commit`` and ``jq -r .`` on ``.``.

    A wrapper (``sudo``, ``env``, ``nice``, ``nohup``, ``timeout``,
    ``command``) is skipped with its options, so ``sudo -u root tee f``
    resolves to ``tee``. That cannot hide anything from an allowlist caller:
    ``sudo -u root bash`` resolves to ``bash``, which no list of data sinks
    contains, so the exemption is withheld either way. Skipping the wrappers
    other than ``sudo`` is a deliberate widening; see :data:`_WRAPPER_GRAMMARS`.

    A word built by EXPANSION (``$SHELL``, ``b$'ash'``), globbing or brace
    expansion, at or before the command word, names no command and is not
    reported -- resolving it would mean running the command the caller
    exists to judge, and an unresolvable word must never satisfy an
    allowlist.

    Args:
        command: The raw Bash command string.

    Returns:
        One command-word basename per quoted heredoc, in the order the
        heredocs appear. Empty if there are none.

    Examples:
        >>> quoted_heredoc_command_words("git commit -F - <<'MSG'\\nbody\\nMSG")
        ['git']
        >>> quoted_heredoc_command_words("sudo -u root bash <<'EOF'\\nbody\\nEOF")
        ['bash']
    """
    resolved_words = (
        _segment_command_word(segment) for segment in _heredoc_receiving_segments(command)
    )
    return [word for word in resolved_words if word is not None]


def segment_command_word(segment: str) -> str | None:
    """Public form of :func:`_segment_command_word`, for a caller outside
    this module that must name a segment's command the same way the heredoc
    exemption here does (``shell_expansion.brace_expansion_view``)."""
    return _segment_command_word(segment)


def _segment_command_word(segment: str) -> str | None:
    """Return the one word naming the command a segment runs, or None.

    An EMPTY resolution means the word was pure grouping punctuation (`{`,
    `(`), which `_WORD_GROUPING_PREFIXES` strips entirely. It names no command,
    so accepting it as the command word matched '' against the caller's
    allowlist, failed, and denied an ordinary `{ cat <<'DOC' ... } > doc.md`.
    Skipping it looks at the next word instead, which is the actual receiver --
    so `( bash <<'X'` still resolves to `bash` and still withholds the
    exemption.

    None means the segment names no command at all, which every caller here
    treats as unknown rather than safe.

    Leading reserved words are skipped the same way (Plan 00422 N25): in
    `do cat <<'EOF'` the receiver is `cat`, and reading `do` withheld the
    exemption from every heredoc in a loop body.

    A wrapper (:data:`_WRAPPER_GRAMMARS`) is skipped together with its
    options and their values, so `sudo -p cat bash` names bash. A word
    starting with `-` where a command should be, or a wrapper option the
    grammar does not know, names nothing (Plan 00466 N101).

    Words are split with quotes respected and judged after quote removal
    (:func:`iter_shell_words`, :func:`resolve_shell_word`), so
    `sudo -p 'x cat' bash` names bash and `c\\at` names cat. A word bash
    could change by expansion, globbing or brace expansion, up to and
    including the command word, names nothing (Plan 00466 N101 round 3).
    """
    chain = segment_command_chain(segment)
    return None if chain is None else chain[-1].rsplit("/", 1)[-1]


def segment_command_chain(segment: str) -> tuple[str, ...] | None:
    """The words in command position of ``segment``, after quote removal
    and NOT reduced to a basename: each wrapper it runs through, then the
    command itself (``sudo -u root /usr/bin/ls x`` is ``("sudo",
    "/usr/bin/ls")``). ``None`` on the same terms as
    :func:`_segment_command_word`, whose command word is the last one."""
    words = _resolved_segment_words(segment)
    chain: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        if word is None:
            return None
        resolved = word.rsplit("/", 1)[-1]
        if not resolved or resolved.startswith("-"):
            return None
        chain.append(word)
        grammar = _WRAPPER_GRAMMARS.get(resolved)
        if grammar is None:
            return tuple(chain)
        after = _skip_wrapper_arguments(grammar, words, index + 1)
        if after is None:
            return None
        index = after
    return None


def _resolved_segment_words(segment: str) -> list[str | None]:
    """The segment's words after quote removal, ending at the first one that
    cannot be resolved (reported as ``None``). Leading grouping punctuation
    (`(`, `{`, and a `(` glued to the command word) opens a subshell or
    group and names no command, so it is dropped."""
    words: list[str | None] = []
    for raw in iter_shell_words(strip_reserved_word_prefix(segment)):
        if raw is not None and not words:
            raw = raw.lstrip("(") if raw.strip("({") else ""
            if not raw:
                continue
        resolved = None if raw is None else resolve_shell_word(raw)
        words.append(resolved)
        if resolved is None:
            break
    return words


def _skip_wrapper_arguments(
    grammar: _WrapperGrammar, words: Sequence[str | None], index: int
) -> int | None:
    """Index of the word a wrapper runs, past its options, their values and
    its operands; ``None`` when any of them cannot be parsed with certainty."""
    operand_pending = grammar.operand is not None
    while index < len(words):
        word = words[index]
        if word is None:
            return None
        if word == "--":
            index += 1
            break
        if word.startswith("--"):
            name, has_value, _ = word[2:].partition("=")
            if (
                name in grammar.long_flags and not has_value
            ) or name in grammar.long_optional_value_flags:
                index += 1
            elif name in grammar.long_value_flags:
                index += 1 if has_value else 2
            else:
                return None
            continue
        if word.startswith("-") and len(word) > 1:
            if grammar.numeric_flags and word[1:].isdigit():
                index += 1
                continue
            consumed = _short_option_cluster_width(grammar, word[1:])
            if consumed is None:
                return None
            index += consumed
            continue
        if grammar.assignments:
            assignment = _ENV_ASSIGNMENT_PATTERN.match(word)
            if assignment is not None:
                if assignment.group("name") == "PATH":
                    return None
                index += 1
                continue
        break
    if operand_pending:
        if index >= len(words) or grammar.operand is None:
            return None
        operand = words[index]
        if operand is None or not grammar.operand.fullmatch(operand):
            return None
        index += 1
    return index if index <= len(words) else None


def _short_option_cluster_width(grammar: _WrapperGrammar, letters: str) -> int | None:
    """Words a short-option cluster takes: 1, or 2 when its last letter's
    value is the next word; ``None`` for a letter the grammar lacks."""
    for position, letter in enumerate(letters):
        if letter in grammar.flags:
            continue
        if letter in grammar.value_flags:
            return 1 if position + 1 < len(letters) else 2
        return None
    return 1


def split_unquoted(text: str, separators: Sequence[str]) -> list[str]:
    """Split ``text`` on ``separators`` that appear outside quotes.

    Args:
        text: The raw command string.
        separators: Separator strings to split on. Multi-character separators
            (``&&``, ``||``) are matched whole, so order them longest-first when
            one is a prefix of another.

    Returns:
        The segments, quote characters and escapes preserved verbatim so callers
        can pattern-match them. Always at least one element; separators
        themselves are not included.

    Examples:
        >>> split_unquoted("cd x\\ngrep y", (";", "\\n"))
        ['cd x', 'grep y']
        >>> split_unquoted('grep -E "a;b"', (";",))
        ['grep -E "a;b"']
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    in_comment = False
    index = 0

    while index < len(text):
        char = text[index]
        unquoted = not in_single and not in_double

        # A comment runs to the newline and its quotes are characters, but its
        # separators still split: judging comment text as commands is the
        # conservative reading, and a quote in it must not swallow later lines.
        if in_comment or (unquoted and _starts_comment(text, index)):
            in_comment = char != _NEWLINE
            matched = next((sep for sep in separators if text.startswith(sep, index)), None)
            if matched is not None:
                segments.append("".join(current))
                current = []
                index += len(matched)
                continue
            current.append(char)
            index += 1
            continue

        # `$$` is the pid; a `$'...'` string ends at its first UNESCAPED quote.
        if unquoted and text.startswith(_PID, index):
            current.append(_PID)
            index += len(_PID)
            continue
        if unquoted and text.startswith(_ANSI_C_OPEN, index):
            ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
            end = len(text) if ansi_c is None else ansi_c[1]
            current.append(text[index:end])
            index = end
            continue

        # Rule 1: inside single quotes a backslash is literal, so escape
        # handling is skipped entirely and only the closing quote matters.
        if char == _ESCAPE_CHAR and not in_single:
            current.append(char)
            index += 1
            if index < len(text):
                current.append(text[index])
                index += 1
            continue

        if char == _SINGLE_QUOTE and not in_double:
            in_single = not in_single
        elif char == _DOUBLE_QUOTE and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            matched = next((sep for sep in separators if text.startswith(sep, index)), None)
            if matched is not None:
                segments.append("".join(current))
                current = []
                index += len(matched)
                continue

        current.append(char)
        index += 1

    segments.append("".join(current))
    return segments


def _starts_comment(text: str, index: int) -> bool:
    """Is the unquoted character at ``index`` a ``#`` that starts a word?"""
    return text[index] == "#" and (index == 0 or text[index - 1] in COMMENT_PRECEDERS)
