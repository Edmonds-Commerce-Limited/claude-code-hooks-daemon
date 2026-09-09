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
    load_transport_config,
    regenerate_deployed_hooks,
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

#: The checkout most cases below generate for. Two constants, not two
#: literals per call: the guard bakes BOTH the untracked dir and the checkout
#: root, and neither is derivable from the other (a client install puts the
#: untracked dir at ``<root>/.claude/hooks-daemon/untracked``).
_ROOT = Path("/proj")
_UNTRACKED = Path("/proj/untracked")

#: A checkout deep enough that the natural events dir overflows AF_UNIX.
_DEEP_ROOT = Path("/" + "a" * 90)


# ---------------------------------------------------------------------------
# Default (relay disabled): byte-identical
# ---------------------------------------------------------------------------


def test_disabled_transport_returns_source_unchanged() -> None:
    transport = TransportConfig()
    assert transport.relay_enabled is False

    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
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

    result = generate_forwarder_content(source, hook_file, transport, _UNTRACKED, _ROOT)

    assert result == strip_relay_guard_block(source)
    assert "relay hot path" not in result


def test_disabled_transport_returns_source_unchanged_even_without_anchor() -> None:
    """No init.sh anchor line present: nothing to insert before, so unchanged."""
    transport = TransportConfig()
    weird_source = "#!/bin/bash\necho hi\n"

    result = generate_forwarder_content(
        weird_source, "pre-tool-use", transport, _UNTRACKED, _ROOT
    )

    assert result == weird_source


# ---------------------------------------------------------------------------
# Enabled: guard block inserted
# ---------------------------------------------------------------------------


def test_enabled_transport_inserts_guard_before_init_sh_source() -> None:
    transport = TransportConfig(relay_enabled=True)

    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
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
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
    )

    twice = generate_forwarder_content(once, "pre-tool-use", transport, _UNTRACKED, _ROOT)

    assert twice == once
    assert once.count("relay hot path (generated") == 1


# ---------------------------------------------------------------------------
# Canary run 2 findings F1/F2/F4: strip-then-reapply against a FOREIGN or
# STALE guard already present on disk (this repo dogfoods the relay, so a
# client's deployed forwarder is a copy of a source that may already carry
# a guard block pointing at THIS repo's own paths — proven live to route a
# client's hook traffic to the wrong project's daemon).
# ---------------------------------------------------------------------------


def _foreign_guard_source(
    untracked_dir: str = "/workspace/untracked", project_root: str = "/workspace"
) -> str:
    """A forwarder that already carries a guard baked for a DIFFERENT project."""
    guard = build_relay_guard_block(
        "pre-tool-use",
        TransportConfig(relay_enabled=True),
        Path(untracked_dir),
        Path(project_root),
    )
    return _SAMPLE_SOURCE.replace(INIT_SH_ANCHOR, guard + INIT_SH_ANCHOR)


def test_f1_disabled_config_strips_a_foreign_guard_entirely() -> None:
    """F1 repro: a client's default (disabled) config must never inherit
    another project's guard block — it must be stripped, not copied forward."""
    contaminated = _foreign_guard_source()
    transport = TransportConfig()  # disabled — the client's real default

    result = generate_forwarder_content(
        contaminated, "pre-tool-use", transport, _UNTRACKED, _ROOT
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
        contaminated, "pre-tool-use", transport, Path("/client/untracked"), Path("/client")
    )

    assert "/workspace/untracked" not in result
    assert '_rl_dir="/client/untracked"' in result
    assert '"${BASH_SOURCE[0]}" == "/client/.claude/hooks/"*' in result
    assert result.count("relay hot path (generated") == 1


def test_f4_disabling_transport_strips_a_previously_generated_guard() -> None:
    """F4 repro: flipping transport OFF must restore the byte-identical plain
    shape, not leave a stale guard from when it was last enabled."""
    own_transport = TransportConfig(relay_enabled=True)
    previously_generated = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", own_transport, _UNTRACKED, _ROOT
    )
    assert "relay hot path" in previously_generated  # sanity: guard really is there

    disabled_transport = TransportConfig()
    result = generate_forwarder_content(
        previously_generated, "pre-tool-use", disabled_transport, _UNTRACKED, _ROOT
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

    result = generate_forwarder_content(source, event_file_name, transport, _UNTRACKED, _ROOT)

    assert "relay hot path" not in result
    assert result == source


def test_relay_guard_excluded_but_nc_still_applies_to_stop() -> None:
    """The exclusion is relay-specific — nc is safe for Stop/SubagentStop:
    it only changes the TRANSPORT beneath send_request_stdin, and
    forward_stop_event's own decision=block parsing still runs afterward
    regardless of which rung served the request."""
    transport = TransportConfig(relay_enabled=True, nc_enabled=True)
    source = _SAMPLE_SOURCE.replace('send_request_stdin "PreToolUse"', 'forward_stop_event "Stop"')

    result = generate_forwarder_content(source, "stop", transport, _UNTRACKED, _ROOT)

    assert "relay hot path" not in result
    assert 'forward_stop_event "Stop" "stop"' in result


@pytest.mark.parametrize("hook_file", ["stop", "subagent-stop"])
def test_real_stop_hooks_never_get_relay_guard_when_enabled(hook_file: str) -> None:
    source = (_HOOKS_DIR / hook_file).read_text()
    transport = TransportConfig(relay_enabled=True)

    result = generate_forwarder_content(source, hook_file, transport, _UNTRACKED, _ROOT)

    assert "relay hot path" not in result
    assert result == source


# ---------------------------------------------------------------------------
# Defect 1 fix (Plan 00290 dogfood field report, commit 9d353fd3 EMERGENCY
# suspension): raw_stdout events (StatusLine, WorktreeCreate) are relay
# structurally, not just Stop/SubagentStop — the relay is a pure byte pump
# and cannot perform the client-side JSON-unwrap those two response_modes
# need. Eligibility is derived from EventIDMeta.relay_eligible, not a
# hand-maintained file-name set.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_file_name", ["status-line", "worktree-create"])
def test_relay_guard_excludes_raw_stdout_events(event_file_name: str) -> None:
    transport = TransportConfig(relay_enabled=True)
    source = _SAMPLE_SOURCE.replace(
        'send_request_stdin "PreToolUse"', 'send_request_stdin "Status" "status"'
    )

    result = generate_forwarder_content(source, event_file_name, transport, _UNTRACKED, _ROOT)

    assert "relay hot path" not in result
    assert result == source


@pytest.mark.parametrize("hook_file", ["status-line", "worktree-create"])
def test_real_raw_stdout_hooks_never_get_relay_guard_when_enabled(hook_file: str) -> None:
    source = (_HOOKS_DIR / hook_file).read_text()
    transport = TransportConfig(relay_enabled=True)

    result = generate_forwarder_content(source, hook_file, transport, _UNTRACKED, _ROOT)

    assert "relay hot path" not in result
    assert result == source


def test_relay_excluded_set_matches_typed_catalogue_source() -> None:
    """The generator's exclusion set must be exactly the catalogue's
    relay-ineligible bash_keys — no drift between the two is possible since
    one is now derived from the other, but this pins the derivation itself."""
    from claude_code_hooks_daemon.constants.events import relay_ineligible_bash_keys
    from claude_code_hooks_daemon.install.forwarder_generator import (
        RELAY_EXCLUDED_EVENT_FILE_NAMES,
    )

    assert RELAY_EXCLUDED_EVENT_FILE_NAMES == relay_ineligible_bash_keys()
    assert RELAY_EXCLUDED_EVENT_FILE_NAMES == {
        "status-line",
        "worktree-create",
        "stop",
        "subagent-stop",
    }


def test_enabled_transport_without_anchor_returns_unchanged() -> None:
    """Defensive: no anchor line means no safe insertion point, so skip."""
    transport = TransportConfig(relay_enabled=True)
    weird_source = "#!/bin/bash\necho hi\n"

    result = generate_forwarder_content(
        weird_source, "pre-tool-use", transport, _UNTRACKED, _ROOT
    )

    assert result == weird_source


def test_guard_block_reentry_check_is_first() -> None:
    """The `--no-relay` re-entry check gates the whole guard (loop-safety).

    It is the FIRST condition of the guard's single `if`, so the re-entry the
    relay itself performs cannot reach the exec again whatever the other
    conditions say. The checkout test (Plan 00364 Task 5.1) is conjoined onto
    the same line and is asserted by its own tests below.
    """
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u"), Path("/p")
    )
    lines = [line for line in block.splitlines() if line.strip()]
    assert lines[1].startswith('if [[ "${1:-}" != "--no-relay" &&')
    assert lines[1].endswith("]]; then")


def test_guard_block_names_the_correct_event_socket() -> None:
    block = build_relay_guard_block(
        "user-prompt-submit", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert '_rl_sock="$_rl_events_dir/user-prompt-submit.sock"' in block


def test_guard_block_uses_literal_untracked_dir() -> None:
    block = build_relay_guard_block(
        "pre-tool-use",
        TransportConfig(relay_enabled=True),
        Path("/some/project/untracked"),
        Path("/some/project"),
    )
    assert '_rl_dir="/some/project/untracked"' in block


def test_guard_block_default_relay_binary_path() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert '_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/proj/untracked/bin/hooks-relay}"' in block


def test_guard_block_honours_relay_binary_override() -> None:
    transport = TransportConfig(relay_enabled=True, relay_binary="/opt/custom/hooks-relay")
    block = build_relay_guard_block("pre-tool-use", transport, _UNTRACKED, _ROOT)
    assert '_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/opt/custom/hooks-relay}"' in block
    assert "/proj/untracked/bin/hooks-relay" not in block


def test_guard_block_events_dir_is_env_overridable() -> None:
    """Test-isolation fix: the events dir a fixture needs to redirect must be
    a single env-overridable variable, not just the untracked-dir literal it
    is computed from — mirrors CLAUDE_HOOKS_SOCKET_PATH's override pattern
    for the legacy socket."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert '_rl_events_dir="${HOOKS_DAEMON_EVENTS_DIR:-$_rl_dir/events$_rl_sfx}"' in block
    assert '_rl_sock="$_rl_events_dir/pre-tool-use.sock"' in block


def test_guard_block_relay_binary_is_env_overridable() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert '_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/proj/untracked/bin/hooks-relay}"' in block


def test_guard_block_env_overrides_are_pure_parameter_expansion() -> None:
    """Still zero subshells/spawns — `${VAR:-default}` is a bash builtin."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u"), Path("/p")
    )
    assert "$(" not in block
    assert "`" not in block


def test_guard_block_timeout_ms_derived_from_timeout_seconds() -> None:
    transport = TransportConfig(relay_enabled=True, timeout_seconds=5)
    block = build_relay_guard_block("pre-tool-use", transport, _UNTRACKED, _ROOT)
    assert '--timeout-ms "5000"' in block


def test_guard_block_execs_with_fallback_and_stdin_intact() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u"), Path("/p")
    )
    assert 'exec "$_rl_bin" "$_rl_sock" --fallback "${BASH_SOURCE[0]}"' in block


def test_guard_block_is_pure_builtin_no_subshell_spawn() -> None:
    """No `$( )`/backtick/external command inside the guard — bash builtins only."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u"), Path("/p")
    )
    assert "$(" not in block
    assert "`" not in block


# ---------------------------------------------------------------------------
# Generated content stays valid, parseable bash
# ---------------------------------------------------------------------------


def test_generated_forwarder_is_syntactically_valid_bash() -> None:
    transport = TransportConfig(relay_enabled=True)
    content = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
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
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
    )
    assert result == _SAMPLE_SOURCE


def test_nc_enabled_appends_bash_key_to_send_request_stdin_call() -> None:
    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
    )
    assert 'send_request_stdin "PreToolUse" "" "pre-tool-use"' in result


def test_nc_enabled_preserves_existing_response_mode_arg() -> None:
    source = _SAMPLE_SOURCE.replace(
        'send_request_stdin "PreToolUse"', 'send_request_stdin "Status" "status"'
    )
    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(source, "status-line", transport, _UNTRACKED, _ROOT)
    assert 'send_request_stdin "Status" "status" "status-line"' in result


def test_nc_enabled_appends_to_forward_stop_event_call() -> None:
    source = _SAMPLE_SOURCE.replace('send_request_stdin "PreToolUse"', 'forward_stop_event "Stop"')
    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(source, "stop", transport, _UNTRACKED, _ROOT)
    assert 'forward_stop_event "Stop" "stop"' in result


def test_nc_enabled_is_idempotent() -> None:
    transport = TransportConfig(nc_enabled=True)
    once = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
    )
    twice = generate_forwarder_content(once, "pre-tool-use", transport, _UNTRACKED, _ROOT)
    assert twice == once
    assert once.count('"pre-tool-use"') == 1


def test_both_rungs_enabled_together() -> None:
    transport = TransportConfig(relay_enabled=True, nc_enabled=True)
    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
    )
    assert "relay hot path" in result
    assert 'send_request_stdin "PreToolUse" "" "pre-tool-use"' in result


# ---------------------------------------------------------------------------
# Task 2.5 (Plan 00295): the nc rung's events dir must honour the same
# AF_UNIX-overflow fallback the relay guard and the daemon itself apply —
# a short untracked_dir (the common case) appends an empty trailing arg (no
# override needed, send_request_stdin computes the natural path dynamically
# at hook-run time, unchanged); a deep untracked_dir whose natural events
# dir would overflow the AF_UNIX length limit gets the resolved fallback
# path baked in as a literal 4th/3rd arg, exactly as build_relay_guard_block
# bakes its own `_rl_events_dir` literal for the identical case.
# ---------------------------------------------------------------------------


def test_nc_enabled_short_path_appends_empty_events_dir_override() -> None:
    """The common case: untracked_dir is short enough that the natural
    dynamic path never overflows, so no baked override is needed."""
    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, _UNTRACKED, _ROOT
    )
    assert 'send_request_stdin "PreToolUse" "" "pre-tool-use" ""' in result


def test_nc_enabled_deep_path_bakes_resolved_events_dir_override() -> None:
    """A deep untracked_dir whose natural events dir would overflow AF_UNIX's
    108-byte limit gets the daemon's own resolved fallback path baked in,
    matching build_relay_guard_block's identical decision for the relay
    guard's `_rl_events_dir`."""
    from claude_code_hooks_daemon.daemon.paths import (
        event_socket_dir_is_fallback,
        get_event_socket_dir_from_untracked,
    )

    deep_untracked_dir = Path("/" + "a" * 90 + "/untracked")
    assert event_socket_dir_is_fallback(deep_untracked_dir) is True
    expected_fallback = str(get_event_socket_dir_from_untracked(deep_untracked_dir))

    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", transport, deep_untracked_dir, _DEEP_ROOT
    )

    assert f'send_request_stdin "PreToolUse" "" "pre-tool-use" "{expected_fallback}"' in result


def test_nc_enabled_deep_path_forward_stop_event_bakes_override() -> None:
    from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked

    deep_untracked_dir = Path("/" + "a" * 90 + "/untracked")
    expected_fallback = str(get_event_socket_dir_from_untracked(deep_untracked_dir))

    source = _SAMPLE_SOURCE.replace('send_request_stdin "PreToolUse"', 'forward_stop_event "Stop"')
    transport = TransportConfig(nc_enabled=True)
    result = generate_forwarder_content(source, "stop", transport, deep_untracked_dir, _DEEP_ROOT)

    assert f'forward_stop_event "Stop" "stop" "{expected_fallback}"' in result


def test_nc_enabled_deep_path_is_still_idempotent() -> None:
    deep_untracked_dir = Path("/" + "a" * 90 + "/untracked")
    transport = TransportConfig(nc_enabled=True)
    once = generate_forwarder_content(_SAMPLE_SOURCE, "pre-tool-use", transport, deep_untracked_dir, _DEEP_ROOT)
    twice = generate_forwarder_content(once, "pre-tool-use", transport, deep_untracked_dir, _DEEP_ROOT)
    assert twice == once
    assert once.count('"pre-tool-use"') == 1


# ---------------------------------------------------------------------------
# Idempotency against a PREVIOUS release's generated form. `transport relay
# on|off` calls regenerate_deployed_hooks over already-deployed files with no
# preceding re-copy from source, so the input can be output an older daemon
# wrote — a three-argument call carrying the bash_key but no events-dir arg.
# Appending to that shape hands the bash_key to send_request_stdin as an
# events directory, so the nc rung looks for a relative socket path.
# ---------------------------------------------------------------------------


def _call_line(content: str) -> str:
    """Return the single transport call line a forwarder ends with."""
    for line in content.splitlines():
        if line.startswith(("send_request_stdin ", "forward_stop_event ")):
            return line
    raise AssertionError(f"No transport call line found in:\n{content}")


def _source_with_call(call_line: str) -> str:
    return _SAMPLE_SOURCE.replace('send_request_stdin "PreToolUse"', call_line)


def test_nc_enabled_is_idempotent_against_previous_release_three_arg_form() -> None:
    """A forwarder generated before the events-dir arg existed must not grow
    a second copy of its bash_key."""
    legacy = _source_with_call('send_request_stdin "PreToolUse" "" "pre-tool-use"')
    transport = TransportConfig(nc_enabled=True)

    result = generate_forwarder_content(legacy, "pre-tool-use", transport, _UNTRACKED, _ROOT)

    assert _call_line(result) == 'send_request_stdin "PreToolUse" "" "pre-tool-use" ""'
    assert result.count('"pre-tool-use"') == 1


def test_nc_enabled_is_idempotent_against_previous_release_stop_form() -> None:
    """`forward_stop_event` carries the bash_key one position earlier."""
    legacy = _source_with_call('forward_stop_event "Stop" "stop"')
    transport = TransportConfig(nc_enabled=True)

    result = generate_forwarder_content(legacy, "stop", transport, _UNTRACKED, _ROOT)

    assert _call_line(result) == 'forward_stop_event "Stop" "stop" ""'
    assert result.count('"stop"') == 1


def test_nc_enabled_is_idempotent_against_previous_release_status_form() -> None:
    """A non-empty response_mode does not shift the bash_key's position."""
    legacy = _source_with_call('send_request_stdin "Status" "status" "status-line"')
    transport = TransportConfig(nc_enabled=True)

    result = generate_forwarder_content(legacy, "status-line", transport, _UNTRACKED, _ROOT)

    assert _call_line(result) == 'send_request_stdin "Status" "status" "status-line" ""'
    assert result.count('"status-line"') == 1


def test_nc_enabled_repairs_a_doubled_call_site() -> None:
    """A forwarder already corrupted by the double-append is repaired, not
    extended again — the toggle is the only thing that will ever revisit it."""
    doubled = _source_with_call(
        'send_request_stdin "PreToolUse" "" "pre-tool-use" "pre-tool-use" ""'
    )
    transport = TransportConfig(nc_enabled=True)

    result = generate_forwarder_content(doubled, "pre-tool-use", transport, _UNTRACKED, _ROOT)

    assert _call_line(result) == 'send_request_stdin "PreToolUse" "" "pre-tool-use" ""'


def test_previous_release_form_gains_the_events_dir_override_on_a_deep_path() -> None:
    """Re-generating a legacy call site still bakes the overflow fallback."""
    from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked

    deep_untracked_dir = Path("/" + "a" * 90 + "/untracked")
    expected_fallback = str(get_event_socket_dir_from_untracked(deep_untracked_dir))
    legacy = _source_with_call('send_request_stdin "PreToolUse" "" "pre-tool-use"')
    transport = TransportConfig(nc_enabled=True)

    result = generate_forwarder_content(legacy, "pre-tool-use", transport, deep_untracked_dir, _DEEP_ROOT)

    assert (
        _call_line(result)
        == f'send_request_stdin "PreToolUse" "" "pre-tool-use" "{expected_fallback}"'
    )


def test_previous_release_form_still_generates_valid_bash() -> None:
    legacy = _source_with_call('send_request_stdin "PreToolUse" "" "pre-tool-use"')
    transport = TransportConfig(nc_enabled=True)

    content = generate_forwarder_content(legacy, "pre-tool-use", transport, _UNTRACKED, _ROOT)

    result = subprocess.run(
        ["bash", "-n", "-c", content],
        capture_output=True,
        text=True,
        timeout=Timeout.VALIDATION_CHECK,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "hook_file",
    sorted(p.name for p in _HOOKS_DIR.iterdir() if p.is_file() and p.name != "README.md"),
)
def test_every_real_hook_generates_valid_bash_when_enabled(hook_file: str) -> None:
    source = (_HOOKS_DIR / hook_file).read_text()
    transport = TransportConfig(relay_enabled=True)

    content = generate_forwarder_content(source, hook_file, transport, _UNTRACKED, _ROOT)

    result = subprocess.run(
        ["bash", "-n", "-c", content],
        capture_output=True,
        text=True,
        timeout=Timeout.VALIDATION_CHECK,
    )
    assert result.returncode == 0, f"{hook_file}: {result.stderr}"


# ---------------------------------------------------------------------------
# Per-file resilience: one unreadable/malformed file must not abort the pass
# ---------------------------------------------------------------------------


def test_regenerate_skips_unreadable_file_and_still_strips_siblings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-UTF-8 file in the hooks dir must not prevent sibling files from
    being regenerated — and the skip must be reported, not swallowed."""
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text("daemon:\n  transport: {}\n")

    bad_file = hooks_dir / "pre-tool-use"
    bad_file.write_bytes(b"\xff\xfe\x00bad-bytes-not-utf8")

    good_file = hooks_dir / "post-tool-use"
    good_file.write_text(_SAMPLE_SOURCE)

    with caplog.at_level("WARNING"):
        rewritten = regenerate_deployed_hooks(tmp_path, hooks_dir)

    # The unreadable file was skipped, not written, and is reported.
    assert "pre-tool-use" not in rewritten
    assert any("pre-tool-use" in record.message for record in caplog.records)
    # The sibling file was still processed normally.
    assert bad_file.read_bytes() == b"\xff\xfe\x00bad-bytes-not-utf8"


def test_load_transport_config_falls_back_to_defaults_on_malformed_yaml(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed client config (bad YAML / failed pydantic validation) must
    resolve to pure defaults, matching the documented missing-config
    contract — not abort the whole regeneration pass."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text("daemon: [this is not valid: yaml: at all")

    with caplog.at_level("WARNING"):
        transport = load_transport_config(tmp_path)

    assert transport == TransportConfig()
    assert any("hooks-daemon.yaml" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# The guard belongs to ONE checkout (Plan 00364 Task 5.1)
# ---------------------------------------------------------------------------
#
# Every path in the guard is a literal, deliberately: it is a zero-spawn hot
# path that must not compute anything at hook-run time. A git worktree
# inherits the tracked forwarder VERBATIM, literals and all, so its
# `.claude/hooks/pre-tool-use` dialled the MAIN checkout's relay socket and
# was answered by the main checkout's daemon — the worktree's own handlers,
# config and project handlers never saw the event.
#
# The fix keeps every path a literal and adds one more: the hooks directory
# the forwarder was generated FOR. `${BASH_SOURCE[0]}` is the file bash is
# executing, so comparing it against that literal answers "am I the copy this
# guard was built for?" with a bash builtin and no spawn. A foreign copy
# falls through to init.sh, which computes ITS OWN checkout's socket.


def test_guard_block_requires_the_source_to_live_under_its_own_hooks_dir() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert '"${BASH_SOURCE[0]}" == "/proj/.claude/hooks/"*' in block


def test_the_checkout_test_is_on_the_same_line_as_the_reentry_check() -> None:
    """One `if`, so the guard keeps its single-branch zero-spawn shape."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    conditions = [line for line in block.splitlines() if line.startswith("if [[")]
    assert len(conditions) == 1
    assert conditions[0].startswith('if [[ "${1:-}" != "--no-relay" &&')


def test_the_checkout_test_adds_no_spawn() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert "$(" not in block
    assert "`" not in block


def test_the_relay_binary_override_still_applies() -> None:
    """The override must not become unreachable behind the checkout test."""
    transport = TransportConfig(relay_enabled=True, relay_binary="/opt/custom/hooks-relay")
    block = build_relay_guard_block("pre-tool-use", transport, _UNTRACKED, _ROOT)
    assert '_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/opt/custom/hooks-relay}"' in block
    assert '"${BASH_SOURCE[0]}" == "/proj/.claude/hooks/"*' in block


def test_the_events_dir_override_still_applies() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert '_rl_events_dir="${HOOKS_DAEMON_EVENTS_DIR:-$_rl_dir/events$_rl_sfx}"' in block


def test_a_client_layouts_root_is_not_derived_from_its_untracked_dir() -> None:
    """A client's untracked dir is three levels below the root it must name."""
    block = build_relay_guard_block(
        "pre-tool-use",
        TransportConfig(relay_enabled=True),
        Path("/client/.claude/hooks-daemon/untracked"),
        Path("/client"),
    )
    assert '"${BASH_SOURCE[0]}" == "/client/.claude/hooks/"*' in block
    assert '_rl_dir="/client/.claude/hooks-daemon/untracked"' in block


def test_the_generated_forwarder_carries_the_checkout_test() -> None:
    content = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert '"${BASH_SOURCE[0]}" == "/proj/.claude/hooks/"*' in content


def test_stripping_still_removes_a_guard_that_carries_the_checkout_test() -> None:
    """The strip is marker-based, so it must not care what the body says."""
    generated = generate_forwarder_content(
        _SAMPLE_SOURCE, "pre-tool-use", TransportConfig(relay_enabled=True), _UNTRACKED, _ROOT
    )
    assert strip_relay_guard_block(generated) == _SAMPLE_SOURCE
