"""Status-line fast path in the generated forwarder (issue #131, Plan 00542).

Each status-line tick used to source the ~3,800-line init.sh and start a
python3 before any byte reached the daemon. The generated forwarder now carries
a bash-builtin-only block, above that, that asks the daemon's per-event status
socket for RAW text through a client the transport config enables, prints a
non-empty reply, and otherwise falls through to the unchanged legacy path with
stdin intact.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants.protocol import HookInputField, RawTextReply
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install.forwarder_generator import generate_forwarder_content

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STATUS_SOURCE = (_REPO_ROOT / ".claude" / "hooks" / "status-line").read_text()
_HEADER = "# --- status fast path (generated; Plan 00542) ---"
_SCRIPT_DIR_LINE = 'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"'

#: init.sh stand-in: reaching it means the fast path fell through. It reports
#: that and echoes the stdin it was left with, so a test can assert the payload
#: survived intact.
_LEGACY_INIT_SH = """\
ensure_daemon() { return 0; }
send_request_stdin() { printf 'LEGACY:'; cat; }
"""


def _generate(transport: TransportConfig, tmp_path: Path, name: str = "status-line") -> str:
    return generate_forwarder_content(
        _STATUS_SOURCE, name, transport, tmp_path / "untracked", tmp_path
    )


class TestGeneratedText:
    def test_relay_enabled_inserts_the_block_above_script_dir(self, tmp_path: Path) -> None:
        text = _generate(TransportConfig(relay_enabled=True), tmp_path)
        assert _HEADER in text
        assert text.index(_HEADER) < text.index(_SCRIPT_DIR_LINE)
        assert HookInputField.RAW_TEXT in text
        assert "exec 0<<<" in text, "fall-through must replay stdin"

    def test_nc_only_builds_only_the_nc_client(self, tmp_path: Path) -> None:
        text = _generate(TransportConfig(relay_enabled=False, nc_enabled=True), tmp_path)
        assert _HEADER in text
        assert "nc -U -N" in text
        assert "--no-fallback" not in text

    def test_relay_only_builds_no_nc_client(self, tmp_path: Path) -> None:
        text = _generate(TransportConfig(relay_enabled=True, nc_enabled=False), tmp_path)
        assert "--no-fallback" in text
        assert "nc -U" not in text

    def test_both_disabled_leaves_the_forwarder_untouched(self, tmp_path: Path) -> None:
        text = _generate(TransportConfig(relay_enabled=False, nc_enabled=False), tmp_path)
        assert _HEADER not in text

    def test_other_events_get_no_fast_path(self, tmp_path: Path) -> None:
        source = (_REPO_ROOT / ".claude" / "hooks" / "pre-tool-use").read_text()
        text = generate_forwarder_content(
            source,
            "pre-tool-use",
            TransportConfig(relay_enabled=True, nc_enabled=True),
            tmp_path / "untracked",
            tmp_path,
        )
        assert _HEADER not in text

    def test_regeneration_is_idempotent_and_follows_config(self, tmp_path: Path) -> None:
        on = TransportConfig(relay_enabled=True)
        once = _generate(on, tmp_path)
        twice = generate_forwarder_content(
            once, "status-line", on, tmp_path / "untracked", tmp_path
        )
        assert twice == once
        off = generate_forwarder_content(
            once, "status-line", TransportConfig(relay_enabled=False), tmp_path / "untracked", tmp_path
        )
        assert _HEADER not in off
        assert off == _generate(TransportConfig(relay_enabled=False), tmp_path)

    def test_the_block_is_guarded_to_its_own_checkout(self, tmp_path: Path) -> None:
        text = _generate(TransportConfig(relay_enabled=True), tmp_path)
        assert f'"${{BASH_SOURCE[0]}}" == "{tmp_path}/.claude/hooks/"*' in text

    def test_a_read_status_above_one_is_loud(self, tmp_path: Path) -> None:
        """bash `read` returns 1 for every I/O error (EISDIR, EBADF, EIO, EOF alike) and above 1
        only for a timeout or a bad `-u` fd, so no stdin can drive it there in a test."""
        text = _generate(TransportConfig(relay_enabled=True), tmp_path)
        assert '[[ "$_sf_rc" -gt 1 ]]' in text
        assert "could not read its input" in text

    def test_the_block_forks_nothing_outside_the_client_call(self, tmp_path: Path) -> None:
        text = _generate(TransportConfig(relay_enabled=True, nc_enabled=True), tmp_path)
        block = text[text.index(_HEADER) : text.index(_SCRIPT_DIR_LINE)]
        for forbidden in ("cat ", "grep ", "awk ", "dirname", "basename", "mktemp", "python"):
            assert forbidden not in block, forbidden


SENTINEL = RawTextReply.SENTINEL


@pytest.fixture
def short_dir() -> Generator[Path, None, None]:
    """A short directory: an AF_UNIX path may not exceed ~100 bytes."""
    path = Path(tempfile.mkdtemp(prefix="sf"))
    yield path
    shutil.rmtree(path)


class _Rig:
    """A project dir holding a generated status-line, a fake init.sh, a bound
    status socket and a recording fake client."""

    def __init__(self, project: Path, events: Path, transport: TransportConfig) -> None:
        self.project = project
        self.events = events
        hooks = project / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (project / ".claude" / "init.sh").write_text(_LEGACY_INIT_SH)
        self.forwarder = hooks / "status-line"
        self.forwarder.write_text(_generate(transport, project))
        events.mkdir(exist_ok=True)
        self.sock_path = events / "status-line.sock"
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(self.sock_path))
        self.record = project / "client-record"
        self.client = project / "fake-client"

    def close(self) -> None:
        self._server.close()

    def install_client(self, reply: str, rc: int = 0) -> None:
        """A client stand-in that records argv and stdin and prints ``reply``.

        Used both as the relay binary and, named ``nc``, as the nc client.
        """
        self.client.write_text(
            "#!/bin/bash\n"
            f'printf \'%s\\n\' "$*" > "{self.record}"\n'
            f'cat >> "{self.record}"\n'
            f"printf '%s' '{reply}'\n"
            f"exit {rc}\n"
        )
        self.client.chmod(0o755)

    def run(
        self, payload: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        base = {"PATH": "/usr/bin:/bin", "HOOKS_DAEMON_EVENTS_DIR": str(self.events)}
        base.update(env or {})
        return subprocess.run(
            ["/bin/bash", str(self.forwarder)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_DEFAULT,
            env=base,
            check=False,
        )


@pytest.fixture
def rig(tmp_path: Path, short_dir: Path) -> Generator[_Rig, None, None]:
    made = _Rig(tmp_path, short_dir / "ev", TransportConfig(relay_enabled=True))
    made.install_client(f"{SENTINEL}model | 25%\n")
    yield made
    made.close()


def _relay_env(rig: _Rig) -> dict[str, str]:
    return {"HOOKS_DAEMON_RELAY_BINARY": str(rig.client)}


PAYLOAD = '{"model": {"display_name": "M"}}'

_RED = "\x1b[31m"


def _is_loud(result: subprocess.CompletedProcess[str], message: str) -> bool:
    """One red status line naming the fault, exit 0, and no hand-off to the legacy path."""
    lines = result.stdout.splitlines()
    return (
        result.returncode == 0
        and len(lines) == 1
        and lines[0].startswith(_RED)
        and message in lines[0]
        and "LEGACY" not in result.stdout
    )


class TestRelayFastPath:
    def test_a_non_empty_reply_is_printed_and_the_legacy_path_never_runs(self, rig: _Rig) -> None:
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert result.stdout == "model | 25%\n"
        assert result.returncode == 0
        assert "LEGACY" not in result.stdout

    def test_the_request_asks_for_raw_text_and_carries_the_terminal_size(self, rig: _Rig) -> None:
        rig.run(PAYLOAD, {**_relay_env(rig), "COLUMNS": "120", "LINES": "40"})
        recorded = rig.record.read_text()
        assert str(rig.sock_path) in recorded.splitlines()[0]
        assert "--no-fallback" in recorded.splitlines()[0]
        assert '"hooks_daemon_raw_text":true' in recorded
        assert '"terminal_columns":120' in recorded
        assert '"terminal_lines":40' in recorded
        assert '"model": {"display_name": "M"}' in recorded

    def test_a_non_numeric_or_unset_size_is_left_out(self, rig: _Rig) -> None:
        rig.run(PAYLOAD, {**_relay_env(rig), "COLUMNS": "wide", "LINES": "007"})
        recorded = rig.record.read_text()
        assert "terminal_columns" not in recorded
        assert "terminal_lines" not in recorded

    def test_an_empty_object_payload_stays_valid_json(self, rig: _Rig) -> None:
        rig.run("{ }\n", _relay_env(rig))
        assert '{"hooks_daemon_raw_text":true}' in rig.record.read_text()

    def test_trailing_whitespace_after_the_object_is_tolerated(self, rig: _Rig) -> None:
        result = rig.run(PAYLOAD + "\n\n", _relay_env(rig))
        assert result.stdout == "model | 25%\n"

    def test_the_sentinel_is_stripped_and_exactly_the_text_is_printed(self, rig: _Rig) -> None:
        rig.install_client(f"{SENTINEL}one | two\n")
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert result.stdout == "one | two\n"
        assert SENTINEL not in result.stdout

    @pytest.mark.parametrize(
        "reply",
        [
            '{"text": "x"}',
            '{"text": "x"}\n',
            '{"error": "unknown field"}',
            "plain text from nowhere\n",
            f"x{SENTINEL}not at the start\n",
        ],
    )
    def test_a_non_empty_reply_without_the_sentinel_is_loud_and_never_printed(
        self, rig: _Rig, reply: str
    ) -> None:
        """An older daemon answers raw requests with JSON: name the fault, never print it."""
        rig.install_client(reply)
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert _is_loud(result, "daemon older than its forwarder: run bin/hooks-daemon restart")
        assert '"text"' not in result.stdout
        assert '"error"' not in result.stdout

    @pytest.mark.parametrize("reply", ["", SENTINEL, f"{SENTINEL}\n"])
    def test_an_empty_reply_is_a_protocol_fault_and_loud(self, rig: _Rig, reply: str) -> None:
        rig.install_client(reply)
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert _is_loud(result, "empty status reply")

    def test_a_daemon_error_reply_is_printed_as_the_python_rung_prints_it(self, rig: _Rig) -> None:
        rig.install_client(f"{SENTINEL}⚠️ ERROR: boom\n")
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert result.stdout == "⚠️ ERROR: boom\n"
        assert result.returncode == 0

    def test_a_relay_timeout_is_loud(self, rig: _Rig) -> None:
        rig.install_client("partial", 11)
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert _is_loud(result, "status timed out after 2s (daemon busy)")
        assert "partial" not in result.stdout

    @pytest.mark.parametrize("rc", [12, 13, 99])
    def test_any_other_relay_failure_is_loud_and_names_the_exit_code(
        self, rig: _Rig, rc: int
    ) -> None:
        rig.install_client("", rc)
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert _is_loud(result, f"status client failed (exit {rc})")

    def test_a_refused_connection_hands_off_to_the_startup_path_with_stdin_intact(
        self, rig: _Rig
    ) -> None:
        rig.install_client("", 10)
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert result.stdout.startswith("LEGACY:")
        assert PAYLOAD in result.stdout
        assert _RED not in result.stdout

    def test_no_socket_hands_off_without_invoking_the_client(self, rig: _Rig) -> None:
        rig.sock_path.unlink()
        result = rig.run(PAYLOAD, _relay_env(rig))
        assert result.stdout.startswith("LEGACY:")
        assert not rig.record.exists()

    def test_a_missing_relay_binary_is_loud_and_names_the_fix(self, rig: _Rig) -> None:
        result = rig.run(PAYLOAD, {"HOOKS_DAEMON_RELAY_BINARY": str(rig.project / "absent")})
        assert _is_loud(result, "hooks-relay missing")
        assert "run bin/hooks-daemon transport on" in result.stdout
        assert "LEGACY" not in result.stdout

    def test_a_missing_relay_binary_is_loud_even_with_no_socket(self, rig: _Rig) -> None:
        rig.sock_path.unlink()
        result = rig.run(PAYLOAD, {"HOOKS_DAEMON_RELAY_BINARY": str(rig.project / "absent")})
        assert _is_loud(result, "hooks-relay missing")


class TestNcFastPath:
    @pytest.fixture
    def nc_rig(self, tmp_path: Path, short_dir: Path) -> Generator[_Rig, None, None]:
        made = _Rig(tmp_path, short_dir / "ev", TransportConfig(relay_enabled=False, nc_enabled=True))
        made.install_client(f"{SENTINEL}from nc\n")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "nc").symlink_to(made.client)
        yield made
        made.close()

    def _env(self, rig: _Rig) -> dict[str, str]:
        return {"PATH": f"{rig.project / 'bin'}:/usr/bin:/bin"}

    def test_nc_is_used_only_when_the_probe_recorded_capability(self, nc_rig: _Rig) -> None:
        (nc_rig.project / ".claude" / "hooks-daemon.env").write_text(
            'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH"\nHOOKS_DAEMON_NC_UNIX_CAPABLE="1"\n'
        )
        result = nc_rig.run(PAYLOAD, self._env(nc_rig))
        assert result.stdout == "from nc\n"
        assert "-U -N -w" in nc_rig.record.read_text().splitlines()[0]

    def test_an_incapable_nc_is_loud_and_names_the_probe_result(self, nc_rig: _Rig) -> None:
        (nc_rig.project / ".claude" / "hooks-daemon.env").write_text(
            'HOOKS_DAEMON_NC_UNIX_CAPABLE="0"\n'
        )
        result = nc_rig.run(PAYLOAD, self._env(nc_rig))
        assert _is_loud(result, "nc cannot do unix sockets (HOOKS_DAEMON_NC_UNIX_CAPABLE=0)")
        assert not nc_rig.record.exists()

    def test_no_env_file_is_loud_as_an_unprobed_nc(self, nc_rig: _Rig) -> None:
        result = nc_rig.run(PAYLOAD, self._env(nc_rig))
        assert _is_loud(result, "nc cannot do unix sockets (HOOKS_DAEMON_NC_UNIX_CAPABLE=0)")
        assert not nc_rig.record.exists()

    def _capable(self, rig: _Rig) -> None:
        (rig.project / ".claude" / "hooks-daemon.env").write_text(
            'HOOKS_DAEMON_NC_UNIX_CAPABLE="1"\n'
        )

    def test_nc_not_on_the_path_is_loud(self, nc_rig: _Rig) -> None:
        self._capable(nc_rig)
        (nc_rig.project / "bin" / "nc").unlink()
        result = nc_rig.run(PAYLOAD, {"PATH": str(nc_rig.project / "bin")})
        assert _is_loud(result, "nc not found")

    def test_nc_refused_hands_off_to_the_startup_path(self, nc_rig: _Rig) -> None:
        """nc exits 1 for a refused connection; the socket file exists (a stale one)."""
        self._capable(nc_rig)
        nc_rig.install_client("", 1)
        result = nc_rig.run(PAYLOAD, self._env(nc_rig))
        assert result.stdout.startswith("LEGACY:")
        assert PAYLOAD in result.stdout

    def test_nc_no_socket_hands_off_without_invoking_nc(self, nc_rig: _Rig) -> None:
        self._capable(nc_rig)
        nc_rig.sock_path.unlink()
        result = nc_rig.run(PAYLOAD, self._env(nc_rig))
        assert result.stdout.startswith("LEGACY:")
        assert not nc_rig.record.exists()

    def test_nc_silent_timeout_is_an_empty_reply_and_loud(self, nc_rig: _Rig) -> None:
        """A silent listener makes `nc -w` exit 0 with an empty reply."""
        self._capable(nc_rig)
        nc_rig.install_client("", 0)
        result = nc_rig.run(PAYLOAD, self._env(nc_rig))
        assert _is_loud(result, "timed out after 2s")

    def test_nc_failure_is_loud(self, nc_rig: _Rig) -> None:
        self._capable(nc_rig)
        nc_rig.install_client("", 2)
        result = nc_rig.run(PAYLOAD, self._env(nc_rig))
        assert _is_loud(result, "status client failed (exit 2)")

    def test_the_env_file_is_read_not_sourced(self, nc_rig: _Rig) -> None:
        """Sourcing would run its contents under set -u (an unset PROJECT_PATH)."""
        (nc_rig.project / ".claude" / "hooks-daemon.env").write_text(
            'touch "$PROJECT_PATH/pwned"\nHOOKS_DAEMON_NC_UNIX_CAPABLE="1"\n'
        )
        result = nc_rig.run(PAYLOAD, self._env(nc_rig))
        assert result.stdout == "from nc\n"
        assert not (nc_rig.project / "pwned").exists()
