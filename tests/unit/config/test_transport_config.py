"""Tests for ``TransportConfig`` (Plan 00290, Task 2.1)."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, DaemonConfig, TransportConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.constants.events import EventID
from claude_code_hooks_daemon.utils.hook_registration import canonical_hook_entry


class TestDefaults:
    def test_relay_and_nc_default_off(self) -> None:
        transport = TransportConfig()
        assert transport.relay_enabled is False
        assert transport.nc_enabled is False

    def test_timeout_defaults_to_thirty_seconds(self) -> None:
        assert TransportConfig().timeout_seconds == 30

    def test_relay_binary_defaults_to_none(self) -> None:
        assert TransportConfig().relay_binary is None

    def test_relay_source_defaults_to_none(self) -> None:
        assert TransportConfig().relay_source is None

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

    def test_rejects_unknown_relay_source(self) -> None:
        with pytest.raises(ValidationError):
            TransportConfig.model_validate({"relay_source": "curl"})


_RELAY_SOURCE = Path(__file__).resolve().parents[3] / "relay" / "hooks_relay.rs"


class TestTheRelayTimeoutFitsTheHookTimeout:
    """Plan 00466 N126 round 2 (F3): after the relay's own wait, a failed
    PreToolUse exchange is handed to the forwarder, which can take up to the
    relay's hand-off budget. Claude Code cancels the hook at the timeout the
    daemon registers for it, and a cancelled PreToolUse hook lets the call
    run unjudged, so the relay wait plus the hand-off plus a margin must stay
    under that timeout."""

    def test_the_budget_adds_up_to_the_hook_timeout(self) -> None:
        total = (
            Timeout.RELAY_TIMEOUT_CAP
            + Timeout.RELAY_HANDOFF_BUDGET
            + Timeout.RELAY_HOOK_TIMEOUT_MARGIN
        )
        assert total == Timeout.REGISTERED_HOOK_TIMEOUT
        assert Timeout.RELAY_HOOK_TIMEOUT_MARGIN > 0
        assert TransportConfig().timeout_seconds <= Timeout.RELAY_TIMEOUT_CAP

    def test_the_registered_pretooluse_timeout_is_the_one_budgeted(self) -> None:
        entry = canonical_hook_entry(EventID.PRE_TOOL_USE.bash_key)
        assert entry["timeout"] == Timeout.REGISTERED_HOOK_TIMEOUT

    def test_the_relays_hand_off_deadline_is_the_one_budgeted(self) -> None:
        match = re.search(r"const HANDOFF_TIMEOUT_MS: u64 = ([\d_]+);", _RELAY_SOURCE.read_text())
        assert match is not None
        handoff_ms = int(match.group(1).replace("_", ""))
        assert handoff_ms == Timeout.RELAY_HANDOFF_BUDGET * Timeout.MILLISECONDS_PER_SECOND

    def test_the_cap_itself_is_accepted(self) -> None:
        transport = TransportConfig(timeout_seconds=Timeout.RELAY_TIMEOUT_CAP)
        assert transport.timeout_seconds == Timeout.RELAY_TIMEOUT_CAP

    def test_a_timeout_over_the_cap_is_rejected_and_says_why(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            TransportConfig.model_validate({"timeout_seconds": Timeout.RELAY_TIMEOUT_CAP + 1})
        message = str(excinfo.value)
        assert f"at most {Timeout.RELAY_TIMEOUT_CAP}" in message, message
        assert f"{Timeout.REGISTERED_HOOK_TIMEOUT}s hook timeout" in message, message
        assert "unjudged" in message, message


class TestRelaySource:
    def test_accepts_build(self) -> None:
        assert TransportConfig(relay_source="build").relay_source == "build"

    def test_accepts_download(self) -> None:
        assert TransportConfig(relay_source="download").relay_source == "download"

    def test_accepts_null(self) -> None:
        assert TransportConfig(relay_source=None).relay_source is None
