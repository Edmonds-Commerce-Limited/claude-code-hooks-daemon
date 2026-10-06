"""UpgradeApprovalGuardHandler — an agent cannot grant its own upgrade approval.

Plan 00376, review finding MAJOR 4. The pre-deploy upgrade gate lets the
project OWNER approve a breaking upgrade via a one-shot marker file, written
by ``hooks-daemon approve-upgrade <version> --from <previous>`` — a command
that requires an interactive TTY and a typed confirmation phrase, so an agent
cannot answer the prompt itself. That is the control; this handler closes the
three ways an agent could still reach the same outcome without the human ever
answering it:

1. **Running the approval command itself** — ``approve-upgrade`` as a
   subcommand of the daemon CLI (`bin/hooks-daemon`, a path-qualified copy,
   or the module-invocation spelling — `python -m` plus the dotted
   `claude_code_hooks_daemon.daemon.cli` module path), or the venv-free
   standalone gate's own ``approve`` subcommand
   (``upgrade_gate_standalone.py approve``). Both write the exact marker the
   TTY prompt exists to gate.
2. **Writing the marker directly** — ``touch``/redirect/``tee``/``cp``/``mv``/
   ``mkdir`` reaching a path under an ``upgrade-approvals/`` directory by any
   Bash route, or authoring it with ``Write``/``Edit``/``NotebookEdit``.
3. **Impersonating Layer 1 or steering the upgrade** — assigning, exporting
   or ``env``-setting ``HOOKS_DAEMON_UPGRADE_HANDOFF``, the path of the
   one-shot handoff file ``scripts/upgrade.sh`` writes for
   ``scripts/upgrade_version.sh`` (Layer 2 believes that file only when its
   parent wrote it; a command that sets the variable and runs Layer 2 IS that
   parent); or, on a command that runs the upgrade, setting a variable that
   picks its interpreter, venv, tools, forwarded flags or code
   (``_UPGRADE_STEERING_VARS``) by any spelling -- not only ``NAME=`` but
   ``read``/``printf -v``/an indirect name, an ``x``-flagged ``declare``, a
   computed ``export`` operand, ``set -a``, ``eval`` or sourcing another file
   -- or exporting a shell function. The upgrade
   is recognised by what it is, not its file name: an entry point by name,
   Layer 1's own ``--skip-reading-confirmation`` flag, a script whose content
   carries the handoff variable (every copy of Layer 1 and Layer 2 does), or
   a script that cannot be read (``bash "$tmp"``) run with the upgrade's
   arguments (``--project-root``, or the daemon clone as Layer 2's operand).
   A program held in a variable (``$PY -m pytest``, ``$PY scripts/x.py``) is
   judged by the module or script it is given; only an unresolved one
   (``$PY -c``, ``$PY "$SCRIPT"``, the daemon's own package) counts.
4. **Forging the installer's own version stamp** — writing a venv's
   ``.daemon-version`` file (under ``untracked/venv*/``) by any of the same
   routes as (2), which would make the gate believe the target is already
   installed.
5. **Moving the daemon clone by hand** — ``checkout``/``switch``/``pull``/
   ``merge``/``reset`` (and the other ref-moving subcommands) on
   ``.claude/hooks-daemon``, or writing into its ``.git/`` by any of the
   routes in (2), which installs a version the gate never saw.

Two distinct Rules (Decision B): route 3 is a different failure mode from
1/2/4/5 — steering the gate's control flow, rather than forging or skipping
what it protects — so it gets its own rule_id and its own remedy text.

**Reading is never denied.** ``ls``/``cat``/``stat``/``grep``/``find ...
-print``/``test -f`` over an approvals path or a version stamp, and merely
reading the env var (``echo "$VAR"``, ``grep VAR file``), are all
unaffected — matching only requires the token pattern this handler denies
(an assignment carries ``=``; a read does not).

**Inert-text exemption.** Mentioning ``approve-upgrade`` inside a
``git commit`` message, non-executing ``echo``/``printf`` prose, a ``grep``
search, or a quoted-delimiter heredoc body written to a file must not be
denied — the same house pattern every other Bash-scanning safety handler
uses (`claude_code_hooks_daemon.utils.shell_segmentation.strip_inert_spans`
for git/gh message values and quoted heredoc bodies fed to a data sink; a
per-segment ``grep``/``echo``/``printf`` head check here for the rest, the
same shape `sed_blocker` established). An ``echo``/``printf`` argument that
can genuinely EXECUTE something (a live ``$(...)``/backtick substitution) is
NOT exempt — it is scanned like any other command.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path
from claude_code_hooks_daemon.handlers.utils.bash_file_writes import bash_file_writes
from claude_code_hooks_daemon.install.install_stamp import STAMP_FILENAME
from claude_code_hooks_daemon.install.upgrade_gate import APPROVAL_SUBDIR
from claude_code_hooks_daemon.utils import linear_shlex
from claude_code_hooks_daemon.utils.path_predicates import (
    TextOrReason,
    path_is_dir,
    path_is_file,
    read_text_or_reason,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    command_word,
    split_unquoted,
    strip_inert_spans,
)

#: Decode policy for the one read this handler makes (a patch file
#: `bash_file_writes` follows) — only ASCII path text matters here, so a
#: stray byte cannot raise.
_DECODE_REPLACE: Final[str] = "replace"

# --- item 1: running the approval command itself ---------------------------

#: `bin/hooks-daemon`, a path-qualified copy, or a bare `hooks-daemon`. The
#: negative lookahead stops `hooks-daemon.yaml`/`hooks-daemon-anything` from
#: reading as the CLI binary.
_HOOKS_DAEMON_BIN_RE: Final[str] = r"(?:\S*/)?hooks-daemon(?![\w.-])"
#: The daemon's own package; a module under it may carry an upgrade subcommand.
_DAEMON_PACKAGE: Final[str] = "claude_code_hooks_daemon"
#: `python3 -m` plus the dotted `claude_code_hooks_daemon.daemon.cli` module
#: path — the module-invocation spelling of the same CLI.
_HOOKS_DAEMON_MODULE_RE: Final[str] = (
    r"python3?\s+-m\s+claude_code_hooks_daemon\.daemon\.cli(?![\w.])"
)
#: Either invocation, followed — permissively, any run of option tokens is
#: allowed between (`--project-root <path>`, `--pid-file <path>`, ...) — by
#: the `approve-upgrade` subcommand. Runs within ONE already-segmented stage
#: (see `_SEGMENT_SEPARATORS`), so the option run cannot cross into another
#: command.
_APPROVE_UPGRADE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?:{_HOOKS_DAEMON_BIN_RE}|{_HOOKS_DAEMON_MODULE_RE})(?:\s+\S+)*?\s+approve-upgrade\b"
)
#: The venv-free standalone gate's own `approve` subcommand.
_STANDALONE_APPROVE_RE: Final[re.Pattern[str]] = re.compile(
    r"\bupgrade_gate_standalone\.py\b(?:\s+\S+)*?\s+approve\b"
)

# --- item 3: impersonating Layer 1 via an env var ----------------------------

#: The variable Layer 1 (`scripts/upgrade.sh`) hands Layer 2 its one-shot
#: handoff file in (Plan 00376). Kept here as the single source of truth for
#: THIS handler's pattern; the scripts are shell, not importable.
ENV_VAR_UPGRADE_HANDOFF: Final[str] = "HOOKS_DAEMON_UPGRADE_HANDOFF"
_GUARDED_ENV_VARS: Final[tuple[str, ...]] = (ENV_VAR_UPGRADE_HANDOFF,)
_ENV_VAR_GROUP: Final[str] = "|".join(_GUARDED_ENV_VARS)
#: An ASSIGNMENT (`VAR=...`, `export VAR`, `declare -x VAR`) — never a read
#: (`$VAR`, `${VAR}`), which carries no `=` immediately after the bare name.
_ENV_VAR_ASSIGN_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:{_ENV_VAR_GROUP})=" rf"|\b(?:export|declare\s+-x|typeset\s+-x)\s+(?:{_ENV_VAR_GROUP})\b"
)

#: Variables the upgrade path reads to choose the interpreter, the venv whose
#: stamp is the installed version, the forwarded flags and pass state, the
#: files git lists for detection, the tools and shell code it runs, or where it
#: writes. Denied only on a command that also runs an upgrade: each has
#: ordinary uses elsewhere. The gate itself takes none of them (it runs under
#: `env -i` with fixed tool locations); this keeps an agent off the rest.
_UPGRADE_STEERING_VARS: Final[tuple[str, ...]] = (
    "HOOKS_DAEMON_PYTHON",
    "HOOKS_DAEMON_VENV_PATH",
    "PATH",
    "HOSTNAME",
    "HOME",
    "TMPDIR",
    "HOOKS_DAEMON_CLONE_URL",
    "HOOKS_DAEMON_UPGRADE_BASE_URL",
    "HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION",
    "HOOKS_DAEMON_UPGRADE_SECOND_PASS",
    "UPGRADE_FLAGS",
    "GIT_*",
    "BASH_ENV",
    "ENV",
    "BASH_FUNC_*",
    "SHELLOPTS",
    "BASHOPTS",
    "LD_*",
    "DYLD_*",
    "PYTHON*",
    # Layer 1's own handover to Layer 2: the baselines the config and
    # settings merges diff against.
    "HOOKS_DAEMON_OLD_DEFAULT_*",
    # Where the venv build takes its packages and build backend from, and the
    # interpreter uv would pick (review4 m1). Layer 1 forwards UV_* for the
    # operator's own mirror or cache; an agent must not choose them.
    "UV_INDEX*",
    "UV_DEFAULT_INDEX",
    "UV_EXTRA_INDEX_URL",
    "UV_FIND_LINKS",
    "UV_CONFIG_FILE",
    "UV_PYTHON*",
    # pipx's bin directory is searched for the uv that builds the venv, and what
    # builds the venv decides what code the daemon runs.
    "PIPX_BIN_DIR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
#: A wildcard name part; exported functions travel as `BASH_FUNC_<name>%%`.
_WILDCARD_NAME: Final[str] = r"[A-Za-z0-9_]*(?:%%)?"
_STEERING_GROUP: Final[str] = "|".join(
    re.escape(name).replace(r"\*", _WILDCARD_NAME) for name in _UPGRADE_STEERING_VARS
)
_STEERING_ASSIGN_RE: Final[re.Pattern[str]] = re.compile(
    rf"\b(?:{_STEERING_GROUP})="
    rf"|\b(?:export|declare\s+-x|typeset\s+-x)\s+(?:{_STEERING_GROUP})\b"
    # A function exported to the environment, which shadows a tool by name.
    r"|\bexport\s+-f\b|\b(?:declare|typeset)\s+-(?=[a-z]*f)(?=[a-z]*x)[a-z]+\b"
)
#: A steering NAME anywhere but a read (review4 MAJOR 1): `read -r BASH_ENV`,
#: `printf -v BASH_ENV`, `n=BASH_ENV; export "$n=f"` and `export -- BASH_ENV`
#: all set one with no `NAME=` token. `$NAME` and `${NAME}` only read it.
_STEERING_NAME_RE: Final[re.Pattern[str]] = re.compile(rf"(?<![$\w{{])(?:{_STEERING_GROUP})(?!\w)")
#: Builtins that can put a variable in the environment by a flag.
_DECLARING_HEADS: Final[frozenset[str]] = frozenset({"declare", "typeset", "local"})
#: An `export` operand naming its variable literally, with or without a value.
_LITERAL_EXPORT_OPERAND_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:=.*)?$", re.DOTALL
)
#: The characters a variable name built from expansions can hold.
_COMPUTED_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[\w${}`]+")
#: Separators of the unconditional chain a leading `cd` may sit in. `||` and `|`
#: are deliberately absent: a `cd` beside them is conditional or in a subshell.
_CD_CHAIN_SEPARATORS: Final[tuple[str, ...]] = ("&&", ";", "\n")
#: Characters that make a `cd` target something other than a literal directory.
_CD_UNLITERAL_MARKERS: Final[tuple[str, ...]] = ("$", "`", "*", "?", "[", "{", "(", "\\")
#: A directory-changing command anywhere in text, as a word of its own.
_CD_WORD_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\w./-])(?:cd|pushd|popd)(?![\w-])")
#: Commands that run shell code this handler cannot see (`eval`, sourcing).
_OPAQUE_CODE_HEADS: Final[frozenset[str]] = frozenset({"eval", "source", "."})
#: The upgrade's entry points by name: Layer 1 (and the skill shim of the same
#: name), Layer 2, and the gate itself.
_UPGRADE_ENTRY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\s/])(?:upgrade\.sh|upgrade_version\.sh|upgrade_gate_standalone\.py)\b"
)
#: Commands that run the script named by their first operand in the current shell.
_SCRIPT_RUNNER_HEADS: Final[frozenset[str]] = frozenset({"source", "."})
#: An argument only the upgrade takes: Layer 1's acknowledgement flag.
_UPGRADE_ONLY_ARG_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|\s)--skip-reading-confirmation\b")
#: Arguments the upgrade's scripts take: Layer 1's required `--project-root`,
#: or Layer 2's daemon-dir positional (the clone itself).
_UPGRADE_SHAPED_ARG_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)--project-root\b|\.claude/hooks-daemon/?[\"']?(?:\s|$)"
)
#: The per-run argument that names the uv building the venv (`--uv <path>` or
#: `--uv=<path>`). Only the human passes it: it picks the code the daemon runs.
_UV_OVERRIDE_ARG_RE: Final[re.Pattern[str]] = re.compile(r"(?:^|\s)--uv(?:=|\s|$)")
#: This process's own stdin/fd, which is NEVER what a real subprocess would
#: read from its own redirect -- reading it here answers a different question.
_UNRESOLVABLE_STDIN_RE: Final[re.Pattern[str]] = re.compile(r"^/dev/(?:stdin|fd/\d+)$")
#: Text every copy of Layer 1 and Layer 2 carries, whatever the file is named.
_UPGRADE_SCRIPT_SIGNATURE: Final[str] = "HOOKS_DAEMON_UPGRADE_HANDOFF"
#: Enough of a script to find the signature without reading a huge file.
_SCRIPT_READ_LIMIT: Final[int] = 4_194_304
#: How deep `bash -c '...'` strings are followed before the scan stops.
_MAX_INLINE_DEPTH: Final[int] = 4
#: Shells that run a script file named as their first operand.
_SHELL_HEADS: Final[frozenset[str]] = frozenset({"bash", "sh", "dash", "zsh", "ksh", "source", "."})
#: Words that run the rest of the segment as a command.
_WRAPPER_HEADS: Final[frozenset[str]] = frozenset(
    {
        "env",
        "exec",
        "nohup",
        "command",
        "time",
        "timeout",
        "nice",
        "setsid",
        "stdbuf",
        "sudo",
        "xargs",
        "ionice",
        "chrt",
        "taskset",
        "flock",
        "strace",
        "ltrace",
    }
)
#: Per wrapper, the SHORT options that take a separate value (`nice -n 10`,
#: `sudo -u root`). Without this the value is mistaken for the command the
#: wrapper runs and the real program is never examined. An option missing here
#: is read as a flag without a value. Every head in `_WRAPPER_HEADS` has an
#: entry in both tables.
_WRAPPER_SHORT_VALUE_OPTIONS: Final[dict[str, frozenset[str]]] = {
    "env": frozenset("uCS"),
    "exec": frozenset("a"),
    "nohup": frozenset(),
    "command": frozenset(),
    "setsid": frozenset(),
    "flock": frozenset("wEc"),
    "strace": frozenset("abeEIoOpPsSuUX"),
    "ltrace": frozenset("aAeEFlnopsSuUxX"),
    "time": frozenset("fo"),
    "timeout": frozenset("ks"),
    "nice": frozenset("n"),
    "stdbuf": frozenset("ioe"),
    "sudo": frozenset("ugChprtUDRT"),
    "xargs": frozenset("adEILnPs"),
    "ionice": frozenset("cnpPu"),
    "chrt": frozenset(),
    "taskset": frozenset("c"),
}
#: Per wrapper, the LONG options that take a separate value (`--user root`).
_WRAPPER_LONG_VALUE_OPTIONS: Final[dict[str, frozenset[str]]] = {
    "env": frozenset({"--unset", "--chdir", "--split-string", "--argv0"}),
    "exec": frozenset(),
    "nohup": frozenset(),
    "command": frozenset(),
    "setsid": frozenset(),
    "flock": frozenset({"--timeout", "--wait", "--conflict-exit-code", "--command"}),
    "strace": frozenset({"--output", "--expr", "--signal", "--user", "--env", "--attach"}),
    "ltrace": frozenset({"--output", "--library", "--user", "--align"}),
    "time": frozenset({"--format", "--output"}),
    "timeout": frozenset({"--kill-after", "--signal"}),
    "nice": frozenset({"--adjustment"}),
    "stdbuf": frozenset({"--input", "--output", "--error"}),
    "sudo": frozenset(
        {
            "--user",
            "--group",
            "--close-from",
            "--chdir",
            "--host",
            "--prompt",
            "--role",
            "--type",
            "--other-user",
            "--chroot",
            "--command-timeout",
        }
    ),
    "xargs": frozenset(
        {
            "--arg-file",
            "--delimiter",
            "--eof",
            "--replace",
            "--max-lines",
            "--max-args",
            "--max-procs",
            "--max-chars",
        }
    ),
    "ionice": frozenset({"--class", "--classdata", "--pid", "--pgid", "--uid"}),
    "chrt": frozenset(),
    "taskset": frozenset(),
}
#: Wrappers whose first operand after their options is not the command:
#: `timeout`'s duration, `chrt`'s priority, `taskset`'s CPU mask, `flock`'s
#: lock file.
_WRAPPER_LEADING_OPERAND_HEADS: Final[frozenset[str]] = frozenset(
    {"timeout", "chrt", "taskset", "flock"}
)
#: Python short options that take a value, attached (`-Wignore`) or as the next
#: word (`-W ignore`), also at the end of a cluster (`-uW ignore`). `-m` names a
#: module and `-c` inline code, so neither is followed by a script.
_PYTHON_VALUE_CHARS: Final[frozenset[str]] = frozenset("WXQmc")
#: The script operand that makes python read its program from stdin.
_PYTHON_STDIN_SCRIPT: Final[str] = "-"
#: A redirection word whose target is the NEXT word (`<`, `2>`, `>>`, `&>`).
_REDIRECT_OPERATOR_RE: Final[re.Pattern[str]] = re.compile(r"\d*(?:<<<|<>|<&|>&|>>|>\||&>>|&>|<|>)")
#: A redirection word carrying its own target (`<file`, `2>/dev/null`).
_REDIRECT_WITH_TARGET_RE: Final[re.Pattern[str]] = re.compile(r"\d*(?:<|>|&>)")

# --- the daemon clone moved by hand ------------------------------------------

#: A path naming the client's daemon clone (or its `.git`).
_DAEMON_CLONE_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|/)\.claude/hooks-daemon(?:/\.git)?/?$"
)
#: The path parts naming the daemon clone's own git metadata.
_DAEMON_CLONE_GIT_PARTS: Final[tuple[str, ...]] = (".claude", "hooks-daemon", ".git")
#: git subcommands that move the checkout to another commit.
_HEAD_MOVING_GIT_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {"checkout", "switch", "pull", "merge", "rebase", "reset", "cherry-pick", "am", "revert"}
)
#: git global options whose value names the repository or work tree.
_GIT_PATH_OPTIONS: Final[frozenset[str]] = frozenset({"-C", "--git-dir", "--work-tree"})
#: git global options that take a separate value to skip.
_GIT_VALUE_OPTIONS: Final[frozenset[str]] = frozenset({"-c", "--namespace", "--exec-path"})
#: `git remote` subcommands that change what a remote points to or exists at
#: all (review2 MINOR 2). `-v`/`show`/a bare `remote` only list/read.
_REMOTE_MUTATING_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {"add", "remove", "rm", "rename", "set-url", "set-branches", "set-head", "prune"}
)
#: `git config` flags that write rather than read a value.
_CONFIG_MUTATING_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "--add",
        "--unset",
        "--unset-all",
        "--replace-all",
        "--rename-section",
        "--remove-section",
        "-e",
        "--edit",
    }
)
#: `git config` flags that read a value, so a `key value` positional PAIR is
#: not what decides (a value can itself look like a second positional word).
_CONFIG_READ_ONLY_FLAGS: Final[frozenset[str]] = frozenset(
    {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list", "--get-color"}
)

# --- segmentation and the inert-text exemption ------------------------------

#: Splits a Bash command into top-level stages: `;`, `&&`, `||`, a pipe stage,
#: a newline. Longest-first so `&&`/`||` are not read as two `&`/`|`.
_SEGMENT_SEPARATORS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", "\n")
#: Spans meaning bash will EXECUTE something inside a quoted argument.
_SUBSTITUTION_MARKERS: Final[tuple[str, ...]] = ("$(", "`")
#: A path-named Python interpreter (`/v/bin/python`, `.venv/bin/python3.11`):
#: judged by what it is given to run, not as a script that must be readable.
_PYTHON_INTERPRETER_RE: Final[re.Pattern[str]] = re.compile(r"python[0-9.]*")
#: A `VAR=value` assignment prefix, skipped when resolving a segment's head.
_ASSIGNMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
#: `grep`/`rg` never execute what they search for, so any occurrence of a
#: guarded pattern in one of their segments is a SEARCH, not a run.
_ALWAYS_INERT_HEADS: Final[frozenset[str]] = frozenset({"grep", "rg"})
#: `echo`/`printf` are exempt UNLESS their argument can substitute (item 1's
#: "echo with live substitution is still denied" case).
_CONDITIONALLY_INERT_HEADS: Final[frozenset[str]] = frozenset({"echo", "printf"})

# --- item 2 / item 4: writes bash_file_writes cannot show -------------------

#: `bash_file_writes` follows redirects, `tee`, `cp`/`mv`/`install`/`dd`,
#: `ln`/`rsync`, in-place editors and interpreter one-liners, but not a bare
#: `touch`/`mkdir` — neither authors content nor relocates an existing file,
#: so neither shape `bash_write_destinations` recognises applies. Detected
#: here instead: every non-flag operand of a `touch`/`mkdir` head.
_EXTRA_WRITE_VERBS: Final[frozenset[str]] = frozenset({"touch", "mkdir"})

logger = logging.getLogger(__name__)


def _shell_words(segment: str) -> list[str]:
    """Shell words of one segment; whitespace words when shlex cannot parse it.

    A stray unbalanced quote in prose text must cost only this segment, not
    the whole scan — so a parse failure is logged and degrades to a plain
    split rather than raising (matches `handlers/utils/bash_file_writes.py`'s
    `_words`).
    """
    try:
        return linear_shlex.split(segment)
    except ValueError as exc:
        logger.debug("upgrade_approval_guard: shlex could not parse %r (%s)", segment, exc)
        return segment.split()


def _segment_head(segment: str) -> str:
    """The command a segment runs, past any `VAR=value` assignment prefix."""
    for token in _shell_words(segment):
        if _ASSIGNMENT_RE.match(token):
            continue
        return command_word(token)
    return ""


def _is_inert_mention_segment(segment: str) -> bool:
    """Whether ``segment`` only MENTIONS guarded text rather than running it."""
    head = _segment_head(segment)
    if head in _ALWAYS_INERT_HEADS:
        return True
    if head in _CONDITIONALLY_INERT_HEADS:
        return not any(marker in segment for marker in _SUBSTITUTION_MARKERS)
    return False


def _executable_segments(command: str) -> list[str]:
    """Top-level stages of ``command``, with inert text stripped first."""
    executable = strip_inert_spans(command)
    return split_unquoted(executable, _SEGMENT_SEPARATORS)


def _bash_runs_guarded_action(command: str) -> bool:
    """Whether ``command`` runs `approve-upgrade` or the standalone `approve`."""
    for segment in _executable_segments(command):
        if _is_inert_mention_segment(segment):
            continue
        if _APPROVE_UPGRADE_RE.search(segment) or _STANDALONE_APPROVE_RE.search(segment):
            return True
    return False


def _without_grouping(segment: str) -> str:
    """``segment`` without the subshell parentheses that wrap or cut it.

    `(A=1 prog)` runs `prog` with `A` set exactly as `A=1 prog` does, but its
    first word reads `(A=1`, which is neither an assignment nor a command
    (ledger 00474 N311). Each leading `(` goes with one trailing `)`; a `)` left
    over past that closes a group that opened in an earlier segment
    (`(cd d && prog)` splits at the `&&`).
    """
    text = segment.strip()
    while text.startswith("("):
        text = text[1:].strip()
        if text.endswith(")") and text.count("(") < text.count(")"):
            text = text[:-1].strip()
    while text.endswith(")") and text.count("(") < text.count(")"):
        text = text[:-1].strip()
    return text


def _live_segments(command: str) -> list[str]:
    """The stages of ``command`` that run something rather than mention it."""
    grouped = (_without_grouping(segment) for segment in _executable_segments(command))
    return [segment for segment in grouped if not _is_inert_mention_segment(segment)]


def _past_wrappers(words: list[str]) -> list[str]:
    """``words`` from the command a wrapper chain finally runs.

    Skips `VAR=value` prefixes and the wrappers in `_WRAPPER_HEADS` with their
    options (a valued option's value too), `env`'s assignments and the leading
    operand of `timeout`/`chrt`/`taskset`. `env -S` carries a command string,
    which is spliced in as the words that follow.
    """
    words = list(words)
    index = 0
    while index < len(words):
        word = words[index]
        if _ASSIGNMENT_RE.match(word):
            index += 1
            continue
        head = command_word(word)
        if head not in _WRAPPER_HEADS:
            return words[index:]
        index += 1
        leading_operand = head in _WRAPPER_LEADING_OPERAND_HEADS
        while index < len(words) and (words[index].startswith("-") or "=" in words[index]):
            option = words[index]
            index += 1
            if option == "--" or not option.startswith("-"):
                continue
            attached_command = _attached_split_string(head, option)
            if attached_command is not None:
                words[index:index] = _shell_words(attached_command)
                continue
            value, split_string = _wrapper_option_value(head, option, words, index)
            if head == "taskset" and option.startswith("-c"):
                leading_operand = False
            if value is not None:
                index += 1
                if split_string:
                    words[index:index] = _shell_words(value)
        if leading_operand and index < len(words):
            index += 1
    return []


def _attached_split_string(head: str, option: str) -> str | None:
    """The command line `env -S` carries attached to ``option`` (`-S'cmd'`), else None."""
    if head != "env":
        return None
    if option.startswith("--"):
        name, equals, value = option.partition("=")
        return value if equals and name == "--split-string" else None
    takes_chars = _WRAPPER_SHORT_VALUE_OPTIONS[head]
    first = next((at for at, char in enumerate(option[1:], start=1) if char in takes_chars), None)
    if first is None or option[first] != "S" or first == len(option) - 1:
        return None
    return option[first + 1 :]


def _wrapper_option_value(
    head: str, option: str, words: list[str], index: int
) -> tuple[str | None, bool]:
    """The separate value word of wrapper ``head``'s ``option``, if it takes one.

    Returns ``(value, is_split_string)``; ``value`` is ``None`` when the option
    is a flag, carries its value attached (`-n10`, `--user=root`) or the value
    word is missing. ``is_split_string`` marks `env -S`, whose value is itself a
    command line.
    """
    if option.startswith("--"):
        name = option.partition("=")[0]
        takes = "=" not in option and name in _WRAPPER_LONG_VALUE_OPTIONS[head]
        split_string = name == "--split-string"
    else:
        takes_chars = _WRAPPER_SHORT_VALUE_OPTIONS[head]
        flag_position = next((i for i, char in enumerate(option[1:]) if char in takes_chars), None)
        takes = flag_position is not None and flag_position == len(option) - 2
        split_string = head == "env" and takes and option.endswith("S")
    if not takes or index >= len(words):
        return None, False
    return words[index], split_string


def _script_carries_the_upgrade(script: Path) -> bool:
    """Whether the file ``script`` is a copy of Layer 1 or 2.

    Raises ``OSError`` when it cannot be read; `_script_run_is_upgrade`
    decides what "cannot tell" means for the command around it.
    """
    with script.open("rb") as handle:
        return _UPGRADE_SCRIPT_SIGNATURE.encode() in handle.read(_SCRIPT_READ_LIMIT)


def _script_is_statically_unresolvable(script: str) -> bool:
    """Whether ``script`` cannot be judged by content AT ALL, whatever
    ``path_is_file``/``open`` say about it (review3 MAJOR 1, the N29 shape).

    A ``$``-path is a variable reference this handler never expands: there is
    no file to read, ever. ``/dev/stdin``/``/dev/fd/N`` name THIS process's
    own descriptor, not the real subprocess's later redirect -- reading it
    here answers a different question, and could even happen to succeed by
    accident. Unexpanded process-substitution syntax (``<(...)``) is not a
    path the shell parser hands back either.
    """
    if "$" in script:
        return True
    if _UNRESOLVABLE_STDIN_RE.match(script):
        return True
    return script.startswith("<(")


def _script_run_is_upgrade(
    script: str, arguments: list[str], cwd: str | None, *, steered: bool
) -> bool:
    """Whether running ``script`` with ``arguments`` is an upgrade.

    A script this handler can read AND resolve statically is judged by its
    content (every copy of Layer 1 and Layer 2 carries the handoff variable,
    whatever the file is named). Otherwise -- statically unresolvable
    (`_script_is_statically_unresolvable`), a relative path with no ``cwd``
    to resolve it against, not a readable file, or a READ that failed -- a
    command that also carries a steering assignment counts as running the
    upgrade outright: ``BASH_ENV`` runs inside Layer 2 before
    ``_sanitise_layer2_env`` ever gets a say, so "cannot tell" must not mean
    "allow" once something is already steering it. Unsteered, the command's
    own argument shape decides.

    ``path_is_file(..., unreadable_means=False)`` rather than a raw
    ``is_file`` (`check_eacces_safe_predicates`): an untraversable ancestor
    raises ``PermissionError`` there, which would crash ``matches()`` for the
    whole handler rather than misjudge this one script.
    """
    if _script_is_statically_unresolvable(script):
        return _cannot_tell_script(arguments, steered=steered)
    path = Path(script)
    if not path.is_absolute() and cwd is not None:
        path = Path(cwd) / path
    if not (path.is_absolute() and path_is_file(path, unreadable_means=False)):
        return _cannot_tell_script(arguments, steered=steered)
    try:
        return _script_carries_the_upgrade(path)
    except OSError as exc:
        logger.warning(
            "upgrade_approval_guard: cannot read %s to tell whether it is the upgrade (%s)",
            path,
            exc,
        )
        return _cannot_tell_script(arguments, steered=steered)


def _cannot_tell_script(arguments: list[str], *, steered: bool) -> bool:
    """The verdict on a script whose content cannot be judged: the upgrade
    when anything steers the command, else whatever its arguments say."""
    if steered:
        return True
    return _UPGRADE_SHAPED_ARG_RE.search(" ".join(arguments)) is not None


def _shell_run_is_upgrade(
    operands: list[str], cwd: str | None, depth: int, *, steered: bool
) -> bool:
    """Whether a shell given ``operands`` runs the upgrade.

    `-c` runs its string, which is scanned as a command; `-s` (or no script
    operand) reads the script from stdin, so only its arguments -- or, when
    steered, the steering assignment itself -- can tell.
    """
    inline = False
    reads_stdin = False
    while operands and operands[0].startswith("-"):
        flag, operands = operands[0], operands[1:]
        if flag == "--":
            break
        if not flag.startswith("--"):
            if "n" in flag[1:]:
                return False  # `-n` reads the script for syntax errors only
            inline = inline or "c" in flag[1:]
            reads_stdin = reads_stdin or "s" in flag[1:]
    if inline:
        return bool(operands) and _command_runs_upgrade(
            operands[0], cwd, depth + 1, steered=steered
        )
    if reads_stdin or not operands:
        if steered:
            return True
        return _UPGRADE_SHAPED_ARG_RE.search(" ".join(operands)) is not None
    return _script_run_is_upgrade(operands[0], operands[1:], cwd, steered=steered)


def _python_code_source(arguments: list[str]) -> tuple[str, int, str]:
    """Where a python interpreter given ``arguments`` takes its program from.

    Returns ``(kind, index, attached)``: ``kind`` is ``"script"`` (the word at
    ``index``, `-` meaning stdin), ``"module"`` or ``"inline"`` (the option at
    ``index``, with ``attached`` its attached value, `-mpytest`), or ``"none"``.
    A valued option's value (`-W ignore`, `-uX dev`) is skipped.
    """
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word == "--":
            return ("script", index + 1, "") if index + 1 < len(arguments) else ("none", index, "")
        if _REDIRECT_OPERATOR_RE.fullmatch(word):
            index += 2
            continue
        if _REDIRECT_WITH_TARGET_RE.match(word):
            index += 1
            continue
        if word == _PYTHON_STDIN_SCRIPT or not word.startswith("-"):
            return "script", index, ""
        if word.startswith("--"):
            index += 1
            continue
        position = next(
            (at for at, char in enumerate(word[1:], start=1) if char in _PYTHON_VALUE_CHARS), None
        )
        if position is None:
            index += 1
            continue
        char, attached = word[position], word[position + 1 :]
        if char == "c":
            return "inline", index, attached
        if char == "m":
            return "module", index, attached
        index += 1 if attached else 2
    return "none", index, ""


def _python_runs_entry_point(arguments: list[str]) -> bool:
    """Whether a python interpreter given ``arguments`` runs an entry point.

    The script operand is judged by name. `-m <module>` runs a module, whose
    own operands count only when positional (`-m pytest scripts/upgrade.sh`,
    not `-k upgrade.sh`). `-c` runs inline code, which is not a script.
    """
    kind, index, attached = _python_code_source(arguments)
    if kind == "script":
        return _UPGRADE_ENTRY_RE.search(arguments[index]) is not None
    if kind == "module":
        if attached:
            return _positional_names_entry_point(arguments[index + 1 :], [attached])
        return _positional_names_entry_point(arguments[index + 2 :], arguments[index + 1 :])
    return False


def _positional_names_entry_point(words: list[str], preceded_by: list[str]) -> bool:
    """Whether a word of ``words`` that no dash-word precedes names an entry point.

    A word following a dash-word is taken to be that flag's value
    (`-k upgrade.sh`). ``preceded_by`` starts with the word before ``words``.
    """
    previous = preceded_by[0] if preceded_by else "-"
    for word in words:
        if (
            not previous.startswith("-")
            and not word.startswith("-")
            and _UPGRADE_ENTRY_RE.search(word) is not None
        ):
            return True
        previous = word
    return False


def _shell_script_operand_is_entry_point(arguments: list[str]) -> bool:
    """Whether a shell (or `source`) given ``arguments`` runs an entry point.

    `-c` runs a string (judged by recursion, not here) and `-n` only checks
    syntax, so neither runs a script operand. Otherwise the first non-option
    word is the script.
    """
    for word in arguments:
        if word.startswith("--"):
            continue
        if word.startswith("-"):
            if "c" in word[1:] or "n" in word[1:]:
                return False
            continue
        return _UPGRADE_ENTRY_RE.search(word) is not None
    return False


def _runs_upgrade_entry_point(words: list[str]) -> bool:
    """Whether the command in ``words`` (past its wrappers) RUNS an entry point.

    The entry point counts only in program position, or as the script operand
    of a shell, an interpreter, or `source`/`.`. Anywhere else (`git log --
    scripts/upgrade.sh`, `shellcheck scripts/upgrade.sh`, `pytest -k
    upgrade.sh`) it is data the command reads, not something it runs.
    """
    if _UPGRADE_ENTRY_RE.search(words[0]):
        return True
    head = command_word(words[0])
    if head in _SHELL_HEADS or head in _SCRIPT_RUNNER_HEADS:
        return _shell_script_operand_is_entry_point(words[1:])
    if _PYTHON_INTERPRETER_RE.fullmatch(head):
        return _python_runs_entry_point(words[1:])
    if words[0].startswith("$"):
        # An interpreter's (or an unexpanded program's) positional operands:
        # a word following a dash-word is a flag's value (`-k upgrade.sh`).
        return any(
            _UPGRADE_ENTRY_RE.search(word) is not None
            for previous, word in pairwise(words)
            if not previous.startswith("-") and not word.startswith("-")
        )
    return False


def _segment_runs_upgrade(segment: str, cwd: str | None, depth: int, *, steered: bool) -> bool:
    """Whether ``segment`` runs the upgrade, by name, argument or content."""
    if _UPGRADE_ONLY_ARG_RE.search(segment):
        return True
    words = _past_wrappers(_shell_words(segment))
    if not words:
        return False
    if _runs_upgrade_entry_point(words):
        return True
    head = command_word(words[0])
    if steered and _PYTHON_INTERPRETER_RE.fullmatch(head):
        # The program arrives on stdin (`-`, or no script operand with an
        # entry point redirected in), so its content cannot be judged here.
        kind, index, _attached = _python_code_source(words[1:])
        if kind == "script" and words[1:][index] == _PYTHON_STDIN_SCRIPT:
            return True
        if kind == "none" and _UPGRADE_ENTRY_RE.search(segment) is not None:
            return True
    if head in _SHELL_HEADS:
        return _shell_run_is_upgrade(words[1:], cwd, depth, steered=steered)
    if words[0].startswith("$"):
        return _variable_program_is_upgrade(words[1:], cwd, steered=steered)
    if "/" in words[0]:
        if _PYTHON_INTERPRETER_RE.fullmatch(head):
            return _variable_program_is_upgrade(words[1:], cwd, steered=steered)
        return _script_run_is_upgrade(words[0], words[1:], cwd, steered=steered)
    return False


def _inline_program_is_upgrade(arguments: list[str], index: int, *, steered: bool) -> bool:
    """Whether the `-c` program at ``arguments[index]`` (the flag) runs the upgrade
    (ledger 00474 N354).

    A literal program is text this handler can read: it runs the upgrade only
    if it names one of the upgrade's own entry points or arguments, exactly the
    signals every other branch requires. A program with no text, or one the
    shell expands (`$CODE`, a backtick), cannot be read, and stays "cannot
    tell", which counts as the upgrade once something steers.
    """
    flag = arguments[index]
    attached = flag[flag.index("c") + 1 :]
    following = arguments[index + 1] if index + 1 < len(arguments) else ""
    program = f"{attached} {following}".strip()
    if not program or "$" in program or "`" in program:
        return _cannot_tell_script(arguments, steered=steered)
    return (
        _UPGRADE_ENTRY_RE.search(program) is not None
        or _UPGRADE_SHAPED_ARG_RE.search(program) is not None
    )


def _variable_program_is_upgrade(arguments: list[str], cwd: str | None, *, steered: bool) -> bool:
    """Whether a command whose program is a variable (`$PY`, `$PY/python`)
    runs the upgrade, judged by what its ARGUMENTS name (ledger 00474 N285).

    The variable is never expanded, so the program itself is unknown; what it
    is given to run can still be literal. `-m <module>` and a script path with
    no `$` are judged like any other run (a script by its content, a module by
    not being the daemon's own CLI). `-c`, no operand, stdin, a computed
    module or script, and the daemon's own `-m claude_code_hooks_daemon...`
    stay "cannot tell", which counts as the upgrade once something steers.
    """
    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        flag = arguments[index]
        if "c" in flag[1:] and not flag.startswith("--"):
            return _inline_program_is_upgrade(arguments, index, steered=steered)
        if flag in ("-", "--"):
            return _cannot_tell_script(arguments, steered=steered)
        if flag == "-m":
            module = arguments[index + 1] if index + 1 < len(arguments) else ""
            if not module or "$" in module or "`" in module:
                return _cannot_tell_script(arguments, steered=steered)
            if module.startswith(_DAEMON_PACKAGE):
                return _cannot_tell_script(arguments, steered=steered)
            return False
        index += 1
    if index >= len(arguments):
        return _cannot_tell_script(arguments, steered=steered)
    return _script_run_is_upgrade(arguments[index], arguments[index + 1 :], cwd, steered=steered)


def _command_runs_upgrade(
    command: str, cwd: str | None, depth: int = 0, *, steered: bool = False
) -> bool:
    """Whether any stage of ``command`` runs the upgrade."""
    if depth > _MAX_INLINE_DEPTH:
        return False
    return any(
        _segment_runs_upgrade(segment, cwd, depth, steered=steered)
        for segment in _live_segments(command)
    )


def _assigns_a_computed_name(word: str) -> bool:
    """Whether ``word`` is `NAME=value` with a NAME only known at run time
    (`$n=f`, `${n}_ENV=f`), not merely text holding `$` before an `=`."""
    name, separator, _value = word.partition("=")
    if not separator or _COMPUTED_NAME_RE.fullmatch(name) is None:
        return False
    return any(marker in name for marker in ("$", "`"))


def _segment_exports_by_another_spelling(words: list[str]) -> bool:
    """Whether a segment's words export something without a literal steering
    `NAME=` (review4 MAJOR 1): a `declare`/`typeset`/`local` flag containing
    `x`, an `export` with a flag or a computed operand, or a computed name in
    any assignment (`env "$n=f"`)."""
    if any(_assigns_a_computed_name(word) for word in words):
        return True
    head_words = _past_wrappers(words)
    if not head_words:
        return False
    head = command_word(head_words[0])
    operands = head_words[1:]
    if head in _DECLARING_HEADS:
        return any(word.startswith("-") and "x" in word for word in operands)
    if head == "export":
        return any(
            word.startswith("-") or not _LITERAL_EXPORT_OPERAND_RE.match(word) for word in operands
        )
    return False


def _segment_steers(segment: str) -> bool:
    """Whether ``segment`` sets, exports or names a steering variable."""
    if _STEERING_ASSIGN_RE.search(segment) or _STEERING_NAME_RE.search(segment):
        return True
    return _segment_exports_by_another_spelling(_shell_words(segment))


def _turns_on_allexport(words: list[str]) -> bool:
    """Whether `set` words turn on allexport (`-a` in a cluster, `-o allexport`)."""
    for index, word in enumerate(words):
        if word == "-o" and index + 1 < len(words) and words[index + 1] == "allexport":
            return True
        if word.startswith("-") and not word.startswith("--") and "a" in word[1:]:
            return True
    return False


def _segment_prepares_the_shell(segment: str) -> bool:
    """Whether ``segment`` can change the environment in ways this handler
    cannot read: `eval`, sourcing a file, or `set -a` (every later assignment
    is exported). These have ordinary uses (`eval "$(ssh-agent)"`, loading a
    `.env`), so they count only on a command already recognised as running
    the upgrade."""
    words = _past_wrappers(_shell_words(segment))
    if not words:
        return False
    head = command_word(words[0])
    if head == "set":
        return _turns_on_allexport(words[1:])
    return head in _OPAQUE_CODE_HEADS


def _literal_cd_target(chunk: str) -> str | None:
    """The directory a chunk that is exactly `cd <literal-dir>` moves to, else None.

    A target that is computed, home-relative, a glob, the previous directory or
    climbs with `..` is not literal: where it lands is not known statically.
    """
    words = _shell_words(chunk.strip())
    if len(words) != 2 or words[0] != "cd":
        return None
    target = words[1]
    if not target or target == "-" or target.startswith("~"):
        return None
    if any(marker in target for marker in _CD_UNLITERAL_MARKERS):
        return None
    if ".." in Path(target).parts:
        return None
    return target


def _leading_cd_cwd(command: str, cwd: str | None) -> str | None:
    """The directory ``command``'s relative paths resolve against (ledger 00474 N292).

    A command that begins `cd <dir> && ...` runs everything after it in
    ``<dir>``, so a relative script path must be judged there, not in the
    hook's own cwd (where it would look missing, which counts as the upgrade
    once something steers). Only an unconditional leading chain of `cd <literal
    existing dir>` joined by `&&`/`;`/newline is followed, and only when no
    other `cd`/`pushd`/`popd` appears later: a missing target leaves the shell
    where it was under `;`, and a subshell, pipe, `||` or later move makes the
    directory unknowable. Every such case returns ``cwd`` unchanged.
    """
    chunks = split_unquoted(command, _CD_CHAIN_SEPARATORS)
    base = cwd
    consumed = 0
    for chunk in chunks:
        target = _literal_cd_target(chunk)
        if target is None:
            break
        path = Path(target)
        if not path.is_absolute():
            if base is None:
                return cwd
            path = Path(base) / path
        if not path_is_dir(path, unreadable_means=False):
            return cwd
        base = str(path)
        consumed += 1
    if consumed == 0 or any(_CD_WORD_RE.search(chunk) for chunk in chunks[consumed:]):
        return cwd
    return base


def _bash_sets_bypass_env_var(command: str, cwd: str | None) -> bool:
    """Whether ``command`` sets the handoff variable, or steers an upgrade it runs."""
    cwd = _leading_cd_cwd(command, cwd)
    segments = _live_segments(command)
    if any(_ENV_VAR_ASSIGN_RE.search(segment) for segment in segments):
        return True
    if any(_segment_steers(segment) or _UV_OVERRIDE_ARG_RE.search(segment) for segment in segments):
        return _command_runs_upgrade(command, cwd, steered=True)
    preparing = [segment for segment in segments if _segment_prepares_the_shell(segment)]
    if not preparing:
        return False
    return any(
        _segment_runs_upgrade(segment, cwd, 0, steered=False)
        for segment in segments
        if segment not in preparing
    )


def _remote_mutates(words: list[str], index: int) -> bool:
    """Whether `git remote ...` (subcommand word at ``index``) changes a remote.

    A bare `git remote`, or one followed only by `-v`/`show`/`get-url`, lists
    or reads; `add`/`remove`/`rename`/`set-url` (etc.) change what `origin`
    points to or whether it exists (review2 MINOR 2: a `fetch --tags --force`
    that follows trusts whatever `origin` NAMES).
    """
    for word in words[index + 1 :]:
        if word.startswith("-"):
            continue
        return word in _REMOTE_MUTATING_SUBCOMMANDS
    return False


def _config_mutates(words: list[str], index: int) -> bool:
    """Whether `git config ...` (subcommand word at ``index``) writes a value.

    A read (`--get`, `-l`, or a bare `key` with no value) is not this; a
    write is a mutating flag, or two positional words (`key value`).
    """
    positional = 0
    for word in words[index + 1 :]:
        if word in _CONFIG_MUTATING_FLAGS:
            return True
        if word in _CONFIG_READ_ONLY_FLAGS:
            return False
        if word.startswith("-"):
            continue
        positional += 1
    return positional >= 2


def _git_moves_daemon_clone(words: list[str], clone_cwd: bool) -> bool:
    """Whether a `git ...` word list moves the daemon clone to another commit,
    or redirects where it next fetches FROM (review2 MINOR 2: `remote`/`config`
    writes to `origin` are the same class of route -- neither moves HEAD by
    itself, but both decide what the next `checkout`/`fetch` lands on).

    ``clone_cwd`` says an earlier stage changed into the clone, so a git with
    no `-C` acts on it.
    """
    names_clone = clone_cwd
    index = 1
    while index < len(words):
        word = words[index]
        option, _, value = word.partition("=")
        if option in _GIT_PATH_OPTIONS:
            if not value and index + 1 < len(words):
                index += 1
                value = words[index]
            if _DAEMON_CLONE_PATH_RE.search(value):
                names_clone = True
            elif option == "-C":
                names_clone = False
            index += 1
            continue
        if word in _GIT_VALUE_OPTIONS:
            index += 2
            continue
        if word.startswith("-"):
            index += 1
            continue
        if not names_clone:
            return False
        if word in _HEAD_MOVING_GIT_SUBCOMMANDS:
            return True
        if word == "remote":
            return _remote_mutates(words, index)
        if word == "config":
            return _config_mutates(words, index)
        return False
    return False


def _bash_moves_daemon_clone(command: str) -> bool:
    """Whether ``command`` checks out, pulls or resets the daemon clone by hand."""
    in_clone = False
    for segment in _live_segments(command):
        words = _past_wrappers(_shell_words(segment))
        if not words:
            continue
        head = command_word(words[0])
        if head in ("cd", "pushd"):
            in_clone = len(words) > 1 and _DAEMON_CLONE_PATH_RE.search(words[-1]) is not None
            continue
        if head == "git" and _git_moves_daemon_clone(words, in_clone):
            return True
    return False


def _extra_write_targets(command: str) -> list[str]:
    """Operand paths of a bare `touch`/`mkdir` invocation, per segment."""
    targets: list[str] = []
    for segment in _executable_segments(command):
        if _is_inert_mention_segment(segment):
            continue
        tokens = _shell_words(segment)
        head_index: int | None = None
        for index, token in enumerate(tokens):
            if _ASSIGNMENT_RE.match(token):
                continue
            head_index = index
            break
        if head_index is None:
            continue
        if command_word(tokens[head_index]) not in _EXTRA_WRITE_VERBS:
            continue
        targets.extend(token for token in tokens[head_index + 1 :] if not token.startswith("-"))
    return targets


def _has_upgrade_approvals_segment(path: str) -> bool:
    """Whether ``path`` names something under an `upgrade-approvals/` directory."""
    return APPROVAL_SUBDIR in Path(path).parts


def _is_venv_version_stamp(path: str) -> bool:
    """Whether ``path`` is a `.daemon-version` stamp under `untracked/venv*/`.

    review2 N2: the LAST `untracked` segment, not the first. A project that
    itself sits under an `untracked/` ancestor -- this repo's own worktrees,
    `untracked/worktrees/<name>/` -- has an outer `untracked` earlier in the
    path than the venv's own `untracked/venv*/`; matching the first one
    checked `worktrees` against `venv*` and missed the real stamp.
    """
    parts = Path(path).parts
    if not parts or parts[-1] != STAMP_FILENAME:
        return False
    try:
        index = len(parts) - 1 - parts[::-1].index("untracked")
    except ValueError:
        return False
    return index + 1 < len(parts) and parts[index + 1].startswith("venv")


def _is_daemon_clone_git_metadata(path: str) -> bool:
    """Whether ``path`` is the daemon clone's `.git`, or anything under it.

    review4 MAJOR 3 / review3 m2: an appended `url.insteadOf` or second
    origin URL in `.claude/hooks-daemon/.git/config`, a hook, a moved tag, or
    a `.git` gitfile pointing elsewhere all decide what the next fetch and
    checkout install, with no `git config`/`remote` command to recognise.
    """
    parts = Path(path).parts
    return any(
        parts[index : index + len(_DAEMON_CLONE_GIT_PARTS)] == _DAEMON_CLONE_GIT_PARTS
        for index in range(len(parts))
    )


def _guarded_write_target(path: str) -> str | None:
    """Which guarded surface ``path`` hits — for the deny message — or None."""
    if _has_upgrade_approvals_segment(path):
        return "the one-shot upgrade-approval marker directory (`upgrade-approvals/`)"
    if _is_venv_version_stamp(path):
        return "a venv's installer version stamp (`.daemon-version`)"
    if _is_daemon_clone_git_metadata(path):
        return (
            "the daemon clone's own git metadata (`.claude/hooks-daemon/.git`), which "
            "decides what the next upgrade fetches and checks out"
        )
    return None


def _read_text(path: Path) -> TextOrReason:
    """The one read `bash_file_writes` may make (a patch file it follows)."""
    return read_text_or_reason(path, errors=_DECODE_REPLACE)


@dataclass(frozen=True)
class _Violation:
    """What this call would do, and the Rule it violates."""

    rule_id: str
    note: str


class UpgradeApprovalGuardHandler(PreToolUseHandlerBase):
    """Deny an agent action that grants or bypasses the owner's upgrade approval."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.UPGRADE_APPROVAL_GUARD,
            priority=Priority.UPGRADE_APPROVAL_GUARD,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        self._rule_agent_action = Rule(
            rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
            blocked=(
                "an agent action that grants or forges the owner's upgrade approval "
                "(running `approve-upgrade`, writing/touching a marker under "
                "`upgrade-approvals/`, forging a venv `.daemon-version` stamp, or moving "
                "the `.claude/hooks-daemon` clone to another ref by hand)"
            ),
            why=(
                "Approving a breaking upgrade is the project OWNER's step, not the "
                "agent's — the gate exists so a human reads what changed before it happens"
            ),
            fix=(
                "Report the gate's reasons to the user and stop; the owner runs "
                "`hooks-daemon approve-upgrade <version> --from <previous>` in their own "
                "terminal (it requires a TTY and a typed confirmation phrase)"
            ),
            verbose=(
                "The upgrade gate's escalation path exists for the OWNER to read what a "
                "breaking upgrade changes and decide, in their own terminal — "
                "`hooks-daemon approve-upgrade <version> --from <previous>` requires an "
                "interactive TTY and a typed confirmation phrase precisely so an agent "
                "cannot answer the prompt on the owner's behalf.\n\n"
                "An agent must never reach the same outcome by another route: running "
                "`approve-upgrade` (or the standalone gate's `approve` subcommand) "
                "itself, writing or touching the `<version>.approved` marker under "
                "`upgrade-approvals/` by any Bash route or with Write/Edit/NotebookEdit, "
                "forging a venv's `.daemon-version` stamp (which would make the gate "
                "believe the target is already installed), or moving the "
                "`.claude/hooks-daemon` clone to another ref by hand (`checkout`, "
                "`switch`, `pull`, `merge`, `reset`, `rebase` and the like) or writing "
                "into its `.git/` (a redirect into `.git/config`, a hook, a tag), which "
                "installs a version the gate never read. Upgrade through "
                "`scripts/upgrade.sh`, which runs the gate first.\n\n"
                "What to do instead: report the gate's reasons to the user and STOP. "
                "The owner decides, in their own terminal."
            ),
        )
        self._rule_env_bypass = Rule(
            rule_id=RuleID.UPGRADE_APPROVAL_ENV_BYPASS,
            blocked=(
                f"a Bash command that sets `{ENV_VAR_UPGRADE_HANDOFF}`, or runs an upgrade "
                "with a variable that picks its interpreter, venv, flags or code, or "
                "passes `--uv <path>`"
            ),
            why="The upgrade and its pre-deploy gate run as shipped, not as an agent steers them",
            fix="Run the upgrade with no such variable set; if it cannot run, tell the user",
            verbose=(
                f"`{ENV_VAR_UPGRADE_HANDOFF}` names the one-shot handoff file "
                "`scripts/upgrade.sh` (Layer 1) writes for `scripts/upgrade_version.sh` "
                "(Layer 2). Layer 2 believes it only when its parent process wrote it, and "
                "a command that sets the variable and runs Layer 2 is that parent, so "
                "setting it anywhere impersonates Layer 1.\n\n"
                "On a command that runs the upgrade, these are denied too: "
                f"{', '.join(f'`{name}`' for name in _UPGRADE_STEERING_VARS)}, and "
                "exporting a shell function (`export -f`). Every spelling counts: "
                "naming one of those variables other than to read it (`read -r NAME`, "
                "`printf -v NAME`, `n=NAME`), `declare`/`typeset`/`local` with an `x` "
                "flag, `export` with a flag or a computed name, `set -a`, `eval`, and "
                "sourcing another file. The upgrade is recognised by "
                "what it is, not its file name: `upgrade.sh`, `upgrade_version.sh` or "
                "`upgrade_gate_standalone.py` by name; Layer 1's "
                "`--skip-reading-confirmation`; a script whose content carries the "
                "handoff variable, as every copy of Layer 1 and Layer 2 does; or a "
                'script that cannot be read (`bash "$tmp"`, stdin) run with the '
                "upgrade's arguments (`--project-root`, or the `.claude/hooks-daemon` "
                "clone). The variables choose the interpreter, the venv whose stamp is "
                "the installed version, the tools and shell code that run, or the "
                "forwarded flags. The gate itself takes none of them: it runs from fixed "
                "system locations under a cleared environment and hands its verdict back "
                "in a file bound to a one-time nonce. This rule keeps an agent from "
                "steering the rest of the upgrade.\n\n"
                "The uv that builds the venv is steered the same way: `--uv <path>` on "
                "the upgrade, and `PIPX_BIN_DIR`, are the human's to set, because what "
                "builds the venv decides what code the daemon runs.\n\n"
                "Run the upgrade with none of them set. If it genuinely needs one (a "
                "Python 3.11+ outside the system locations, or a uv outside the trusted "
                "locations, say), tell the user, who can run it themselves."
            ),
        )
        self._formatter = RuleFormatter()

    def get_rules(self) -> list[Rule]:
        """Return the two Rules backing this handler's deny paths (Decision B)."""
        return [self._rule_agent_action, self._rule_env_bypass]

    # ------------------------------------------------------------------
    # Single dispatch point (matches()/handle() must never disagree)
    # ------------------------------------------------------------------

    def _violation(self, hook_input: dict[str, Any]) -> _Violation | None:
        """What this call would do, or None when it is unaffected."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.BASH:
            return self._bash_violation(hook_input)
        if tool_name in (ToolName.WRITE, ToolName.EDIT):
            return self._file_path_violation(get_file_path(hook_input))
        if tool_name == ToolName.NOTEBOOK_EDIT:
            tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
            path = tool_input.get("notebook_path") if isinstance(tool_input, dict) else None
            return self._file_path_violation(path if isinstance(path, str) else None)
        return None

    def _file_path_violation(self, path: str | None) -> _Violation | None:
        if not path:
            return None
        surface = _guarded_write_target(path)
        if surface is None:
            return None
        return _Violation(
            rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
            note=f"Target: `{path}` — {surface}.",
        )

    def _bash_violation(self, hook_input: dict[str, Any]) -> _Violation | None:
        command = get_bash_command(hook_input)
        if not command:
            return None

        raw_cwd = hook_input.get(HookInputField.CWD)
        cwd = raw_cwd if isinstance(raw_cwd, str) and raw_cwd else None

        if _bash_sets_bypass_env_var(command, cwd):
            return _Violation(
                rule_id=RuleID.UPGRADE_APPROVAL_ENV_BYPASS,
                note=f"COMMAND: {command}",
            )

        if _bash_runs_guarded_action(command):
            return _Violation(
                rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
                note=f"COMMAND: {command}",
            )

        if _bash_moves_daemon_clone(command):
            return _Violation(
                rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
                note=(
                    f"COMMAND: {command}\n\nMoving `.claude/hooks-daemon` to another ref by "
                    "hand installs that version without the pre-deploy gate. Run the "
                    "upgrade through `scripts/upgrade.sh`, which runs the gate first."
                ),
            )

        writes = bash_file_writes(command, cwd, _read_text)
        destinations = list(writes.destinations) + _extra_write_targets(command)
        for destination in destinations:
            surface = _guarded_write_target(destination)
            if surface is not None:
                return _Violation(
                    rule_id=RuleID.UPGRADE_APPROVAL_AGENT_ACTION,
                    note=f"Target: `{destination}` — {surface}.",
                )
        return None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match any of the guarded agent actions."""
        return self._violation(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny, naming the owner's own remedy and the specific target/command."""
        violation = self._violation(hook_input)
        # Precondition: matches() found a violation on this same input.
        assert violation is not None, "Handler called without matches check"

        rule = (
            self._rule_env_bypass
            if violation.rule_id == RuleID.UPGRADE_APPROVAL_ENV_BYPASS
            else self._rule_agent_action
        )
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)

        message += f"\n\n{violation.note}"
        return GatingResult(decision=Decision.DENY, reason=message)

    def get_claude_md(self) -> str | None:
        return (
            "## upgrade_approval_guard — an agent cannot grant its own upgrade approval\n\n"
            "The pre-deploy upgrade gate's escalation path is the project OWNER's step: "
            "`hooks-daemon approve-upgrade <version> --from <previous>` requires an "
            "interactive TTY and a typed confirmation phrase, run in the owner's own "
            "terminal. An agent cannot answer that prompt, and this handler denies "
            "every other route to the same outcome:\n\n"
            "1. Running `approve-upgrade` itself (any spelling: `bin/hooks-daemon`, a "
            "path-qualified copy, or `python -m` plus the dotted "
            "`claude_code_hooks_daemon.daemon.cli` module path), or the standalone "
            "gate's own `upgrade_gate_standalone.py approve` subcommand.\n"
            "2. Writing the `<version>.approved` marker under `upgrade-approvals/` by "
            "any Bash route (`touch`, a redirect, `tee`, `cp`/`mv`, `mkdir` of the "
            "directory) or with Write/Edit/NotebookEdit.\n"
            "3. Assigning, exporting or `env`-setting `HOOKS_DAEMON_UPGRADE_HANDOFF`, "
            "which impersonates the upgrade's Layer 1 (`scripts/upgrade.sh`); or, on a "
            "command that runs the upgrade, setting a variable that picks its "
            "interpreter, venv, tools, flags, pass state, git view or code: "
            f"{', '.join(f'`{name}`' for name in _UPGRADE_STEERING_VARS)}, or "
            "exporting a shell function. Any spelling counts: naming one of those "
            "variables other than to read it (`read -r NAME`, `printf -v NAME`, "
            "`n=NAME`), `declare`/`typeset`/`local` with an `x` flag, `export` with a "
            "flag or a computed name, passing `--uv <path>` to the upgrade, and — on a "
            "command that runs the upgrade — "
            "`set -a`, `eval` or sourcing another file. The upgrade is recognised by "
            "what it is, not its file name: `upgrade.sh`/`upgrade_version.sh`/"
            "`upgrade_gate_standalone.py` by name, `--skip-reading-confirmation`, a "
            "script carrying `HOOKS_DAEMON_UPGRADE_HANDOFF`, or an unreadable script "
            '(`bash "$tmp"`) run with `--project-root` or the daemon clone as an '
            "argument. Run the upgrade with none of them set.\n"
            "4. Forging a venv's `.daemon-version` stamp under `untracked/venv*/`, by "
            "any of the routes in (2).\n"
            "5. Moving the `.claude/hooks-daemon` clone to another ref by hand "
            "(`git -C .claude/hooks-daemon checkout|switch|pull|merge|reset|rebase ...`), "
            "or writing into its `.git/` (config, hooks, refs): that installs a version "
            "the gate never read. Upgrade through `scripts/upgrade.sh`; fetching, "
            "`show`, `log` and `describe` are fine.\n\n"
            "**If you hit this**: report the gate's reasons to the user and STOP. Do "
            "not retry with a different spelling — ask the owner to run the approval "
            "command themselves.\n\n"
            "**Never denied**: reading — `ls`/`cat`/`stat`/`grep`/`find ... -print`/"
            "`test -f` over an approvals path or a version stamp, and merely reading "
            'the env var (`echo "$VAR"`, `grep VAR file`). Mentioning '
            "`approve-upgrade` inside a `git commit` message, non-executing "
            "`echo`/`printf` prose, a `grep` search, or a quoted-delimiter heredoc body "
            "written to a file is not denied either — an `echo`/`printf` argument that "
            "can genuinely EXECUTE something (a live `$(...)`/backtick substitution) is "
            "the one exception, and is scanned like any other command."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the upgrade approval guard."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Block an agent running approve-upgrade itself",
                command="bin/hooks-daemon approve-upgrade 99.0.0 --from 1.0.0",
                dispatch_as_bash=True,
                description=(
                    "An agent invoking the owner-only `approve-upgrade` subcommand is "
                    "denied before it can run (Plan 00376 review finding MAJOR 4)."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"approve-upgrade"],
                safety_notes="Denied before execution; the version is a dummy that cannot exist.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Block forging the upgrade-approval marker with touch",
                command="touch untracked/upgrade-approvals/99.0.0.approved",
                dispatch_as_bash=True,
                description="Writing the marker directly, bypassing the TTY prompt, is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"upgrade-approvals"],
                safety_notes="Denied before execution; no file is created.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Block exporting the Layer 1 handoff variable",
                command=f"export {ENV_VAR_UPGRADE_HANDOFF}=/tmp/handoff",
                dispatch_as_bash=True,
                description="Impersonating the upgrade's Layer 1 by hand is denied.",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"Layer 1"],
                safety_notes="Denied before execution; no shell state changes.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Allow reading an approval marker",
                command="cat untracked/upgrade-approvals/99.0.0.approved",
                dispatch_as_bash=True,
                description="A read-only reference to the approvals directory is never denied.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read of a file that does not exist; the shell reports the error, not the guard.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
