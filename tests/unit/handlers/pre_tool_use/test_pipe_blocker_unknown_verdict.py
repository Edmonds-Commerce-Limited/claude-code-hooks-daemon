"""pipe_blocker: a producer on neither list warns instead of denying (Plan 00478 row 26).

Whitelisted producers still allow silently, blacklisted (known expensive) ones
still deny, and a producer the handler knows nothing about is allowed with the
shared advisory naming ``bin/echd-capture`` and ``extra_whitelist``.
"""

from typing import Any

import pytest
from tests.support.unknown_verdict_asserts import assert_unknown_verdict, unknown_verdict_records

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

_GUARD = "pipe_blocker"


def _event(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


UNKNOWN_PRODUCERS = [
    "my_report --all | tail -n 20",
    "my_report --all | head -5",
    "frobnicate widgets 2>&1 | tail",
]


@pytest.mark.parametrize("command", UNKNOWN_PRODUCERS)
def test_an_unknown_producer_allows_with_an_advisory(
    handler: PipeBlockerHandler, command: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert handler.matches(_event(command)) is True
    result = handler.handle(_event(command))
    advisory = assert_unknown_verdict(
        result,
        caplog,
        _GUARD,
        "echd-capture",
        "extra_whitelist",
        "my_report" if command.startswith("my_report") else "frobnicate",
    )
    assert "pipe_blocker" in advisory


@pytest.mark.parametrize("command", UNKNOWN_PRODUCERS)
def test_the_unknown_warning_repeats_every_time(
    handler: PipeBlockerHandler, command: str, caplog: pytest.LogCaptureFixture
) -> None:
    first = handler.handle(_event(command))
    second = handler.handle(_event(command))
    assert first.decision == second.decision == Decision.ALLOW
    assert len(unknown_verdict_records(caplog)) == 2


@pytest.mark.parametrize(
    "command",
    ["pytest tests/ | tail -20", "npm test | head", "cargo build 2>&1 | tail"],
)
def test_a_blacklisted_producer_still_denies(handler: PipeBlockerHandler, command: str) -> None:
    result = handler.handle(_event(command))
    assert result.decision == Decision.DENY
    assert result.rule is not None


def test_a_deny_does_not_use_up_the_verbose_message_of_an_unknown_warning(
    handler: PipeBlockerHandler,
) -> None:
    """An unknown warning leaves the disclosure state alone, so the first DENY is verbose."""
    event = {**_event("my_report | tail"), "transcript_path": "/tmp/t-unknown-then-deny.jsonl"}
    assert handler.handle(event).decision == Decision.ALLOW
    deny = {**_event("pytest | tail"), "transcript_path": "/tmp/t-unknown-then-deny.jsonl"}
    assert "WHY BLOCKED" in (handler.handle(deny).reason or "")


@pytest.mark.parametrize("command", ["grep x f | tail -n 5", "git log | head -3", "ls | head"])
def test_a_whitelisted_producer_matches_nothing(
    handler: PipeBlockerHandler, command: str, caplog: pytest.LogCaptureFixture
) -> None:
    assert handler.matches(_event(command)) is False
    assert unknown_verdict_records(caplog) == []


def test_a_configured_whitelist_entry_silences_the_unknown_warning(
    handler: PipeBlockerHandler,
) -> None:
    handler._extra_whitelist = [r"^my_report\b"]
    assert handler.matches(_event("my_report | tail")) is False


def test_a_compound_closer_and_prose_still_deny(handler: PipeBlockerHandler) -> None:
    compound = handler.handle(_event("for f in a b; do echo $f; done | tail"))
    assert compound.decision == Decision.DENY
    prose = handler.handle(_event("the guardrail blocks piping straight to a pager | tail"))
    assert prose.decision == Decision.DENY
