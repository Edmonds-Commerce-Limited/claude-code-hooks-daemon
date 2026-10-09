"""``check-effective-handlers`` exit codes, the contract ``scripts/upgrade.sh`` reads.

0 = the effective handler set is unchanged, 1 = handlers start or stop (a normal
outcome the upgrade reports), 2 = the check could not run (no config, unusable
versions), 3 = the config is not valid YAML. A malformed config must never share
exit 1, which upgrade.sh prints under "HANDLERS THAT CHANGE STATE".
"""

import argparse
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.init_config import generate_config
from claude_code_hooks_daemon.install import config_cli

UNCHANGED, CHANGED, ERROR, MALFORMED = 0, 1, 2, 3


def _args(config: Path, *, output_format: str = "text") -> argparse.Namespace:
    return argparse.Namespace(
        from_version="3.69.0",
        to_version="3.69.0",
        config=str(config),
        format=output_format,
        project_root=None,
    )


def _stub(monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]) -> None:
    monkeypatch.setattr(config_cli, "run_check_effective_handlers", lambda **_: result)


def test_exit_0_when_nothing_changes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "hooks-daemon.yaml"
    config.write_text(generate_config("full"), encoding="utf-8")

    assert cli.cmd_check_effective_handlers(_args(config)) == UNCHANGED
    assert capsys.readouterr().out == ""


def test_exit_1_and_the_report_when_handlers_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, {"has_changes": True, "text": "1 handler(s) STOP running"})

    assert cli.cmd_check_effective_handlers(_args(tmp_path / "c.yaml")) == CHANGED
    assert "STOP running" in capsys.readouterr().out


def test_exit_1_in_json_prints_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub(monkeypatch, {"has_changes": True, "changes": []})

    assert cli.cmd_check_effective_handlers(_args(tmp_path / "c.yaml", output_format="json")) == 1
    assert '"has_changes": true' in capsys.readouterr().out


def test_exit_2_when_the_config_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.cmd_check_effective_handlers(_args(tmp_path / "absent.yaml")) == ERROR
    assert "not found" in capsys.readouterr().err


def test_exit_2_when_a_version_is_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(**_: Any) -> dict[str, Any]:
        raise ValueError("not a version: 'x'")

    monkeypatch.setattr(config_cli, "run_check_effective_handlers", refuse)

    assert cli.cmd_check_effective_handlers(_args(tmp_path / "c.yaml")) == ERROR
    assert "not a version" in capsys.readouterr().err


@pytest.mark.parametrize(
    "text", ["handlers: [unclosed\n", "key: value: another\n  bad: [", "- a\n- b\n", "just text\n"]
)
def test_exit_3_when_the_config_is_not_a_yaml_mapping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    config = tmp_path / "hooks-daemon.yaml"
    config.write_text(text, encoding="utf-8")

    assert cli.cmd_check_effective_handlers(_args(config)) == MALFORMED
    assert "ERROR" in capsys.readouterr().err


def test_malformed_yaml_is_a_value_error_for_every_config_reader(tmp_path: Path) -> None:
    config = tmp_path / "hooks-daemon.yaml"
    config.write_text("handlers: [unclosed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid YAML"):
        config_cli.run_check_effective_handlers("3.69.0", "3.69.0", config)
