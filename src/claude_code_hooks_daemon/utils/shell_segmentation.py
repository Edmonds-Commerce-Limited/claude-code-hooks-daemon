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

import contextvars
import re
import stat
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NamedTuple

from claude_code_hooks_daemon.utils.ansi_c import ansi_c_string
from claude_code_hooks_daemon.utils.command_evasion import (
    git_subcommand_index,
    strip_reserved_word_prefix,
)
from claude_code_hooks_daemon.utils.heredoc_operators import (
    COMMENT_PRECEDERS,
    Heredoc,
    HeredocScan,
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

#: Commands that run a heredoc body fed to them as SHELL, so its redirects are
#: writes the command performs (Plan 00466 N101 round 10, S3).
SHELL_BODY_RUNNERS: frozenset[str] = frozenset({"sh", "bash", "zsh", "dash", "ksh", "source", "."})

#: Variables bash or the login environment set to a shell, by the shell each
#: names.
_SHELL_VARIABLES: dict[str, str] = {"SHELL": "sh", "BASH": "bash"}

#: A command word that is one variable expansion, optionally quoted and
#: followed by a literal path tail: ``$PY``, ``"${PY}"``, ``$VENV/bin/python``.
_VARIABLE_COMMAND_PATTERN = re.compile(
    r"(?P<quote>\"?)\$(?:\{(?P<braced>[A-Za-z_]\w*)\}|(?P<bare>[A-Za-z_]\w*))"
    r"(?P<tail>[^\s\"'`$\\;&|<>(){}*?\[]*)(?P=quote)(?=\s|$)"
)

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
#: a sink name LESS than a bare one, N89). `exec` replaces the shell with
#: the command and `builtin` runs a builtin by name: both only name it.
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
    "exec": _WrapperGrammar(flags=frozenset("cl"), value_flags=frozenset("a")),
    "builtin": _WrapperGrammar(),
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
        "less",
        "more",
        "base64",
        "md5sum",
        "sha1sum",
        "sha256sum",
        # Structured data
        "jq",
        "yq",
    }
)

#: The arguments each sink may carry and still only READ its body (Plan 00466
#: N101 round 10, S1). A sink name is not enough: `tee >(bash)`, `git -c
#: alias.r='!bash' r` and `sort --compress-program=sh` all hand the body to
#: an executor. A sink listed here accepts only the options named; one not
#: listed has no option that executes anything, so any option is inert.
#: Either way a process substitution, an fd other than 1 or 2, or a write
#: target that is not a regular file withholds the exemption.
#:
#: Taken off `DATA_SINKS` by the same review, each an executor reading its
#: commands from the body: `ftp` (`!cmd`), `mail`/`mailx` (`~!cmd`),
#: `sendmail` (a `|program` recipient) and `patch` (an ed-style diff is run by
#: `ed`, whose `!` runs a shell).
_SINK_OPTIONS: dict[str, frozenset[str]] = {
    "tee": frozenset({"-a", "-i", "-p", "--append", "--ignore-interrupts", "--output-error"}),
    "sort": frozenset(
        {
            *(f"-{letter}" for letter in "bdfgiMhnRrVcCmsuzktoST"),
            "--numeric-sort",
            "--reverse",
            "--unique",
            "--key",
            "--field-separator",
            "--output",
            "--stable",
            "--ignore-case",
            "--human-numeric-sort",
            "--version-sort",
        }
    ),
    "less": frozenset({"-R", "-S", "-N", "-F", "-X", "-r"}),
    "more": frozenset(),
}

#: Short options of an allowlisted sink that take the next word as a value.
_SINK_VALUE_OPTIONS: dict[str, frozenset[str]] = {
    "sort": frozenset({"-k", "-t", "-o", "-S", "-T"}),
}

#: Options whose value is a file the sink WRITES.
_SINK_OUTPUT_OPTIONS: dict[str, frozenset[str]] = {"sort": frozenset({"-o", "--output"})}

#: Sinks whose every operand is a file they write.
_SINK_OUTPUT_OPERANDS: frozenset[str] = frozenset({"tee"})

#: `git` options before the subcommand that change nothing about what runs.
_GIT_INERT_GLOBAL_FLAGS: frozenset[str] = frozenset({"--no-pager", "-P", "--no-optional-locks"})
_GIT_DIRECTORY_FLAG = "-C"

#: The git subcommands that read a heredoc body as data. Anything else may be
#: an alias, and a `!` alias runs a shell on the body.
_GIT_DATA_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "commit",
        "tag",
        "notes",
        "apply",
        "am",
        "hash-object",
        "update-index",
        "mktag",
        "mktree",
        "check-ignore",
        "check-attr",
        "cat-file",
        "interpret-trailers",
        "stripspace",
        "commit-tree",
        "rev-list",
    }
)

#: Receivers that only ever read a heredoc body as TEXT to print, count,
#: filter, write or encode (Plan 00474 N256). Narrower than
#: :data:`DATA_SINKS`, which answers "does it EXECUTE the body?"; this list
#: answers "does anything OPEN the words of the body as paths?", and so leaves
#: out what `DATA_SINKS` keeps:
#:
#:   git -- plumbing reads path and object names from stdin (`update-index
#:     --stdin`, `cat-file --batch`); it qualifies only as a message reader
#:     (:data:`_GIT_MESSAGE_SUBCOMMANDS`)
#:   patch -- edits the files a body names; ftp -- runs a body's `get`;
#:     mail/mailx -- honour tilde escapes
#:   jq, yq -- can load files by name; md5sum, sha1sum, sha256sum -- `-c`
#:     opens the files a body names
#:   less, more, diff -- pagers and a file comparer, no text-only use here
#:
#: Every entry is also in :data:`DATA_SINKS`, so a stage must pass that
#: list's option and redirect checks too.
TEXT_READING_SINKS: frozenset[str] = frozenset(
    {
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
        "base64",
    }
)

#: `git` subcommands whose `-F -`/`--file=-` reads stdin as a message.
_GIT_MESSAGE_SUBCOMMANDS: frozenset[str] = frozenset({"commit", "tag"})

#: `-F -` spelled as one word, or as the flag word followed by `-`.
_GIT_STDIN_MESSAGE_WORDS: frozenset[str] = frozenset({"-F-", "--file=-"})
_GIT_MESSAGE_FILE_FLAGS: frozenset[str] = frozenset({"-F", "--file"})
_GIT_PATHSPEC_OPTION_PREFIX = "--pathspec"

_AMPERSAND_REDIRECT = "&>"

#: Text that routes a body or a word somewhere the command word does not
#: say: a command or process substitution, or a backtick.
_REROUTING_MARKERS: tuple[str, ...] = ("$(", "<(", ">(", "`")

#: Write targets that are no file an executor could read from.
_INERT_DEVICES: frozenset[str] = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr"})
_DEVICE_ROOTS: tuple[str, ...] = ("/dev/", "/proc/")
#: fds a redirect may duplicate onto and stay inert: stdout, stderr, closed.
_INERT_FD_TARGETS: frozenset[str] = frozenset({"1", "2", "-"})
_PROCESS_SUBSTITUTIONS: tuple[str, ...] = (">(", "<(")
#: A redirect operator at the start of a word, with an optional fd before it.
_REDIRECT_WORD_PATTERN = re.compile(
    r"(?P<fd>\d*|&)(?P<op><<<|<<-?|>>|>\||>&|<&|<>|>|<)(?P<rest>.*)"
)
_READ_OPERATORS: frozenset[str] = frozenset({"<", "<<", "<<-", "<<<"})
#: Text that can leave an fd open on a process: a process substitution,
#: ``exec`` with a redirect, or a ``coproc``. Where a command carries one, an
#: unresolved write target may be ``/dev/fd/N`` for it (Plan 00466 N213).
_FD_PROCESS_PATTERN = re.compile(r"[<>]\(|\bexec\b|\bcoproc\b")
#: Characters that, outside quotes, make bash split or glob a word.
_SPLITTING_CHARACTERS = frozenset("$`*?[")

#: Variables bash sets or reads itself (bash 5.2, "Shell Variables"), and the
#: ones that point a sink at a helper program. An assignment to one neither
#: pins its value nor leaves a later sink's name meaning the sink (Plan 00466
#: N101 rounds 12 and 13, N214 and N215).
_SPECIAL_VARIABLES: frozenset[str] = frozenset(
    {
        "_",
        "BASH",
        "BASHOPTS",
        "BASHPID",
        "CDPATH",
        "CHILD_MAX",
        "COLUMNS",
        "COMPREPLY",
        "COPROC",
        "DIRSTACK",
        "EDITOR",
        "EMACS",
        "ENV",
        "EPOCHREALTIME",
        "EPOCHSECONDS",
        "EUID",
        "EXECIGNORE",
        "FCEDIT",
        "FIGNORE",
        "FUNCNAME",
        "FUNCNEST",
        "GLOBIGNORE",
        "GROUPS",
        "HISTCMD",
        "HISTCONTROL",
        "HISTFILE",
        "HISTFILESIZE",
        "HISTIGNORE",
        "HISTSIZE",
        "HISTTIMEFORMAT",
        "HOME",
        "HOSTFILE",
        "HOSTNAME",
        "HOSTTYPE",
        "IFS",
        "IGNOREEOF",
        "INPUTRC",
        "INSIDE_EMACS",
        "LANG",
        "LINENO",
        "LINES",
        "MACHTYPE",
        "MAIL",
        "MAILCHECK",
        "MAILPATH",
        "MANPAGER",
        "MAPFILE",
        "OLDPWD",
        "OPTARG",
        "OPTERR",
        "OPTIND",
        "OSTYPE",
        "PAGER",
        "PATH",
        "PIPESTATUS",
        "POSIXLY_CORRECT",
        "PPID",
        "PROMPT_COMMAND",
        "PROMPT_DIRTRIM",
        "PS0",
        "PS1",
        "PS2",
        "PS3",
        "PS4",
        "PWD",
        "RANDOM",
        "READLINE_ARGUMENT",
        "READLINE_LINE",
        "READLINE_MARK",
        "READLINE_POINT",
        "REPLY",
        "SECONDS",
        "SHELL",
        "SHELLOPTS",
        "SHLVL",
        "SRANDOM",
        "TERM",
        "TIMEFORMAT",
        "TMOUT",
        "TMPDIR",
        "UID",
        "VISUAL",
        "auto_resume",
        "histchars",
    }
)
_SPECIAL_VARIABLE_PREFIXES: tuple[str, ...] = ("BASH_", "COMP_", "GIT_", "LC_", "LD_", "LESS")

#: Builtins and keywords that may set a variable the text never spells as
#: ``NAME=value``: while one runs, no variable is known.
_NAME_WRITERS: frozenset[str] = frozenset(
    {
        "read",
        "mapfile",
        "readarray",
        "getopts",
        "eval",
        "source",
        ".",
        "let",
        "trap",
        "alias",
        "declare",
        "typeset",
        "local",
        "unset",
        "for",
        "select",
    }
)
#: Where bash reads a command word, in text with its quote characters
#: removed: after an operator or a reserved word a command follows, then
#: any assignments and ``builtin``/``command``/``time`` prefixes.
_COMMAND_POSITION = (
    r"(?:^|[;&|(){}`\n]|(?<![\w-])(?:then|else|elif|do|if|while|until|time)(?=\s)"
    r"|(?<!\S)!(?=\s))\s*(?:[A-Za-z_]\w*(?:\[[^\]]*\])?\+?=[^\s;&|()<>`]*\s+)*"
    r"(?:(?:builtin|command|time)\s+(?:-\S+\s+)*)*"
)
_NAME_WRITER_PATTERN = re.compile(
    _COMMAND_POSITION
    + "(?:"
    + "|".join(re.escape(word) for word in sorted(_NAME_WRITERS))
    + r")(?=[\s;&|()]|$)"
)
_PRINTF_TARGET_PATTERN = re.compile(_COMMAND_POSITION + r"printf\s[^;&|\n]*?(?<=\s)-v")
#: A command word bash computes: a variable, a substitution or a backtick.
_COMPUTED_COMMAND_PATTERN = re.compile(
    _COMMAND_POSITION + r"(?:\$(?:\{?(?P<name>[A-Za-z_]\w*)|[^A-Za-z_])|`)"
)
_QUOTING_CHARACTERS = re.compile(r"[\\'\"]")
#: ``$NAME`` or ``${NAME}``.
_VARIABLE_REFERENCE = re.compile(r"\$(?:\{(?P<braced>[A-Za-z_]\w*)\}|(?P<bare>[A-Za-z_]\w*))")
#: Anything that reads a variable: ``$NAME``, ``${NAME…``, ``${#NAME}``.
_REFERENCED_NAME = re.compile(r"\$\{?[#!]?([A-Za-z_]\w*)")
#: Anything that may assign one: ``NAME=``, ``NAME+=``, ``NAME[KEY]=``.
_ASSIGNED_NAME = re.compile(r"(?<![\w$])([A-Za-z_]\w*)(?:\[[^\]]*\])?\+?=")
#: Characters in a value that bash splits or globs where it is used unquoted.
_UNPLAIN_VALUE_CHARACTERS = frozenset(" \t\n*?[")
#: Text that writes a variable through a computed name or an expansion
#: (arithmetic, ``${!name}``, ``${NAME:=value}``, a ``${ …; }`` substitution),
#: or changes how an unquoted value splits (``IFS``).
_COMPUTED_WRITE_PATTERN = re.compile(
    r"\(\(|\$\[|\$\{!|\$\{[A-Za-z_]\w*(?:\[[^\]]*\])?:?=|\$\{[\s|]|\bIFS\b"
)
#: A whole word that assigns a variable: ``NAME=value``.
_ASSIGNMENT_WORD = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)\Z", re.DOTALL)
#: Characters that, unquoted, open a group, a substitution or a compound
#: command.
_NESTING_CHARACTERS: tuple[str, ...] = ("(", ")", "{", "}", "`")
#: Reserved words: a statement opening with one is compound.
_RESERVED_WORDS: frozenset[str] = frozenset(
    {
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "do",
        "done",
        "while",
        "until",
        "for",
        "case",
        "esac",
        "select",
        "function",
        "time",
        "coproc",
        "!",
        "{",
        "}",
        "[[",
        "]]",
    }
)
#: Redirects that write no file: an fd duplicated or closed, or ``/dev/null``.
_HARMLESS_REDIRECT_PATTERN = re.compile(
    r"[0-9]*[<>]&(?:[0-9]+|-)(?![\w./-])|(?:[0-9]*|&)>>?\s*/dev/null(?![\w./-])"
)


class _Word(NamedTuple):
    """A shell word as written, and after quote removal (None when an
    expansion leaves it unresolved)."""

    raw: str
    value: str | None


#: The working directory of the event being judged. Per dispatch, never on a
#: shared object: the daemon runs from `/`, and a relative write target lands
#: in the Bash call's own cwd.
_EVENT_CWD: contextvars.ContextVar[str | None] = contextvars.ContextVar("event_cwd", default=None)


def bind_event_cwd(cwd: str | None) -> contextvars.Token[str | None]:
    """Make ``cwd`` the base for relative paths until :func:`reset_event_cwd`."""
    return _EVENT_CWD.set(cwd)


def reset_event_cwd(token: contextvars.Token[str | None]) -> None:
    """Undo the :func:`bind_event_cwd` that returned ``token``."""
    _EVENT_CWD.reset(token)


_DUPLICATE_OPERATORS: frozenset[str] = frozenset({">&", "<&"})


#: Matches a `-m`/`--message`/`-F`/`--file` flag immediately followed by its
#: VALUE, so the value can be excluded from a command scan. Three value shapes,
#: tried in order (DOTALL so `.` spans newlines, needed for the heredoc
#: alternative's body):
#:   1. The canonical heredoc-embedded message idiom: -m "$(cat <<'EOF' … EOF)"
#:      (leading whitespace before the closing delimiter is tolerated — messages
#:      are often re-indented). Any delimiter word, quoted or not, as bash
#:      allows; whether the value is inert is `value_can_substitute`'s call.
#:   2. A single- or double-quoted string (may span literal newlines). Bash
#:      ends a single-quoted string at the next `'`: a backslash is literal
#:      there, so `-m 'x\' ; git reset --hard` leaves the reset running.
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
    r"|'[^']*'"
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


def shell_word_spans(text: str) -> list[tuple[int, int]]:
    """:func:`iter_shell_words` as ``(start, end)`` offsets into ``text``.

    Ends at the same point that function does: at the first word whose extent
    a substitution or an unterminated quote hides. Every span returned is
    exact; nothing after the cut is guessed at.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    length = len(text)
    while True:
        while index < length and text[index] in _WORD_BREAK_CHARS:
            index += 1
        if index >= length:
            return spans
        start = index
        while index < length and text[index] not in _WORD_BREAK_CHARS:
            end = _quoted_span_end(text, index)
            if end is None:
                return spans
            index = end
        spans.append((start, index))


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
    group or an unterminated quote -- because a caller
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
        elif word.startswith(_ANSI_C_OPEN, index):
            # `$'...'` is quote removal plus fixed escapes, so it resolves
            # exactly (`\n` is a newline, a command separator).
            ansi_c = ansi_c_string(word, index + len(_ANSI_C_OPEN))
            if ansi_c is None:
                return None
            out.append(ansi_c[0])
            index = ansi_c[1]
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


@dataclass(frozen=True, slots=True)
class CommandWrapper:
    """A command that RUNS another command, and what to skip to reach it.

    Attributes:
        value_flags: Flags whose following word is a value, not the command.
        positional_operands: Positional words consumed before the wrapped
            command starts. ``timeout``'s DURATION is the only one shipped.
            Option parsing stops at the last of them, so the word after it is
            the command whatever it looks like.
        lone_dash_is_flag: ``env -`` is ``env -i``, so a lone ``-`` is a flag.
    """

    value_flags: frozenset[str]
    positional_operands: int = 0
    lone_dash_is_flag: bool = False


#: Wrappers whose job is to run the command after them. One table, because two
#: guards reading two copies came to disagree about ``env``: one peeled it, the
#: other whitelisted it, and the same command was judged under two names. The
#: pipe whitelist must stay disjoint from these keys, which
#: ``scripts/qa/declared-invariant-pairs.yaml`` enforces.
COMMAND_WRAPPERS: Final[dict[str, CommandWrapper]] = {
    "watch": CommandWrapper(value_flags=frozenset({"-n", "--interval"})),
    "timeout": CommandWrapper(
        value_flags=frozenset({"-s", "--signal", "-k", "--kill-after"}),
        positional_operands=1,
    ),
    "nohup": CommandWrapper(value_flags=frozenset()),
    "sudo": CommandWrapper(value_flags=frozenset({"-u", "-g", "-p"})),
    "env": CommandWrapper(
        value_flags=frozenset({"-u", "--unset", "-C", "--chdir"}), lone_dash_is_flag=True
    ),
    "nice": CommandWrapper(value_flags=frozenset({"-n", "--adjustment"})),
    "stdbuf": CommandWrapper(value_flags=frozenset({"-i", "-o", "-e"})),
    "command": CommandWrapper(value_flags=frozenset()),
}

#: A flag starts with this, except the two spellings below that are operands.
FLAG_PREFIX: Final[str] = "-"
LONE_DASH: Final[str] = "-"
END_OF_OPTIONS: Final[str] = "--"


def peel_command_wrappers(argv: Sequence[str]) -> tuple[tuple[str, ...], int]:
    """Skip the wrappers at the front of ``argv`` to reach the command they run.

    ``timeout -s KILL 60 nice -n 5 pytest`` runs ``pytest``. A guard that judged
    the first word would judge ``timeout``, and a guard that judged every word
    would mistake ``KILL`` for a command. Peeling uses each wrapper's own flag
    grammar, so a value flag takes its value with it and a positional operand
    is consumed exactly as the wrapper consumes it.

    Args:
        argv: The words of ONE command, already split. Environment assignments
            are the caller's concern, because whether ``FOO=1`` is an
            assignment or an operand depends on where it sits.

    Returns:
        ``(names, start)``: the wrapper names peeled, in order, and the index of
        the wrapped command's first word. ``start == len(argv)`` means the
        wrappers wrapped nothing.
    """
    names: list[str] = []
    index = 0
    while index < len(argv):
        name = command_word(argv[index])
        wrapper = COMMAND_WRAPPERS.get(name)
        if wrapper is None:
            break
        names.append(name)
        index += 1
        positionals = wrapper.positional_operands
        options_ended = False
        while index < len(argv):
            argument = argv[index]
            if argument == END_OF_OPTIONS and not options_ended:
                # ``env -- pytest`` runs pytest: ``--`` ends the wrapper's
                # options and is never the wrapped command.
                options_ended = True
                index += 1
                continue
            is_flag = not options_ended and (
                (argument.startswith(FLAG_PREFIX) and argument != LONE_DASH)
                or (argument == LONE_DASH and wrapper.lone_dash_is_flag)
            )
            if is_flag:
                index += 1
                if _takes_next_word(argument, wrapper.value_flags) and index < len(argv):
                    index += 1
                continue
            if positionals > 0:
                index += 1
                positionals -= 1
                if positionals == 0:
                    break
                continue
            break
    return tuple(names), index


def _takes_next_word(flag: str, value_flags: frozenset[str]) -> bool:
    """Whether a wrapper flag consumes the next word: a value flag, or a cluster ending in one.

    ``env -iu HOME`` is ``-i -u HOME``. A value flag with its value attached
    (``-n5``, ``-iCdir``) takes nothing more.
    """
    if flag in value_flags:
        return True
    if flag.startswith(END_OF_OPTIONS) or len(flag) <= len(FLAG_PREFIX) + 1:
        return False
    for position, letter in enumerate(flag[1:], start=1):
        if FLAG_PREFIX + letter in value_flags:
            return position == len(flag) - 1
    return False


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


#: Command heads that never EXECUTE their arguments, so a guarded command named
#: in one is text rather than a command (Plan 00408 Task 3.3). `echo 'git merge
#: x'` and `bash -c 'git merge x'` are structurally identical, so only knowing
#: the head separates them.
#:
#: An ALLOWLIST, for the reason `DATA_SINKS` is one: a missing entry costs a
#: false positive, a wrong entry costs a guard. `echo -e` and `printf %b` only
#: decode escapes into OUTPUT, and `:`/`true` discard their arguments; what is
#: left -- expansion, `printf -v`, where the output goes -- is refused by
#: :func:`is_wholly_inert_command` rather than by this list.
INERT_COMMAND_HEADS: frozenset[str] = frozenset({"echo", "printf", ":", "true"})

#: A bare head: bash's blanks (space and tab ONLY, not Python's whitespace),
#: the literal name, then a blank. Quoting, an escape, a path, a wrapper or an
#: assignment prefix before the name all fail to match.
_INERT_HEAD_PATTERN = re.compile(
    r"[ \t]*(" + "|".join(re.escape(head) for head in sorted(INERT_COMMAND_HEADS)) + r")[ \t]"
)

_PRINTF_HEAD = "printf"
_OPTION_PREFIX = "-"
_INLINE_BLANKS = " \t"
_LINE_BREAKS = "\n\r"

#: Unquoted characters that make a command more than one simple command, or
#: make an argument something bash computes rather than reads: control
#: operators, grouping, redirection, every expansion, and history expansion.
_UNQUOTED_REFUSED = frozenset(";&|()<>{}`$~*?[!")

#: The same inside double quotes, where only these still act.
_DOUBLE_QUOTED_REFUSED = frozenset("$`!")


def is_wholly_inert_command(command: str) -> bool:
    """Whether ``command`` is ONE bare inert head that nothing can make run.

    True only when every one of these holds:

    * the whole text is a single simple command: no control operator, pipe,
      `&`, grouping, line break or redirection (so no heredoc) outside quotes,
      and no line break anywhere;
    * it opens with spaces or tabs, then an unquoted, unescaped name from
      :data:`INERT_COMMAND_HEADS`, then a space or tab -- so no assignment
      prefix, wrapper, path or quoted name;
    * no argument expands: no `$` or backtick outside single quotes, and no
      unquoted `~`, `{`, `*`, `?` or `[`; nor `!`, which history expansion
      reads;
    * a `printf` takes no option at all, so `-v` in any quoting cannot assign.

    WHOLE-COMMAND on purpose. The per-segment form this replaced was walked
    past through a LATER segment three ways -- an escaped `#`, `$_`, a `trap`
    or `BASH_ALIASES` rebinding -- and every bash feature that reaches across
    segments is another. A command that fails here is judged exactly as it
    would be with no exemption: a false positive, never a bypass.

    Call it on the RAW command, before any blanking, and only to answer "is
    there a command here at all?". A rule that asks what an `echo` itself does
    -- `echo CLAUDE/Plan/0*` expands a glob -- must not use it.

    Args:
        command: The raw Bash command string.

    Returns:
        True when the command is inert as a whole, False otherwise.
    """
    head = _INERT_HEAD_PATTERN.match(command)
    if head is None or any(char in command for char in _LINE_BREAKS):
        return False
    words: list[str] = []
    word: list[str] = []
    quote: str | None = None
    index = head.end()
    length = len(command)
    while index < length:
        char = command[index]
        if quote == _SINGLE_QUOTE:
            if char == _SINGLE_QUOTE:
                quote = None
            else:
                word.append(char)
        elif char == _ESCAPE_CHAR:
            word.append(command[index + 1 : index + 2])
            index += 2
            continue
        elif quote == _DOUBLE_QUOTE:
            if char in _DOUBLE_QUOTED_REFUSED:
                return False
            if char == _DOUBLE_QUOTE:
                quote = None
            else:
                word.append(char)
        elif char in (_SINGLE_QUOTE, _DOUBLE_QUOTE):
            quote = char
        elif char in _INLINE_BLANKS:
            words.append("".join(word))
            word = []
        elif char in _UNQUOTED_REFUSED:
            return False
        else:
            word.append(char)
        index += 1
    words.append("".join(word))
    arguments = [argument for argument in words if argument]
    if quote is not None or not arguments:
        return False
    return not (head.group(1) == _PRINTF_HEAD and arguments[0].startswith(_OPTION_PREFIX))


def strip_quoted_heredoc_bodies(command: str, *, text_readers_only: bool = False) -> str:
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
        text_readers_only: Blank a body only where every command it reaches
            reads it as TEXT (:data:`TEXT_READING_SINKS`, or a ``git
            commit``/``git tag`` taking its message from stdin), for a caller
            whose question is whether anything opens the body's words as
            paths rather than whether anything runs them. Narrower than the
            default: it blanks nothing the default keeps.

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
    fds_may_run = _FD_PROCESS_PATTERN.search(command) is not None
    pieces: list[str] = []
    copied_to = 0
    for heredoc in _quoted_heredocs(command):
        # Three questions, because each was separately a real hole: who
        # RECEIVES the body, what it is PIPED ON to, and whether the whole
        # command sits in a SUBSTITUTION whose output lands in command
        # position. Any one of them failing keeps the body. What an earlier
        # statement may have rebound (an alias, a function, PATH) is not asked:
        # a careless agent does not do that (Plan 00483 A2).
        if not _receiver_is_data_sink(
            command, heredoc, depth_tracker, newline_tracker, fds_may_run, text_readers_only
        ):
            continue
        if not _downstream_is_all_data_sinks(
            _opener_tail(command, heredoc), fds_may_run, text_readers_only
        ):
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
    heredoc: Heredoc,
    depth_tracker: _SubstitutionDepthTracker,
    newline_tracker: _LastNewlineTracker,
    fds_may_run: bool,
    text_readers_only: bool = False,
) -> bool:
    """Does the command feeding ``heredoc`` only READ it?

    Its words on both sides of the operator count: ``cat <<'EOF' > >(bash)``
    names its executor after it (:func:`_stage_is_inert_sink`).

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
    opener_start = heredoc.operator.start
    if depth_tracker.inside_substitution_at(opener_start):
        return False
    segment = _receiving_segment(command, opener_start, newline_tracker)
    if _SUBSTITUTION_OPENER_PATTERN.match(segment.lstrip()):
        return False
    opener_tail = _opener_tail(command, heredoc)
    if text_readers_only and _AMPERSAND_REDIRECT in (
        command[newline_tracker.line_start_before(opener_start) : opener_start] + opener_tail
    ):
        # `_receiving_segment` blanks a `&>` as an fd redirect, which leaves
        # its file target looking like a plain operand: a write that cannot
        # be told apart from a read, so the body keeps being judged.
        return False
    receiving_stage = segment + " " + split_unquoted(opener_tail, ("|", *_PIPELINE_TERMINATORS))[0]
    if not text_readers_only and _segment_command_word(receiving_stage) == _LOOP_END_WORD:
        return _loop_only_prints_its_input(command[:opener_start], receiving_stage, fds_may_run)
    return _stage_is_inert_sink(receiving_stage, fds_may_run, text_readers_only)


#: The word that closes a loop; a heredoc after it is the loop's standard input.
_LOOP_END_WORD = "done"

#: Words that open a loop, whose word list is data and runs nothing itself.
_LOOP_LIST_HEADS: frozenset[str] = frozenset({"for", "select"})

#: What a loop may run for its standard input to stay data: reserved words that
#: only structure it, and commands that read, print, count or compare their
#: input and cannot run it. `eval`, an interpreter, `xargs` and a command word
#: that is itself an expansion (`$line`) are the ways a loop RUNS the lines it
#: reads, and none of them is listed.
_LOOP_DATA_COMMANDS: frozenset[str] = frozenset(
    {
        "read",
        "echo",
        "printf",
        "cat",
        "grep",
        "wc",
        "sort",
        "uniq",
        "cut",
        "tr",
        "basename",
        "dirname",
        "test",
        "[",
        "true",
        "false",
        ":",
        "let",
        "expr",
        "do",
        "done",
        "then",
        "else",
        "fi",
        "esac",
    }
)


def _without_plain_assignments(statement: str) -> str:
    """``statement`` without leading `NAME=value` words that expand nothing
    (`IFS= read -r line` is the command `read`)."""
    while True:
        spans = shell_word_spans(statement)
        if not spans:
            return statement
        word = statement[spans[0][0] : spans[0][1]]
        if not _ASSIGNMENT_WORD.match(word) or "$" in word or "`" in word:
            return statement
        statement = statement[spans[0][1] :]


def _loop_only_prints_its_input(prefix: str, receiving_stage: str, fds_may_run: bool) -> bool:
    """Whether the loop ending at ``receiving_stage`` only READS its heredoc.

    ``while read l; do echo "$l"; done <<'EOF'`` hands the body to `read`, which
    stores it. The lines are data unless a command of the loop runs them, so
    every statement before the opener must be a loop word or a command that
    cannot (:data:`_LOOP_DATA_COMMANDS`); anything else, or anything this reader
    cannot place, keeps the body scanned. The wording is deliberately
    conservative: an unrelated command earlier in the same command withholds
    the exemption, which costs a false positive and never a guard.
    """
    words = _segment_words(receiving_stage)
    if not words or any(opener in receiving_stage for opener in _PROCESS_SUBSTITUTIONS):
        return False
    arguments = _arguments_after_command(words, _LOOP_END_WORD)
    if arguments is None or _inert_redirects(arguments, fds_may_run) != []:
        return False
    for start, end in split_unquoted_spans(prefix, (*_RECEIVER_SEPARATORS, _NEWLINE)):
        statement = prefix[start:end]
        if not statement.strip():
            continue
        if "$(" in statement or "`" in statement:
            # `echo "$($l)"` runs the line it read.
            return False
        first = next(iter(iter_shell_words(statement)), None)
        if first in _LOOP_LIST_HEADS:
            continue
        statement = _without_plain_assignments(strip_reserved_word_prefix(statement))
        if _segment_command_word(statement) not in _LOOP_DATA_COMMANDS:
            return False
    return True


def _stage_is_inert_sink(stage: str, fds_may_run: bool, text_readers_only: bool = False) -> bool:
    """Does ``stage`` run a :data:`DATA_SINKS` command whose every argument
    only reads the body (Plan 00466 N101 round 10, S1)?

    An allowlist in both halves: the command must be a listed sink, and each
    word must be one of the shapes that sink is known to take without
    executing anything.

    A word the reader cannot resolve (``"$OUT"``) is judged by where it sits
    (round 11, minor F). As a file the sink writes, a ``git -C`` directory
    or an option's value it hands the body to nothing, so only the
    receiver's identity decides. Where it could be an OPTION of a sink with
    an allowlist, or an fd a redirect duplicates, it is not inert.

    Two things make an unresolved word unknown wherever it sits (round 12).
    Unquoted, bash may split it into several words, any of which may be an
    option (MAJOR 1). As a file the sink writes, it may be ``/dev/fd/N`` for
    a process the command opened an fd on, when ``fds_may_run`` (N213).

    ``text_readers_only`` (Plan 00474 N256) narrows the answer to a command
    that reads the body as TEXT: its word is in :data:`TEXT_READING_SINKS`,
    or it is a ``git commit``/``git tag`` taking its message from stdin and no
    pathspec; and the stage carries no substitution at all.
    """
    word = _segment_command_word(stage)
    if word == _GH_COMMAND and not text_readers_only:
        return _gh_reads_body_as_data(stage, fds_may_run)
    if word is None or word not in DATA_SINKS:
        return False
    if text_readers_only and (
        (word not in TEXT_READING_SINKS and word != "git")
        or any(marker in stage for marker in _REROUTING_MARKERS)
    ):
        return False
    if any(opener in stage for opener in _PROCESS_SUBSTITUTIONS):
        return False
    words = _segment_words(stage)
    if not words:
        return False
    arguments = _arguments_after_command(words, word)
    if arguments is None:
        return False
    remaining = _inert_redirects(arguments, fds_may_run)
    if remaining is None:
        return False
    if text_readers_only and _stage_writes_a_file(word, words, remaining):
        return False
    if word == "git":
        if text_readers_only:
            return _git_reads_stdin_as_message(remaining)
        return _git_reads_body_as_data(remaining)
    return _sink_arguments_are_inert(word, remaining, fds_may_run)


_GH_COMMAND = "gh"

#: The `gh` command groups that read a heredoc as a body, comment, notes or
#: JSON input (`--body-file -`, `-F -`, `--input -`). Built-in names, which a
#: user alias cannot shadow, so none of them can be a `!` alias running a shell.
_GH_DATA_SUBCOMMANDS: frozenset[str] = frozenset({"pr", "issue", "release", "gist", "api"})


def _gh_reads_body_as_data(stage: str, fds_may_run: bool) -> bool:
    """Whether ``stage`` is a `gh` command group that only reads its stdin."""
    if any(opener in stage for opener in _PROCESS_SUBSTITUTIONS):
        return False
    words = _segment_words(stage)
    arguments = None if not words else _arguments_after_command(words, _GH_COMMAND)
    remaining = None if arguments is None else _inert_redirects(arguments, fds_may_run)
    if not remaining:
        return False
    return remaining[0].value in _GH_DATA_SUBCOMMANDS


def _stage_writes_a_file(command: str, words: list[_Word], remaining: list[_Word]) -> bool:
    """Does a text reader's stage write what it reads to a file?

    A body written to a file is not text that dies with the command: it is
    authored content (``cat > run.sh <<'EOF'``) that a later command runs
    or opens, so the body keeps being judged. ``/dev/null`` and a duplicated
    fd write no file. ``words`` is the whole stage, so a redirect before the
    command word counts; ``remaining`` is the arguments without redirects,
    where ``tee`` names its files and ``sort`` its ``-o`` output."""
    index = 0
    while index < len(words):
        match = _REDIRECT_WORD_PATTERN.fullmatch(words[index].raw)
        index += 1
        if match is None:
            continue
        rest = match.group("rest")
        if rest:
            target = resolve_shell_word(rest)
        else:
            target = words[index].value if index < len(words) else None
            index += 1
        operator = match.group("op")
        if operator in _READ_OPERATORS:
            continue
        if operator in _DUPLICATE_OPERATORS and target is not None:
            if target.isdigit() or target == "-":
                continue
        if target not in _INERT_DEVICES:
            return True
    arguments = [word.value for word in remaining]
    if command == "tee":
        return any(
            value is None or not value.startswith("-") or value == "-" for value in arguments
        )
    if command == "sort":
        return any(
            value is None
            or value.startswith("--output")
            or (not value.startswith("--") and value.startswith("-") and "o" in value)
            for value in arguments
        )
    return False


def _may_split(raw: str) -> bool:
    """Could bash split or glob ``raw`` into several words? True when an
    expansion or a glob character sits outside quotes."""
    quote = ""
    index = 0
    while index < len(raw):
        character = raw[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if character == quote:
                quote = ""
        elif character in "'\"":
            quote = character
        elif character in _SPLITTING_CHARACTERS:
            return True
        index += 1
    return False


def _segment_words(segment: str) -> list[_Word] | None:
    """Every word of ``segment`` as written and after quote removal
    (``None`` where an expansion leaves it unresolved); None when a word's
    extent itself is unknown. Leading grouping punctuation is dropped, as
    :func:`_resolved_segment_words` drops it."""
    words: list[_Word] = []
    for raw in iter_shell_words(strip_reserved_word_prefix(segment)):
        if raw is None:
            return None
        if not words:
            raw = raw.lstrip("(") if raw.strip("({") else ""
            if not raw:
                continue
        words.append(_Word(raw, resolve_shell_word(raw)))
    return words


def _arguments_after_command(words: list[_Word], command: str) -> list[_Word] | None:
    """The words after the one naming ``command`` (past any wrapper). Every
    word up to it resolved, or :func:`_segment_command_word` named nothing."""
    for index, candidate in enumerate(words):
        if candidate.value is not None and candidate.value.rsplit("/", 1)[-1] == command:
            return words[index + 1 :]
    return None


def _inert_redirects(arguments: list[_Word], fds_may_run: bool) -> list[_Word] | None:
    """``arguments`` without their redirects, or None if one could hand the
    body to something that runs it. An operator is read as written, so a
    quoted ``'>'`` is an argument, as it is to bash. A redirect target is
    never split (bash refuses an ambiguous one), so only ``fds_may_run``
    makes an unresolved one unknown."""
    remaining: list[_Word] = []
    index = 0
    while index < len(arguments):
        match = _REDIRECT_WORD_PATTERN.fullmatch(arguments[index].raw)
        index += 1
        if match is None:
            remaining.append(arguments[index - 1])
            continue
        rest = match.group("rest")
        if rest:
            target = resolve_shell_word(rest)
        else:
            if index >= len(arguments):
                return None
            target = arguments[index].value
            index += 1
        operator = match.group("op")
        if operator in _READ_OPERATORS:
            continue
        if operator in _DUPLICATE_OPERATORS:
            if target is None:
                return None
            if target.isdigit() or target == "-":
                if target not in _INERT_FD_TARGETS:
                    return None
                continue
        if target is None:
            if fds_may_run:
                return None
            continue
        if not _is_inert_write_target(target):
            return None
    return remaining


def _sink_arguments_are_inert(command: str, arguments: list[_Word], fds_may_run: bool) -> bool:
    allowed = _SINK_OPTIONS.get(command)
    value_options = _SINK_VALUE_OPTIONS.get(command, frozenset())
    output_options = _SINK_OUTPUT_OPTIONS.get(command, frozenset())
    index = 0
    while index < len(arguments):
        word = arguments[index]
        argument = word.value
        index += 1
        if argument is None:
            # Could expand to an option: inert only for a sink with none
            # that executes, or one whose every operand is a file it writes
            # and cannot be an fd a process reads.
            if allowed is not None and command not in _SINK_OUTPUT_OPERANDS:
                return False
            if command in _SINK_OUTPUT_OPERANDS and (fds_may_run or _may_split(word.raw)):
                return False
            continue
        if argument.startswith("-") and argument not in ("-", "--"):
            name, has_value, value = argument.partition("=")
            if allowed is not None and not _option_is_allowed(name, allowed):
                return False
            if name in value_options and not has_value and len(name) == len("-x"):
                if index >= len(arguments):
                    return False
                next_word = arguments[index]
                next_value = next_word.value
                index += 1
                if next_value is None:
                    if _may_split(next_word.raw):
                        return False
                    if fds_may_run and name in output_options:
                        return False
                    continue
                value = next_value
                has_value = "="
            if name[:2] in output_options or name in output_options:
                output = value if has_value else name[2:]
                if not _is_inert_write_target(output):
                    return False
            continue
        if allowed is not None and argument.startswith("+"):
            return False
        if command in _SINK_OUTPUT_OPERANDS and argument != "-":
            if not _is_inert_write_target(argument):
                return False
    return True


def _option_is_allowed(name: str, allowed: frozenset[str]) -> bool:
    """A long option by name; a short cluster (``-rn``) letter by letter,
    where a value-taking letter ends the cluster (``-k2,2``)."""
    if name.startswith("--"):
        return name in allowed
    for letter in name[1:]:
        if f"-{letter}" not in allowed:
            return False
        if f"-{letter}" in _VALUE_LETTERS:
            return True
    return True


#: Short options, across every allowlisted sink, whose value may be glued on.
_VALUE_LETTERS: frozenset[str] = frozenset().union(*_SINK_VALUE_OPTIONS.values())


def _git_reads_body_as_data(arguments: list[_Word]) -> bool:
    """``git`` with only inert global options, running a subcommand that
    reads stdin as data. ``-c``, ``--config-env`` and an alias can each run a
    shell on the body. The ``-C`` directory may be unresolved, but not
    unquoted, where bash may split it into options; the subcommand may
    not."""
    return _git_data_subcommand_index(arguments) is not None


def _git_data_subcommand_index(arguments: list[_Word]) -> int | None:
    """Index of the subcommand in ``arguments`` when only inert global
    options precede it and it is one of :data:`_GIT_DATA_SUBCOMMANDS`."""
    index = 0
    while index < len(arguments):
        argument = arguments[index].value
        if argument == _GIT_DIRECTORY_FLAG:
            if index + 1 < len(arguments) and _may_split(arguments[index + 1].raw):
                return None
            index += 2
            continue
        if argument in _GIT_INERT_GLOBAL_FLAGS:
            index += 1
            continue
        return index if argument in _GIT_DATA_SUBCOMMANDS else None
    return None


def _git_reads_stdin_as_message(arguments: list[_Word]) -> bool:
    """``git commit``/``git tag`` taking its message from stdin (``-F -``,
    ``-F-``, ``--file=-``) and reading no pathspec from it. A word that
    expansion leaves unresolved could be any option, so it is not a message
    reader."""
    subcommand_index = _git_data_subcommand_index(arguments)
    if (
        subcommand_index is None
        or arguments[subcommand_index].value not in _GIT_MESSAGE_SUBCOMMANDS
    ):
        return False
    values = [word.value for word in arguments[subcommand_index + 1 :]]
    if any(value is None for value in values):
        return False
    options = [value for value in values if value is not None]
    if any(option.startswith(_GIT_PATHSPEC_OPTION_PREFIX) for option in options):
        return False
    return any(
        option in _GIT_STDIN_MESSAGE_WORDS
        or (option in _GIT_MESSAGE_FILE_FLAGS and following == "-")
        for option, following in zip(options, [*options[1:], None], strict=True)
    )


def _is_inert_write_target(target: str) -> bool:
    """Is ``target`` a file the sink writes that nothing executes from?

    A regular file, a directory (the write fails) or a path that does not
    exist yet (the write creates a regular file) is inert, as are
    ``/dev/null``, ``/dev/stdout`` and ``/dev/stderr``. Any other device or
    ``/proc`` path, a FIFO, a socket, a word that resolves to nothing, or a
    path ``stat`` cannot judge is not. A word with an expansion never reaches
    here: its caller judges it by whether it may split and whether the
    command opens an fd on a process (Plan 00466 N213). A relative path is
    judged from the event's cwd
    (:func:`bind_event_cwd`), or the process's own outside a dispatch.
    """
    resolved = resolve_shell_word(target)
    if resolved is None or not resolved:
        return False
    if resolved in _INERT_DEVICES:
        return True
    if resolved.startswith(_DEVICE_ROOTS):
        return False
    path = Path(resolved).expanduser()
    if not path.is_absolute():
        cwd = _EVENT_CWD.get()
        path = (Path(cwd) if cwd is not None else Path.cwd()) / path
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return stat.S_ISREG(mode) or stat.S_ISDIR(mode)


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


def _downstream_is_all_data_sinks(
    opener_tail: str, fds_may_run: bool, text_readers_only: bool = False
) -> bool:
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
        fds_may_run: Whether the whole command opens an fd on a process.

    Returns:
        True when there are no downstream stages, or every one of them names a
        recognised data sink. An unrecognised or unnameable stage returns
        False, which withholds the exemption and scans the body.
    """
    pipeline = split_unquoted(opener_tail, _PIPELINE_TERMINATORS)[0]
    return all(
        _stage_is_inert_sink(stage, fds_may_run, text_readers_only)
        for stage in split_unquoted(pipeline, ("|",))[1:]
    )


def is_inert_pipeline_stage(stage: str) -> bool:
    """Is ``stage`` a recognised data sink that only READS its stdin?

    The same allowlist the quoted-heredoc exemption applies to a body's
    receivers. An unrecognised or unnameable stage is not inert. A process
    substitution anywhere in the stage is refused, and fds are assumed able to
    reach a process, so the answer errs towards "may run".

    An ``awk`` stage also counts when :func:`_awk_stage_only_reads` holds
    (Plan 00474 N313).
    """
    return _stage_is_inert_sink(stage, fds_may_run=True) or _awk_stage_only_reads(stage)


#: Program text that lets awk run a command, read a command's output, or write
#: a file: `system`, `getline`, a pipe (`print | "sh"`, `|&`) and a redirect
#: (`print > "f"`). `@` opens gawk's `@include`/`@load`.
_AWK_ESCAPE_MARKERS: tuple[str, ...] = ("system", "getline", "|", ">", "@")


def _awk_stage_only_reads(stage: str) -> bool:
    """Is ``stage`` a bare ``awk`` whose program is ONE single-quoted literal
    that cannot run a command or write a file?

    Conservative on purpose: no option of any kind (`-f` loads a program file,
    `-v` and a `name=value` operand assign variables, `--` hides the next
    word), the program must be the first word and a single-quoted literal with
    no :data:`_AWK_ESCAPE_MARKERS`, and every other word an ordinary file
    operand. A stage carrying a substitution is refused, and redirects are
    judged as for a sink. A refusal costs a false positive, never a bypass.
    """
    if _segment_command_word(stage) != "awk":
        return False
    if any(marker in stage for marker in (*_REROUTING_MARKERS, *_PROCESS_SUBSTITUTIONS)):
        return False
    words = _segment_words(stage)
    if not words:
        return False
    arguments = _arguments_after_command(words, "awk")
    if arguments is None:
        return False
    remaining = _inert_redirects(arguments, fds_may_run=True)
    if not remaining:
        return False
    program, *operands = remaining
    raw = program.raw
    if len(raw) < 2 or raw[0] != "'" or raw[-1] != "'" or "'" in raw[1:-1]:
        return False
    if any(marker in raw for marker in _AWK_ESCAPE_MARKERS):
        return False
    return all(
        operand.value is not None and not operand.value.startswith("-") and "=" not in operand.value
        for operand in operands
    )


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


def heredoc_consumers(command: str, heredocs: Sequence[Heredoc]) -> list[tuple[str | None, ...]]:
    """For each heredoc, the command word of the stage its body feeds, then of
    each stage that output is piped on to; None for a word that names no
    command bash could be sure of (Plan 00466 N101 round 10, S3).

    ``heredocs`` must come in opener order, as ``scan_heredocs`` gives them:
    one newline tracker serves the whole call (Plan 00466 N25).

    Round 12 makes the receiving word None when a top-level :data:`DATA_SINKS`
    stage's arguments may hand the body on (``cat <<'EOF' > >(bash)``): that is
    no sink.
    """
    newline_tracker = _LastNewlineTracker(command)
    depth_tracker = _SubstitutionDepthTracker(command)
    known = known_variables(command)
    fds_may_run = _FD_PROCESS_PATTERN.search(command) is not None
    consumers: list[tuple[str | None, ...]] = []
    for heredoc in heredocs:
        opener_start = heredoc.operator.start
        receiving = _receiving_segment(command, opener_start, newline_tracker)
        # Inside `<(…)` or `>(…)` the stage starts at the opener: the command
        # around it only reads a file name.
        cut = max(receiving.rfind(opener) for opener in _PROCESS_SUBSTITUTIONS)
        if cut >= 0:
            receiving = receiving[cut + len(_PROCESS_SUBSTITUTIONS[0]) :]
        tail = _opener_tail(command, heredoc)
        pipeline = split_unquoted(tail, _PIPELINE_TERMINATORS)[0]
        downstream = split_unquoted(pipeline, ("|",))[1:]
        words = [_consumer_word(stage, known) for stage in (receiving, *downstream)]
        receiving_stage = receiving + " " + split_unquoted(pipeline, ("|",))[0]
        if (
            words[0] in DATA_SINKS
            and not depth_tracker.inside_substitution_at(opener_start)
            and not _stage_is_inert_sink(receiving_stage, fds_may_run)
        ):
            words[0] = None
        consumers.append(tuple(words))
    return consumers


def body_may_run(consumers: Sequence[str | None]) -> bool:
    """Do these :func:`heredoc_consumers` words run the body as shell? A
    word nothing names is unknown, and so may (round 12, N212)."""
    return any(word is None or word in SHELL_BODY_RUNNERS for word in consumers)


def _consumer_word(stage: str, known: dict[str, str]) -> str | None:
    """The command ``stage`` runs, or the one its variable is known to name."""
    word = _segment_command_word(stage)
    return word if word is not None else _variable_command_word(stage, known)


def _variable_command_word(stage: str, known: dict[str, str]) -> str | None:
    """The command a stage names through a variable, where the text says
    which (round 11, minor E): a literal basename after a quoted expansion
    (``"$VENV/bin/python"``), ``$SHELL`` or ``$BASH``, or a variable
    :func:`known_variables` pins to a value that does not split
    (``PY=python3; $PY -``). None -- unknown, judged fail closed by every
    caller -- when nothing says (round 12, N212): ``$0``, ``${X:-…}``,
    ``PY='bash -e'``, ``read PY``, or two assignments to one name."""
    match = _VARIABLE_COMMAND_PATTERN.match(strip_reserved_word_prefix(stage).lstrip("({ \t"))
    if match is None:
        return None
    name = match.group("braced") or match.group("bare")
    value = known.get(name)
    plain = value is not None and not any(char in _UNPLAIN_VALUE_CHARACTERS for char in value)
    tail = match.group("tail")
    if tail:
        basename = tail.rsplit("/", 1)[-1]
        if "/" not in tail or not basename:
            return None
        return basename if match.group("quote") or plain else None
    if name in _SHELL_VARIABLES:
        return _SHELL_VARIABLES[name]
    if value is None or not plain:
        return None
    return value.rsplit("/", 1)[-1] or None


def known_variables(command: str) -> dict[str, str]:
    """Each variable ``command`` sets to a literal by a plain top-level
    statement, with its value (Plan 00466 N101 round 12, N212 and N215).

    Plain means a statement of assignments only, on its own between ``;`` or
    newlines (or leading an ``&&`` chain: an assignment of a literal cannot
    fail, N320), before anything opens a group, a substitution or a compound
    command, so it surely runs in this shell. The name is assigned nowhere
    else in the call and read nowhere before it, and it is no variable bash
    sets or a helper program reads. No variable is known at all where the
    call may write one through a name it does not spell: ``read``,
    ``mapfile``, ``declare -n``, ``printf -v``, ``eval``, ``source``, a
    ``for`` loop, arithmetic, ``${NAME:=…}``, ``IFS``, or a command word it
    computes. A value may still hold blanks: a caller using it unquoted must
    refuse it.
    """
    scan = scan_heredocs(command)
    if scan.stopped_at is not None:
        return {}
    text = _blank_quoted_bodies(command, scan)
    if _COMPUTED_WRITE_PATTERN.search(text):
        return {}
    unquoted = _collapse_blank_runs(_QUOTING_CHARACTERS.sub("", text))
    if _NAME_WRITER_PATTERN.search(unquoted) or _PRINTF_TARGET_PATTERN.search(unquoted):
        return {}
    assignments = Counter(match.group(1) for match in _ASSIGNED_NAME.finditer(text))
    first_reference: dict[str, int] = {}
    for match in _REFERENCED_NAME.finditer(text):
        first_reference.setdefault(match.group(1), match.start())
    known: dict[str, str] = {}
    for name, (start, value) in _leading_assignments(text).items():
        if _is_special_variable(name) or assignments[name] != 1:
            continue
        if first_reference.get(name, len(text)) < start:
            continue
        known[name] = value
    for match in _COMPUTED_COMMAND_PATTERN.finditer(unquoted):
        command_value = known.get(match.group("name") or "")
        if command_value is None or command_value.rsplit("/", 1)[-1] in _NAME_WRITERS:
            return {}
    return known


def _collapse_blank_runs(text: str) -> str:
    """``text`` with each run of blanks reduced to one: a newline where the
    run holds one, else a space. :data:`_COMMAND_POSITION` opens with a
    separator and then ``\\s*``, so on a long run every newline started a
    scan to its end (Plan 00466 N101 round 13: 32,000 newlines took 30 s)."""
    return _BLANK_RUN.sub(lambda match: _NEWLINE if _NEWLINE in match.group() else " ", text)


_BLANK_RUN = re.compile(r"\s+")


def _leading_assignments(text: str) -> dict[str, tuple[int, str]]:
    """The literal assignments of the statements before the first one that
    opens a group, a substitution or a compound command: the name, the
    statement's offset and the value after quote removal."""
    found: dict[str, tuple[int, str]] = {}
    for start, end in split_unquoted_spans(text, (";", _NEWLINE)):
        statement = text[start:end]
        if not statement.strip():
            continue
        words = list(iter_shell_words(statement))
        if (
            len(split_unquoted(statement, _NESTING_CHARACTERS)) > 1
            or None in words
            or words[0] in _RESERVED_WORDS
        ):
            break
        # A literal assignment cannot fail, so `A=1 && B=2 && cmd` runs every
        # part as `;` would. Only the assignments that LEAD the chain count: a
        # part after a command runs only if that command succeeded. `||` is no
        # `&&`, so it stays inside one part and the part is skipped (N320).
        for part_start, part_end in split_unquoted_spans(statement, ("&&",)):
            part = statement[part_start:part_end]
            if len(split_unquoted(_blank_harmless_redirects(part), _RECEIVER_SEPARATORS)) > 1:
                break
            matches = [
                _ASSIGNMENT_WORD.match(word) for word in iter_shell_words(part) if word is not None
            ]
            if not matches or not all(matches):
                break
            for match in matches:
                assert match is not None  # all() above
                value = resolve_shell_word(match.group("value"))
                if value is not None:
                    found.setdefault(match.group("name"), (start + part_start, value))
    return found


def substitute_known_variables(token: str, known: dict[str, str]) -> str | None:
    """``token`` with each ``$NAME`` or ``${NAME}`` replaced by its value in
    ``known``, or None when a name is not known, its value would split or
    glob, or another expansion remains (Plan 00466 N101 round 12, N215)."""
    parts: list[str] = []
    copied_to = 0
    for match in _VARIABLE_REFERENCE.finditer(token):
        value = known.get(match.group("braced") or match.group("bare"))
        if value is None or any(char in _UNPLAIN_VALUE_CHARACTERS for char in value):
            return None
        parts.extend([token[copied_to : match.start()], value])
        copied_to = match.end()
    parts.append(token[copied_to:])
    if any("$" in literal or _BACKTICK in literal for literal in parts[0::2]):
        return None
    return "".join(parts)


def _is_special_variable(name: str) -> bool:
    return name in _SPECIAL_VARIABLES or name.startswith(_SPECIAL_VARIABLE_PREFIXES)


def _blank_quoted_bodies(command: str, scan: HeredocScan) -> str:
    """``command`` with each terminated quoted heredoc's body and closer
    replaced by blanks, offsets kept: bash reads none of it as shell."""
    return _blank_bodies(command, [h for h in scan.heredocs if h.operator.quoted])


def _blank_bodies(command: str, heredocs: Sequence[Heredoc]) -> str:
    """``command`` with the body and closer of each terminated heredoc of
    ``heredocs`` replaced by blanks, offsets kept."""
    pieces: list[str] = []
    copied_to = 0
    bodies = sorted(
        (h for h in heredocs if h.terminated),
        key=lambda heredoc: heredoc.body_start,
    )
    for heredoc in bodies:
        if heredoc.body_start < copied_to:
            continue
        pieces.append(command[copied_to : heredoc.body_start])
        pieces.append(" " * (heredoc.closer_end - heredoc.body_start))
        copied_to = heredoc.closer_end
    pieces.append(command[copied_to:])
    return "".join(pieces)


def _blank_harmless_redirects(text: str) -> str:
    """``text`` with each redirect that writes no file blanked, offsets kept."""
    return _HARMLESS_REDIRECT_PATTERN.sub(lambda match: " " * len(match.group()), text)


def mask_quoted(text: str, keep_double: bool) -> str:
    """``text`` with what quoting makes literal blanked, offsets kept: the
    inside of ``'…'`` and ``$'…'`` and an escaped character, and the inside
    of ``"…"`` too unless ``keep_double`` (bash expands parameters there,
    but never globs)."""
    out = list(text)
    index = 0
    in_double = False
    while index < len(text):
        char = text[index]
        if char == _ESCAPE_CHAR:
            end = min(index + 2, len(text))
            out[index:end] = " " * (end - index)
            index = end
            continue
        if char == _DOUBLE_QUOTE:
            in_double = not in_double
        elif in_double:
            if not keep_double:
                out[index] = " "
        elif text.startswith(_ANSI_C_OPEN, index):
            ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
            end = len(text) if ansi_c is None else ansi_c[1]
            out[index + len(_ANSI_C_OPEN) : end] = " " * (end - index - len(_ANSI_C_OPEN))
            index = end
            continue
        elif char == _SINGLE_QUOTE:
            close = text.find(_SINGLE_QUOTE, index + 1)
            end = len(text) if close < 0 else close
            out[index + 1 : end] = " " * (end - index - 1)
            index = end + 1
            continue
        index += 1
    return "".join(out)


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
    chain = segment_command_chain(strip_reserved_word_prefix(segment))
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
    return [text[start:end] for start, end in split_unquoted_spans(text, separators)]


def split_unquoted_spans(text: str, separators: Sequence[str]) -> list[tuple[int, int]]:
    """:func:`split_unquoted` as ``(start, end)`` offsets into ``text``, for a
    caller that must map a segment back to where it sits."""
    spans: list[tuple[int, int]] = []
    start = 0
    in_single = False
    in_double = False
    in_comment = False
    index = 0
    # A separator can only start at one of these characters, so the per-
    # character scan of `separators` is skipped everywhere else (N265). An
    # empty separator matches anywhere and keeps the full scan.
    first_chars = frozenset(sep[0] for sep in separators if sep)
    all_nonempty = all(separators)

    while index < len(text):
        char = text[index]
        unquoted = not in_single and not in_double
        may_separate = char in first_chars or not all_nonempty

        # A comment runs to the newline and its quotes are characters, but its
        # separators still split: judging comment text as commands is the
        # conservative reading, and a quote in it must not swallow later lines.
        if in_comment or (unquoted and _starts_comment(text, index)):
            in_comment = char != _NEWLINE
            matched = (
                next((sep for sep in separators if text.startswith(sep, index)), None)
                if may_separate
                else None
            )
            if matched is not None:
                spans.append((start, index))
                index += len(matched)
                start = index
                continue
            index += 1
            continue

        # `$$` is the pid; a `$'...'` string ends at its first UNESCAPED quote.
        if unquoted and text.startswith(_PID, index):
            index += len(_PID)
            continue
        if unquoted and text.startswith(_ANSI_C_OPEN, index):
            ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
            index = len(text) if ansi_c is None else ansi_c[1]
            continue

        # Rule 1: inside single quotes a backslash is literal, so escape
        # handling is skipped entirely and only the closing quote matters.
        if char == _ESCAPE_CHAR and not in_single:
            index = min(index + 2, len(text))
            continue

        if char == _SINGLE_QUOTE and not in_double:
            in_single = not in_single
        elif char == _DOUBLE_QUOTE and not in_single:
            in_double = not in_double
        elif not in_single and not in_double and may_separate:
            matched = next((sep for sep in separators if text.startswith(sep, index)), None)
            if matched is not None:
                spans.append((start, index))
                index += len(matched)
                start = index
                continue

        index += 1

    spans.append((start, len(text)))
    return spans


#: How deep substitutions may nest before the text is declared unplaceable.
_MAX_SUBSTITUTION_DEPTH: Final[int] = 32
_OPEN_PAREN = "("
_CLOSE_PAREN = ")"
_BACKTICK = "`"
#: Openers are built from parts: this module's own text is read by the secret
#: guard, which cannot place an unbalanced substitution opener spelled whole.
_COMMAND_SUBSTITUTION_OPEN: Final[str] = "$" + _OPEN_PAREN
_PROCESS_SUBSTITUTION_OPENS: Final[tuple[str, ...]] = ("<" + _OPEN_PAREN, ">" + _OPEN_PAREN)
_OPENER_WIDTH: Final[int] = 2


class UnplaceableSubstitutionError(Exception):
    """A substitution's extent cannot be known without running the shell."""


def substitution_inner_spans(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` offsets of the command text inside every substitution.

    One span per command substitution, backtick pair and process substitution
    that bash would run, nested ones included, each excluding its delimiters.
    An opener inside single quotes or after a backslash, or a process
    substitution inside double quotes, is literal text and yields no span.
    Quotes inside a span are tracked afresh, so a close paren in a quoted word
    does not end it.

    Raises:
        UnplaceableSubstitutionError: a span cannot be placed with certainty
            (an unterminated quote or substitution, nesting beyond
            :data:`_MAX_SUBSTITUTION_DEPTH`). A caller relaxing anything on the
            strength of these spans must then relax nothing.
    """
    spans: list[tuple[int, int]] = []
    _scan_command_text(text, 0, None, 0, spans)
    return spans


def _scan_command_text(
    text: str, index: int, closer: str | None, depth: int, spans: list[tuple[int, int]]
) -> int:
    """Scan command text from ``index`` to the unquoted ``closer`` (a close
    paren or a backtick) and return its offset; ``closer=None`` scans to the
    end of ``text`` and returns its length. Spans of every substitution met on
    the way are appended to ``spans``."""
    if depth > _MAX_SUBSTITUTION_DEPTH:
        raise UnplaceableSubstitutionError
    length = len(text)
    groups = 0
    while index < length:
        char = text[index]
        if char == _ESCAPE_CHAR:
            index += 2
        elif char == _SINGLE_QUOTE:
            end = text.find(_SINGLE_QUOTE, index + 1)
            if end == -1:
                raise UnplaceableSubstitutionError
            index = end + 1
        elif text.startswith(_ANSI_C_OPEN, index):
            ansi_c = ansi_c_string(text, index + len(_ANSI_C_OPEN))
            if ansi_c is None:
                raise UnplaceableSubstitutionError
            index = ansi_c[1]
        elif char == _DOUBLE_QUOTE:
            index = _scan_double_quoted(text, index, depth, spans)
        elif char == _BACKTICK:
            if closer == _BACKTICK:
                return index
            index = _record_span(text, index + 1, _BACKTICK, depth, spans)
        elif text.startswith((_COMMAND_SUBSTITUTION_OPEN, *_PROCESS_SUBSTITUTION_OPENS), index):
            index = _record_span(text, index + _OPENER_WIDTH, _CLOSE_PAREN, depth, spans)
        elif closer == _CLOSE_PAREN and char == _OPEN_PAREN:
            groups += 1
            index += 1
        elif closer == _CLOSE_PAREN and char == _CLOSE_PAREN:
            if groups == 0:
                return index
            groups -= 1
            index += 1
        else:
            index += 1
    if closer is not None:
        raise UnplaceableSubstitutionError
    return length


def _record_span(
    text: str, start: int, closer: str, depth: int, spans: list[tuple[int, int]]
) -> int:
    """Scan one substitution body from ``start``, record its span, and return
    the offset past its closer."""
    end = _scan_command_text(text, start, closer, depth + 1, spans)
    spans.append((start, end))
    return end + 1


def _scan_double_quoted(text: str, index: int, depth: int, spans: list[tuple[int, int]]) -> int:
    """Offset past the double-quoted string opening at ``index``; a command or
    backtick substitution inside it is live and recorded."""
    cursor = index + 1
    while cursor < len(text):
        char = text[cursor]
        if char == _ESCAPE_CHAR:
            cursor += 2
        elif char == _DOUBLE_QUOTE:
            return cursor + 1
        elif char == _BACKTICK:
            cursor = _record_span(text, cursor + 1, _BACKTICK, depth, spans)
        elif text.startswith(_COMMAND_SUBSTITUTION_OPEN, cursor):
            cursor = _record_span(text, cursor + _OPENER_WIDTH, _CLOSE_PAREN, depth, spans)
        else:
            cursor += 1
    raise UnplaceableSubstitutionError


def _starts_comment(text: str, index: int) -> bool:
    """Is the unquoted character at ``index`` a ``#`` that starts a word?"""
    return text[index] == "#" and (index == 0 or text[index - 1] in COMMENT_PRECEDERS)
