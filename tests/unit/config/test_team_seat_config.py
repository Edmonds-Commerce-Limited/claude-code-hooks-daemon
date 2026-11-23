"""The `team_seat` config block (Plan 00631 Task 2.3).

Two keys only: ``detection`` (``auto`` probes when the session carries a
teamchat runtime, ``off`` never probes) and ``resolve_ttl_seconds`` (how long a
role answer is reused; a role change takes effect within one TTL).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, TeamSeatConfig


class TestDefaults:
    def test_detection_is_auto(self) -> None:
        assert TeamSeatConfig().detection == "auto"

    def test_ttl_is_sixty_seconds(self) -> None:
        assert TeamSeatConfig().resolve_ttl_seconds == 60

    def test_root_config_carries_the_block(self) -> None:
        assert Config().team_seat == TeamSeatConfig()

    def test_detection_enabled_follows_the_mode(self) -> None:
        assert TeamSeatConfig().detection_enabled is True
        assert TeamSeatConfig(detection="off").detection_enabled is False


class TestValidation:
    def test_unknown_detection_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TeamSeatConfig.model_validate({"detection": "on"})

    @pytest.mark.parametrize("ttl", [0, -5, 3601])
    def test_ttl_out_of_range_is_rejected(self, ttl: int) -> None:
        with pytest.raises(ValidationError):
            TeamSeatConfig.model_validate({"resolve_ttl_seconds": ttl})

    def test_extra_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TeamSeatConfig.model_validate({"role": "coordinator"})

    def test_the_block_loads_from_a_config_document(self) -> None:
        config = Config.model_validate(
            {"team_seat": {"detection": "off", "resolve_ttl_seconds": 30}}
        )
        assert config.team_seat.detection == "off"
        assert config.team_seat.resolve_ttl_seconds == 30
