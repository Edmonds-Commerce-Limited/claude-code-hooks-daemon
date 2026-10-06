"""Tests for the top-level ``autonomy:`` config block (Plan 00498 Task 2.1).

``autonomy`` decides, per environment, whether the work-DRIVING machinery (crons,
the goal ledger, goal injection, recovery advice) runs at all. The default is
every environment so a project that says nothing behaves exactly as before.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import AutonomyConfig, Config


class TestDefaults:
    def test_a_project_that_says_nothing_allows_every_environment(self) -> None:
        config = Config()
        for environment in ("host", "docker", "podman", "lxc", "generic"):
            assert config.autonomy.allows(environment, "any-host") is True

    def test_default_hosts_is_empty(self) -> None:
        assert AutonomyConfig().hosts == []


class TestEnvironments:
    def test_the_bare_host_can_be_left_out(self) -> None:
        autonomy = AutonomyConfig(environments=["docker", "podman", "lxc", "generic"])
        assert autonomy.allows("host", "laptop") is False
        assert autonomy.allows("docker", "laptop") is True

    def test_an_environment_not_listed_is_refused(self) -> None:
        autonomy = AutonomyConfig(environments=["lxc"])
        assert autonomy.allows("docker", "x") is False
        assert autonomy.allows("lxc", "x") is True

    def test_an_empty_list_means_no_environment_at_all(self) -> None:
        autonomy = AutonomyConfig(environments=[])
        assert autonomy.allows("docker", "x") is False

    def test_an_unknown_environment_name_is_rejected(self) -> None:
        payload: dict[str, Any] = {"environments": ["desktop"]}
        with pytest.raises(ValidationError):
            AutonomyConfig.model_validate(payload)

    def test_parses_from_a_yaml_shaped_mapping(self) -> None:
        config = Config.model_validate(
            {"autonomy": {"environments": ["docker", "generic"], "hosts": ["cchd-*"]}}
        )
        assert config.autonomy.environments == ["docker", "generic"]
        assert config.autonomy.hosts == ["cchd-*"]


class TestHosts:
    def test_a_matching_role_alias_allows_autonomy_even_on_the_bare_host(self) -> None:
        autonomy = AutonomyConfig(environments=[], hosts=["cchd-sdlc-runner"])
        assert autonomy.allows("host", "cchd-sdlc-runner") is True

    def test_a_glob_matches(self) -> None:
        autonomy = AutonomyConfig(environments=["docker"], hosts=["runner-*"])
        assert autonomy.allows("host", "runner-7") is True
        assert autonomy.allows("host", "laptop") is False

    @pytest.mark.parametrize("bad", [[""], ["  "]])
    def test_a_blank_host_entry_is_rejected(self, bad: list[str]) -> None:
        with pytest.raises(ValidationError):
            AutonomyConfig(hosts=bad)

    def test_unknown_keys_are_rejected(self) -> None:
        payload: dict[str, Any] = {"environment": ["docker"]}
        with pytest.raises(ValidationError):
            AutonomyConfig.model_validate(payload)
