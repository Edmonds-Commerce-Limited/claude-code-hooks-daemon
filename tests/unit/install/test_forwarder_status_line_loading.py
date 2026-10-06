"""Plan 00495 Task 2.7: a slow daemon start is "loading", a failed start is "failed".

The status line is a DISPLAY line. While the daemon is still starting the
forwarder answers at once with a baseline "loading" line (and exits 0, since
it handled the event) instead of waiting out the start deadline and then
printing the outage marker. A start that has genuinely failed keeps printing
the distinct outage marker and exiting non-zero.

The forwarders are driven for real, under ``bash``, against a stub ``init.sh``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants.events import EventID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install.forwarder_generator import (
    apply_raw_stdout_daemon_down,
    generate_forwarder_content,
)
from tests.unit.install.test_forwarder_generator_raw_stdout import (
    _DAEMON_DOWN_INIT_SH,
    _HOOKS_DIR,
)

_LOADING_TEXT = "⏳ hooks daemon loading…"

#: ensure_daemon fails the way start_daemon reports "still starting"; it also
#: insists the forwarder asked for a non-blocking start.
_DAEMON_STARTING_INIT_SH = """\
ensure_daemon() {
    [[ "${_HOOKS_DAEMON_NONBLOCKING_START:-}" == "true" ]] || return 3
    _HOOKS_DAEMON_STARTING=true
    return 1
}
send_request_stdin() { echo "TRANSPORT MUST NOT RUN"; exit 99; }
"""


def _run_with_init_sh(
    tmp_path: Path, event_file_name: str, init_sh: str
) -> subprocess.CompletedProcess[str]:
    """Generate the forwarder for ``event_file_name`` and run it against ``init_sh``."""
    source = (_HOOKS_DIR / event_file_name).read_text()
    generated = generate_forwarder_content(
        source, event_file_name, TransportConfig(), tmp_path / "untracked", tmp_path
    )
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    (tmp_path / ".claude" / "init.sh").write_text(init_sh)
    forwarder = hooks_dir / event_file_name
    forwarder.write_text(generated)
    return subprocess.run(
        ["bash", str(forwarder)],
        input='{"hook_event_name": "x"}',
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
        env={"HOOKS_DAEMON_EVENTS_DIR": str(tmp_path / "no-sockets"), "PATH": "/usr/bin:/bin"},
    )


def test_catalogue_names_a_loading_text_for_the_status_line_only() -> None:
    assert EventID.STATUS_LINE.daemon_loading_stdout == _LOADING_TEXT
    assert EventID.WORKTREE_CREATE.daemon_loading_stdout == ""


def test_status_line_while_daemon_starting_prints_loading_and_exits_zero(tmp_path: Path) -> None:
    result = _run_with_init_sh(tmp_path, "status-line", _DAEMON_STARTING_INIT_SH)

    assert result.stdout.strip() == _LOADING_TEXT
    assert result.returncode == 0


def test_status_line_loading_text_can_be_named_by_init_sh(tmp_path: Path) -> None:
    init_sh = '_HOOKS_DAEMON_STATUS_LOADING_TEXT="custom loading"\n' + _DAEMON_STARTING_INIT_SH
    result = _run_with_init_sh(tmp_path, "status-line", init_sh)

    assert result.stdout.strip() == "custom loading"


def test_status_line_genuine_failure_is_still_reported_distinctly(tmp_path: Path) -> None:
    result = _run_with_init_sh(tmp_path, "status-line", _DAEMON_DOWN_INIT_SH)

    assert result.stdout.strip() == "⚠️ DAEMON FAILED"
    assert result.returncode == 1
    assert "daemon_startup_failed" in result.stderr


def test_worktree_create_has_no_loading_branch() -> None:
    """A parsed VALUE is never answered with display text."""
    generated = (_HOOKS_DIR / "worktree-create").read_text()
    assert "loading" not in generated
    assert "NONBLOCKING" not in generated


def test_the_loading_branch_survives_regeneration() -> None:
    generated = (_HOOKS_DIR / "status-line").read_text()
    assert "_HOOKS_DAEMON_NONBLOCKING_START=true ensure_daemon" in generated
    assert apply_raw_stdout_daemon_down(generated, "status-line") == generated
