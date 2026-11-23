"""Tests for the read-only ``team-seat`` diagnostic command (Plan 00631 Task 2.3)."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from tests.support import teamchat

from claude_code_hooks_daemon.config.models import TeamSeatConfig
from claude_code_hooks_daemon.daemon.team_seat_cli import (
    EXIT_OK,
    EXIT_UNRESOLVED,
    EXIT_USAGE,
    load_team_seat_config,
    main,
    run_team_seat,
)
from claude_code_hooks_daemon.utils.teamchat_seat import (
    CommandOutcome,
    CommandStatus,
    SessionSignals,
)

_SIGNALS = SessionSignals(runtime="/run/team/rt", kit="/opt/kit")


class _Runner:
    def __init__(self, outcome: CommandOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def __call__(
        self, args: Sequence[str], env: Mapping[str, str], timeout: float
    ) -> CommandOutcome:
        self.calls.append((tuple(args), dict(env)))
        return self.outcome


def _ok(text: str) -> _Runner:
    return _Runner(CommandOutcome(CommandStatus.OK, text, 0))


def _run(
    runner: _Runner,
    *,
    signals: SessionSignals = _SIGNALS,
    config: TeamSeatConfig | None = None,
    as_json: bool = False,
) -> tuple[int, str]:
    out = io.StringIO()
    code = run_team_seat(
        signals=signals,
        config=config or TeamSeatConfig(),
        as_json=as_json,
        stdout=out,
        runner=runner,
    )
    return code, out.getvalue()


class TestText:
    def test_no_runtime_prints_absent_with_reason_and_runs_nothing(self) -> None:
        runner = _ok(teamchat.WORKER_ONLY)
        code, out = _run(runner, signals=SessionSignals())
        assert code == EXIT_OK
        assert "absent" in out
        assert "no_runtime_signal" in out
        assert runner.calls == []

    def test_detection_off_prints_absent_and_runs_nothing(self) -> None:
        runner = _ok(teamchat.WORKER_ONLY)
        code, out = _run(runner, config=TeamSeatConfig(detection="off"))
        assert code == EXIT_OK
        assert "detection_off" in out
        assert runner.calls == []

    def test_multi_team_prints_one_line_per_team(self) -> None:
        code, out = _run(_ok(teamchat.MULTI_TEAM))
        assert code == EXIT_OK
        assert "resolved" in out
        alpha = next(line for line in out.splitlines() if "alpha" in line)
        beta = next(line for line in out.splitlines() if "beta" in line)
        assert "coordinator" in alpha
        assert "worker" in beta

    def test_unknown_duty_and_null_role_print_unknown(self) -> None:
        code, out = _run(_ok(teamchat.ROLE_NULL))
        assert code == EXIT_OK
        alpha = next(line for line in out.splitlines() if "alpha" in line)
        assert "role unknown" in alpha
        assert "duty unknown" in alpha

    def test_duplicate_team_is_reported_as_advisory(self) -> None:
        _code, out = _run(_ok(teamchat.CONFLICTING_ROWS))
        assert "more than once" in out

    def test_unresolved_exits_non_zero_with_reason(self) -> None:
        code, out = _run(_Runner(CommandOutcome(CommandStatus.TIMEOUT)))
        assert code == EXIT_UNRESOLVED
        assert "unresolved" in out
        assert "command_timeout" in out

    @pytest.mark.parametrize("text", ["[" * 200000, '{"v": 1, "teams": ' + "[" * 100 + "]" * 100])
    def test_hostile_output_exits_unresolved_without_raising(self, text: str) -> None:
        """Review F1: a deeply nested document is exit 3, never a traceback."""
        code, out = _run(_ok(text))
        assert code == EXIT_UNRESOLVED
        assert "unresolved" in out

    def test_exit_69_is_absent(self) -> None:
        code, out = _run(_Runner(CommandOutcome(CommandStatus.EXITED, exit_code=69)))
        assert code == EXIT_OK
        assert "no_session" in out

    def test_raw_output_is_never_printed(self) -> None:
        code, out = _run(_ok(teamchat.NOT_JSON))
        assert code == EXIT_UNRESOLVED
        assert teamchat.NOT_JSON not in out

    def test_signal_paths_are_never_printed(self) -> None:
        _code, out = _run(_ok(teamchat.MULTI_TEAM))
        assert _SIGNALS.runtime not in out
        assert _SIGNALS.kit not in out

    def test_runtime_reaches_the_subprocess_env(self) -> None:
        runner = _ok(teamchat.WORKER_ONLY)
        _run(runner)
        assert runner.calls[0][0][0] == "/opt/kit/bin/teamchat"
        assert runner.calls[0][1] == {"TEAMCHAT_RUNTIME": "/run/team/rt"}


class TestJson:
    def test_resolved_json_shape(self) -> None:
        code, out = _run(_ok(teamchat.HOST_DUTY), as_json=True)
        assert code == EXIT_OK
        document = json.loads(out)
        assert document["state"] == "resolved"
        assert document["reason"] == "resolved"
        teams = {row["team"]: row for row in document["teams"]}
        assert teams["alpha"]["duty"] == "host"
        assert teams["alpha"]["role"] == "worker"
        assert teams["beta"]["duty"] == "worker"
        assert document["duplicate_teams"] == []

    def test_absent_json_has_no_teams(self) -> None:
        code, out = _run(_ok(teamchat.NO_TEAMS), as_json=True)
        assert code == EXIT_OK
        document = json.loads(out)
        assert document == {
            "state": "absent",
            "reason": "no_teams",
            "teams": [],
            "duplicate_teams": [],
        }


class TestConfig:
    def test_missing_config_gives_defaults(self, tmp_path: Path) -> None:
        assert load_team_seat_config(tmp_path) == TeamSeatConfig()

    def test_block_is_read(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '2.0'\nteam_seat:\n  detection: 'off'\n  resolve_ttl_seconds: 5\n"
        )
        config = load_team_seat_config(tmp_path)
        assert config.detection == "off"
        assert config.resolve_ttl_seconds == 5

    def test_malformed_block_raises_value_error(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '2.0'\nteam_seat:\n  detection: sometimes\n"
        )
        with pytest.raises(ValueError):
            load_team_seat_config(tmp_path)

    def test_exit_usage_is_distinct(self) -> None:
        assert len({EXIT_OK, EXIT_UNRESOLVED, EXIT_USAGE}) == 3


class TestMain:
    def test_malformed_config_exits_usage(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '2.0'\nteam_seat:\n  bogus: 1\n"
        )
        out, err = io.StringIO(), io.StringIO()
        code = main(project_root=tmp_path, environ={}, as_json=False, stdout=out, stderr=err)
        assert code == EXIT_USAGE
        assert "team_seat" in err.getvalue()
        assert out.getvalue() == ""

    def test_reads_signals_from_given_environ(self, tmp_path: Path) -> None:
        out, err = io.StringIO(), io.StringIO()
        code = main(project_root=tmp_path, environ={}, as_json=True, stdout=out, stderr=err)
        assert code == EXIT_OK
        assert json.loads(out.getvalue())["reason"] == "no_runtime_signal"

    def test_cli_registers_team_seat(self) -> None:
        from claude_code_hooks_daemon.daemon import cli

        parser = cli.build_parser()
        args = parser.parse_args(["team-seat", "--json"])
        assert args.json is True
        assert args.func is cli.cmd_team_seat
