"""Tests for the ``hooks-daemon agents`` CLI subcommand (Plan 00279)."""

import argparse
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_agents
from claude_code_hooks_daemon.install.agent_assets import (
    DEDUPE_AGENT_NAME,
    OPUS_SECURITY_AGENT_NAME,
    SHIPPED_AGENTS,
    deployed_agent_path,
    spec_by_name,
)

_OPUS_ENABLED_YAML = "agents:\n  opus_security:\n    enabled: true\n"


def _ns(project_root: Path, action: str, name: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(project_root=project_root, action=action, name=name)


def _project(tmp_path: Path, yaml_text: str = "") -> Path:
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text(yaml_text)
    return tmp_path


class TestList:
    def test_lists_every_shipped_agent_with_version_and_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_agents(_ns(_project(tmp_path), "list")) == 0
        out = capsys.readouterr().out
        for spec in SHIPPED_AGENTS:
            assert spec.name in out
            assert spec.version in out
            assert spec.gating_config_key in out


class TestStatus:
    def test_status_shows_classification_per_agent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tmp_path, _OPUS_ENABLED_YAML)
        spec = spec_by_name(OPUS_SECURITY_AGENT_NAME)
        target = deployed_agent_path(spec, project)
        target.parent.mkdir(parents=True)
        target.write_text("hacked\n")
        assert cmd_agents(_ns(project, "status")) == 0
        out = capsys.readouterr().out
        assert "customised" in out
        assert "absent" in out  # dedupe scout not deployed


class TestInstall:
    def test_install_deploys_enabled_agents(self, tmp_path: Path) -> None:
        project = _project(tmp_path, _OPUS_ENABLED_YAML)
        assert cmd_agents(_ns(project, "install")) == 0
        assert deployed_agent_path(spec_by_name(OPUS_SECURITY_AGENT_NAME), project).is_file()

    def test_install_named_disabled_agent_fails_with_guidance(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tmp_path)
        assert cmd_agents(_ns(project, "install", OPUS_SECURITY_AGENT_NAME)) == 1
        captured = capsys.readouterr()
        assert "agents.opus_security.enabled" in captured.err
        assert not deployed_agent_path(spec_by_name(OPUS_SECURITY_AGENT_NAME), project).exists()

    def test_install_named_enabled_agent_deploys_it(self, tmp_path: Path) -> None:
        project = _project(tmp_path, _OPUS_ENABLED_YAML)
        assert cmd_agents(_ns(project, "install", OPUS_SECURITY_AGENT_NAME)) == 0
        assert deployed_agent_path(spec_by_name(OPUS_SECURITY_AGENT_NAME), project).is_file()

    def test_install_unknown_name_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_agents(_ns(_project(tmp_path), "install", "no-such-agent")) == 1
        assert "no-such-agent" in capsys.readouterr().err


class TestRemove:
    def test_remove_requires_name(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert cmd_agents(_ns(_project(tmp_path), "remove")) == 1
        assert "name" in capsys.readouterr().err.lower()

    def test_remove_pristine_agent(self, tmp_path: Path) -> None:
        project = _project(tmp_path, _OPUS_ENABLED_YAML)
        cmd_agents(_ns(project, "install"))
        assert cmd_agents(_ns(project, "remove", OPUS_SECURITY_AGENT_NAME)) == 0
        assert not deployed_agent_path(spec_by_name(OPUS_SECURITY_AGENT_NAME), project).exists()

    def test_remove_refuses_customised(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        project = _project(tmp_path)
        spec = spec_by_name(DEDUPE_AGENT_NAME)
        target = deployed_agent_path(spec, project)
        target.parent.mkdir(parents=True)
        target.write_text("hacked\n")
        assert cmd_agents(_ns(project, "remove", DEDUPE_AGENT_NAME)) == 1
        assert target.exists()
        # The refusal reaches the user ONCE, via the logging system (the CLI
        # routes WARNING to stderr); cmd_agents must not print it a second time.
        assert "REFUSED" in caplog.text
        assert "REFUSED" not in capsys.readouterr().out

    def test_install_customised_warns_once(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        project = _project(tmp_path, _OPUS_ENABLED_YAML)
        spec = spec_by_name(OPUS_SECURITY_AGENT_NAME)
        target = deployed_agent_path(spec, project)
        target.parent.mkdir(parents=True)
        target.write_text("hacked\n")
        assert cmd_agents(_ns(project, "install", OPUS_SECURITY_AGENT_NAME)) == 1
        assert "CUSTOMISED" in caplog.text
        assert "CUSTOMISED" not in capsys.readouterr().out
