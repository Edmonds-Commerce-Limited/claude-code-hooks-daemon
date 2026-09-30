"""Plan 00477 Task 1.1 - the daemon version a project expects, recorded in its config.

``daemon.expected_version`` in ``.claude/hooks-daemon.yaml`` names the version
``provision`` installs into a fresh checkout. ``install`` and ``upgrade`` write
it through ``record_expected_version``, which edits the file as TEXT so a
client's comments and layout survive.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import DaemonConfig
from claude_code_hooks_daemon.install.expected_version import (
    EXPECTED_VERSION_KEY,
    main,
    record_expected_version,
)
from claude_code_hooks_daemon.version import __version__


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".claude" / "hooks-daemon.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return path


def _recorded(path: Path) -> object:
    return yaml.safe_load(path.read_text())["daemon"][EXPECTED_VERSION_KEY]


class TestRecordExpectedVersion:
    def test_inserts_the_key_into_an_existing_daemon_block(self, tmp_path: Path) -> None:
        path = _config(
            tmp_path,
            'version: "2.0"\n\ndaemon:\n  idle_timeout_seconds: 600  # keep me\n  log_level: INFO\n',
        )

        assert record_expected_version(path, "3.68.0") is True

        assert _recorded(path) == "3.68.0"
        text = path.read_text()
        assert "idle_timeout_seconds: 600  # keep me" in text
        assert yaml.safe_load(text)["daemon"]["log_level"] == "INFO"

    def test_replaces_an_existing_value_and_keeps_the_layout(self, tmp_path: Path) -> None:
        path = _config(
            tmp_path,
            'daemon:\n  log_level: INFO\n  expected_version: "3.60.0"  # old\n  strict_mode: true\n'
            "handlers: {}\n",
        )

        assert record_expected_version(path, "3.68.0") is True

        assert _recorded(path) == "3.68.0"
        data = yaml.safe_load(path.read_text())
        assert data["daemon"]["strict_mode"] is True
        assert data["handlers"] == {}
        assert path.read_text().count(EXPECTED_VERSION_KEY) == 1

    def test_is_idempotent(self, tmp_path: Path) -> None:
        path = _config(tmp_path, "daemon:\n  log_level: INFO\n")
        record_expected_version(path, "3.68.0")
        once = path.read_text()

        assert record_expected_version(path, "3.68.0") is False

        assert path.read_text() == once

    def test_appends_a_daemon_block_when_there_is_none(self, tmp_path: Path) -> None:
        path = _config(tmp_path, 'version: "2.0"\nhandlers: {}\n')

        assert record_expected_version(path, "3.68.0") is True

        assert _recorded(path) == "3.68.0"
        assert yaml.safe_load(path.read_text())["handlers"] == {}

    def test_inserts_before_a_nested_block_ends_not_after_the_next_section(
        self, tmp_path: Path
    ) -> None:
        path = _config(
            tmp_path,
            "daemon:\n  input_validation:\n    enabled: true\n\nhandlers:\n  pre_tool_use: {}\n",
        )

        record_expected_version(path, "3.68.0")

        data = yaml.safe_load(path.read_text())
        assert data["daemon"][EXPECTED_VERSION_KEY] == "3.68.0"
        assert data["daemon"]["input_validation"] == {"enabled": True}
        assert "expected_version" not in data["handlers"]

    def test_a_missing_file_fails_fast(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            record_expected_version(tmp_path / "absent.yaml", "3.68.0")

    @pytest.mark.parametrize("bad", ["main", "3.68", "v3.68.0", "3.68.0; rm -rf /", "", "3.68.0\n"])
    def test_a_version_that_is_not_x_y_z_is_refused(self, tmp_path: Path, bad: str) -> None:
        path = _config(tmp_path, "daemon:\n  log_level: INFO\n")
        before = path.read_text()

        with pytest.raises(ValueError, match="X.Y.Z"):
            record_expected_version(path, bad)

        assert path.read_text() == before

    def test_an_inline_daemon_mapping_is_refused_rather_than_guessed_at(
        self, tmp_path: Path
    ) -> None:
        path = _config(tmp_path, "daemon: {log_level: INFO}\n")

        with pytest.raises(ValueError, match="daemon"):
            record_expected_version(path, "3.68.0")


class TestMain:
    def test_records_the_given_version(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _config(tmp_path, "daemon:\n  log_level: INFO\n")

        assert main(["--project-root", str(tmp_path), "--version", "3.68.0"]) == 0

        assert _recorded(path) == "3.68.0"
        assert "recorded 3.68.0" in capsys.readouterr().out

    def test_defaults_to_the_running_daemon_version(self, tmp_path: Path) -> None:
        path = _config(tmp_path, "daemon:\n  log_level: INFO\n")

        assert main(["--project-root", str(tmp_path)]) == 0

        assert _recorded(path) == __version__

    def test_reports_a_second_identical_run_as_already(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _config(tmp_path, "daemon:\n  log_level: INFO\n")
        main(["--project-root", str(tmp_path), "--version", "3.68.0"])
        capsys.readouterr()

        assert main(["--project-root", str(tmp_path), "--version", "3.68.0"]) == 0

        assert "already 3.68.0" in capsys.readouterr().out

    def test_a_bad_version_exits_non_zero_and_says_why(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _config(tmp_path, "daemon:\n  log_level: INFO\n")

        assert main(["--project-root", str(tmp_path), "--version", "main"]) == 1

        assert "X.Y.Z" in capsys.readouterr().err

    def test_a_missing_config_exits_non_zero(self, tmp_path: Path) -> None:
        assert main(["--project-root", str(tmp_path), "--version", "3.68.0"]) == 1


class TestDaemonConfigAcceptsIt:
    def test_defaults_to_none(self) -> None:
        assert DaemonConfig().expected_version is None

    def test_accepts_x_y_z(self) -> None:
        assert DaemonConfig.model_validate({"expected_version": "3.68.0"}).expected_version == (
            "3.68.0"
        )

    @pytest.mark.parametrize("bad", ["main", "3.68", "v3.68.0", "3.68.0-rc1", ""])
    def test_rejects_anything_else(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            DaemonConfig.model_validate({"expected_version": bad})
