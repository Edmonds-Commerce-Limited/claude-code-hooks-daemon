"""Tests for the named "log this failure and carry on" helper (owner ruling B4, N296)."""

from __future__ import annotations

import inspect
import logging

import pytest

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue


class TestLogAndContinue:
    """The helper logs the exception with its reason and returns."""

    def test_logs_reason_and_exception_at_warning_by_default(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        logger = logging.getLogger("test.swallow")
        exc = OSError("disk full")
        with caplog.at_level(logging.DEBUG, logger="test.swallow"):
            log_and_continue(logger, exc, reason="state persistence is best-effort")
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.WARNING
        assert "state persistence is best-effort" in record.getMessage()
        assert "disk full" in record.getMessage()
        assert record.exc_info is not None
        assert record.exc_info[1] is exc

    def test_level_is_selectable(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("test.swallow")
        with caplog.at_level(logging.DEBUG, logger="test.swallow"):
            log_and_continue(
                logger, ValueError("x"), reason="peer already hung up", level=logging.DEBUG
            )
        assert caplog.records[0].levelno == logging.DEBUG

    @pytest.mark.parametrize("reason", ["", "   ", "-->", "todo", "because", "n/a"])
    def test_unacceptable_reason_is_rejected(self, reason: str) -> None:
        with pytest.raises(ValueError, match="reason"):
            log_and_continue(logging.getLogger("test.swallow"), OSError("x"), reason=reason)

    def test_reason_is_a_required_keyword_only_parameter(self) -> None:
        parameter = inspect.signature(log_and_continue).parameters["reason"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty
