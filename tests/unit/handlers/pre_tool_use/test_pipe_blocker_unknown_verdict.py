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


class TestAnUnknownPipeNeverLaundersADeniedOne:
    """EVERY offending pipe is judged; one unknown pipe does not decide the command.

    Review finding C1: only the first non-whitelisted pipe was classified, so an
    unknown producer placed first allowed a blacklisted one after it.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "docker ps | tail -1 && pytest tests/ | tail -5",
            "docker ps | tail -1; npm test | tail -5",
            "foo | head -1 && cargo test | tail -3",
            "foo | head -1 || cargo test | tail -3",
            "foo | head -1\npytest | tail -3",
            "echo $(docker ps | head -1) $(pytest | tail -1)",
            "my_report | tail -2 && for f in a b; do echo $f; done | tail",
        ],
    )
    def test_a_later_denied_pipe_still_denies(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        assert handler.matches(_event(command)) is True
        assert handler.handle(_event(command)).decision == Decision.DENY

    def test_the_deny_names_the_denied_producer_not_the_unknown_one(
        self, handler: PipeBlockerHandler
    ) -> None:
        reason = handler.handle(_event("docker ps | tail -1 && pytest tests/ | tail -5")).reason
        assert "pytest" in (reason or "")
        assert "docker" not in (reason or "").split("COMMAND:")[0]

    def test_every_unknown_producer_is_named_when_all_are_unknown(
        self, handler: PipeBlockerHandler, caplog: pytest.LogCaptureFixture
    ) -> None:
        result = handler.handle(_event("my_report | tail -1 && frobnicate | head -2"))
        assert_unknown_verdict(result, caplog, _GUARD, "my_report", "frobnicate")


class TestAWrappedBlacklistedProducerStillDenies:
    """A wrapper runs the command after it, so the pipe is judged on that command.

    Review finding C2: these all denied at base (unknown tier) and were allowed
    once unknown became a warning, because the blacklist never saw through them.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "env pytest tests/ | tail -5",
            "FOO=1 pytest tests/ | tail -5",
            "timeout 60 pytest tests/ | tail -5",
            "timeout -s KILL 60 nice -n 5 pytest | tail -5",
            "sudo npm test | tail -5",
            "sudo -u ci npm test | tail -5",
            "nice pytest | tail -5",
            "nohup cargo test | tail -5",
            "bash -c 'pytest' | tail -5",
            "sh -c 'cd x && pytest -q' | tail -5",
            'bash -lc "npm test" | head -5',
            "uv run pytest | tail -5",
            "uv run --with rich pytest -q | tail -5",
            "poetry run pytest | tail -5",
            "pipenv run pytest | tail -5",
            "npx jest | tail -5",
            "xargs pytest < f | tail -5",
            "xargs -n 1 pytest < f | tail -5",
            "python3 -m pytest | tail -5",
            "python3.13 -m mypy src | tail -5",
            ".venv/bin/pytest tests/ | tail -5",
            "./node_modules/.bin/jest | head",
        ],
    )
    def test_denied(self, handler: PipeBlockerHandler, command: str) -> None:
        assert handler.matches(_event(command)) is True
        result = handler.handle(_event(command))
        assert result.decision == Decision.DENY
        assert "expensive" in (result.reason or "")

    @pytest.mark.parametrize(
        "command",
        ["./scripts/qa/run_all.sh | tail -5", "timeout 600 scripts/qa/run_all.sh | tail -5"],
    )
    def test_a_configured_blacklist_entry_matches_the_script_at_any_path(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        handler._extra_blacklist = [r"^run_all\.sh\b"]
        assert handler.handle(_event(command)).decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "timeout 5 docker ps | tail -1",
            "bash -c 'pytest | grep FAIL' | tail -5",
            "uv run my_report | tail -5",
        ],
    )
    def test_a_wrapped_unknown_producer_still_only_warns(
        self, handler: PipeBlockerHandler, command: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert handler.handle(_event(command)).decision == Decision.ALLOW
        assert len(unknown_verdict_records(caplog)) == 1


def test_a_compound_closer_and_prose_still_deny(handler: PipeBlockerHandler) -> None:
    compound = handler.handle(_event("for f in a b; do echo $f; done | tail"))
    assert compound.decision == Decision.DENY
    prose = handler.handle(_event("the guardrail blocks piping straight to a pager | tail"))
    assert prose.decision == Decision.DENY
