"""The shared 'unknown verdict' helper (Plan 00478 Task 2.2a)."""

from __future__ import annotations

import logging

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.utils.unknown_verdict import (
    UNKNOWN_VERDICT_LOG_PREFIX,
    unknown_verdict_allow,
    unknown_verdict_line,
)


class TestUnknownVerdictAllow:
    """An unknown verdict is an allow, an advisory and one greppable log line."""

    def test_the_result_allows(self) -> None:
        result = unknown_verdict_allow("my_guard", "git timed out", "retry the commit")
        assert result.decision == Decision.ALLOW

    def test_the_advisory_names_guard_cause_and_rephrase(self) -> None:
        result = unknown_verdict_allow("my_guard", "git timed out", "retry the commit")
        assert len(result.context) == 1
        line = result.context[0]
        assert "my_guard" in line
        assert "git timed out" in line
        assert "retry the commit" in line

    def test_the_advisory_does_not_claim_nothing_was_checked(self) -> None:
        """A guard may have judged part of the call; only the cause names what it could not."""
        line = unknown_verdict_allow("g", "git timed out", "retry").context[0]
        assert "without a check" not in line
        assert "not checked: git timed out" in line

    def test_the_line_helper_is_the_advisory_text(self) -> None:
        result = unknown_verdict_allow("g", "c", "r")
        assert result.context == [unknown_verdict_line("g", "c", "r")]

    def test_one_log_line_with_the_stable_prefix(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.INFO):
            unknown_verdict_allow("my_guard", "git timed out", "retry")
        records = [r for r in caplog.records if UNKNOWN_VERDICT_LOG_PREFIX in r.getMessage()]
        assert len(records) == 1
        assert records[0].getMessage().startswith("UNKNOWN-VERDICT my_guard git timed out")
        assert records[0].levelno == logging.WARNING

    @pytest.mark.parametrize("field", ["", "   "])
    def test_an_empty_field_fails_fast(self, field: str) -> None:
        with pytest.raises(ValueError):
            unknown_verdict_allow(field, "cause", "rephrase")
        with pytest.raises(ValueError):
            unknown_verdict_allow("guard", field, "rephrase")
        with pytest.raises(ValueError):
            unknown_verdict_allow("guard", "cause", field)
