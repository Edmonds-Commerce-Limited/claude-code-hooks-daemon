"""Tests for ``ChainConfig`` — ``daemon.chain`` (Plan 00242, Phase 3; Plan 00466 N25)."""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import (
    ChainConfig,
    Config,
    DaemonConfig,
    TransportConfig,
)
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


def _daemon(transport: dict[str, object], deadline: float | None) -> DaemonConfig:
    return DaemonConfig.model_validate(
        {"transport": transport, "chain": {"deadline_seconds": deadline}}
    )


def _python_rung(deadline: float | None) -> DaemonConfig:
    return _daemon({}, deadline)


class TestDeadlineBelowClientSocketTimeout:
    """Plan 00466 N40 m6: ``deadline_seconds`` should stay well under the
    client's own socket timeout (``Timeout.SOCKET_DISPATCH_ROUNDTRIP``), with
    enough margin left over to actually deliver the response. Past it, the
    client's timeout answers first: a PreToolUse call is then denied as
    ``socket_timeout`` instead of naming the handler.

    Reported, NOT rejected (Plan 00466 N40 review 2 mA4): rejecting the value
    stops the daemon starting, and a daemon that cannot start leaves every
    guard off -- far worse than the imprecise deny it was guarding against.
    """

    def test_a_deadline_flush_against_the_socket_timeout_is_reported(self) -> None:
        (problem,) = _python_rung(Timeout.SOCKET_DISPATCH_ROUNDTRIP).chain_deadline_problems
        assert "socket timeout" in problem

    def test_a_deadline_past_the_socket_timeout_is_reported(self) -> None:
        (problem,) = _python_rung(Timeout.SOCKET_DISPATCH_ROUNDTRIP + 1).chain_deadline_problems
        assert "socket timeout" in problem

    def test_a_deadline_inside_the_timeout_but_without_margin_is_reported(self) -> None:
        """Even strictly under the socket timeout, too little margin to
        actually send the response back is reported, not just a tie or an
        overshoot."""
        too_close = Timeout.SOCKET_DISPATCH_ROUNDTRIP - (
            Timeout.CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS - 1
        )
        (problem,) = _python_rung(too_close).chain_deadline_problems
        assert "margin" in problem

    def test_a_reported_deadline_is_still_loaded_as_configured(self) -> None:
        """The config stays valid, so the daemon starts with every guard on."""
        config = Config.model_validate(
            {"daemon": {"chain": {"deadline_seconds": Timeout.SOCKET_DISPATCH_ROUNDTRIP}}}
        )
        assert config.daemon.chain.deadline_seconds == Timeout.SOCKET_DISPATCH_ROUNDTRIP

    def test_a_deadline_with_adequate_margin_has_no_problem(self) -> None:
        safe = Timeout.SOCKET_DISPATCH_ROUNDTRIP - Timeout.CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS
        assert _python_rung(safe).chain_deadline_problems == []

    def test_the_shipped_default_satisfies_its_own_rule(self) -> None:
        """The default must never trip the rule it applies to everyone else."""
        assert DaemonConfig().chain_deadline_problems == []

    def test_none_still_disables_enforcement_and_is_never_checked(self) -> None:
        assert _python_rung(None).chain_deadline_problems == []


class TestDeadlineAgainstTheConfiguredClientBudget:
    """Plan 00466 N40 review 2 mA4: the deadline is checked against the client
    timeout this config actually deploys, not only the python rung's constant.

    With a per-event rung enabled, the relay (``--timeout-ms``) and ``nc -w``
    give up after ``transport.timeout_seconds``; a deadline the constant accepts
    can still outlast that budget, and then the client, not the daemon, decides.
    The review's probe: deadline 20 with ``timeout_seconds: 10`` reported healthy.
    """

    def test_a_deadline_past_the_relay_budget_is_reported(self) -> None:
        (problem,) = _daemon(
            {"relay_enabled": True, "timeout_seconds": 10}, 20
        ).chain_deadline_problems
        assert "transport.timeout_seconds" in problem

    def test_a_deadline_past_the_nc_budget_is_reported(self) -> None:
        (problem,) = _daemon(
            {"nc_enabled": True, "timeout_seconds": 10}, 20
        ).chain_deadline_problems
        assert "transport.timeout_seconds" in problem

    def test_a_deadline_without_margin_inside_the_relay_budget_is_reported(self) -> None:
        (problem,) = _daemon(
            {"relay_enabled": True, "timeout_seconds": 10}, 8
        ).chain_deadline_problems
        assert "margin" in problem

    def test_a_deadline_with_margin_inside_the_relay_budget_has_no_problem(self) -> None:
        budget = 10
        safe = budget - Timeout.CHAIN_DEADLINE_SOCKET_MARGIN_SECONDS
        config = _daemon({"relay_enabled": True, "timeout_seconds": budget}, safe)
        assert config.chain_deadline_problems == []

    def test_the_transport_budget_is_ignored_while_no_per_event_rung_uses_it(self) -> None:
        """Only the python rung is live, so only its budget binds."""
        assert _daemon({"timeout_seconds": 10}, 20).chain_deadline_problems == []

    def test_raising_the_relay_budget_does_not_lift_the_python_rung_floor(self) -> None:
        """The python rung is every forwarder's fallback, so its budget binds
        even when the relay is given longer."""
        config = _daemon(
            {"relay_enabled": True, "timeout_seconds": 60},
            Timeout.SOCKET_DISPATCH_ROUNDTRIP - 1,
        )
        (problem,) = config.chain_deadline_problems
        assert "socket timeout" in problem

    def test_none_is_never_checked_against_the_transport_budget(self) -> None:
        assert (
            _daemon({"relay_enabled": True, "timeout_seconds": 1}, None).chain_deadline_problems
            == []
        )


class TestClientBudgetSeconds:
    """``TransportConfig.client_budget_seconds``: the tightest client timeout a
    request can meet under this transport config."""

    def test_python_rung_only(self) -> None:
        assert TransportConfig().client_budget_seconds == Timeout.SOCKET_DISPATCH_ROUNDTRIP

    def test_a_tighter_per_event_rung_binds(self) -> None:
        transport = TransportConfig(relay_enabled=True, timeout_seconds=10)
        assert transport.client_budget_seconds == 10

    def test_a_looser_per_event_rung_does_not(self) -> None:
        transport = TransportConfig(nc_enabled=True, timeout_seconds=60)
        assert transport.client_budget_seconds == Timeout.SOCKET_DISPATCH_ROUNDTRIP
