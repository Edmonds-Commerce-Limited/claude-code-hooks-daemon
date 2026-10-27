"""Config-driven generation of deployed hook forwarder scripts (Plan 00290).

The deployed ``.claude/hooks/<event>`` forwarder scripts are, today, a plain
1:1 copy of this repository's own ``.claude/hooks/*`` (see
``install/client_owned_assets.py`` and ``scripts/install/hooks_deploy.sh``).
Plan 00290 adds a relay hot path, on by default: unless
``daemon.transport.relay_enabled`` is false, each deployed forwarder gains a pure-builtin guard block (no subshell
spawns) that execs the static Rust relay binary directly against its per-event
socket, falling back to the untouched legacy body (``--no-relay`` re-entry) on
any failure to connect.

See ``CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md``
§6.1 for the binding guard-block contract this module implements verbatim.

With an explicit ``relay_enabled: false`` (and ``nc_enabled`` off)
:func:`generate_forwarder_content` returns its input completely unchanged —
the deployed file is the plain legacy forwarder, the opt-out transport.
"""

from __future__ import annotations

import argparse
import logging
import re
import string
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config, TransportConfig
from claude_code_hooks_daemon.constants import DaemonPath, Timeout
from claude_code_hooks_daemon.constants.events import (
    STATUS_LINE_JSON_KEY,
    EventIDMeta,
    raw_stdout_bash_keys,
    relay_ineligible_bash_keys,
    wired_event_metas,
)
from claude_code_hooks_daemon.constants.protocol import HookInputField, RawTextReply
from claude_code_hooks_daemon.daemon.paths import (
    event_socket_dir_is_fallback,
    get_event_socket_dir_from_untracked,
    get_untracked_dir,
)
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue

#: The line every current forwarder sources init.sh through. The guard block
#: is inserted directly above this line (DESIGN §6.1) — it is the anchor that
#: makes generation a pure text transform rather than a bash-shape assumption.
INIT_SH_ANCHOR: str = 'source "$SCRIPT_DIR/../init.sh"\n'

INIT_PARSE_GUARD_HEADER: Final[str] = "# --- init.sh parse guard (generated; Plan 00552) ---\n"
INIT_PARSE_GUARD_FOOTER: Final[str] = "# --- end init.sh parse guard ---\n"
_INIT_PARSE_GUARD_PATTERN = re.compile(
    re.escape(INIT_PARSE_GUARD_HEADER) + r".*?" + re.escape(INIT_PARSE_GUARD_FOOTER), re.DOTALL
)

#: The CLI verb that restores a broken install from a terminal (Plan 00552).
REPAIR_INSTALL_VERB: Final[str] = "repair-install"

#: What the parse guard tells the user to do. It sits inside a double-quoted
#: bash string, so it must hold no quote, dollar, backtick or backslash. The
#: client wrapper path is relative to the project root, where the user runs it.
INIT_REPAIR_HINT: Final[str] = (
    f"run .claude/hooks-daemon/bin/hooks-daemon {REPAIR_INSTALL_VERB} from the project root"
)

#: Carries the daemon root to hooks-relay. Twin of ``DAEMON_ROOT_ENV`` in
#: relay/hooks_relay.rs.
RELAY_DAEMON_ROOT_ENV: Final[str] = "HOOKS_DAEMON_RELAY_DAEMON_ROOT"

#: Set by the relay guard when a daemon is listening but the relay binary
#: cannot run, naming that binary; init.sh captures it into the request so the
#: daemon warns on the answer (Plan 00529 Task 2c).
RELAY_UNUSED_ENV: Final[str] = "HOOKS_DAEMON_RELAY_UNUSED"

_GUARD_HEADER = "# --- relay hot path (generated; Plan 00290) ---\n"
_GUARD_FOOTER = "# --- end relay hot path ---\n"

#: Events whose ``bash_key`` the relay guard must NEVER be applied to, at any
#: config — derived from :func:`constants.events.relay_ineligible_bash_keys`,
#: the single typed source (:attr:`EventIDMeta.relay_eligible`). Today this
#: is ``raw_stdout`` events (StatusLine, WorktreeCreate — the relay's pure
#: byte pump cannot perform the client-side JSON-unwrap ``response_mode``
#: needs) and Stop/SubagentStop (``forward_stop_event``'s client-side
#: ``decision=block`` -> exit-code-2 translation the relay has no equivalent
#: for — Plan 00101 Phase 9). Bypassing either would be a real safety/
#: correctness regression (Plan 00290 dogfood field report, commit 9d353fd3
#: EMERGENCY suspension), so this set is computed from the catalogue rather
#: than hand-maintained here — a future catalogue edit can never drift from
#: it silently. See DESIGN-socket-relay.md §1.1.
RELAY_EXCLUDED_EVENT_FILE_NAMES: frozenset[str] = relay_ineligible_bash_keys()

#: Events whose stdout Claude Code reads as a RAW value (a worktree path, the
#: status text) rather than as a JSON decision — derived from
#: :attr:`EventIDMeta.raw_stdout` via :func:`constants.events.raw_stdout_bash_keys`.
#: Their daemon-down branch is rewritten by :func:`apply_raw_stdout_daemon_down`.
RAW_STDOUT_EVENT_FILE_NAMES: frozenset[str] = raw_stdout_bash_keys()

logger = logging.getLogger(__name__)

#: Every wired event's metadata, indexed by ``bash_key``. Built once at import
#: rather than per render: the catalogue is a module constant, and rebuilding
#: the index inside the renderer walked it again for every generated forwarder.
_METAS_BY_BASH_KEY: Final[dict[str, EventIDMeta]] = {m.bash_key: m for m in wired_event_metas()}

#: Characters that mean something to bash inside a double-quoted string. The
#: backslash is escaped FIRST, so the escapes added for the others are not
#: themselves re-escaped.
_SHELL_DOUBLE_QUOTE_ESCAPES: Final[tuple[tuple[str, str], ...]] = (
    ("\\", "\\\\"),
    ('"', '\\"'),
    ("$", "\\$"),
    ("`", "\\`"),
)


def _escape_for_double_quotes(value: str) -> str:
    """Render ``value`` safe to interpolate into a double-quoted shell string.

    The catalogue is an internal constant, so nothing here is hostile input.
    It is escaped anyway because the failure would be silent and remote: an
    entry gaining a quote emits a forwarder that does not parse, and one
    gaining a backtick or ``$`` emits a forwarder that runs a command
    substitution every time the daemon is down (Plan 00364 Task 2.5).
    """
    for raw, escaped in _SHELL_DOUBLE_QUOTE_ESCAPES:
        value = value.replace(raw, escaped)
    return value


#: The variable init.sh sets to name a specific daemon-down state for a display
#: line; the forwarder falls back to the catalogue's marker when it is unset.
_STATUS_DOWN_TEXT_VAR = "_HOOKS_DAEMON_STATUS_DOWN_TEXT"

#: The daemon-down stanza every forwarder opens with. Matches the whole
#: ``if ! ensure_daemon; then ... fi`` block (its body is whatever the source
#: carries — the legacy ``emit_hook_error ...; exit 0`` stanza, or an earlier
#: rendering of the raw-stdout branch) so the rewrite is idempotent.
_ENSURE_DAEMON_BLOCK_PATTERN = re.compile(
    r"^if ! (?:_HOOKS_DAEMON_NONBLOCKING_START=true )?ensure_daemon; then\n"
    r"(?:(?!^fi\n).*\n)*?^fi\n",
    re.MULTILINE,
)

#: The variable init.sh sets to name its own loading line; the forwarder falls
#: back to the catalogue's ``daemon_loading_stdout`` when it is unset.
_STATUS_LOADING_TEXT_VAR = "_HOOKS_DAEMON_STATUS_LOADING_TEXT"


def _render_raw_stdout_daemon_down_block(event_file_name: str) -> str:
    """The daemon-down branch a ``raw_stdout`` forwarder must carry.

    Claude Code reads this hook's stdout raw, so the branch never writes JSON
    there. What it does write is the catalogue's
    :attr:`EventIDMeta.daemon_down_stdout` — nothing for a parsed value
    (``WorktreeCreate``), a visible marker for a display line
    (``StatusLine``). The diagnostic goes to stderr (the same ``HOOKS DAEMON
    ERROR [type]`` line ``emit_hook_error`` logs) and the exit is the event's
    :attr:`EventIDMeta.daemon_down_exit_code` — non-zero for a value, so the
    hook is "not handled" rather than answered with a JSON object, and zero
    for a display line, which Claude Code would otherwise not render.
    """
    meta = _METAS_BY_BASH_KEY[event_file_name]
    if meta.daemon_down_stdout:
        # init.sh may name a more specific outage (a checkout that needs
        # provisioning, Plan 00477) in _HOOKS_DAEMON_STATUS_DOWN_TEXT; the
        # catalogue's marker is the default.
        marker = _escape_for_double_quotes(meta.daemon_down_stdout)
        expansion = "{" + _STATUS_DOWN_TEXT_VAR + ":-" + marker + "}"
        stdout_lines = (
            "    # This stdout is a DISPLAY line, so the outage stays visible.\n"
            f'    echo "${expansion}"\n'
        )
    else:
        stdout_lines = "    # This stdout is parsed as a VALUE, so nothing may be printed.\n"
    guard = "ensure_daemon"
    loading_lines = ""
    if meta.daemon_loading_stdout:
        # Plan 00495 Task 2.7: a display line never waits out a daemon start.
        # The start carries on in the background; this hook answers "loading".
        loading = _escape_for_double_quotes(meta.daemon_loading_stdout)
        loading_expansion = "{" + _STATUS_LOADING_TEXT_VAR + ":-" + loading + "}"
        guard = "_HOOKS_DAEMON_NONBLOCKING_START=true ensure_daemon"
        loading_lines = (
            '    if [[ "${_HOOKS_DAEMON_STARTING:-false}" == "true" ]]; then\n'
            "        # Still starting, not failed: answered, so exit 0.\n"
            f'        echo "${loading_expansion}"\n'
            "        exit 0\n"
            "    fi\n"
        )
    return (
        f"if ! {guard}; then\n"
        "    # raw_stdout event (generated; Plan 00189): Claude Code reads this\n"
        "    # hook's stdout RAW, so a JSON error here would be taken literally.\n"
        f"{loading_lines}"
        "    # Diagnostic on stderr; the exit code is the event's (a value: non-zero =\n"
        "    # not handled; a display line: 0, as Claude Code blanks a failing one).\n"
        f"{stdout_lines}"
        f'    echo "HOOKS DAEMON ERROR [daemon_startup_failed]: {meta.json_key} hook: '
        "failed to start hooks daemon. Use the hooks-daemon skill to check logs "
        '(Skill tool: skill=hooks-daemon, args=logs)" >&2\n'
        f"    exit {meta.daemon_down_exit_code}\n"
        "fi\n"
    )


def apply_raw_stdout_daemon_down(source_content: str, event_file_name: str) -> str:
    """Rewrite the daemon-down stanza of a ``raw_stdout`` forwarder (Plan 00189).

    For an event in :data:`RAW_STDOUT_EVENT_FILE_NAMES` the first
    ``if ! ensure_daemon; then ... fi`` block is replaced with
    :func:`_render_raw_stdout_daemon_down_block` (stdout carries only the
    event's ``daemon_down_stdout``, never JSON); every other event, and a
    source with no such block, is returned unchanged. Idempotent, and applied
    at every config (it is a correctness property of the event, not a
    transport option), so a stale deployed forwarder is corrected on the next
    regeneration and the tracked source stays in generated form.
    """
    if event_file_name not in RAW_STDOUT_EVENT_FILE_NAMES:
        return source_content
    rendered = _render_raw_stdout_daemon_down_block(event_file_name)
    return _ENSURE_DAEMON_BLOCK_PATTERN.sub(lambda _m: rendered, source_content, count=1)


def build_init_parse_guard_block(event_file_name: str) -> str:
    """The block that makes a forwarder fail open when ``init.sh`` does not parse.

    A conflicted or truncated ``init.sh`` makes ``source`` die with bash's
    syntax-error status 2, which Claude Code reads as BLOCK for every event.
    ``bash -n`` checks the file first; on failure the forwarder answers
    non-blocking (exit 0, or the event's own ``daemon_down_exit_code`` for a
    ``raw_stdout`` event) and names the file and the repair step.

    The answer is built from bash builtins only, because ``init.sh`` and its
    ``emit_hook_error`` are exactly what cannot be trusted here. A JSON event
    gets ``{"systemMessage": ...}``; a ``raw_stdout`` display line gets the
    text; a ``raw_stdout`` value gets nothing on stdout. The ``bash -n``
    diagnostic is captured into a variable and sent to stderr, never discarded.
    """
    meta = _METAS_BY_BASH_KEY[event_file_name]
    message = (
        f"hooks daemon: $_ip_file does not parse (merge conflict markers?), "
        f"so hooks are not running. Repair: {INIT_REPAIR_HINT}."
    )
    if not meta.raw_stdout:
        answer = (
            r'    _ip_json="${_ip_msg//\\/\\\\}"; _ip_json="${_ip_json//\"/\\\"}"' + "\n"
            r"""    printf '{"systemMessage":"%s"}\n' "$_ip_json" """.rstrip() + "\n"
        )
    elif meta.daemon_down_stdout:
        answer = r"""    printf '⚠ %s\n' "$_ip_msg" """.rstrip() + "\n"
    else:
        answer = "    # This stdout is parsed as a VALUE, so nothing may be printed.\n"
    return (
        INIT_PARSE_GUARD_HEADER
        + '_ip_file="$SCRIPT_DIR/../init.sh"\n'
        + 'if ! _ip_err="$(bash -n "$_ip_file" 2>&1)"; then\n'
        + f'    _ip_msg="{message}"\n'
        + '    echo "HOOKS DAEMON ERROR [init_sh_unparseable]: $_ip_msg $_ip_err" >&2\n'
        + answer
        + f"    exit {meta.daemon_down_exit_code if meta.raw_stdout else 0}\n"
        + "fi\n"
        + "unset _ip_file _ip_err\n"
        + INIT_PARSE_GUARD_FOOTER
    )


def apply_init_parse_guard(source_content: str, event_file_name: str) -> str:
    """Strip any parse guard, then insert a fresh one directly above the ``init.sh`` source line.

    Idempotent. A source without the anchor (a non-standard forwarder shape) is
    returned without a guard rather than guessing an insertion point.
    """
    stripped = _INIT_PARSE_GUARD_PATTERN.sub("", source_content)
    if INIT_SH_ANCHOR not in stripped:
        return stripped
    guard = build_init_parse_guard_block(event_file_name)
    return stripped.replace(INIT_SH_ANCHOR, guard + INIT_SH_ANCHOR, 1)


def _default_relay_binary_path(untracked_dir: Path) -> str:
    """``{untracked}/bin/hooks-relay`` — the default when unoverridden (design §4)."""
    return str(untracked_dir / "bin" / "hooks-relay")


def deployed_hooks_dir(project_root: Path) -> str:
    """``<project_root>/.claude/hooks/`` — where a deployed forwarder lives.

    Trailing slash included: it is a PREFIX the guard compares
    ``${BASH_SOURCE[0]}`` against, and without it ``/proj/.claude/hooks-old/``
    would match too.
    """
    return f"{project_root}/.claude/hooks/"


def _checkout_guard_open(project_root: Path, *, honour_no_relay: bool) -> str:
    """The ``if`` line that confines a generated block to ONE checkout.

    The condition tests ``${BASH_SOURCE[0]}`` against :func:`deployed_hooks_dir`
    (see :func:`build_relay_guard_block` for why), and, for the relay guard,
    also lets ``--no-relay`` re-entry skip it.
    """
    hooks_dir = _escape_for_double_quotes(deployed_hooks_dir(project_root))
    no_relay = '"${1:-}" != "--no-relay" && ' if honour_no_relay else ""
    return f'if [[ {no_relay}"${{BASH_SOURCE[0]}}" == "{hooks_dir}"* ]]; then\n'


#: "Aa Bb ... Zz": the table the generated lowercase loop walks.
_UPPER_LOWER_PAIRS = " ".join(f"{c.upper()}{c}" for c in string.ascii_lowercase)


def _events_dir_lines(untracked_dir: Path) -> list[str]:
    """Bash lines that set ``_rl_dir`` and ``_rl_events_dir`` with no spawn.

    Shared by the relay guard and the status fast path so both name the same
    per-event socket directory; the lines' shapes are what
    :func:`recorded_untracked_dir` reads back.
    """
    lines = [f'    _rl_dir="{_escape_for_double_quotes(str(untracked_dir))}"\n']
    if event_socket_dir_is_fallback(untracked_dir):
        resolved_events_dir = get_event_socket_dir_from_untracked(untracked_dir)
        # Test-isolation fix (Plan 00290 Phase 6 dogfood finding), preserved
        # in the fallback case too: still `${VAR:-default}` parameter
        # expansion, zero spawns, so a test fixture can still redirect this.
        lines.append(f'    _rl_events_dir="${{HOOKS_DAEMON_EVENTS_DIR:-{resolved_events_dir}}}"\n')
    else:
        # Lowercased with parameter expansion only, one upper/lower pair per
        # pass: `${v,,}` is bash 4+ and macOS ships /bin/bash 3.2, where the
        # bad substitution would exit the forwarder before it judges anything.
        lines.append('    _rl_sfx="-${HOSTNAME:-localhost}"; _rl_sfx="${_rl_sfx// /-}"\n')
        lines.append('    if [[ "$_rl_sfx" == *[[:upper:]]* ]]; then\n')
        lines.append(f"        for _rl_c in {_UPPER_LOWER_PAIRS}; do\n")
        lines.append('            _rl_sfx="${_rl_sfx//${_rl_c:0:1}/${_rl_c:1:1}}"\n')
        lines.append("        done\n")
        lines.append("    fi\n")
        lines.append('    _rl_events_dir="${HOOKS_DAEMON_EVENTS_DIR:-$_rl_dir/events$_rl_sfx}"\n')
    return lines


def build_relay_guard_block(
    event_file_name: str,
    transport: TransportConfig,
    untracked_dir: Path,
    project_root: Path,
) -> str:
    """Render the relay hot-path guard block for one forwarder.

    Pure bash builtins only — zero subshells, zero external spawns — so the
    guard costs microseconds when the relay binary/socket are absent (the
    common case even with the rung enabled but not yet deployed/running).

    Args:
        event_file_name: The kebab-case forwarder basename (identical to the
            ``.claude/hooks/`` filename and the per-event socket filename),
            e.g. ``"pre-tool-use"``.
        transport: The resolved transport config (``relay_enabled`` is not
            consulted here — the caller decides whether to call this at all).
        untracked_dir: The project's daemon untracked directory, already
            resolved for install mode (self-install vs ``.claude/hooks-daemon/``)
            — baked in as a literal absolute path, never computed at hook-run
            time.
        project_root: The checkout this forwarder is generated FOR. Not
            derivable from ``untracked_dir`` (a client install puts that three
            levels down, at ``<root>/.claude/hooks-daemon/untracked``), so it
            is an argument rather than an inference.

    Returns:
        The guard block text, newline-terminated, ready to be inserted
        directly above :data:`INIT_SH_ANCHOR`.

    **One guard belongs to ONE checkout (Plan 00364 Task 5.1)**: every path
    here is a literal, which is what makes the hot path free — and what makes
    a COPY of the file dangerous. A git worktree inherits the tracked
    forwarder verbatim, so its ``.claude/hooks/pre-tool-use`` dialled the main
    checkout's relay socket and was answered by the main checkout's daemon,
    with the worktree's own config and project handlers never consulted. The
    guard therefore also tests ``${BASH_SOURCE[0]}`` — the file bash is
    actually executing — against :func:`deployed_hooks_dir` for
    ``project_root``. A forwarder running from anywhere else falls through to
    ``init.sh``, which computes that checkout's own project-scoped socket.
    Bash builtins throughout, so this costs no spawn; the cost of a false
    negative (a hook invoked by a path that does not match the literal, e.g.
    through a symlinked root) is one legacy-transport round trip, never a
    wrong answer.

    **Events-dir three-way agreement (Plan 00290 F3 fix)**: the events
    directory is normally computed DYNAMICALLY in bash
    (``$_rl_dir/events$_rl_sfx``, using bash's own ``$HOSTNAME`` at hook-run
    time) so a project checkout shared across multiple hosts over NFS gets a
    correctly host-isolated path on every host without redeployment. But on
    a deeply-nested standard client layout that dynamic path can itself
    exceed the AF_UNIX length limit for most event names — silently inert
    (canary-observed). When ``paths.event_socket_dir_is_fallback`` says the
    daemon's own bind decision (``paths.get_event_socket_dir_from_untracked``)
    would use its short fallback root instead, this function BAKES that
    same resolved path as the guard's literal default — computed once, at
    generation time, on the deploying host. This is the one case where the
    dynamic-per-host guarantee is knowingly given up: a project that is
    BOTH multi-host-NFS-shared AND deep enough to overflow must either set
    ``HOOKS_DAEMON_EVENTS_DIR`` per host or accept a shared fallback path
    (still correct — the fallback root is keyed by project, not by host —
    just not host-isolated in that narrow combination).
    """
    relay_binary = transport.relay_binary or _default_relay_binary_path(untracked_dir)
    # An event with its own budget (Plan 00512: the worktree events) waits for
    # it, whatever the transport timeout says; every other event waits for
    # `transport.timeout_seconds`.
    json_key = _METAS_BY_BASH_KEY[event_file_name].json_key
    event_wait = {str(e): wait for e, wait in Timeout.EVENT_CLIENT_WAIT.items()}.get(json_key, 0)
    timeout_ms = max(transport.timeout_seconds, event_wait) * 1000
    # Escaped for the same reason `_escape_for_double_quotes` exists, and with
    # more force: its docstring notes the CATALOGUE is an internal constant and
    # escapes it anyway, because the failure is silent and remote -- a value
    # carrying a backtick or `$` emits a forwarder that runs a command
    # substitution every time the daemon is down. A path is not an internal
    # constant; it is wherever the user cloned the repository.
    #
    # Both sites below are a plain double-quoted string, which is exactly the
    # context this escaper is for. In the `==` comparison the path sits INSIDE
    # the quotes and only the trailing `*` is a pattern, so glob characters in
    # the path are already literal and need nothing further.
    #
    # The two `${VAR:-default}` interpolations further down are NOT escaped
    # here: that context takes `}` as a terminator and this escaper has no rule
    # for it, so applying it there would leave them broken while looking fixed.
    # See DECISION-forwarder-interpolation-contexts.md.
    lines = [
        _GUARD_HEADER,
        _checkout_guard_open(project_root, honour_no_relay=True),
        *_events_dir_lines(untracked_dir),
    ]
    lines.append(f'    _rl_bin="${{HOOKS_DAEMON_RELAY_BINARY:-{relay_binary}}}"\n')
    lines.append(f'    _rl_sock="$_rl_events_dir/{event_file_name}.sock"\n')
    # No socket means no daemon: the bash path below is the start-up path and
    # reports loudly itself. With a socket, a relay that cannot run falls
    # through with RELAY_UNUSED_ENV set, so every answer names it (Plan 00529
    # Task 2c). Only what the kernel's execve itself runs (an ELF file or a `#!`
    # script) is exec'd: on ENOEXEC bash runs the file as a shell script
    # instead. errexit is lifted around the exec because
    # under `set -e` a failed exec exits 1 even with execfail and inside `if`.
    lines.append('    if [[ -S "$_rl_sock" ]]; then\n')
    lines.append('        _rl_magic=""\n')
    lines.append('        if [[ -x "$_rl_bin" && -f "$_rl_bin" ]] \\\n')
    # `read -n` (bash 2.04+), not `-N` (bash 4): on 3.2 `-N` is an invalid option.
    # IFS is emptied so a leading space is not stripped from the four bytes.
    lines.append('            && IFS= read -r -n 4 _rl_magic < "$_rl_bin" \\\n')
    lines.append(
        "            && [[ \"$_rl_magic\" == $'\\x7fELF' || \"$_rl_magic\" == '#!'* ]]; then\n"
    )
    lines.append('            _rl_opts="$-"\n')
    lines.append("            shopt -s execfail\n")
    lines.append("            set +e\n")
    # The daemon root is the untracked dir's parent in both install modes
    # (paths.get_untracked_dir). The relay names this install's launcher by
    # it, with the rule init.sh's carve-out applies (Plan 00466 round 4, P3-2).
    daemon_root = _escape_for_double_quotes(str(untracked_dir.parent))
    # The exec lives in its own function: with execfail a failed exec RETURNS
    # and the script carries on to the fallback below, which shellcheck's
    # SC2093 cannot know. A function whose last command is the exec ends where
    # the exec does, so there is nothing after it for the warning to name.
    lines.append("            _rl_exec_relay() {\n")
    lines.append(f'                {RELAY_DAEMON_ROOT_ENV}="{daemon_root}" \\\n')
    lines.append('                    exec "$_rl_bin" "$_rl_sock" --fallback "$1" \\\n')
    lines.append(f'                    --timeout-ms "{timeout_ms}"\n')
    lines.append("            }\n")
    lines.append('            _rl_exec_relay "${BASH_SOURCE[0]}"\n')
    lines.append("            shopt -u execfail\n")
    lines.append('            if [[ "$_rl_opts" == *e* ]]; then set -e; fi\n')
    lines.append("        fi\n")
    lines.append(f'        {RELAY_UNUSED_ENV}="$_rl_bin"\n')
    lines.append("    fi\n")
    lines.append("fi\n")
    lines.append(_GUARD_FOOTER)
    return "".join(lines)


#: Matches a complete relay guard block, header through footer inclusive
#: (DOTALL so the block body's newlines are matched). The header/footer are
#: fixed literal marker comments emitted verbatim by
#: :func:`build_relay_guard_block`, so this match is exact regardless of
#: what the block's body contains (a foreign project's untracked-dir
#: literal, a stale timeout, a different events-dir — Plan 00290 F1/F2/F4
#: fix: stripping never needs to parse or understand the guard's content).
_GUARD_BLOCK_PATTERN = re.compile(
    re.escape(_GUARD_HEADER) + r".*?" + re.escape(_GUARD_FOOTER), re.DOTALL
)


#: The line the status fast path is inserted above: it must run before the
#: forwarder's first fork (``$(cd ... && pwd)``), let alone ``source init.sh``.
SCRIPT_DIR_ANCHOR: str = 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'

_FAST_PATH_HEADER = "# --- status fast path (generated; Plan 00542) ---\n"
_FAST_PATH_FOOTER = "# --- end status fast path ---\n"
_FAST_PATH_BLOCK_PATTERN = re.compile(
    re.escape(_FAST_PATH_HEADER) + r".*?" + re.escape(_FAST_PATH_FOOTER), re.DOTALL
)

#: The one forwarder that gets a fast path: the status line's ``bash_key``, taken
#: from the catalogue. The others answer a decision, not a display line.
STATUS_FAST_PATH_EVENT_FILE_NAME: Final[str] = next(
    m.bash_key for m in wired_event_metas() if m.json_key == STATUS_LINE_JSON_KEY
)

#: How long the fast path's client waits for the daemon. Short on purpose: past
#: it the legacy path asks again, and a status line must not stall on a busy
#: daemon.
_FAST_PATH_TIMEOUT_SECONDS: Final[int] = 2

#: ``hooks-relay --no-fallback`` exit codes (relay/hooks_relay.rs EXIT_CONNECT_FAIL and
#: EXIT_TIMEOUT): no daemon answered, and a daemon that did not reply in time.
_RELAY_EXIT_CONNECT_FAIL: Final[int] = 10
_RELAY_EXIT_TIMEOUT: Final[int] = 11

#: ``nc -U`` exits 1 for a refused connection. A silent listener hitting ``-w`` exits 0
#: with an empty reply, so nc cannot tell a timeout from a protocol fault.
_NC_EXIT_REFUSED: Final[int] = 1

#: A positive integer without leading zeros: valid JSON as it stands.
_FAST_PATH_DIGITS = "^[1-9][0-9]{0,8}$"


def strip_status_fast_path_block(source_content: str) -> str:
    """Remove any existing status fast-path block (strip-then-reapply, as for the relay guard)."""
    return _FAST_PATH_BLOCK_PATTERN.sub("", source_content)


def build_status_fast_path_block(
    transport: TransportConfig, untracked_dir: Path, project_root: Path
) -> str:
    """Render the status-line fast path: raw status text with no init.sh and no python.

    Pure bash builtins, plus the ONE client process it execs. It asks the
    status per-event socket for RAW text (``hooks_daemon_raw_text``) with the
    terminal size from ``COLUMNS``/``LINES``, and prints the reply once it has
    stripped the leading ``RawTextReply.SENTINEL`` and found text after it.

    No silent fallbacks. The ONE hand-off to the legacy path (stdin replayed)
    is "no daemon answered": no socket file, or a refused connection (relay
    exit 10, nc exit 1); the legacy start-up path starts the daemon and reports
    loudly. A payload that is not a JSON object is also handed off. Every other
    fault prints one red line naming the fault and the fix, and exits 0: a
    configured client that is missing or cannot do unix sockets, a timeout, any
    other client failure, an empty reply, a non-empty reply without the sentinel
    (an older daemon's JSON), a ``read`` fault.

    It uses only the client ``transport`` selects: the relay binary when
    ``relay_enabled``, else nc when ``nc_enabled`` (the install probe must have
    recorded ``HOOKS_DAEMON_NC_UNIX_CAPABLE=1``, read from the env file line by
    line, never sourced: it references variables that are unset here).

    The socket path is the relay guard's (:func:`_events_dir_lines`) and the
    block is confined to its own checkout the same way, so a forwarder copied
    into a worktree is inert. A wrong guess at the path can only fail the
    ``-S`` test or the connect, and then falls through.
    """
    sock = f'"$_rl_events_dir/{STATUS_FAST_PATH_EVENT_FILE_NAME}.sock"'
    sentinel = f"$'\\x{ord(RawTextReply.SENTINEL):02x}'"
    timeout_s = _FAST_PATH_TIMEOUT_SECONDS
    lines = [
        _FAST_PATH_HEADER,
        _checkout_guard_open(project_root, honour_no_relay=False),
        *_events_dir_lines(untracked_dir),
        f"    _sf_sock={sock}\n",
        "    # One red line naming the fault and its fix, then exit 0: the status line\n",
        "    # is the loud channel and nothing below falls back silently.\n",
        "    _sf_loud() { printf '\\033[31m%s\\033[0m\\n' \"$1\"; exit 0; }\n",
    ]
    if transport.relay_enabled:
        relay_binary = transport.relay_binary or _default_relay_binary_path(untracked_dir)
        refused, timed_out = _RELAY_EXIT_CONNECT_FAIL, _RELAY_EXIT_TIMEOUT
        lines += [
            f'    _rl_bin="${{HOOKS_DAEMON_RELAY_BINARY:-{relay_binary}}}"\n',
            '    if [[ ! -x "$_rl_bin" ]]; then\n',
            '        _sf_loud "⚠ hooks-relay missing or not executable ($_rl_bin):'
            ' run bin/hooks-daemon transport on"\n',
            "    fi\n",
        ]
        send = (
            '"$_rl_bin" "$_sf_sock" --no-fallback '
            f'--timeout-ms "{timeout_s * 1000}" <<< "$_sf_req"'
        )
    else:
        refused, timed_out = _NC_EXIT_REFUSED, None
        # Only the capability line of the env file is wanted; `case` on it is a
        # builtin, so reading it forks nothing.
        lines += [
            '    _sf_nc_ok="${HOOKS_DAEMON_NC_UNIX_CAPABLE:-0}"\n',
            '    _sf_env="${BASH_SOURCE[0]%/*}/../hooks-daemon.env"\n',
            '    if [[ -r "$_sf_env" ]]; then\n',
            '        while IFS= read -r _sf_line || [[ -n "$_sf_line" ]]; do\n',
            '            case "$_sf_line" in\n',
            "                'HOOKS_DAEMON_NC_UNIX_CAPABLE=\"1\"') _sf_nc_ok=1;;\n",
            "                'HOOKS_DAEMON_NC_UNIX_CAPABLE=\"0\"') _sf_nc_ok=0;;\n",
            "            esac\n",
            '        done < "$_sf_env"\n',
            "    fi\n",
            '    if [[ "$_sf_nc_ok" != "1" ]]; then\n',
            '        _sf_loud "⚠ nc cannot do unix sockets (HOOKS_DAEMON_NC_UNIX_CAPABLE=$_sf_nc_ok):'
            ' run bin/hooks-daemon transport status"\n',
            "    fi\n",
            "    if ! command -v nc > /dev/null; then\n",
            '        _sf_loud "⚠ nc not found on PATH: install it or run bin/hooks-daemon transport off"\n',
            "    fi\n",
        ]
        send = f'nc -U -N -w "{timeout_s}" "$_sf_sock" <<< "$_sf_req"'
    timeout_check = (
        []
        if timed_out is None
        else [
            f'                    if [[ "$_sf_rc" -eq {timed_out} ]]; then\n',
            f'                        _sf_loud "⚠ status timed out after {timeout_s}s (daemon busy)"\n',
            "                    fi\n",
        ]
    )
    raw = HookInputField.RAW_TEXT
    cols = HookInputField.TERMINAL_COLUMNS
    rows = HookInputField.TERMINAL_LINES
    lines += [
        '    if [[ -S "$_sf_sock" ]]; then\n',
        '        _sf_payload=""; _sf_rc=0\n',
        "        # read returns 1 at a normal EOF (no trailing NUL), above 1 on a real fault.\n",
        "        IFS= read -r -d '' _sf_payload || _sf_rc=$?\n",
        '        if [[ "$_sf_rc" -gt 1 ]]; then\n',
        '            _sf_loud "⚠ status line could not read its input (read status $_sf_rc)"\n',
        "        fi\n",
        '        _sf_req="${_sf_payload%"${_sf_payload##*[![:space:]]}"}"\n',
        '        _sf_req="${_sf_req#"${_sf_req%%[![:space:]]*}"}"\n',
        '        if [[ "$_sf_req" == "{"*"}" ]]; then\n',
        '            _sf_req="${_sf_req%\\}}"\n',
        '            _sf_req="${_sf_req%"${_sf_req##*[![:space:]]}"}"\n',
        '            if [[ "$_sf_req" != "{" ]]; then _sf_req+=","; fi\n',
        f"            _sf_req+='\"{raw}\":true'\n",
        f'            if [[ "${{COLUMNS:-}}" =~ {_FAST_PATH_DIGITS} ]]; then\n',
        f'                _sf_req+=",\\"{cols}\\":$COLUMNS"\n',
        "            fi\n",
        f'            if [[ "${{LINES:-}}" =~ {_FAST_PATH_DIGITS} ]]; then\n',
        f'                _sf_req+=",\\"{rows}\\":$LINES"\n',
        "            fi\n",
        '            _sf_req+="}"\n',
        '            _sf_reply=""; _sf_rc=0\n',
        f'            _sf_reply="$({send})" || _sf_rc=$?\n',
        "            # The ONE hand-off: no daemon answered. The start-up path below starts\n",
        "            # it and already reports loudly; every other outcome is judged here.\n",
        f'            if [[ "$_sf_rc" -ne {refused} ]]; then\n',
        *[line[4:] for line in timeout_check],
        '                if [[ "$_sf_rc" -ne 0 ]]; then\n',
        '                    _sf_loud "⚠ status client failed (exit $_sf_rc)"\n',
        "                fi\n",
        '                if [[ -z "$_sf_reply" ]]; then\n',
        f'                    _sf_loud "⚠ empty status reply (timed out after {timeout_s}s,'
        ' or protocol fault): run bin/hooks-daemon restart"\n',
        "                fi\n",
        f'                if [[ "$_sf_reply" != {sentinel}* ]]; then\n',
        '                    _sf_loud "⚠ daemon older than its forwarder:'
        ' run bin/hooks-daemon restart"\n',
        "                fi\n",
        f'                _sf_reply="${{_sf_reply#{sentinel}}}"\n',
        '                if [[ -z "$_sf_reply" ]]; then\n',
        '                    _sf_loud "⚠ empty status reply (sentinel only):'
        ' run bin/hooks-daemon restart"\n',
        "                fi\n",
        "                printf '%s\\n' \"$_sf_reply\"\n",
        "                exit 0\n",
        "            fi\n",
        "        fi\n",
        "        # Hand-off: give the legacy path the stdin it was owed.\n",
        '        exec 0<<< "$_sf_payload"\n',
        "    fi\n",
        "fi\n",
        _FAST_PATH_FOOTER,
    ]
    return "".join(lines)


def strip_relay_guard_block(source_content: str) -> str:
    """Remove any existing relay guard block from ``source_content``.

    Idempotent: content with no guard block is returned unchanged. This is
    the fix for Plan 00290 findings F1/F2/F4 (canary run 2) — the deployed
    forwarder a client receives is a copy of THIS repository's own
    ``.claude/hooks/*``, which (since this repo dogfoods the relay) already
    carries a guard block pointing at THIS repository's own paths. Without
    an unconditional strip first, that foreign guard survived every
    downstream config state: a disabled client config left it in place
    (F1 — proven to answer a client's hook request from the wrong project's
    daemon), an enabled client config left it un-rewritten because the
    idempotency check saw "a guard is already present" (F2), and disabling
    transport again never removed it (F4). Stripping FIRST, unconditionally,
    then re-applying per the CALLER's own config (see
    :func:`generate_forwarder_content`) makes the transform a single
    bidirectional operation that fixes all three: the result always reflects
    only the current config and the current project's own paths.
    """
    return _GUARD_BLOCK_PATTERN.sub("", source_content)


#: Stands in for the project root when two checkouts' forwarders are compared.
PROJECT_ROOT_PLACEHOLDER = "@@PROJECT_ROOT@@"

#: Absolute paths a forwarder may legitimately name on ANY machine. Anything
#: else surviving :func:`normalise_project_root` is machine-specific content the
#: comparison would otherwise hide — see :func:`surviving_absolute_paths`.
_PORTABLE_PATH_PREFIXES = ("/usr/", "/bin/", "/sbin/", "/etc/", "/dev/", "/proc/")

#: An absolute path as it appears in a shell script. Two conditions, and both
#: were added because a naive `/foo/bar` match reported ordinary shell as
#: machine-specific:
#:
#: - It must not FOLLOW a name character. `$_rl_dir/events` and
#:   `CLAUDE/LLM-INSTALL.md` are a variable expansion and a relative path; only
#:   their tail looks absolute.
#: - Its first component must contain an alphanumeric, so the `/-` inside
#:   `${_rl_sfx// /-}` — a substitution pattern, not a path — is not one.
_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.$])" r"/[A-Za-z0-9._+-]*[A-Za-z0-9][A-Za-z0-9._+-]*" r"(?:/[A-Za-z0-9._+-]+)*"
)

#: A path already rooted at the placeholder, INCLUDING its trailing components.
#: Removed whole before scanning, because leaving it would let the scanner match
#: its tail (`@@PROJECT_ROOT@@/untracked` → `/untracked`) and report an
#: already-normalised path as machine-specific.
_PLACEHOLDER_ROOTED_PATH = re.compile(
    re.escape(PROJECT_ROOT_PLACEHOLDER) + r"(?:/[A-Za-z0-9._+-]+)*"
)


def normalise_project_root(content: str, project_root: str) -> str:
    """Replace a checkout's own absolute root with a stable placeholder.

    The generated forwarders bake the project root as a literal, deliberately:
    ``build_relay_guard_block`` is a zero-spawn hot path that must not compute
    a path at hook-run time. That makes the artefact correct and
    machine-specific at once, so a byte comparison between two checkouts fails
    on the root alone.

    Normalising it lets the comparison stay EXACT on everything else. The
    surface is small enough to be safe: two distinct lines, in 27 of the 31
    tracked hook files (Plan 00250 Task 2.4c). Pair this with
    :func:`surviving_absolute_paths` so normalising one path cannot hide a
    second one appearing later.
    """
    return content.replace(project_root.rstrip("/"), PROJECT_ROOT_PLACEHOLDER)


#: The `_rl_dir="..."` assignment every relay guard opens with, which records
#: the untracked directory the forwarder was generated for.
_RECORDED_UNTRACKED_DIR = re.compile(r'^\s*_rl_dir="([^"]+)"', re.MULTILINE)

#: The guard's checkout test, which records the project root it was generated
#: for — the second literal a forwarder bakes (see `build_relay_guard_block`).
_RECORDED_PROJECT_ROOT = re.compile(r'\$\{BASH_SOURCE\[0\]\}" == "([^"]+)/\.claude/hooks/"\*')


def _one_recorded_value(
    hook_contents: dict[str, str], pattern: re.Pattern[str], what: str
) -> Path | None:
    """The single value ``pattern`` reads back out of every guarded forwarder.

    Shared by :func:`recorded_untracked_dir` and :func:`recorded_project_root`
    so "what the artefact records" and "what counts as the files disagreeing"
    cannot drift into two answers.

    Raises:
        AssertionError: if two forwarders record DIFFERENT values.
    """
    found: dict[str, str] = {}
    for name, content in hook_contents.items():
        match = pattern.search(content)
        if match:
            found[name] = match.group(1)
    if not found:
        return None

    distinct = sorted(set(found.values()))
    if len(distinct) > 1:
        raise AssertionError(
            f"the deployed forwarders disagree about the {what} "
            f"they were generated for: {distinct}. One has been hand-edited — "
            f"regenerate them all rather than reconciling by hand.\n{found}"
        )
    return Path(distinct[0])


def recorded_untracked_dir(hook_contents: dict[str, str]) -> Path | None:
    """The untracked dir the deployed forwarders say they were generated for.

    Comparing a tracked forwarder against a regeneration is only meaningful if
    both are generated for the SAME root — otherwise the comparison asserts that
    this checkout sits where the committed file's did, which no caller wants and
    which is false on every machine but one.

    Reading the root back out of the artefact lets the comparison stay exact and
    machine-independent. Safe because the recorded root is short: it keeps the
    generator on its dynamic events branch anywhere, with 54 characters of
    hostname headroom against a 64-character OS cap.

    Returns ``None`` when no forwarder carries a guard (relay disabled), so the
    caller falls back to the live project. Files without a guard —
    ``status-line``, ``stop``, ``subagent-stop``, ``worktree-create`` — are
    ignored rather than treated as disagreement.

    Raises:
        AssertionError: if two forwarders record DIFFERENT roots. That means one
            was hand-edited, and regenerating to match either would launder the
            edit the comparison exists to catch.
    """
    return _one_recorded_value(hook_contents, _RECORDED_UNTRACKED_DIR, "untracked directory")


def recorded_project_root(hook_contents: dict[str, str]) -> Path | None:
    """The checkout the deployed forwarders' relay guard belongs to.

    The guard bakes TWO absolute paths, and a caller that reads back only one
    of them re-makes the mistake :func:`recorded_untracked_dir` was written to
    fix: it silently assumes the other is this checkout's, which is true only
    on the machine that generated the artefact. Same contract as its sibling —
    ``None`` when no forwarder carries a guard, ``AssertionError`` when two
    disagree.
    """
    return _one_recorded_value(hook_contents, _RECORDED_PROJECT_ROOT, "project root")


def surviving_absolute_paths(content: str) -> list[str]:
    """Machine-specific absolute paths left after normalisation, if any.

    Without this, :func:`normalise_project_root` would be a blind spot: a third
    baked path added later would be compared away rather than caught. System
    paths (``/usr/bin/env`` and the like) are portable and excluded.
    """
    scannable = _PLACEHOLDER_ROOTED_PATH.sub("", content)
    return sorted(
        {
            match.group(0)
            for match in _ABSOLUTE_PATH.finditer(scannable)
            if not match.group(0).startswith(_PORTABLE_PATH_PREFIXES)
        }
    )


def unexpected_absolute_paths(content: str, baked_roots: Iterable[str | Path]) -> list[str]:
    """Absolute paths beyond the ones a forwarder is DESIGNED to bake.

    ``surviving_absolute_paths`` alone answers "what is left after normalising
    one root", which silently assumes the caller knows which root that is. A
    caller that reaches for the LIVE checkout gets the right answer only on the
    machine that generated the artefact — the same mistake Task 2.4c fixed in
    the comparison, repeated in the guard that watches it.

    Declaring the roots makes the assumption an argument. Pass every root the
    forwarders legitimately bake (the recorded untracked dir, and the live
    checkout — on one machine they are the same string); anything else absolute
    and non-portable that survives is a second baked path the byte comparison
    would hide.

    Roots are stripped longest-first so an overlapping pair (``/repo`` and
    ``/repo/untracked``) cannot leave the longer one's tail looking like a
    fresh absolute path.
    """
    normalised = content
    for root in sorted((str(root) for root in baked_roots), key=len, reverse=True):
        normalised = normalise_project_root(normalised, root)
    return surviving_absolute_paths(normalised)


#: Matches the single `send_request_stdin "Event" [mode]` or
#: `forward_stop_event "Event"` call line every deployed forwarder ends with.
#: Captures: (1) function name, (2) the already-quoted argument list.
_TRANSPORT_CALL_PATTERN = re.compile(
    r'^(send_request_stdin|forward_stop_event)((?: "[^"]*")+)$', re.MULTILINE
)


def append_nc_socket_arg(source_content: str, event_file_name: str, untracked_dir: Path) -> str:
    """Append the event's bash_key + resolved events-dir override as trailing
    literal args (design §6.2; events-dir override added by Plan 00295 Task
    2.5).

    ``send_request_stdin``/``forward_stop_event`` receive the PascalCase
    event name at runtime and have no way to derive the per-event socket's
    kebab-case filename from it without a spawn or a lookup table. Baking
    the filename in at generation time — exactly as :func:`build_relay_guard_block`
    bakes in the untracked dir — avoids both: ``send_request_stdin`` only
    ever needs to string-concatenate this literal onto the (already
    computed) untracked dir + hostname suffix to reach the socket.

    A SECOND trailing arg carries the resolved events directory, but only
    when :func:`~claude_code_hooks_daemon.daemon.paths.event_socket_dir_is_fallback`
    says the natural ``$_untracked_dir/events$_hostname_suffix`` path would
    overflow the AF_UNIX socket length limit for at least one wired event —
    the identical decision :func:`build_relay_guard_block` makes for its own
    ``_rl_events_dir``. The common (non-overflowing) case appends an empty
    string placeholder, so ``send_request_stdin`` keeps computing the
    dynamic path at hook-run time exactly as before (a project checkout
    shared across hosts over NFS still gets a correctly host-isolated path
    on every host). ``send_request_stdin`` itself still checks
    ``HOOKS_DAEMON_EVENTS_DIR`` FIRST, ahead of either this baked value or
    the dynamic default — an operator's own override always wins.

    A missing existing ``response_mode`` argument is filled with an empty
    string placeholder so the new arguments always land in a fixed position
    (args 3-4 for ``send_request_stdin``, args 2-3 for ``forward_stop_event``).

    Idempotent by POSITION, not by distance from the end: the bash_key always
    lands at a fixed index, so a call line already carrying it there keeps its
    prefix and has everything after it re-baked. Anything else is a stale bake
    (an older daemon appended the key with no events-dir arg beside it, or a
    forwarder was copied from another event) — same strip-then-reapply
    discipline the relay guard uses, and the reason a `transport relay on|off`
    toggle over already-deployed files converges instead of accumulating.
    """
    baked_events_dir = (
        str(get_event_socket_dir_from_untracked(untracked_dir))
        if event_socket_dir_is_fallback(untracked_dir)
        else ""
    )

    def _augment(match: re.Match[str]) -> str:
        func = match.group(1)
        existing_args = re.findall(r'"([^"]*)"', match.group(2))
        # send_request_stdin takes (event, response_mode, bash_key, events_dir);
        # forward_stop_event takes (event, bash_key, events_dir) — it has no
        # response_mode of its own, it passes "" through to send_request_stdin.
        key_index = 2 if func == "send_request_stdin" else 1
        if len(existing_args) > key_index and existing_args[key_index] == event_file_name:
            kept = existing_args[: key_index + 1]
        else:
            kept = existing_args[:key_index]
            kept.extend([""] * (key_index - len(kept)))
            kept.append(event_file_name)
        rendered = " ".join(f'"{arg}"' for arg in [*kept, baked_events_dir])
        return f"{func} {rendered}"

    return _TRANSPORT_CALL_PATTERN.sub(_augment, source_content, count=1)


def generate_forwarder_content(
    source_content: str,
    event_file_name: str,
    transport: TransportConfig,
    untracked_dir: Path,
    project_root: Path,
) -> str:
    """Generate the content to deploy for one hook forwarder (Task 4.1).

    Args:
        source_content: The canonical source forwarder content (this
            repository's own ``.claude/hooks/<event_file_name>``).
        event_file_name: The kebab-case forwarder basename, e.g.
            ``"pre-tool-use"``.
        transport: The resolved ``daemon.transport`` config.
        untracked_dir: The target project's resolved daemon untracked
            directory (install-mode aware).
        project_root: The target project's root — the checkout the relay
            guard will refuse to fire outside of (see
            :func:`build_relay_guard_block`).

    The relay guard is handled as a single STRIP-then-REAPPLY transform
    (Plan 00290 F1/F2/F4 fix), unconditionally:

    1. :func:`strip_relay_guard_block` removes any EXISTING guard block
       first, regardless of config — including one baked for a different
       project entirely (see that function's docstring for why this must
       never be conditional on the current config).
    2. Only then, iff ``transport.relay_enabled`` and ``event_file_name`` is
       not in :data:`RELAY_EXCLUDED_EVENT_FILE_NAMES` (``status-line``,
       ``worktree-create``, ``stop``, ``subagent-stop`` — see that
       constant's docstring) and the
       ``source init.sh`` anchor is present, a FRESH guard block
       (:func:`build_relay_guard_block`) is inserted directly above it,
       reflecting the caller's own ``untracked_dir``/config. If the anchor
       is absent (a non-standard forwarder shape), this half is skipped
       rather than guessing an insertion point.

    A source with no guard and a disabled config round-trips unchanged
    (strip is a no-op, nothing is re-added) — the default byte-identical
    guarantee still holds.

    Independently, ``transport.nc_enabled`` appends the event's bash_key as
    a trailing literal arg to the file's ``send_request_stdin``/
    ``forward_stop_event`` call (:func:`append_nc_socket_arg`). Applies to
    every event, including the two excluded from the relay guard — nc only
    changes the transport beneath ``send_request_stdin``, so
    ``forward_stop_event``'s own decision=block parsing still runs
    afterward regardless of which rung served the request.

    Also independently of config, a ``raw_stdout`` event's daemon-down
    stanza is rewritten by :func:`apply_raw_stdout_daemon_down` (Plan
    00189) so it never puts JSON on a stdout Claude Code reads raw — only
    the catalogue's per-event ``daemon_down_stdout`` text, if any.
    """
    result = apply_raw_stdout_daemon_down(strip_relay_guard_block(source_content), event_file_name)
    result = apply_init_parse_guard(result, event_file_name)
    # The relay hot path goes ABOVE the parse guard: a relayed hook never
    # sources init.sh, so it must not pay for `bash -n` on it.
    if (
        transport.relay_enabled
        and event_file_name not in RELAY_EXCLUDED_EVENT_FILE_NAMES
        and INIT_PARSE_GUARD_HEADER in result
    ):
        guard = build_relay_guard_block(event_file_name, transport, untracked_dir, project_root)
        result = result.replace(INIT_PARSE_GUARD_HEADER, guard + INIT_PARSE_GUARD_HEADER, 1)
    result = strip_status_fast_path_block(result)
    if (
        event_file_name == STATUS_FAST_PATH_EVENT_FILE_NAME
        and (transport.relay_enabled or transport.nc_enabled)
        and SCRIPT_DIR_ANCHOR in result
    ):
        fast_path = build_status_fast_path_block(transport, untracked_dir, project_root)
        result = result.replace(SCRIPT_DIR_ANCHOR, fast_path + SCRIPT_DIR_ANCHOR, 1)
    if transport.nc_enabled:
        result = append_nc_socket_arg(result, event_file_name, untracked_dir)
    return result


def load_transport_config(project_root: Path) -> TransportConfig:
    """Resolve the effective ``daemon.transport`` config for ``project_root``.

    A missing config file resolves to the pure defaults (relay on, since the
    relay is the shipped default). A key absent from an existing file also
    takes the default; an explicit ``relay_enabled: false`` is respected.
    A config file that EXISTS but fails to parse (malformed YAML) or fails
    pydantic validation cannot show whether the client opted out, so it
    resolves to the legacy transport (relay off), the permanent fallback
    rung, with the failure logged rather than aborting the caller — a
    client's broken config must not take down forwarder regeneration.

    Only ``project_root``'s own config is read: an upward search would hand a
    nested project the ENCLOSING repository's transport (Plan 00466 N24).
    """
    config_path = project_root / DaemonPath.CLAUDE_DIR / DaemonPath.CONFIG_FILE
    try:
        raw = ConfigLoader.load(config_path)
        merged = ConfigLoader.merge_with_defaults(raw)
        return Config.model_validate(merged).daemon.transport
    except FileNotFoundError:
        return TransportConfig()
    except Exception as exc:
        # ValueError (malformed YAML/JSON, from ConfigLoader.load) and
        # pydantic.ValidationError (from Config.model_validate) both land
        # here — neither is a case worth distinguishing from "no usable
        # config", so both fall back to the legacy transport with an advisory.
        logger.warning(
            "daemon.transport config at %s is unusable (%s); falling back to the "
            "legacy transport (relay off)",
            project_root / ".claude" / "hooks-daemon.yaml",
            exc,
        )
        return TransportConfig(relay_enabled=False)


def regenerate_deployed_hooks(project_root: Path, hooks_dir: Path) -> list[str]:
    """Rewrite every deployed forwarder in ``hooks_dir`` in place (Task 4.1).

    ALWAYS scans every file (Plan 00290 F1/F2/F4 fix) — it must, even with
    the resolved transport config at BOTH ``relay_enabled: False`` AND
    ``nc_enabled: False`` (the default), because a deployed forwarder can
    carry a STALE or FOREIGN guard block from an earlier config state or
    from a contaminated deploy source (see :func:`strip_relay_guard_block`).
    A file is only ever WRITTEN when :func:`generate_forwarder_content`'s
    output actually differs from what's on disk, so the common case (no
    guard present, config disabled) still touches nothing — the
    byte-identical-by-default guarantee holds via a no-op comparison rather
    than an early return.

    Args:
        project_root: The target project's root directory.
        hooks_dir: The deployed ``.claude/hooks`` directory to rewrite.

    Returns:
        Basenames of the files actually rewritten (empty when every file was
        already in its generated form).
    """
    transport = load_transport_config(project_root)
    untracked_dir = get_untracked_dir(project_root)
    rewritten: list[str] = []
    for path in sorted(hooks_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            source = path.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            # A single unreadable/non-UTF-8 file must not abort the pass for
            # every sibling — skip it, report it, and keep going. The
            # unconditional F1 guard-strip still runs on every OTHER file.
            log_and_continue(
                logger,
                exc,
                reason=(
                    f"skipping unreadable forwarder {path}: a single unreadable or non-UTF-8 "
                    "forwarder must not abort the pass for its siblings, and the guard-strip "
                    "still runs on every other file"
                ),
            )
            continue
        generated = generate_forwarder_content(
            source, path.name, transport, untracked_dir, project_root
        )
        if generated != source:
            path.write_text(generated)
            rewritten.append(path.name)
    return rewritten


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``python -m claude_code_hooks_daemon.install.forwarder_generator``.

    Invoked from ``scripts/install/hooks_deploy.sh`` after the plain-``cp``
    deploy step, so it only ever needs to REWRITE files already on disk — the
    default (relay disabled) path never touches them.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--hooks-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    hooks_dir = args.hooks_dir.resolve()
    if not hooks_dir.is_dir():
        print(f"forwarder_generator: hooks dir not found: {hooks_dir}", file=sys.stderr)
        return 1

    rewritten = regenerate_deployed_hooks(project_root, hooks_dir)
    if rewritten:
        transport = load_transport_config(project_root)
        if transport.relay_enabled:
            action = "applied relay guard to"
        elif transport.nc_enabled:
            action = "applied nc transport rung to"
        else:
            action = "stripped transport transforms from"
        print(f"forwarder_generator: {action} {len(rewritten)} forwarder(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
