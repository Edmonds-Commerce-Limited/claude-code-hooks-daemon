"""Tests for ``ChainConfig`` — ``daemon.chain`` (Plan 00242, Phase 3; Plan 00466 N25)."""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import ChainConfig, Config, DaemonConfig
from claude_code_hooks_daemon.constants import Timeout


class TestDefaults:
    def test_collect_all_violations_defaults_off(self) -> None:
        assert ChainConfig().collect_all_violations is False

    def test_daemon_config_carries_a_chain_block(self) -> None:
        daemon_config = DaemonConfig()
        assert isinstance(daemon_config.chain, ChainConfig)
        assert daemon_config.chain.collect_all_violations is False

    def test_default_config_keeps_the_short_circuit(self) -> None:
        """A client that never set the key gets today's deny-short-circuit."""
        assert Config().daemon.chain.collect_all_violations is False

    def test_deadline_seconds_defaults_well_under_the_client_timeout(self) -> None:
        """Plan 00466 N25: enforcement is ON by default, under HOOK_TOTAL (30s)."""
        deadline_seconds = ChainConfig().deadline_seconds
        assert deadline_seconds == Timeout.CHAIN_DEADLINE_DEFAULT
        assert deadline_seconds is not None
        assert deadline_seconds < Timeout.HOOK_TOTAL / Timeout.MILLISECONDS_PER_SECOND


class TestParsing:
    def test_parses_daemon_chain_block(self) -> None:
        config = Config.model_validate({"daemon": {"chain": {"collect_all_violations": True}}})
        assert config.daemon.chain.collect_all_violations is True

    def test_rejects_unknown_key(self) -> None:
        with pytest.raises(ValidationError):
            ChainConfig.model_validate({"collect_everything": True})

    def test_rejects_non_boolean(self) -> None:
        with pytest.raises(ValidationError):
            ChainConfig.model_validate({"collect_all_violations": "yes please"})

    def test_parses_deadline_seconds(self) -> None:
        config = Config.model_validate({"daemon": {"chain": {"deadline_seconds": 15}}})
        assert config.daemon.chain.deadline_seconds == 15

    def test_deadline_seconds_none_disables_enforcement(self) -> None:
        config = ChainConfig.model_validate({"deadline_seconds": None})
        assert config.deadline_seconds is None

    def test_rejects_a_non_positive_deadline(self) -> None:
        with pytest.raises(ValidationError):
            ChainConfig.model_validate({"deadline_seconds": 0})
