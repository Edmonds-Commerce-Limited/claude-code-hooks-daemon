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
import re
import sys
from pathlib import Path

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.config.models import Config, TransportConfig
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir

#: The line every current forwarder sources init.sh through. The guard block
#: is inserted directly above this line (DESIGN §6.1) — it is the anchor that
#: makes generation a pure text transform rather than a bash-shape assumption.
INIT_SH_ANCHOR: str = 'source "$SCRIPT_DIR/../init.sh"\n'

_GUARD_HEADER = "# --- relay hot path (generated; Plan 00290) ---\n"
_GUARD_FOOTER = "# --- end relay hot path ---\n"


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
    """
    relay_binary = transport.relay_binary or _default_relay_binary_path(untracked_dir)
    timeout_ms = transport.timeout_seconds * 1000
    return (
        _GUARD_HEADER
        + 'if [[ "${1:-}" != "--no-relay" ]]; then\n'
        + f'    _rl_dir="{untracked_dir}"\n'
        + '    _rl_sfx="-${HOSTNAME:-localhost}"; _rl_sfx="${_rl_sfx,,}"; '
        + '_rl_sfx="${_rl_sfx// /-}"\n'
        + f'    _rl_bin="{relay_binary}"\n'
        + f'    _rl_sock="$_rl_dir/events$_rl_sfx/{event_file_name}.sock"\n'
        + '    if [[ -x "$_rl_bin" && -S "$_rl_sock" ]]; then\n'
        + '        exec "$_rl_bin" "$_rl_sock" --fallback "${BASH_SOURCE[0]}" \\\n'
        + f'            --timeout-ms "{timeout_ms}"\n'
        + "    fi\n"
        + "fi\n"
        + _GUARD_FOOTER
    )


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

    Two independent, order-safe transforms — each gated on its own config
    flag, so an unopted-in rung leaves ``source_content`` byte-identical:

    - ``transport.relay_enabled``: the relay guard block
      (:func:`build_relay_guard_block`) is inserted directly above the
      ``source init.sh`` line. If that anchor is absent (a non-standard
      forwarder shape), this transform is skipped rather than guessing an
      insertion point.
    - ``transport.nc_enabled``: the event's bash_key is appended as a
      trailing literal arg to the file's ``send_request_stdin``/
      ``forward_stop_event`` call (:func:`append_nc_socket_arg`).

    With both flags False (the default) this returns ``source_content``
    completely unchanged.
    """
    result = source_content
    if transport.relay_enabled and INIT_SH_ANCHOR in result and _GUARD_HEADER not in result:
        guard = build_relay_guard_block(event_file_name, transport, untracked_dir)
        result = result.replace(INIT_SH_ANCHOR, guard + INIT_SH_ANCHOR, 1)
    if transport.nc_enabled:
        result = append_nc_socket_arg(result, event_file_name)
    return result


def load_transport_config(project_root: Path) -> TransportConfig:
    """Resolve the effective ``daemon.transport`` config for ``project_root``.

    Missing/absent config file resolves to the pure defaults (relay
    disabled) — the same fail-safe behaviour every other config-driven
    installer step uses.
    """
    try:
        config_path = ConfigLoader.find_config(str(project_root))
        raw = ConfigLoader.load(config_path)
        merged = ConfigLoader.merge_with_defaults(raw)
    except FileNotFoundError:
        return TransportConfig()
    return Config.model_validate(merged).daemon.transport


def regenerate_deployed_hooks(project_root: Path, hooks_dir: Path) -> list[str]:
    """Rewrite every deployed forwarder in ``hooks_dir`` in place (Task 4.1).

    No-op (touches nothing) when the resolved transport config has
    ``relay_enabled: False`` — the deployed tree is left exactly as
    ``deploy_hook_scripts`` (a plain ``cp``) already produced it, which is
    how the byte-identical-by-default guarantee holds without this function
    even needing to inspect file contents in the common case.

    Args:
        project_root: The target project's root directory.
        hooks_dir: The deployed ``.claude/hooks`` directory to rewrite.

    Returns:
        Basenames of the files actually rewritten (empty when disabled or
        when every file was already in its generated form).
    """
    transport = load_transport_config(project_root)
    if not transport.relay_enabled:
        return []

    untracked_dir = get_event_socket_dir(project_root).parent
    rewritten: list[str] = []
    for path in sorted(hooks_dir.iterdir()):
        if not path.is_file():
            continue
        source = path.read_text()
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
        print(f"forwarder_generator: inserted relay guard into {len(rewritten)} forwarder(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
