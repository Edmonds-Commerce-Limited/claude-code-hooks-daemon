"""Tests for ``autonomy_allowed`` and its verdict (Plan 00498 Task 2.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import AutonomyConfig, Config
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import ProjectContext
from claude_code_hooks_daemon.utils import autonomy
from claude_code_hooks_daemon.utils.autonomy import (
    autonomy_allowed,
    autonomy_verdict,
    current_environment,
    environment_label,
)

_CONTAINERS_ONLY = Config(
    autonomy=AutonomyConfig(environments=["docker", "podman", "lxc", "generic"])
)


class TestEnvironment:
    def test_no_runtime_is_the_bare_host(self) -> None:
        assert environment_label(None) == "host"

    def test_a_runtime_is_its_own_label(self) -> None:
        assert environment_label("lxc") == "lxc"

    def test_an_unknown_runtime_is_a_generic_container_never_the_host(self) -> None:
        assert environment_label("kubernetes") == "generic"

    def test_detects_when_not_told(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: "podman")
        assert current_environment() == "podman"
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert current_environment() == "host"


class TestVerdict:
    @pytest.fixture(autouse=True)
    def _no_role_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_HOSTNAME", raising=False)
        monkeypatch.delenv("CCY_HOST_HOSTNAME", raising=False)

    def test_default_config_allows_everywhere(self) -> None:
        assert autonomy_verdict(config=Config(), environment="host").allowed is True

    def test_host_is_refused_by_a_containers_only_config(self) -> None:
        verdict = autonomy_verdict(config=_CONTAINERS_ONLY, environment="host")
        assert verdict.allowed is False
        assert verdict.environment == "host"

    def test_a_container_is_allowed_by_a_containers_only_config(self) -> None:
        assert autonomy_verdict(config=_CONTAINERS_ONLY, environment="docker").allowed is True

    def test_the_payload_hostname_alias_overrides_the_environment(self) -> None:
        config = Config(autonomy=AutonomyConfig(environments=[], hosts=["cchd-sdlc-runner"]))
        payload = {HookInputField.SESSION_HOSTNAME: "cchd-sdlc-runner"}
        verdict = autonomy_verdict(payload, config=config, environment="host")
        assert verdict.allowed is True

    def test_an_environment_variable_alias_is_read_without_a_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOOKS_DAEMON_HOSTNAME", "role-x")
        config = Config(autonomy=AutonomyConfig(environments=[], hosts=["role-*"]))
        assert autonomy_verdict(config=config, environment="host").allowed is True

    def test_the_explanation_names_the_environment_and_the_remedy(self) -> None:
        text = autonomy_verdict(config=_CONTAINERS_ONLY, environment="host").explain()
        assert "host" in text
        assert "autonomy.environments" in text


class TestAutonomyAllowedLoadsTheProjectConfig:
    @staticmethod
    def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(body)
        monkeypatch.setattr(ProjectContext, "config_path", classmethod(lambda cls: config_path))
        monkeypatch.delenv("HOOKS_DAEMON_HOSTNAME", raising=False)
        monkeypatch.delenv("CCY_HOST_HOSTNAME", raising=False)

    def test_off_on_the_host_when_the_project_says_containers_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._project(
            tmp_path, monkeypatch, "version: '2.0'\nautonomy:\n  environments: [docker]\n"
        )
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert autonomy_allowed() is False

    def test_on_in_a_listed_container(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._project(
            tmp_path, monkeypatch, "version: '2.0'\nautonomy:\n  environments: [docker]\n"
        )
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: "docker")
        assert autonomy_allowed() is True

    def test_on_when_the_project_has_no_autonomy_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._project(tmp_path, monkeypatch, "version: '2.0'\n")
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert autonomy_allowed() is True

    def test_an_unloadable_config_keeps_the_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._project(tmp_path, monkeypatch, "autonomy: [not a mapping\n")
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert autonomy_allowed() is True

    def test_no_project_context_keeps_the_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ProjectContext.reset()
        monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: None)
        assert autonomy_allowed() is True
