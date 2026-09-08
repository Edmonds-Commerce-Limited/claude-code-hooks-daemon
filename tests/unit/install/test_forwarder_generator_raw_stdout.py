"""Daemon-down branch of a ``raw_stdout`` forwarder (Plan 00189, via Plan 00362 D8).

Claude Code parses a ``raw_stdout`` hook's stdout as a RAW value — the created
worktree's absolute path for ``WorktreeCreate``, the rendered status text for
``StatusLine``. The shared daemon-down stanza every JSON-decision forwarder
ends with (``emit_hook_error ... ; exit 0``) is therefore WRONG for these
events: the JSON error object lands on a stdout Claude Code reads as a path,
so a daemon that cannot start yields the literal path ``/<cwd>/{...json...}``.

The contract for a ``raw_stdout`` event's daemon-down branch is: never JSON on
stdout — only the catalogue's per-event ``daemon_down_stdout`` (empty for a
parsed VALUE such as the worktree path; a visible marker for a DISPLAY line
such as the status line) — the diagnostic on stderr, and a non-zero exit so
Claude Code treats the hook as not handled. It is generalised over the
catalogue's ``raw_stdout`` flag (single source of truth), so the tests below
run over EVERY wired ``raw_stdout`` event and keep one JSON-decision event as
the control.

The forwarders are driven for real, under ``bash``, against a stub ``init.sh``
whose ``ensure_daemon`` fails — so the assertion is about what actually
reaches stdout, not about the text of the script.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants.events import (
    EventID,
    raw_stdout_bash_keys,
    wired_event_metas,
)
from claude_code_hooks_daemon.install.forwarder_generator import (
    apply_raw_stdout_daemon_down,
    generate_forwarder_content,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOKS_DIR = _REPO_ROOT / ".claude" / "hooks"

_RAW_STDOUT_EVENTS: tuple[str, ...] = tuple(sorted(raw_stdout_bash_keys()))
_CONTROL_EVENT = "pre-tool-use"

#: Stand-in for ``.claude/init.sh`` whose daemon can never be started. The
#: JSON-decision helpers behave exactly as the real ones do on stdout — that
#: is the whole hazard under test — and the transport must never be reached.
_DAEMON_DOWN_INIT_SH = """\
ensure_daemon() { return 1; }
emit_hook_error() {
    echo "HOOKS DAEMON ERROR [$2]: $3" >&2
    printf '{"hookSpecificOutput": {"hookEventName": "%s", "additionalContext": "%s"}}\\n' "$1" "$3"
}
send_request_stdin() { echo "TRANSPORT MUST NOT RUN WITH THE DAEMON DOWN"; exit 99; }
forward_stop_event() { send_request_stdin "$@"; }
"""


def _run_generated_forwarder(
    tmp_path: Path, event_file_name: str
) -> subprocess.CompletedProcess[str]:
    """Generate the forwarder for ``event_file_name`` and run it daemon-down."""
    source = (_HOOKS_DIR / event_file_name).read_text()
    generated = generate_forwarder_content(
        source, event_file_name, TransportConfig(), tmp_path / "untracked"
    )
    claude_dir = tmp_path / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True)
    (claude_dir / "init.sh").write_text(_DAEMON_DOWN_INIT_SH)
    forwarder = hooks_dir / event_file_name
    forwarder.write_text(generated)
    return subprocess.run(
        ["bash", str(forwarder)],
        input='{"hook_event_name": "x"}',
        capture_output=True,
        text=True,
        timeout=30,
        env={"HOOKS_DAEMON_EVENTS_DIR": str(tmp_path / "no-sockets"), "PATH": "/usr/bin:/bin"},
    )


def test_the_catalogue_has_raw_stdout_events_to_cover() -> None:
    """The parametrisation below must never silently collapse to nothing."""
    assert "worktree-create" in _RAW_STDOUT_EVENTS
    assert "status-line" in _RAW_STDOUT_EVENTS
    assert _CONTROL_EVENT not in _RAW_STDOUT_EVENTS


def test_raw_stdout_bash_keys_derive_from_the_flag() -> None:
    expected = frozenset(m.bash_key for m in wired_event_metas() if m.raw_stdout)
    assert raw_stdout_bash_keys() == expected


@pytest.mark.parametrize("event_file_name", _RAW_STDOUT_EVENTS)
def test_raw_stdout_forwarder_daemon_down_prints_only_the_catalogue_text(
    tmp_path: Path, event_file_name: str
) -> None:
    meta = next(m for m in wired_event_metas() if m.bash_key == event_file_name)
    result = _run_generated_forwarder(tmp_path, event_file_name)

    assert result.stdout.strip() == meta.daemon_down_stdout, (
        f"{event_file_name}: Claude Code reads this stdout raw; expected "
        f"{meta.daemon_down_stdout!r}, got {result.stdout!r}"
    )
    assert "{" not in result.stdout, f"{event_file_name}: JSON reached a raw stdout"
    assert result.returncode != 0, f"{event_file_name}: must exit non-zero (not handled)"
    assert result.returncode != 99, f"{event_file_name}: transport ran with the daemon down"
    assert "HOOKS DAEMON ERROR" in result.stderr
    assert "daemon_startup_failed" in result.stderr


def test_worktree_create_daemon_down_prints_nothing(tmp_path: Path) -> None:
    """The stdout IS the path: anything printed becomes a garbage directory name."""
    assert EventID.WORKTREE_CREATE.daemon_down_stdout == ""
    result = _run_generated_forwarder(tmp_path, "worktree-create")

    assert result.stdout == ""
    assert result.returncode == 1


def test_status_line_daemon_down_keeps_the_visible_marker(tmp_path: Path) -> None:
    """The stdout is a DISPLAY line: silence would hide the outage from the human."""
    assert EventID.STATUS_LINE.daemon_down_stdout == "⚠️ DAEMON FAILED"
    result = _run_generated_forwarder(tmp_path, "status-line")

    assert result.stdout.strip() == "⚠️ DAEMON FAILED"
    assert result.returncode == 1
    assert "daemon_startup_failed" in result.stderr


def test_json_decision_forwarder_daemon_down_is_unchanged_control(tmp_path: Path) -> None:
    """The control: a JSON-decision event keeps emitting error JSON + exit 0."""
    result = _run_generated_forwarder(tmp_path, _CONTROL_EVENT)

    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


# ---------------------------------------------------------------------------
# The transform itself
# ---------------------------------------------------------------------------

_LEGACY_STANZA_SOURCE = """\
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

# Try to start daemon - if it fails, output proper JSON error to stdout
if ! ensure_daemon; then
    emit_hook_error "WorktreeCreate" "daemon_startup_failed" \\
        "Failed to start hooks daemon."
    exit 0  # Exit 0 so Claude processes the JSON response
fi

send_request_stdin "WorktreeCreate" "worktree"
"""


def test_transform_rewrites_the_legacy_stanza_for_a_raw_stdout_event() -> None:
    result = apply_raw_stdout_daemon_down(_LEGACY_STANZA_SOURCE, "worktree-create")

    assert "emit_hook_error" not in result
    assert "exit 0" not in result
    assert ">&2" in result
    assert "exit 1" in result
    assert "DAEMON FAILED" not in result  # a parsed value gets no stdout text
    # Everything outside the stanza is untouched.
    assert result.endswith('send_request_stdin "WorktreeCreate" "worktree"\n')
    assert result.startswith("#!/bin/bash\nset -euo pipefail\n")


def test_transform_is_idempotent() -> None:
    once = apply_raw_stdout_daemon_down(_LEGACY_STANZA_SOURCE, "worktree-create")
    twice = apply_raw_stdout_daemon_down(once, "worktree-create")
    assert twice == once


def test_transform_leaves_a_json_decision_event_untouched() -> None:
    source = _LEGACY_STANZA_SOURCE.replace("WorktreeCreate", "PreToolUse")
    assert apply_raw_stdout_daemon_down(source, _CONTROL_EVENT) == source


def test_transform_leaves_a_source_with_no_stanza_untouched() -> None:
    source = 'source "$SCRIPT_DIR/../init.sh"\nsend_request_stdin "WorktreeCreate" "worktree"\n'
    assert apply_raw_stdout_daemon_down(source, "worktree-create") == source


@pytest.mark.parametrize("event_file_name", _RAW_STDOUT_EVENTS)
def test_tracked_raw_stdout_forwarders_are_already_in_generated_form(
    event_file_name: str,
) -> None:
    """The committed ``.claude/hooks/<event>`` is what the generator emits.

    A client deploy that skips the Python regeneration step (no venv yet)
    ships a plain copy of this file, so the tracked copy itself must already
    carry the correct daemon-down branch.
    """
    source = (_HOOKS_DIR / event_file_name).read_text()
    assert apply_raw_stdout_daemon_down(source, event_file_name) == source
