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
    ensure_relay_binary,
    read_last_toggle_state,
    read_relay_enabled,
    run_toggle,
    seed_relay_enabled_line,
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
    """A minimal client-layout project with a commented transport config.

    A fake relay binary sits at the default resolved path so enabling the
    relay short-circuits provisioning (binary already present) — the
    provisioning paths themselves are covered by TestRelayProvisioning.
    """
    claude_dir = tmp_path / ".claude"
    hooks_dir = claude_dir / "hooks"
    hooks_dir.mkdir(parents=True)
    (claude_dir / "hooks-daemon").mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text(_CONFIG_WITH_COMMENTS)
    (hooks_dir / "pre-tool-use").write_text(_FORWARDER_BODY)
    relay_binary = claude_dir / "hooks-daemon" / "untracked" / "bin" / "hooks-relay"
    relay_binary.parent.mkdir(parents=True)
    relay_binary.write_text("#!/bin/bash\ncat >/dev/null\necho '{}'\n")
    relay_binary.chmod(0o755)
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


class TestSeedRelayEnabled:
    """D3 (canary run 4): a fresh client config has no ``relay_enabled:``
    line — seed it (comment-preserving) instead of refusing."""

    def test_seed_into_existing_transport_block(self, tmp_path: Path) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(
            "daemon:\n"
            "  # a comment that must survive\n"
            "  transport:\n"
            "    nc_enabled: false\n"
            "handlers: {}\n"
        )

        seeded = seed_relay_enabled_line(config_path)

        assert seeded is True
        content = config_path.read_text()
        assert read_relay_enabled(config_path) is False
        assert "# a comment that must survive" in content
        assert "nc_enabled: false" in content
        # The seeded line is indented as a child of transport:.
        assert "\n    relay_enabled: false\n" in content

    def test_seed_creates_transport_block_under_daemon(self, tmp_path: Path) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text("daemon:\n  log_level: INFO\nhandlers: {}\n")

        seeded = seed_relay_enabled_line(config_path)

        assert seeded is True
        assert read_relay_enabled(config_path) is False
        assert "  transport:\n    relay_enabled: false\n" in config_path.read_text()

    def test_seed_is_a_no_op_when_the_line_exists(self, tmp_path: Path) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text("daemon:\n  transport:\n    relay_enabled: true\n")
        before = config_path.read_text()

        assert seed_relay_enabled_line(config_path) is False
        assert config_path.read_text() == before

    def test_seed_without_daemon_section_raises_with_the_yaml_to_add(self, tmp_path: Path) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text("handlers: {}\n")

        with pytest.raises(TransportToggleError) as exc_info:
            seed_relay_enabled_line(config_path)

        assert "relay_enabled" in str(exc_info.value)

    def test_run_toggle_seeds_a_fresh_config_and_enables(self, project: Path) -> None:
        config_path = _config_path(project)
        config_path.write_text("daemon:\n  transport:\n    nc_enabled: false\nhandlers: {}\n")

        outcome = run_toggle(project, enable=True, restart_fn=lambda: 0, verify_fn=_passing_probes)

        assert outcome.verified is True
        assert read_relay_enabled(config_path) is True

    def test_run_toggle_off_on_a_fresh_config_is_a_seeded_no_op(self, project: Path) -> None:
        config_path = _config_path(project)
        config_path.write_text("daemon:\n  transport:\n    nc_enabled: false\nhandlers: {}\n")

        outcome = run_toggle(project, enable=False, restart_fn=lambda: 0, verify_fn=_passing_probes)

        assert outcome.changed is False
        assert read_relay_enabled(config_path) is False


class TestRelayProvisioning:
    """D2 (canary run 4): enabling must ensure the relay binary EXISTS —
    otherwise the guards silently fall through to legacy while probes pass."""

    def _remove_fixture_binary(self, project: Path) -> Path:
        binary = project / ".claude" / "hooks-daemon" / "untracked" / "bin" / "hooks-relay"
        binary.unlink()
        return binary

    def test_absent_binary_with_null_relay_source_fails_before_any_change(
        self, project: Path
    ) -> None:
        self._remove_fixture_binary(project)
        restarts: list[int] = []

        def restart() -> int:
            restarts.append(1)
            return 0

        outcome = run_toggle(project, enable=True, restart_fn=restart, verify_fn=_passing_probes)

        assert outcome.verified is False
        assert any("relay-binary" in failure for failure in outcome.failures)
        assert any("relay_source" in failure for failure in outcome.failures)
        assert outcome.reverted is False
        # Nothing was changed: config untouched, no restart, no guard.
        assert read_relay_enabled(_config_path(project)) is False
        assert restarts == []
        assert "relay hot path" not in (_hooks_dir(project) / "pre-tool-use").read_text()

    def test_injected_provision_failure_fails_before_any_change(self, project: Path) -> None:
        outcome = run_toggle(
            project,
            enable=True,
            restart_fn=lambda: 0,
            verify_fn=_passing_probes,
            provision_fn=lambda: "relay-binary: build exited 1: rustc not found",
        )

        assert outcome.verified is False
        assert any("build exited 1" in failure for failure in outcome.failures)
        assert read_relay_enabled(_config_path(project)) is False

    def test_provisioning_is_skipped_when_disabling(self, project: Path) -> None:
        set_relay_enabled(_config_path(project), True)
        self._remove_fixture_binary(project)

        outcome = run_toggle(project, enable=False, restart_fn=lambda: 0, verify_fn=_passing_probes)

        assert outcome.verified is True

    def test_ensure_relay_binary_short_circuits_on_present_binary(self, project: Path) -> None:
        assert ensure_relay_binary(project) is None

    def test_ensure_relay_binary_reports_null_source(self, project: Path) -> None:
        self._remove_fixture_binary(project)
        message = ensure_relay_binary(project)
        assert message is not None
        assert "relay_source" in message

    def test_ensure_relay_binary_delegates_to_configured_route(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.install.relay_deploy import RelayDeployResult

        binary = self._remove_fixture_binary(project)
        config_path = _config_path(project)
        config_path.write_text(
            config_path.read_text().replace(
                "timeout_seconds: 30", "timeout_seconds: 30\n    relay_source: build"
            )
        )
        calls: list[str] = []

        def fake_deploy(*_a: object, **_k: object) -> RelayDeployResult:
            calls.append("deploy")
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("#!/bin/bash\necho '{}'\n")
            binary.chmod(0o755)
            return RelayDeployResult(True, "build", ("built",))

        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.transport_toggle.deploy_relay_if_configured",
            fake_deploy,
        )

        assert ensure_relay_binary(project) is None
        assert calls == ["deploy"]

    def test_ensure_relay_binary_reports_route_failure(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.install.relay_deploy import RelayDeployResult

        self._remove_fixture_binary(project)
        config_path = _config_path(project)
        config_path.write_text(
            config_path.read_text().replace(
                "timeout_seconds: 30", "timeout_seconds: 30\n    relay_source: build"
            )
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.transport_toggle.deploy_relay_if_configured",
            lambda *_a, **_k: RelayDeployResult(False, "build", ("no musl toolchain",)),
        )

        message = ensure_relay_binary(project)

        assert message is not None
        assert "no musl toolchain" in message


class TestStatusSnapshot:
    def test_status_reports_disabled_state(self, project: Path) -> None:
        snapshot = status_snapshot(project)
        assert snapshot["relay_enabled"] is False
        assert snapshot["nc_enabled"] is False
        # The fixture ships a fake binary; the rung is still the fallback
        # because relay_enabled is false.
        assert snapshot["rung"] == "bash+python3"
        assert snapshot["listener_count"] == 0
        assert snapshot["relay_binary"]["present"] is True
        assert snapshot["last_toggle"] is None

    def test_status_reports_enabled_state_and_binary_facts(self, project: Path) -> None:
        set_relay_enabled(_config_path(project), True)
        binary = project / ".claude" / "hooks-daemon" / "untracked" / "bin" / "hooks-relay"
        binary.parent.mkdir(parents=True, exist_ok=True)
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
        (project / ".claude" / "hooks-daemon" / "untracked" / "bin" / "hooks-relay").unlink()
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
        path.parent.mkdir(parents=True, exist_ok=True)
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
