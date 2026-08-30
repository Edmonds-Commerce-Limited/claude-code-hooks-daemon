"""Unit tests for the ``transport on|off|status`` toggle machinery (Plan 00294).

The toggle is the operational finish for the Plan 00290 relay transport: ONE
command each way performing config flip -> forwarder regeneration -> daemon
restart -> verification, with AUTO-REVERT on any verification failure. These
tests drive the orchestration with injected restart/verify callables so no
real daemon is involved; the real-daemon path is covered by
``tests/acceptance/test_transport_toggle_cycle.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.forwarder_generator import INIT_SH_ANCHOR
from claude_code_hooks_daemon.install.transport_toggle import (
    ToggleOutcome,
    TransportToggleError,
    read_last_toggle_state,
    read_relay_enabled,
    run_toggle,
    set_relay_enabled,
    state_file_path,
    status_snapshot,
)
from claude_code_hooks_daemon.install.transport_verify import ProbeResult

_CONFIG_WITH_COMMENTS = """\
version: '1.0'
daemon:
  self_install_mode: false
  # Transport (Plan 00290) - opt-in relay rung.
  transport:
    # DOGFOOD SUSPENDED (owner escalation): this comment block must survive
    # every toggle round-trip byte-for-byte.
    relay_enabled: false
    nc_enabled: false
    timeout_seconds: 30
handlers:
  pre_tool_use: {}
  post_tool_use: {}
"""

_FORWARDER_BODY = (
    "#!/bin/bash\n"
    'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
    + INIT_SH_ANCHOR
    + 'send_request_stdin "PreToolUse"\n'
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal client-layout project with a commented transport config."""
    claude_dir = tmp_path / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True)
    (claude_dir / "hooks-daemon").mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text(_CONFIG_WITH_COMMENTS)
    (hooks_dir / "pre-tool-use").write_text(_FORWARDER_BODY)
    return tmp_path


def _config_path(project: Path) -> Path:
    return project / ".claude" / "hooks-daemon.yaml"


def _hooks_dir(project: Path) -> Path:
    return project / ".claude" / "hooks"


def _passing_probes(expect_relay: bool) -> list[ProbeResult]:
    return [ProbeResult(name="stub-probe", passed=True, detail="ok")]


def _failing_probes(expect_relay: bool) -> list[ProbeResult]:
    return [
        ProbeResult(name="stub-probe", passed=True, detail="ok"),
        ProbeResult(name="pre-tool-use-json", passed=False, detail="not JSON"),
    ]


class TestConfigFlip:
    def test_read_relay_enabled_false(self, project: Path) -> None:
        assert read_relay_enabled(_config_path(project)) is False

    def test_flip_to_true_preserves_comments_and_other_lines(self, project: Path) -> None:
        config_path = _config_path(project)
        before = config_path.read_text()

        changed = set_relay_enabled(config_path, True)

        assert changed is True
        after = config_path.read_text()
        assert read_relay_enabled(config_path) is True
        assert "DOGFOOD SUSPENDED (owner escalation)" in after
        assert "every toggle round-trip byte-for-byte." in after
        # Everything except the flipped value survives byte-for-byte.
        assert after.replace("relay_enabled: true", "relay_enabled: false") == before

    def test_flip_round_trip_is_byte_identical(self, project: Path) -> None:
        config_path = _config_path(project)
        before = config_path.read_text()
        set_relay_enabled(config_path, True)
        set_relay_enabled(config_path, False)
        assert config_path.read_text() == before

    def test_flip_to_current_value_is_a_no_op(self, project: Path) -> None:
        config_path = _config_path(project)
        before = config_path.read_text()
        changed = set_relay_enabled(config_path, False)
        assert changed is False
        assert config_path.read_text() == before

    def test_flip_preserves_trailing_comment_on_the_value_line(self, tmp_path: Path) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text("daemon:\n  transport:\n    relay_enabled: false  # keep me\n")
        set_relay_enabled(config_path, True)
        assert "relay_enabled: true  # keep me" in config_path.read_text()

    def test_missing_relay_enabled_line_raises(self, tmp_path: Path) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text("daemon:\n  transport:\n    nc_enabled: false\n")
        with pytest.raises(TransportToggleError):
            set_relay_enabled(config_path, True)
        with pytest.raises(TransportToggleError):
            read_relay_enabled(config_path)

    def test_multiple_relay_enabled_lines_raise(self, tmp_path: Path) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text("relay_enabled: false\nrelay_enabled: true\n")
        with pytest.raises(TransportToggleError):
            set_relay_enabled(config_path, True)

    def test_missing_config_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(TransportToggleError):
            read_relay_enabled(tmp_path / "absent.yaml")


class TestRunToggleNoOp:
    def test_off_when_off_is_a_clean_no_op(self, project: Path) -> None:
        calls: list[str] = []

        def restart() -> int:
            calls.append("restart")
            return 0

        outcome = run_toggle(project, enable=False, restart_fn=restart, verify_fn=_passing_probes)

        assert outcome.changed is False
        assert outcome.verified is None
        assert outcome.failures == []
        assert outcome.reverted is False
        assert calls == []
        assert not state_file_path(project).exists()

    def test_on_when_on_is_a_clean_no_op(self, project: Path) -> None:
        set_relay_enabled(_config_path(project), True)
        outcome = run_toggle(
            project,
            enable=True,
            restart_fn=lambda: 0,
            verify_fn=_passing_probes,
        )
        assert outcome.changed is False
        assert read_relay_enabled(_config_path(project)) is True


class TestRunToggleSuccess:
    def test_enable_flips_config_regenerates_restarts_and_verifies(self, project: Path) -> None:
        restarts: list[int] = []
        verify_expectations: list[bool] = []

        def restart() -> int:
            restarts.append(1)
            return 0

        def verify(expect_relay: bool) -> list[ProbeResult]:
            verify_expectations.append(expect_relay)
            return _passing_probes(expect_relay)

        outcome = run_toggle(project, enable=True, restart_fn=restart, verify_fn=verify)

        assert outcome.changed is True
        assert outcome.verified is True
        assert outcome.failures == []
        assert outcome.reverted is False
        assert read_relay_enabled(_config_path(project)) is True
        assert len(restarts) == 1
        assert verify_expectations == [True]
        # Forwarder regeneration really ran: the eligible forwarder now
        # carries the relay guard block.
        forwarder = (_hooks_dir(project) / "pre-tool-use").read_text()
        assert "relay hot path" in forwarder

    def test_disable_strips_guard_and_verifies_off_state(self, project: Path) -> None:
        run_toggle(project, enable=True, restart_fn=lambda: 0, verify_fn=_passing_probes)
        expectations: list[bool] = []

        def verify(expect_relay: bool) -> list[ProbeResult]:
            expectations.append(expect_relay)
            return _passing_probes(expect_relay)

        outcome = run_toggle(project, enable=False, restart_fn=lambda: 0, verify_fn=verify)

        assert outcome.verified is True
        assert read_relay_enabled(_config_path(project)) is False
        assert expectations == [False]
        forwarder = (_hooks_dir(project) / "pre-tool-use").read_text()
        assert "relay hot path" not in forwarder

    def test_success_writes_state_file(self, project: Path) -> None:
        run_toggle(project, enable=True, restart_fn=lambda: 0, verify_fn=_passing_probes)
        state = read_last_toggle_state(project)
        assert state is not None
        assert state["action"] == "on"
        assert state["verified"] is True
        assert state["reverted"] is False
        assert state["failures"] == []
        assert "timestamp" in state


class TestRunToggleAutoRevert:
    def test_probe_failure_reverts_config_and_forwarders(self, project: Path) -> None:
        restarts: list[int] = []
        expectations: list[bool] = []

        def restart() -> int:
            restarts.append(1)
            return 0

        def verify(expect_relay: bool) -> list[ProbeResult]:
            expectations.append(expect_relay)
            if expect_relay:
                return _failing_probes(expect_relay)
            return _passing_probes(expect_relay)

        outcome = run_toggle(project, enable=True, restart_fn=restart, verify_fn=verify)

        assert outcome.verified is False
        assert outcome.reverted is True
        assert outcome.revert_verified is True
        assert any("pre-tool-use-json" in failure for failure in outcome.failures)
        # Config and forwarders are back to the prior state.
        assert read_relay_enabled(_config_path(project)) is False
        forwarder = (_hooks_dir(project) / "pre-tool-use").read_text()
        assert "relay hot path" not in forwarder
        # Restarted for the attempt AND for the revert; verified both states.
        assert len(restarts) == 2
        assert expectations == [True, False]

    def test_restart_failure_reverts_and_names_the_failure(self, project: Path) -> None:
        restart_results = iter([1, 0])

        def restart() -> int:
            return next(restart_results)

        outcome = run_toggle(project, enable=True, restart_fn=restart, verify_fn=_passing_probes)

        assert outcome.verified is False
        assert outcome.reverted is True
        assert any("daemon-restart" in failure for failure in outcome.failures)
        assert read_relay_enabled(_config_path(project)) is False

    def test_failed_revert_verification_is_reported(self, project: Path) -> None:
        def verify(expect_relay: bool) -> list[ProbeResult]:
            return _failing_probes(expect_relay)

        outcome = run_toggle(project, enable=True, restart_fn=lambda: 0, verify_fn=verify)

        assert outcome.verified is False
        assert outcome.reverted is True
        assert outcome.revert_verified is False

    def test_revert_writes_state_file_with_failures(self, project: Path) -> None:
        def verify(expect_relay: bool) -> list[ProbeResult]:
            if expect_relay:
                return _failing_probes(expect_relay)
            return _passing_probes(expect_relay)

        run_toggle(project, enable=True, restart_fn=lambda: 0, verify_fn=verify)

        state = read_last_toggle_state(project)
        assert state is not None
        assert state["verified"] is False
        assert state["reverted"] is True
        assert state["revert_verified"] is True
        assert any("pre-tool-use-json" in failure for failure in state["failures"])


class TestStatusSnapshot:
    def test_status_reports_disabled_state(self, project: Path) -> None:
        snapshot = status_snapshot(project)
        assert snapshot["relay_enabled"] is False
        assert snapshot["nc_enabled"] is False
        assert snapshot["rung"] == "bash+python3"
        assert snapshot["listener_count"] == 0
        assert snapshot["relay_binary"]["present"] is False
        assert snapshot["last_toggle"] is None

    def test_status_reports_enabled_state_and_binary_facts(self, project: Path) -> None:
        set_relay_enabled(_config_path(project), True)
        binary = project / ".claude" / "hooks-daemon" / "untracked" / "bin" / "hooks-relay"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/bash\nexit 0\n")
        binary.chmod(0o755)

        snapshot = status_snapshot(project)

        assert snapshot["relay_enabled"] is True
        assert snapshot["rung"] == "relay"
        assert snapshot["relay_binary"]["present"] is True
        assert snapshot["relay_binary"]["executable"] is True
        assert snapshot["relay_binary"]["path"] == str(binary)
        assert len(snapshot["relay_binary"]["sha256"]) == 64

    def test_status_relay_enabled_without_binary_reports_fallback_rung(self, project: Path) -> None:
        set_relay_enabled(_config_path(project), True)
        snapshot = status_snapshot(project)
        assert snapshot["rung"] == "bash+python3"

    def test_status_includes_last_toggle_result(self, project: Path) -> None:
        run_toggle(project, enable=True, restart_fn=lambda: 0, verify_fn=_passing_probes)
        snapshot = status_snapshot(project)
        assert snapshot["last_toggle"] is not None
        assert snapshot["last_toggle"]["action"] == "on"
        assert snapshot["last_toggle"]["verified"] is True


class TestStateFile:
    def test_state_file_lives_in_the_daemon_untracked_dir(self, project: Path) -> None:
        path = state_file_path(project)
        assert path == (
            project / ".claude" / "hooks-daemon" / "untracked" / "transport-toggle-state.json"
        )

    def test_corrupt_state_file_reads_as_none(self, project: Path) -> None:
        path = state_file_path(project)
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        assert read_last_toggle_state(project) is None

    def test_outcome_dataclass_round_trips_through_json(self, project: Path) -> None:
        outcome = ToggleOutcome(
            action="on",
            changed=True,
            verified=False,
            failures=["pre-tool-use-json: not JSON"],
            reverted=True,
            revert_verified=True,
        )
        encoded = json.dumps(outcome.as_dict())
        assert json.loads(encoded)["action"] == "on"
