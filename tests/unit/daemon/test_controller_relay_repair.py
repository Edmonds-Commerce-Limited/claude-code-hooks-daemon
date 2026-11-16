"""The relay repair also starts where the daemon starts (Plan 00608).

A clone provisioned after its session began never gets a SessionStart that
reaches the daemon, so the daemon's own start-up starts the same once-per-cause
detached repair. It must never stop the daemon serving, and a failure is logged.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.install.relay_repair import RepairNotice, spawn_owned
from claude_code_hooks_daemon.version import __version__

_MODULE = "claude_code_hooks_daemon.daemon.controller"
_CONFIG = "version: '2.0'\ndaemon:\n  idle_timeout_seconds: 600\nhandlers: {}\n"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / ".claude" / "hooks-daemon.yaml"
    path.parent.mkdir()
    path.write_text(_CONFIG, encoding="utf-8")
    return path


def _notice(tmp_path: Path, *, started: bool, failure: str | None = None) -> RepairNotice:
    return RepairNotice(started, None, failure, tmp_path / "s.state", tmp_path / "s.log")


class TestStartRelayRepair:
    def test_starts_the_repair_for_the_loaded_config(
        self, tmp_path: Path, config_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = Config.load_or_default(config_path)
        binary = tmp_path / "hooks-relay"
        with patch(f"{_MODULE}.repair_unusable_relay") as repair:
            repair.return_value = (binary, _notice(tmp_path, started=True))
            with caplog.at_level("INFO", logger=_MODULE):
                DaemonController()._start_relay_repair(tmp_path, config_path, config)

        (call,) = repair.call_args_list
        assert call.args == (tmp_path, config.daemon.transport)
        assert call.kwargs["version"] == __version__
        # The daemon owns the repair it starts, so a stop can end it.
        assert call.kwargs["spawn_fn"] is spawn_owned
        assert any("started" in r.getMessage() for r in caplog.records)

    def test_loads_the_config_when_none_is_given(self, tmp_path: Path, config_path: Path) -> None:
        with patch(f"{_MODULE}.repair_unusable_relay", return_value=None) as repair:
            DaemonController()._start_relay_repair(tmp_path, config_path, None)

        assert repair.call_args.args[1].relay_enabled is True

    def test_a_usable_relay_starts_nothing_and_is_quiet(
        self, tmp_path: Path, config_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch(f"{_MODULE}.repair_unusable_relay", return_value=None):
            with caplog.at_level("INFO", logger=_MODULE):
                DaemonController()._start_relay_repair(tmp_path, config_path, None)

        assert [r for r in caplog.records if r.name == _MODULE] == []

    def test_a_repair_that_could_not_start_is_logged_as_an_error(
        self, tmp_path: Path, config_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        notice = _notice(tmp_path, started=False, failure="the repair state file cannot be created")
        with patch(f"{_MODULE}.repair_unusable_relay", return_value=(tmp_path / "b", notice)):
            with caplog.at_level("ERROR", logger=_MODULE):
                DaemonController()._start_relay_repair(tmp_path, config_path, None)

        assert any("cannot be created" in r.getMessage() for r in caplog.records)

    def test_an_already_claimed_cause_is_logged_at_info(
        self, tmp_path: Path, config_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch(
            f"{_MODULE}.repair_unusable_relay",
            return_value=(tmp_path / "b", _notice(tmp_path, started=False)),
        ):
            with caplog.at_level("INFO", logger=_MODULE):
                DaemonController()._start_relay_repair(tmp_path, config_path, None)

        assert any("already attempted" in r.getMessage() for r in caplog.records)

    def test_an_unreadable_config_is_logged_not_raised(
        self, tmp_path: Path, config_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        config_path.write_text("daemon:\n  transport:\n    relay_enabled: [no]\n", encoding="utf-8")
        repair = MagicMock()
        with patch(f"{_MODULE}.repair_unusable_relay", repair):
            with caplog.at_level("ERROR", logger=_MODULE):
                DaemonController()._start_relay_repair(tmp_path, config_path, None)

        repair.assert_not_called()
        assert any("relay repair" in r.getMessage() for r in caplog.records)

    def test_an_oserror_is_logged_not_raised(self, tmp_path: Path, config_path: Path) -> None:
        with patch(f"{_MODULE}.repair_unusable_relay", side_effect=OSError("disk gone")):
            DaemonController()._start_relay_repair(tmp_path, config_path, None)
