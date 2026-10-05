"""`upgrade.sh` reports the effective handler change and a true config summary (Plan 00493).

A client upgraded v3.67.0 to v3.68.0 and found 11 opt-in handlers switched off
under a config file that had not changed. The upgrade's metadata said
``config_diff_summary=no config changes`` because the summary read
``hooks-daemon.yaml.backup``, a path nothing writes (the installer writes
``hooks-daemon.yaml.backup-<timestamp>``), and because a diff of FILES cannot
see a change of RULES.

The blocks under test are lifted verbatim out of the real script, so a copy
cannot keep passing after the script changes.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — runs the trusted system `bash`
import sys
from pathlib import Path
from typing import Any, Final, Literal

import pytest
import yaml

from claude_code_hooks_daemon.daemon.init_config import generate_config

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_UPGRADE_SH: Final[Path] = _REPO_ROOT / "scripts" / "upgrade.sh"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 120

_REPORT_START: Final[str] = "# Version change and effective handler set (Plan 00493)"
_REPORT_END: Final[str] = "# Post-upgrade tasks (Plan 00376 Task 4.3)"
_FINDER_START: Final[str] = "_find_new_config_backup() {"
_NO_CHANGES: Final[str] = "no config changes"

_PRELUDE: Final[str] = """\
set -euo pipefail
_info() { echo ">>> $1"; }
_warn() { echo "WARN $1"; }
_ok() { echo "OK $1"; }
_BOLD=""
_NC=""
"""


def _source() -> str:
    return _UPGRADE_SH.read_text(encoding="utf-8")


def _report_block() -> str:
    source = _source()
    start = source.index(_REPORT_START)
    return source[start : source.index(_REPORT_END, start)]


def _finder_function() -> str:
    source = _source()
    start = source.index(_FINDER_START)
    return source[start : source.index("\n}\n", start) + len("\n}\n")]


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — trusted bash, test-authored script
        [_BASH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def _config(mode: Literal["minimal", "full"]) -> dict[str, Any]:
    loaded = yaml.safe_load(generate_config(mode))
    assert isinstance(loaded, dict)
    return loaded


def _run_report(tmp_path: Path, config: dict[str, Any], from_version: str) -> dict[str, str]:
    config_file = tmp_path / "hooks-daemon.yaml"
    config_file.write_text(yaml.safe_dump(config), encoding="utf-8")
    script = (
        _PRELUDE
        + f"""\
FROM_VERSION="{from_version}"
TARGET_DISPLAY="v3.68.0"
TARGET_SEMVER="v3.68.0"
_metadata_venv_python="{sys.executable}"
_metadata_config_file="{config_file}"
_metadata_config_summary="{_NO_CHANGES}"
"""
        + _report_block()
        + """
echo "SUMMARY=$_metadata_config_summary"
echo "CHANGES=$_metadata_handler_changes"
"""
    )
    result = _run(script)
    assert result.returncode == 0, result.stderr
    fields = dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if line.startswith(("SUMMARY=", "CHANGES="))
    )
    fields["stdout"] = result.stdout
    return fields


class TestEffectiveHandlerReport:
    def test_minimal_config_names_every_handler_that_stops(self, tmp_path: Path) -> None:
        fields = _run_report(tmp_path, _config("minimal"), "v3.67.0")

        assert "HANDLERS THAT CHANGE STATE" in fields["stdout"]
        assert "handlers.pre_tool_use.lsp_enforcement" in fields["stdout"]
        assert "enabled: true" in fields["stdout"]
        assert "stops:handlers.pre_tool_use.lsp_enforcement" in fields["CHANGES"]

    def test_summary_cannot_say_no_config_changes_while_the_set_differs(
        self, tmp_path: Path
    ) -> None:
        fields = _run_report(tmp_path, _config("minimal"), "v3.67.0")

        assert fields["SUMMARY"] != _NO_CHANGES
        assert "effective handler set changed" in fields["SUMMARY"]

    def test_current_full_config_reports_no_change(self, tmp_path: Path) -> None:
        fields = _run_report(tmp_path, _config("full"), "v3.67.0")

        assert "HANDLERS THAT CHANGE STATE" not in fields["stdout"]
        assert fields["CHANGES"] == ""
        assert fields["SUMMARY"] == _NO_CHANGES

    def test_the_version_change_is_named(self, tmp_path: Path) -> None:
        fields = _run_report(tmp_path, _config("full"), "v3.67.0")

        assert "Daemon version: v3.67.0 -> v3.68.0" in fields["stdout"]


class TestConfigBackupLookup:
    """The summary reads the backup the installer actually writes."""

    def _lookup(self, project: Path, before: list[Path]) -> str:
        listing = "".join(f"{path}\n" for path in before)
        script = (
            _PRELUDE
            + f'PROJECT_ROOT="{project}"\n'
            + f"_PRE_UPGRADE_BACKUPS='{listing}'\n"
            + _finder_function()
            + "_find_new_config_backup\n"
        )
        result = _run(script)
        assert result.returncode == 0, result.stderr
        return result.stdout

    def test_finds_the_timestamped_backup_this_run_wrote(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        claude.mkdir()
        old = claude / "hooks-daemon.yaml.backup-20260101-000000"
        old.write_text("old", encoding="utf-8")
        new = claude / "hooks-daemon.yaml.backup-20261005-120000"
        new.write_text("new", encoding="utf-8")

        assert self._lookup(tmp_path, [old]) == str(new)

    def test_empty_when_this_run_wrote_no_backup(self, tmp_path: Path) -> None:
        claude = tmp_path / ".claude"
        claude.mkdir()
        old = claude / "hooks-daemon.yaml.backup-20260101-000000"
        old.write_text("old", encoding="utf-8")

        assert self._lookup(tmp_path, [old]) == ""

    def test_script_does_not_read_the_unwritten_bare_backup_path(self) -> None:
        assert 'hooks-daemon.yaml.backup"' not in _source()


@pytest.mark.parametrize("marker", [_REPORT_START, _REPORT_END, _FINDER_START])
def test_markers_exist_in_script(marker: str) -> None:
    assert marker in _source()
