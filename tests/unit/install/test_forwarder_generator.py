"""Tests for config-driven forwarder generation (Plan 00290 Task 4.1).

``generate_forwarder_content`` decides what gets written to a deployed
``.claude/hooks/<event>`` forwarder: byte-identical to the source when the
relay rung is disabled (the default), or the source with the pure-builtin
relay hot-path guard block (DESIGN-socket-relay.md §6.1) inserted directly
above the ``source init.sh`` line when it is enabled.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.install.forwarder_generator import (
    INIT_SH_ANCHOR,
    build_relay_guard_block,
    generate_forwarder_content,
    strip_relay_guard_block,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"

_SAMPLE_SOURCE = """#!/bin/bash
#
# DAEMON-OWNED FILE - do not edit.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

send_request_stdin "PreToolUse"
"""


# ---------------------------------------------------------------------------
# Default (relay disabled): byte-identical
# ---------------------------------------------------------------------------


def test_disabled_transport_returns_source_unchanged() -> None:
    transport = TransportConfig()
    assert transport.relay_enabled is False

    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, Path("/proj/untracked")
    )

    assert result == _SAMPLE_SOURCE


@pytest.mark.parametrize(
    "hook_file",
    sorted(p.name for p in _HOOKS_DIR.iterdir() if p.is_file() and p.name != "README.md"),
)
def test_every_real_deployed_hook_is_byte_identical_when_disabled(hook_file: str) -> None:
    """Pin default behaviour against every hook script actually shipped today.

    This repo dogfoods the relay (Plan 00290 F1 canary finding), so its own
    tracked ``.claude/hooks/*`` may already carry a guard block pointing at
    THIS repo's own paths. A disabled client config must always strip that
    away and produce the guard-free canonical shape — never copy it forward
    verbatim (that was F1: a client silently inheriting this repo's guard).
    """
    source = (_HOOKS_DIR / hook_file).read_text()
    transport = TransportConfig()

    result = generate_forwarder_content(source, hook_file, transport, Path("/proj/untracked"))

    assert result == strip_relay_guard_block(source)
    assert "relay hot path" not in result


def test_disabled_transport_returns_source_unchanged_even_without_anchor() -> None:
    """No init.sh anchor line present: nothing to insert before, so unchanged."""
    transport = TransportConfig()
    weird_source = "#!/bin/bash\necho hi\n"

    result = generate_forwarder_content(
        weird_source, "pre-tool-use", transport, Path("/proj/untracked")
    )

    assert result == weird_source


# ---------------------------------------------------------------------------
# Enabled: guard block inserted
# ---------------------------------------------------------------------------


def test_enabled_transport_inserts_guard_before_init_sh_source() -> None:
    transport = TransportConfig(relay_enabled=True)

    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, Path("/proj/untracked")
    )

    assert result != _SAMPLE_SOURCE
    guard_pos = result.index("relay hot path")
    init_pos = result.index('source "$SCRIPT_DIR/../init.sh"')
    assert guard_pos < init_pos, "guard block must sit ABOVE the init.sh source line"
    # Nothing else in the file changed — the rest of the content is untouched.
    assert result.endswith('send_request_stdin "PreToolUse"\n')


def test_enabled_transport_is_idempotent_against_already_generated_content() -> None:
    """Running generation twice must not stack a second guard block."""
    transport = TransportConfig(relay_enabled=True)
    once = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, Path("/proj/untracked")
    )

    twice = generate_forwarder_content(once, "pre-tool-use", transport, Path("/proj/untracked"))

    assert twice == once
    assert once.count("relay hot path (generated") == 1


# ---------------------------------------------------------------------------
# Canary run 2 findings F1/F2/F4: strip-then-reapply against a FOREIGN or
# STALE guard already present on disk (this repo dogfoods the relay, so a
# client's deployed forwarder is a copy of a source that may already carry
# a guard block pointing at THIS repo's own paths — proven live to route a
# client's hook traffic to the wrong project's daemon).
# ---------------------------------------------------------------------------


def _foreign_guard_source(untracked_dir: str = "/workspace/untracked") -> str:
    """A forwarder that already carries a guard baked for a DIFFERENT project."""
    guard = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path(untracked_dir)
    )
    return _SAMPLE_SOURCE.replace(INIT_SH_ANCHOR, guard + INIT_SH_ANCHOR)


def test_f1_disabled_config_strips_a_foreign_guard_entirely() -> None:
    """F1 repro: a client's default (disabled) config must never inherit
    another project's guard block — it must be stripped, not copied forward."""
    contaminated = _foreign_guard_source()
    transport = TransportConfig()  # disabled — the client's real default

    result = generate_forwarder_content(
        contaminated, "pre-tool-use", transport, Path("/proj/untracked")
    )

    assert "relay hot path" not in result
    assert "/workspace/untracked" not in result
    assert result == _SAMPLE_SOURCE


def test_f2_enabled_config_replaces_foreign_guard_with_clients_own_paths() -> None:
    """F2 repro: enabling transport over an already-contaminated deploy must
    rewrite the guard to the CLIENT's own paths, not leave the foreign one
    (the old idempotency check saw "a guard is already present" and skipped)."""
    contaminated = _foreign_guard_source()
    transport = TransportConfig(relay_enabled=True)

    result = generate_forwarder_content(
        contaminated, "pre-tool-use", transport, Path("/client/untracked")
    )

    assert "/workspace/untracked" not in result
    assert '_rl_dir="/client/untracked"' in result
    assert result.count("relay hot path (generated") == 1


def test_f4_disabling_transport_strips_a_previously_generated_guard() -> None:
    """F4 repro: flipping transport OFF must restore the byte-identical plain
    shape, not leave a stale guard from when it was last enabled."""
    own_transport = TransportConfig(relay_enabled=True)
    previously_generated = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", own_transport, Path("/proj/untracked")
    )
    assert "relay hot path" in previously_generated  # sanity: guard really is there

    disabled_transport = TransportConfig()
    result = generate_forwarder_content(
        previously_generated, "pre-tool-use", disabled_transport, Path("/proj/untracked")
    )

    assert result == _SAMPLE_SOURCE


@pytest.mark.parametrize("event_file_name", ["stop", "subagent-stop"])
def test_relay_guard_excludes_stop_events(event_file_name: str) -> None:
    """Stop/SubagentStop must NEVER get the relay guard.

    The relay `exec`s directly and is a protocol-ignorant byte pump — it has
    no equivalent of `forward_stop_event`'s daemon `decision=block` JSON ->
    exit-code-2 translation (Claude Code's hard re-entry contract). Ruling
    (Plan 00290 Phase 6 dogfood finding): those two forwarders always keep
    the bash path; the relay hot path never applies to them, at any config.
    """
    transport = TransportConfig(relay_enabled=True)
    source = _SAMPLE_SOURCE.replace('send_request_stdin "PreToolUse"', 'forward_stop_event "Stop"')

    result = generate_forwarder_content(source, event_file_name, transport, Path("/proj/untracked"))

    assert "relay hot path" not in result
    assert result == source


def test_relay_guard_excluded_but_nc_still_applies_to_stop() -> None:
    """The exclusion is relay-specific — nc is safe for Stop/SubagentStop:
    it only changes the TRANSPORT beneath send_request_stdin, and
    forward_stop_event's own decision=block parsing still runs afterward
    regardless of which rung served the request."""
    transport = TransportConfig(relay_enabled=True, nc_enabled=True)
    source = _SAMPLE_SOURCE.replace('send_request_stdin "PreToolUse"', 'forward_stop_event "Stop"')

    result = generate_forwarder_content(source, "stop", transport, Path("/proj/untracked"))

    assert "relay hot path" not in result
    assert 'forward_stop_event "Stop" "stop"' in result


@pytest.mark.parametrize("hook_file", ["stop", "subagent-stop"])
def test_real_stop_hooks_never_get_relay_guard_when_enabled(hook_file: str) -> None:
    source = (_HOOKS_DIR / hook_file).read_text()
    transport = TransportConfig(relay_enabled=True)

    result = generate_forwarder_content(source, hook_file, transport, Path("/proj/untracked"))

    assert "relay hot path" not in result
    assert result == source


def test_enabled_transport_without_anchor_returns_unchanged() -> None:
    """Defensive: no anchor line means no safe insertion point, so skip."""
    transport = TransportConfig(relay_enabled=True)
    weird_source = "#!/bin/bash\necho hi\n"

    result = generate_forwarder_content(
        weird_source, "pre-tool-use", transport, Path("/proj/untracked")
    )

    assert result == weird_source


def test_guard_block_reentry_check_is_first() -> None:
    """The `--no-relay` re-entry check gates the whole guard (loop-safety)."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u")
    )
    lines = [line for line in block.splitlines() if line.strip()]
    assert lines[1] == 'if [[ "${1:-}" != "--no-relay" ]]; then'


def test_guard_block_names_the_correct_event_socket() -> None:
    block = build_relay_guard_block(
        "user-prompt-submit", TransportConfig(relay_enabled=True), Path("/proj/untracked")
    )
    assert '_rl_sock="$_rl_events_dir/user-prompt-submit.sock"' in block


def test_guard_block_uses_literal_untracked_dir() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/some/project/untracked")
    )
    assert '_rl_dir="/some/project/untracked"' in block


def test_guard_block_default_relay_binary_path() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/proj/untracked")
    )
    assert '_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/proj/untracked/bin/hooks-relay}"' in block


def test_guard_block_honours_relay_binary_override() -> None:
    transport = TransportConfig(relay_enabled=True, relay_binary="/opt/custom/hooks-relay")
    block = build_relay_guard_block("pre-tool-use", transport, Path("/proj/untracked"))
    assert '_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/opt/custom/hooks-relay}"' in block
    assert "/proj/untracked/bin/hooks-relay" not in block


def test_guard_block_events_dir_is_env_overridable() -> None:
    """Test-isolation fix: the events dir a fixture needs to redirect must be
    a single env-overridable variable, not just the untracked-dir literal it
    is computed from — mirrors CLAUDE_HOOKS_SOCKET_PATH's override pattern
    for the legacy socket."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/proj/untracked")
    )
    assert '_rl_events_dir="${HOOKS_DAEMON_EVENTS_DIR:-$_rl_dir/events$_rl_sfx}"' in block
    assert '_rl_sock="$_rl_events_dir/pre-tool-use.sock"' in block


def test_guard_block_relay_binary_is_env_overridable() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/proj/untracked")
    )
    assert '_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/proj/untracked/bin/hooks-relay}"' in block


def test_guard_block_env_overrides_are_pure_parameter_expansion() -> None:
    """Still zero subshells/spawns — `${VAR:-default}` is a bash builtin."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u")
    )
    assert "$(" not in block
    assert "`" not in block


def test_guard_block_timeout_ms_derived_from_timeout_seconds() -> None:
    transport = TransportConfig(relay_enabled=True, timeout_seconds=5)
    block = build_relay_guard_block("pre-tool-use", transport, Path("/proj/untracked"))
    assert '--timeout-ms "5000"' in block


def test_guard_block_execs_with_fallback_and_stdin_intact() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u")
    )
    assert 'exec "$_rl_bin" "$_rl_sock" --fallback "${BASH_SOURCE[0]}"' in block


def test_guard_block_is_pure_builtin_no_subshell_spawn() -> None:
    """No `$( )`/backtick/external command inside the guard — bash builtins only."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u")
    )
    assert "$(" not in block
    assert "`" not in block


# ---------------------------------------------------------------------------
# Generated content stays valid, parseable bash
# ---------------------------------------------------------------------------


def test_generated_forwarder_is_syntactically_valid_bash() -> None:
    transport = TransportConfig(relay_enabled=True)
    content = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, Path("/proj/untracked")
    )

    result = subprocess.run(
        ["bash", "-n", "-c", content],
        capture_output=True,
        text=True,
        timeout=Timeout.VALIDATION_CHECK,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# nc rung (design §6.2): the deployed call site gains the event's bash_key
# as a trailing arg so send_request_stdin can attempt the nc -U rung without
# any PascalCase->kebab mapping table at runtime.
# ---------------------------------------------------------------------------


def test_nc_disabled_leaves_call_site_unchanged() -> None:
    transport = TransportConfig(nc_enabled=False)
    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, Path("/proj/untracked")
    )
    assert result == _SAMPLE_SOURCE


def test_nc_enabled_appends_bash_key_to_send_request_stdin_call() -> None:
    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, Path("/proj/untracked")
    )
    assert 'send_request_stdin "PreToolUse" "" "pre-tool-use"' in result


def test_nc_enabled_preserves_existing_response_mode_arg() -> None:
    source = _SAMPLE_SOURCE.replace(
        'send_request_stdin "PreToolUse"', 'send_request_stdin "Status" "status"'
    )
    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(source, "status-line", transport, Path("/proj/untracked"))
    assert 'send_request_stdin "Status" "status" "status-line"' in result


def test_nc_enabled_appends_to_forward_stop_event_call() -> None:
    source = _SAMPLE_SOURCE.replace('send_request_stdin "PreToolUse"', 'forward_stop_event "Stop"')
    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(source, "stop", transport, Path("/proj/untracked"))
    assert 'forward_stop_event "Stop" "stop"' in result


def test_nc_enabled_is_idempotent() -> None:
    transport = TransportConfig(nc_enabled=True)
    once = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, Path("/proj/untracked")
    )
    twice = generate_forwarder_content(once, "pre-tool-use", transport, Path("/proj/untracked"))
    assert twice == once
    assert once.count('"pre-tool-use"') == 1


def test_both_rungs_enabled_together() -> None:
    transport = TransportConfig(relay_enabled=True, nc_enabled=True)
    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, Path("/proj/untracked")
    )
    assert "relay hot path" in result
    assert 'send_request_stdin "PreToolUse" "" "pre-tool-use"' in result


@pytest.mark.parametrize(
    "hook_file",
    sorted(p.name for p in _HOOKS_DIR.iterdir() if p.is_file() and p.name != "README.md"),
)
def test_every_real_hook_generates_valid_bash_when_enabled(hook_file: str) -> None:
    source = (_HOOKS_DIR / hook_file).read_text()
    transport = TransportConfig(relay_enabled=True)

    content = generate_forwarder_content(source, hook_file, transport, Path("/proj/untracked"))

    result = subprocess.run(
        ["bash", "-n", "-c", content],
        capture_output=True,
        text=True,
        timeout=Timeout.VALIDATION_CHECK,
    )
    assert result.returncode == 0, f"{hook_file}: {result.stderr}"
