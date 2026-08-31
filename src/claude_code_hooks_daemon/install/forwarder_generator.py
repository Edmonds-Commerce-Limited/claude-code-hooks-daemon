"""Config-driven generation of deployed hook forwarder scripts (Plan 00290).

The deployed ``.claude/hooks/<event>`` forwarder scripts are, today, a plain
1:1 copy of this repository's own ``.claude/hooks/*`` (see
``install/client_owned_assets.py`` and ``scripts/install/hooks_deploy.sh``).
Plan 00290 adds an opt-in relay hot path: when ``daemon.transport.relay_enabled``
is set, each deployed forwarder gains a pure-builtin guard block (no subshell
spawns) that execs the static Rust relay binary directly against its per-event
socket, falling back to the untouched legacy body (``--no-relay`` re-entry) on
any failure to connect.

See ``CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md``
§6.1 for the binding guard-block contract this module implements verbatim.

With the config default (``relay_enabled: False``) :func:`generate_forwarder_content`
returns its input completely unchanged — the deployed file is byte-identical
to today's, which is the whole point of shipping this rung opt-in.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config, TransportConfig
from claude_code_hooks_daemon.constants.events import relay_ineligible_bash_keys
from claude_code_hooks_daemon.daemon.paths import (
    event_socket_dir_is_fallback,
    get_event_socket_dir_from_untracked,
    get_untracked_dir,
)

#: The line every current forwarder sources init.sh through. The guard block
#: is inserted directly above this line (DESIGN §6.1) — it is the anchor that
#: makes generation a pure text transform rather than a bash-shape assumption.
INIT_SH_ANCHOR: str = 'source "$SCRIPT_DIR/../init.sh"\n'

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

logger = logging.getLogger(__name__)


def _default_relay_binary_path(untracked_dir: Path) -> str:
    """``{untracked}/bin/hooks-relay`` — the default when unoverridden (design §4)."""
    return str(untracked_dir / "bin" / "hooks-relay")


def build_relay_guard_block(
    event_file_name: str,
    transport: TransportConfig,
    untracked_dir: Path,
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

    Returns:
        The guard block text, newline-terminated, ready to be inserted
        directly above :data:`INIT_SH_ANCHOR`.

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
    timeout_ms = transport.timeout_seconds * 1000
    lines = [
        _GUARD_HEADER,
        'if [[ "${1:-}" != "--no-relay" ]]; then\n',
        f'    _rl_dir="{untracked_dir}"\n',
    ]
    if event_socket_dir_is_fallback(untracked_dir):
        resolved_events_dir = get_event_socket_dir_from_untracked(untracked_dir)
        # Test-isolation fix (Plan 00290 Phase 6 dogfood finding), preserved
        # in the fallback case too: still `${VAR:-default}` parameter
        # expansion, zero spawns, so a test fixture can still redirect this.
        lines.append(f'    _rl_events_dir="${{HOOKS_DAEMON_EVENTS_DIR:-{resolved_events_dir}}}"\n')
    else:
        lines.append(
            '    _rl_sfx="-${HOSTNAME:-localhost}"; _rl_sfx="${_rl_sfx,,}"; '
            '_rl_sfx="${_rl_sfx// /-}"\n'
        )
        lines.append('    _rl_events_dir="${HOOKS_DAEMON_EVENTS_DIR:-$_rl_dir/events$_rl_sfx}"\n')
    lines.append(f'    _rl_bin="${{HOOKS_DAEMON_RELAY_BINARY:-{relay_binary}}}"\n')
    lines.append(f'    _rl_sock="$_rl_events_dir/{event_file_name}.sock"\n')
    lines.append('    if [[ -x "$_rl_bin" && -S "$_rl_sock" ]]; then\n')
    lines.append('        exec "$_rl_bin" "$_rl_sock" --fallback "${BASH_SOURCE[0]}" \\\n')
    lines.append(f'            --timeout-ms "{timeout_ms}"\n')
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


#: Matches the single `send_request_stdin "Event" [mode]` or
#: `forward_stop_event "Event"` call line every deployed forwarder ends with.
#: Captures: (1) function name, (2) the already-quoted argument list.
_TRANSPORT_CALL_PATTERN = re.compile(
    r'^(send_request_stdin|forward_stop_event)((?: "[^"]*")+)$', re.MULTILINE
)


def append_nc_socket_arg(source_content: str, event_file_name: str) -> str:
    """Append the event's bash_key as a trailing literal arg (design §6.2).

    ``send_request_stdin``/``forward_stop_event`` receive the PascalCase
    event name at runtime and have no way to derive the per-event socket's
    kebab-case filename from it without a spawn or a lookup table. Baking
    the filename in at generation time — exactly as :func:`build_relay_guard_block`
    bakes in the untracked dir — avoids both: ``send_request_stdin`` only
    ever needs to string-concatenate this literal onto the (already
    computed) untracked dir + hostname suffix to reach the socket.

    A missing existing ``response_mode`` argument is filled with an empty
    string placeholder so the new argument always lands in a fixed position
    (arg 3 for ``send_request_stdin``, arg 2 for ``forward_stop_event``).
    Idempotent: a call line already carrying ``event_file_name`` as its
    final argument is left untouched.
    """

    def _augment(match: re.Match[str]) -> str:
        func = match.group(1)
        existing_args = re.findall(r'"([^"]*)"', match.group(2))
        if existing_args and existing_args[-1] == event_file_name:
            return match.group(0)
        if func == "send_request_stdin" and len(existing_args) < 2:
            existing_args.append("")
        existing_args.append(event_file_name)
        rendered = " ".join(f'"{arg}"' for arg in existing_args)
        return f"{func} {rendered}"

    return _TRANSPORT_CALL_PATTERN.sub(_augment, source_content, count=1)


def generate_forwarder_content(
    source_content: str,
    event_file_name: str,
    transport: TransportConfig,
    untracked_dir: Path,
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
    """
    result = strip_relay_guard_block(source_content)
    if (
        transport.relay_enabled
        and event_file_name not in RELAY_EXCLUDED_EVENT_FILE_NAMES
        and INIT_SH_ANCHOR in result
    ):
        guard = build_relay_guard_block(event_file_name, transport, untracked_dir)
        result = result.replace(INIT_SH_ANCHOR, guard + INIT_SH_ANCHOR, 1)
    if transport.nc_enabled:
        result = append_nc_socket_arg(result, event_file_name)
    return result


def load_transport_config(project_root: Path) -> TransportConfig:
    """Resolve the effective ``daemon.transport`` config for ``project_root``.

    Missing/absent config file resolves to the pure defaults (relay
    disabled) — the same fail-safe behaviour every other config-driven
    installer step uses. A config file that EXISTS but fails to parse
    (malformed YAML) or fails pydantic validation resolves the same way,
    with the failure logged rather than aborting the caller — a client's
    broken config must not take down forwarder regeneration entirely.
    """
    try:
        config_path = ConfigLoader.find_config(str(project_root))
        raw = ConfigLoader.load(config_path)
        merged = ConfigLoader.merge_with_defaults(raw)
        return Config.model_validate(merged).daemon.transport
    except FileNotFoundError:
        return TransportConfig()
    except Exception as exc:
        # ValueError (malformed YAML/JSON, from ConfigLoader.load) and
        # pydantic.ValidationError (from Config.model_validate) both land
        # here — neither is a case worth distinguishing from "no usable
        # config", so both fall back to defaults with an explicit advisory.
        logger.warning(
            "daemon.transport config at %s is unusable (%s); falling back to defaults",
            project_root / ".claude" / "hooks-daemon.yaml",
            exc,
        )
        return TransportConfig()


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
            logger.warning("skipping unreadable forwarder %s: %s", path, exc)
            continue
        generated = generate_forwarder_content(source, path.name, transport, untracked_dir)
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
