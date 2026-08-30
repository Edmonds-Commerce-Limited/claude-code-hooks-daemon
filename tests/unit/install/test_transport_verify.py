"""Unit tests for the transport verification probes (Plan 00294).

The probes assert the THREE host-boundary contracts from
``CLAUDE/development/LESSONS.md`` "Test in the host's invocation context":
stdin is a genuine SOCKET (socketpair, never a pipe), payloads are what
Claude Code actually sends (nothing hand-added that a layer under test
injects), and the RESPONSE shape is the one the host consumes (JSON decision
object / raw text / exit-code-2). Here each probe runs against stub
forwarder scripts emitting known-good and known-bad shapes; the real
deployed-forwarder path is covered by the acceptance cycle test.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants.events import wired_event_metas
from claude_code_hooks_daemon.install.forwarder_generator import (
    INIT_SH_ANCHOR,
    build_relay_guard_block,
)
from claude_code_hooks_daemon.install.transport_verify import (
    probe_forwarder_guard_state,
    probe_listener_count,
    probe_no_event_listeners,
    probe_pre_tool_use,
    probe_status_line,
    probe_stop_hard_block,
    run_probes,
)


def _write_script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(0o755)
    return path


class TestPreToolUseProbe:
    def test_json_object_response_passes(self, tmp_path: Path) -> None:
        _write_script(tmp_path / "pre-tool-use", "cat >/dev/null\necho '{}'\n")
        result = probe_pre_tool_use(tmp_path)
        assert result.passed, result.detail
        assert result.name == "pre-tool-use-json"

    def test_reads_stdin_from_a_socket_not_a_pipe(self, tmp_path: Path) -> None:
        # `< /dev/stdin` re-opens the stdin path — an open() on a socket fails
        # ENXIO. A probe faithfully reproducing the host's invocation manner
        # must make this stub FAIL, exactly as the live outage did.
        _write_script(
            tmp_path / "pre-tool-use",
            'cat < /dev/stdin >/dev/null 2>&1 || { echo "reopen failed" >&2; exit 1; }\n'
            "echo '{}'\n",
        )
        result = probe_pre_tool_use(tmp_path)
        assert not result.passed

    def test_non_json_response_fails(self, tmp_path: Path) -> None:
        _write_script(tmp_path / "pre-tool-use", "cat >/dev/null\necho 'garbage'\n")
        result = probe_pre_tool_use(tmp_path)
        assert not result.passed
        assert "garbage" in result.detail

    def test_nonzero_exit_fails(self, tmp_path: Path) -> None:
        _write_script(tmp_path / "pre-tool-use", "cat >/dev/null\necho '{}'\nexit 3\n")
        result = probe_pre_tool_use(tmp_path)
        assert not result.passed

    def test_missing_forwarder_fails(self, tmp_path: Path) -> None:
        result = probe_pre_tool_use(tmp_path)
        assert not result.passed
        assert "pre-tool-use" in result.detail


class TestStatusLineProbe:
    def test_raw_text_response_passes(self, tmp_path: Path) -> None:
        _write_script(tmp_path / "status-line", "cat >/dev/null\necho 'main | Sonnet'\n")
        result = probe_status_line(tmp_path)
        assert result.passed, result.detail
        assert result.name == "status-line-raw"

    def test_json_object_response_fails(self, tmp_path: Path) -> None:
        # raw_stdout contract: Claude Code renders these bytes verbatim — a
        # JSON envelope on stdout means the unwrap never happened.
        _write_script(tmp_path / "status-line", 'cat >/dev/null\necho \'{"line":"x"}\'\n')
        result = probe_status_line(tmp_path)
        assert not result.passed

    def test_empty_response_fails(self, tmp_path: Path) -> None:
        _write_script(tmp_path / "status-line", "cat >/dev/null\n")
        result = probe_status_line(tmp_path)
        assert not result.passed


class TestStopHardBlockProbe:
    def test_exit_2_with_reason_on_stderr_passes(self, tmp_path: Path) -> None:
        _write_script(
            tmp_path / "stop",
            "cat >/dev/null\n"
            'echo \'{"decision":"block","reason":"explain the stop"}\'\n'
            'echo "explain the stop" >&2\n'
            "exit 2\n",
        )
        result = probe_stop_hard_block(tmp_path)
        assert result.passed, result.detail
        assert result.name == "stop-hard-block"

    def test_exit_0_fails(self, tmp_path: Path) -> None:
        _write_script(
            tmp_path / "stop",
            'cat >/dev/null\necho \'{"decision":"block","reason":"r"}\'\n',
        )
        result = probe_stop_hard_block(tmp_path)
        assert not result.passed

    def test_reason_missing_from_stderr_fails(self, tmp_path: Path) -> None:
        _write_script(
            tmp_path / "stop",
            "cat >/dev/null\n" 'echo \'{"decision":"block","reason":"the reason"}\'\n' "exit 2\n",
        )
        result = probe_stop_hard_block(tmp_path)
        assert not result.passed


class TestListenerProbes:
    def test_all_wired_sockets_present_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        monkeypatch.setenv("HOOKS_DAEMON_EVENTS_DIR", str(events_dir))
        for meta in wired_event_metas():
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(events_dir / f"{meta.bash_key}.sock"))
            sock.close()

        result = probe_listener_count(tmp_path)

        assert result.passed, result.detail
        assert str(len(wired_event_metas())) in result.detail

    def test_missing_socket_fails_and_names_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        monkeypatch.setenv("HOOKS_DAEMON_EVENTS_DIR", str(events_dir))
        for meta in wired_event_metas():
            if meta.bash_key == "pre-tool-use":
                continue
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(events_dir / f"{meta.bash_key}.sock"))
            sock.close()

        result = probe_listener_count(tmp_path)

        assert not result.passed
        assert "pre-tool-use" in result.detail

    def test_no_event_listeners_passes_on_stale_unbound_socket_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A stale socket FILE with no live listener must not fail the
        # off-state check — only an accepting listener means the daemon is
        # still serving the relay path.
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        monkeypatch.setenv("HOOKS_DAEMON_EVENTS_DIR", str(events_dir))
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(events_dir / "pre-tool-use.sock"))
        sock.close()

        result = probe_no_event_listeners(tmp_path)

        assert result.passed, result.detail

    def test_no_event_listeners_fails_on_a_live_listener(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        monkeypatch.setenv("HOOKS_DAEMON_EVENTS_DIR", str(events_dir))
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(events_dir / "pre-tool-use.sock"))
        listener.listen(1)
        try:
            result = probe_no_event_listeners(tmp_path)
        finally:
            listener.close()

        assert not result.passed
        assert "pre-tool-use" in result.detail


class TestGuardStateProbe:
    def test_guard_expected_and_present_passes(self, tmp_path: Path) -> None:
        guard = build_relay_guard_block("pre-tool-use", TransportConfig(), tmp_path)
        (tmp_path / "pre-tool-use").write_text("#!/bin/bash\n" + guard + INIT_SH_ANCHOR)
        result = probe_forwarder_guard_state(tmp_path, expect_relay=True)
        assert result.passed, result.detail

    def test_guard_expected_but_absent_fails(self, tmp_path: Path) -> None:
        (tmp_path / "pre-tool-use").write_text("#!/bin/bash\n" + INIT_SH_ANCHOR)
        result = probe_forwarder_guard_state(tmp_path, expect_relay=True)
        assert not result.passed

    def test_guard_unexpected_but_present_fails(self, tmp_path: Path) -> None:
        guard = build_relay_guard_block("pre-tool-use", TransportConfig(), tmp_path)
        (tmp_path / "pre-tool-use").write_text("#!/bin/bash\n" + guard + INIT_SH_ANCHOR)
        result = probe_forwarder_guard_state(tmp_path, expect_relay=False)
        assert not result.passed
        assert "pre-tool-use" in result.detail

    def test_clean_forwarders_with_relay_off_passes(self, tmp_path: Path) -> None:
        (tmp_path / "pre-tool-use").write_text("#!/bin/bash\n" + INIT_SH_ANCHOR)
        result = probe_forwarder_guard_state(tmp_path, expect_relay=False)
        assert result.passed, result.detail


class TestRunProbesComposition:
    def test_on_state_runs_the_documented_probe_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        monkeypatch.setenv("HOOKS_DAEMON_EVENTS_DIR", str(events_dir))

        results = run_probes(tmp_path, hooks_dir, expect_relay=True)

        names = [result.name for result in results]
        assert names == [
            "forwarder-guard-state",
            "listener-count",
            "pre-tool-use-json",
            "status-line-raw",
            "stop-hard-block",
        ]

    def test_off_state_swaps_listener_probe_for_no_listener_probe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        monkeypatch.setenv("HOOKS_DAEMON_EVENTS_DIR", str(tmp_path / "events"))

        results = run_probes(tmp_path, hooks_dir, expect_relay=False)

        names = [result.name for result in results]
        assert names == [
            "forwarder-guard-state",
            "no-event-listeners",
            "pre-tool-use-json",
            "status-line-raw",
            "stop-hard-block",
        ]
