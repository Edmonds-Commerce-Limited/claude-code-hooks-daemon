"""Plan 00294 acceptance gate — the transport toggle against a REAL daemon.

Drives ``transport on|off|status`` end-to-end in an ISOLATED client-layout
project (its own config, forwarders, daemon, sockets and untracked dir at a
short ``/tmp`` path), so nothing here can ever touch this repository's live
daemon or deployed forwarders. The cycle proves:

- on -> verify -> off -> verify, each as ONE command, with the built-in
  socket-stdin verification passing against the real daemon;
- idempotent no-ops (on-when-on, off-when-off);
- comment preservation through the real config flip;
- AUTO-REVERT: a deliberately broken relay binary makes ``transport on``
  fail verification, restore the off state end-to-end, re-verify it, exit
  non-zero and name the failing probe.

The fixture project's ``init.sh``/forwarders are copies of this repo's own
deployed hooks; their legacy transport needs only a system ``python3`` while
the daemon is already running, and the daemon itself runs from this test
process's interpreter (the repo venv) — the same recipe as the daemon smoke
suite.
"""

from __future__ import annotations

import json
import os
import shutil

# SECURITY: subprocess runs only [sys.executable, -m, <this package's CLI>]
# with fixed argument lists, no shell, no user input.
import subprocess  # nosec B404
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir_from_untracked

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_RELAY_BINARY = REPO_ROOT / "untracked" / "bin" / "hooks-relay"

_COMMENT_SENTINEL = "comment sentinel: must survive every toggle"

_START_TIMEOUT_SECONDS = 30
_CLI_TIMEOUT_SECONDS = 300


def _fixture_config(relay_binary: Path) -> str:
    return f"""\
version: '1.0'
daemon:
  idle_timeout_seconds: 600
  log_level: INFO
  self_install_mode: false
  transport:
    # {_COMMENT_SENTINEL}
    relay_enabled: false
    nc_enabled: false
    timeout_seconds: 30
    relay_binary: {relay_binary}
handlers:
  stop:
    auto_continue_stop:
      enabled: true
  status_line:
    model_context:
      enabled: true
"""


def _clean_env() -> dict[str, str]:
    """This test process's env minus every hooks-daemon path override, so the
    fixture daemon and forwarders resolve everything from the FIXTURE project."""
    env = dict(os.environ)
    for key in (
        "CLAUDE_HOOKS_SOCKET_PATH",
        "CLAUDE_HOOKS_PID_PATH",
        "CLAUDE_HOOKS_LOG_PATH",
        "HOOKS_DAEMON_EVENTS_DIR",
        "HOOKS_DAEMON_RELAY_BINARY",
        "HOOKS_DAEMON_ROOT_DIR",
        "CLAUDE_PROJECT_DIR",
    ):
        env.pop(key, None)
    return env


def _run_cli(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # SECURITY: fixed argv — this interpreter, this package's CLI. No shell.
    return subprocess.run(  # nosec B603
        [
            sys.executable,
            "-m",
            "claude_code_hooks_daemon.daemon.cli",
            "--project-root",
            str(project),
            *args,
        ],
        cwd=project,
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=_CLI_TIMEOUT_SECONDS,
        check=False,
    )


def _daemon_lifecycle(project: Path, action: str) -> None:
    """start/stop with output to DEVNULL — a captured pipe would make run()
    wait for the daemonised child, not the CLI (daemon-smoke lesson)."""
    # SECURITY: fixed argv — this interpreter, this package's CLI. No shell.
    subprocess.run(  # nosec B603
        [
            sys.executable,
            "-m",
            "claude_code_hooks_daemon.daemon.cli",
            "--project-root",
            str(project),
            action,
        ],
        cwd=project,
        env=_clean_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=_CLI_TIMEOUT_SECONDS,
        check=False,
    )


def _wait_for_running(project: Path) -> None:
    deadline = time.monotonic() + _START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        status = _run_cli(project, "status")
        if "RUNNING" in status.stdout:
            return
        time.sleep(0.5)
    pytest.fail("fixture daemon did not report RUNNING in time")


def _git(project: Path, *args: str) -> None:
    # SECURITY: trusted system tool, list form, fixture-local repo.
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)  # nosec B603 B607


@pytest.fixture(scope="module")
def client_project() -> Iterator[Path]:
    if not REAL_RELAY_BINARY.is_file():
        pytest.skip(f"relay binary not built: {REAL_RELAY_BINARY}")
    # A SHORT path, deliberately not tmp_path: the fixture's per-event socket
    # paths must fit the AF_UNIX limit without engaging the fallback root.
    root = Path(tempfile.mkdtemp(prefix="hdtt-", dir="/tmp"))  # nosec B108
    try:
        claude_dir = root / ".claude"
        (claude_dir / "hooks-daemon" / "untracked").mkdir(parents=True)
        # Real deployed forwarders + init.sh, copied from this repo's own.
        shutil.copytree(
            REPO_ROOT / ".claude" / "hooks",
            claude_dir / "hooks",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copy2(REPO_ROOT / ".claude" / "init.sh", claude_dir / "init.sh")

        # Clients legitimately ship their own files in .claude/hooks/ (canary
        # run 4, defect D1) — verification must never judge these.
        for foreign in ("php-qa-ci__custom.py", "CLAUDE.md", "README.md", "test-all-hooks.sh"):
            (claude_dir / "hooks" / foreign).write_text("# client-owned file, not a forwarder\n")

        # Relay SOURCE ships in every install; the build-provisioning test
        # (defect D2) compiles it for real from the fixture's own daemon dir.
        relay_src_dir = claude_dir / "hooks-daemon" / "relay"
        relay_src_dir.mkdir()
        shutil.copy2(REPO_ROOT / "relay" / "hooks_relay.rs", relay_src_dir / "hooks_relay.rs")
        shutil.copy2(REPO_ROOT / "relay" / "build.sh", relay_src_dir / "build.sh")

        relay_binary = root / "relay-bin" / "hooks-relay"
        relay_binary.parent.mkdir()
        shutil.copy2(REAL_RELAY_BINARY, relay_binary)

        (claude_dir / "hooks-daemon.yaml").write_text(_fixture_config(relay_binary))

        _git(root, "init")
        _git(root, "config", "user.email", "test@test.invalid")
        _git(root, "config", "user.name", "Test User")
        _git(root, "remote", "add", "origin", "https://github.com/test/repo.git")

        _daemon_lifecycle(root, "start")
        _wait_for_running(root)
        yield root
    finally:
        _daemon_lifecycle(root, "stop")
        shutil.rmtree(root, ignore_errors=True)


def _config_text(project: Path) -> str:
    return (project / ".claude" / "hooks-daemon.yaml").read_text()


def _forwarder_text(project: Path, name: str) -> str:
    return (project / ".claude" / "hooks" / name).read_text()


def _toggle_state(project: Path) -> dict[str, object]:
    state_path = project / ".claude" / "hooks-daemon" / "untracked" / "transport-toggle-state.json"
    assert state_path.is_file(), "toggle state file missing"
    loaded = json.loads(state_path.read_text())
    assert isinstance(loaded, dict)
    return loaded


class TestToggleCycle:
    """on -> verify -> off -> verify, plus idempotent no-ops, in order."""

    def test_initial_status_reports_relay_off(self, client_project: Path) -> None:
        result = _run_cli(client_project, "transport", "status", "--json")
        assert result.returncode == 0, result.stderr
        snapshot = json.loads(result.stdout)
        assert snapshot["relay_enabled"] is False
        assert snapshot["rung"] == "bash+python3"

    def test_transport_on_verifies_against_the_real_daemon(self, client_project: Path) -> None:
        result = _run_cli(client_project, "transport", "on")

        assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
        assert "verified" in result.stdout
        assert "relay_enabled: true" in _config_text(client_project)
        assert _COMMENT_SENTINEL in _config_text(client_project)
        assert "relay hot path" in _forwarder_text(client_project, "pre-tool-use")
        # raw_stdout + stop events must never gain a guard.
        assert "relay hot path" not in _forwarder_text(client_project, "status-line")
        assert "relay hot path" not in _forwarder_text(client_project, "stop")
        # The daemon really bound the per-event listeners.
        events_dir = get_event_socket_dir_from_untracked(
            client_project / ".claude" / "hooks-daemon" / "untracked"
        )
        assert (events_dir / "pre-tool-use.sock").is_socket()
        state = _toggle_state(client_project)
        assert state["action"] == "on"
        assert state["verified"] is True
        assert state["reverted"] is False

    def test_transport_on_when_on_is_a_clean_no_op(self, client_project: Path) -> None:
        result = _run_cli(client_project, "transport", "on")
        assert result.returncode == 0, result.stderr
        assert "already" in result.stdout
        assert "relay_enabled: true" in _config_text(client_project)

    def test_status_reports_relay_rung_and_listeners(self, client_project: Path) -> None:
        result = _run_cli(client_project, "transport", "status", "--json")
        snapshot = json.loads(result.stdout)
        assert snapshot["relay_enabled"] is True
        assert snapshot["rung"] == "relay"
        assert snapshot["relay_binary"]["present"] is True
        assert int(snapshot["listener_count"]) > 0
        assert snapshot["last_toggle"]["verified"] is True

    def test_transport_off_verifies_the_restored_state(self, client_project: Path) -> None:
        result = _run_cli(client_project, "transport", "off")

        assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
        assert "relay_enabled: false" in _config_text(client_project)
        assert _COMMENT_SENTINEL in _config_text(client_project)
        assert "relay hot path" not in _forwarder_text(client_project, "pre-tool-use")
        state = _toggle_state(client_project)
        assert state["action"] == "off"
        assert state["verified"] is True

    def test_transport_off_when_off_is_a_clean_no_op(self, client_project: Path) -> None:
        result = _run_cli(client_project, "transport", "off")
        assert result.returncode == 0, result.stderr
        assert "already" in result.stdout


class TestInducedFailureAutoRevert:
    """A broken relay binary must fail verification and auto-revert to off."""

    def test_broken_relay_binary_triggers_verified_auto_revert(self, client_project: Path) -> None:
        relay_binary = client_project / "relay-bin" / "hooks-relay"
        relay_binary.write_text("#!/bin/bash\necho 'BROKEN-RELAY-OUTPUT'\nexit 0\n")
        relay_binary.chmod(0o755)

        result = _run_cli(client_project, "transport", "on")

        assert result.returncode != 0, "a failed verification must exit non-zero"
        assert "VERIFICATION FAILED" in result.stderr
        assert "pre-tool-use-json" in result.stderr, result.stderr
        assert "AUTO-REVERTED" in result.stderr
        # The previous (off) state is fully restored...
        assert "relay_enabled: false" in _config_text(client_project)
        assert _COMMENT_SENTINEL in _config_text(client_project)
        assert "relay hot path" not in _forwarder_text(client_project, "pre-tool-use")
        # ...and the revert itself was re-verified with the same probes.
        state = _toggle_state(client_project)
        assert state["verified"] is False
        assert state["reverted"] is True
        assert state["revert_verified"] is True
        failures = state["failures"]
        assert isinstance(failures, list)
        assert any("pre-tool-use-json" in str(failure) for failure in failures)

    def test_daemon_still_running_after_the_revert(self, client_project: Path) -> None:
        status = _run_cli(client_project, "status")
        assert "RUNNING" in status.stdout


class TestFreshClientConfig:
    """Defects D3 and D2 (canary run 4) against the real CLI, in order: a
    fresh config gains a seeded key; an absent binary with no relay_source
    refuses before changing anything; relay_source: build compiles the relay
    for real and the enable goes green."""

    def test_transport_off_seeds_a_missing_relay_enabled_key(self, client_project: Path) -> None:
        config = client_project / ".claude" / "hooks-daemon.yaml"
        config.write_text(
            "version: '1.0'\n"
            "daemon:\n"
            "  idle_timeout_seconds: 600\n"
            "  log_level: INFO\n"
            "  self_install_mode: false\n"
            "handlers:\n"
            "  stop:\n"
            "    auto_continue_stop:\n"
            "      enabled: true\n"
            "  status_line:\n"
            "    model_context:\n"
            "      enabled: true\n"
        )

        result = _run_cli(client_project, "transport", "off")

        assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
        assert "already" in result.stdout
        assert "relay_enabled: false" in config.read_text()

    def test_transport_on_with_absent_binary_and_null_source_refuses_untouched(
        self, client_project: Path
    ) -> None:
        # The seeded config has no relay_binary override and no relay_source;
        # the default resolved path has no binary.
        config = client_project / ".claude" / "hooks-daemon.yaml"

        result = _run_cli(client_project, "transport", "on")

        assert result.returncode != 0
        assert "relay_source" in result.stderr, result.stderr
        assert "AUTO-REVERTED" not in result.stderr
        assert "relay_enabled: false" in config.read_text()
        assert "relay hot path" not in _forwarder_text(client_project, "pre-tool-use")

    def test_transport_on_builds_the_relay_via_relay_source_build(
        self, client_project: Path
    ) -> None:
        built_binary = client_project / "built-bin" / "hooks-relay"
        config = client_project / ".claude" / "hooks-daemon.yaml"
        config.write_text(
            _fixture_config(built_binary).replace(
                "    timeout_seconds: 30\n",
                "    timeout_seconds: 30\n    relay_source: build\n",
            )
        )
        assert not built_binary.exists()

        result = _run_cli(client_project, "transport", "on")

        assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
        assert built_binary.is_file(), "transport on must have built and deployed the relay"
        assert os.access(built_binary, os.X_OK)
        assert (built_binary.parent / "hooks-relay.route").read_text().strip() == "build"
        state = _toggle_state(client_project)
        assert state["verified"] is True

        off = _run_cli(client_project, "transport", "off")
        assert off.returncode == 0, off.stderr
