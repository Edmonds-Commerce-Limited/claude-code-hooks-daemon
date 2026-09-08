"""Tests for ``ChainConfig`` — ``daemon.chain`` (Plan 00242, Phase 3)."""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import ChainConfig, Config, DaemonConfig


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
