"""Tests for ``TransportConfig`` (Plan 00290, Task 2.1)."""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, DaemonConfig, TransportConfig


class TestDefaults:
    def test_relay_and_nc_default_off(self) -> None:
        transport = TransportConfig()
        assert transport.relay_enabled is False
        assert transport.nc_enabled is False

    def test_timeout_defaults_to_thirty_seconds(self) -> None:
        assert TransportConfig().timeout_seconds == 30

    def test_relay_binary_defaults_to_none(self) -> None:
        assert TransportConfig().relay_binary is None

    def test_per_event_sockets_needed_false_by_default(self) -> None:
        assert TransportConfig().per_event_sockets_needed is False


class TestPerEventSocketsNeeded:
    def test_true_when_relay_enabled(self) -> None:
        assert TransportConfig(relay_enabled=True).per_event_sockets_needed is True

    def test_true_when_nc_enabled(self) -> None:
        assert TransportConfig(nc_enabled=True).per_event_sockets_needed is True

    def test_false_when_both_disabled(self) -> None:
        transport = TransportConfig(relay_enabled=False, nc_enabled=False)
        assert transport.per_event_sockets_needed is False


class TestDaemonConfigCarriesATransportBlock:
    def test_absent_block_gets_defaults(self) -> None:
        daemon_config = DaemonConfig()
        assert isinstance(daemon_config.transport, TransportConfig)
        assert daemon_config.transport.relay_enabled is False

    def test_parses_full_block(self) -> None:
        raw = {
            "transport": {
                "relay_enabled": True,
                "nc_enabled": True,
                "timeout_seconds": 5,
                "relay_binary": "/opt/hooks-relay",
            }
        }
        config = Config.model_validate({"daemon": raw})
        assert config.daemon.transport.relay_enabled is True
        assert config.daemon.transport.nc_enabled is True
        assert config.daemon.transport.timeout_seconds == 5
        assert config.daemon.transport.relay_binary == "/opt/hooks-relay"

    def test_default_config_behaviour_is_byte_identical(self) -> None:
        """Default config never needs per-event sockets (PLAN.md Success Criteria)."""
        config = Config()
        assert config.daemon.transport.per_event_sockets_needed is False


class TestStrictValidation:
    def test_rejects_unknown_top_level_key(self) -> None:
        with pytest.raises(ValidationError):
            TransportConfig.model_validate({"bogus": True})

    def test_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValidationError):
            TransportConfig.model_validate({"timeout_seconds": 0})

    def test_rejects_negative_timeout(self) -> None:
        with pytest.raises(ValidationError):
            TransportConfig.model_validate({"timeout_seconds": -5})
