"""`env` is a command RUNNER, not a cheap filter — Plan 00412.

Found by the `declared-invariant-pairs` Detector's first row, as an instance of
`asymmetric-sibling-protection`: the correct reading of `env` already existed at
a sibling site, and this handler disagreed with it.

`utils/process_probe.py`'s `_WRAPPERS` classifies `env` as a wrapper, and the
evasion suite asserts `env git commit`, `env gh issue create`, `env pgrep` and
`env cat <DETAIL>` are every one of them judged on the WRAPPED command. The pipe
whitelist was the single site treating it as a cheap filter whose own output is
safe to truncate — so `env pytest tests/ | head -20` was attributed to the
whitelisted `env` at the head and the truncation went through.

The asymmetry is what makes this a defect rather than a preference: two parts of
one codebase cannot both be right about what `env` is.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestEnvIsNotACheapFilter:
    """A whitelisted producer makes `matches()` False; these must be True."""

    @pytest.mark.parametrize(
        "command",
        [
            "env pytest tests/ | head -20",
            "env pytest tests/ | tail -20",
            "env FOO=1 pytest tests/ | head -5",
            "env -u PYTHONPATH npm run build | tail -n 30",
        ],
    )
    def test_a_wrapped_expensive_command_is_not_whitelisted(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is True


class TestTheCheapUseSurvives:
    """Removing `env` must not cost the legitimate 'show me the environment' pipe."""

    @pytest.mark.parametrize(
        "command",
        [
            "printenv | head -20",
            "printenv PATH | tail -n 2",
        ],
    )
    def test_printenv_is_still_whitelisted(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        """`printenv` is the non-wrapper spelling and does the same job.

        It cannot run another command at all, so it carries none of the hazard
        that `env` does and stays on the whitelist.
        """
        assert handler.matches(_bash(command)) is False


class TestTheOtherWhitelistEntriesAreUntouched:
    """A guard that the removal was surgical rather than a whitelist regression."""

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r pattern . | head -20",
            "ls -la /tmp | head -n 15",
            "ps aux | head -5",
            "df -h | tail -3",
        ],
    )
    def test_a_genuinely_cheap_producer_is_still_allowed(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False
