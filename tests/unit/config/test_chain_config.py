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


class TestDeadlineBelowClientSocketTimeout:
    """Plan 00466 N40 m6: ``deadline_seconds`` must stay well under the
    client's own socket timeout (``Timeout.SOCKET_DISPATCH_ROUNDTRIP``), with
    enough margin left over to actually deliver the response. A deadline that
    reaches (or merely grazes) the client timeout reproduces the exact
    fail-open bypass ``deadline_seconds`` exists to close: the client gives up
    and fails the WHOLE chain open before the daemon's own deadline-triggered
    deny can ever be serialised and sent back.
    """

    def test_a_deadline_flush_against_the_socket_timeout_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="socket timeout"):
            ChainConfig.model_validate({"deadline_seconds": Timeout.SOCKET_DISPATCH_ROUNDTRIP})

    def test_a_deadline_past_the_socket_timeout_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="socket timeout"):
            ChainConfig.model_validate({"deadline_seconds": Timeout.SOCKET_DISPATCH_ROUNDTRIP + 1})

    def test_a_deadline_inside_the_timeout_but_without_margin_is_rejected(self) -> None:
        """Even strictly under the socket timeout, too little margin to
        actually send the response back is refused, not just a tie or an
        overshoot."""
        too_close = Timeout.SOCKET_DISPATCH_ROUNDTRIP - (
            Timeout.CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS - 1
        )
        with pytest.raises(ValidationError, match="margin"):
            ChainConfig.model_validate({"deadline_seconds": too_close})

    def test_a_deadline_with_adequate_margin_is_accepted(self) -> None:
        safe = Timeout.SOCKET_DISPATCH_ROUNDTRIP - Timeout.CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS
        config = ChainConfig.model_validate({"deadline_seconds": safe})
        assert config.deadline_seconds == safe

    def test_the_shipped_default_satisfies_its_own_rule(self) -> None:
        """The default must never trip the rule it enforces on everyone else."""
        ChainConfig()  # must not raise

    def test_none_still_disables_enforcement_and_is_never_checked(self) -> None:
        config = ChainConfig.model_validate({"deadline_seconds": None})
        assert config.deadline_seconds is None
