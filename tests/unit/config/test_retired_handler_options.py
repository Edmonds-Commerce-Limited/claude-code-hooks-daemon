"""A config still setting a retired handler option loads, and the dead key is named.

Plan 00501 Task 2.2 removed two options when the awaiting-human marker moved to
the session-modes registry: ``expiry_hours`` (failsafe_cron_blockage_suppressor)
and ``marker_expiry_hours`` (idle_workable_issue_stop_gate). A client's config
is their file, so it must keep loading (the Plan 00503 precedent for a removed
guard); the key does nothing now, so it is never silently ignored either.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from claude_code_hooks_daemon.config.validator import ConfigValidator as StartupValidator
from claude_code_hooks_daemon.constants.handlers import RETIRED_HANDLER_OPTIONS
from claude_code_hooks_daemon.install.config_validator import ConfigValidator

_SUPPRESSOR_PATH = (
    "handlers.user_prompt_submit.failsafe_cron_blockage_suppressor.options.expiry_hours"
)
_IDLE_GATE_PATH = "handlers.stop.idle_workable_issue_stop_gate.options.marker_expiry_hours"


def _config_with_retired_options() -> dict[str, Any]:
    return {
        "version": "1.0",
        "daemon": {"idle_timeout_seconds": 600, "log_level": "INFO"},
        "handlers": {
            "user_prompt_submit": {
                "failsafe_cron_blockage_suppressor": {
                    "enabled": True,
                    "options": {"expiry_hours": 24},
                }
            },
            "stop": {
                "idle_workable_issue_stop_gate": {
                    "enabled": True,
                    "options": {"marker_expiry_hours": 12, "job_id": "issue-sdlc"},
                }
            },
        },
    }


def test_both_removed_options_are_registered_as_retired() -> None:
    assert "expiry_hours" in RETIRED_HANDLER_OPTIONS["failsafe_cron_blockage_suppressor"]
    assert "marker_expiry_hours" in RETIRED_HANDLER_OPTIONS["idle_workable_issue_stop_gate"]


def test_the_startup_validator_accepts_the_config_and_warns_naming_each_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        errors = StartupValidator.validate(
            _config_with_retired_options(), validate_handler_names=False
        )
    assert errors == []
    assert _SUPPRESSOR_PATH in caplog.text
    assert _IDLE_GATE_PATH in caplog.text


def test_config_validate_is_valid_with_a_warning_naming_each_key() -> None:
    result = ConfigValidator().validate(_config_with_retired_options())
    assert result.valid is True
    assert any(_SUPPRESSOR_PATH in warning for warning in result.warnings)
    assert any(_IDLE_GATE_PATH in warning for warning in result.warnings)


def test_the_warning_says_the_key_does_nothing_and_points_at_the_session_mode() -> None:
    messages = StartupValidator.retired_option_messages(_config_with_retired_options())
    assert len(messages) == 2
    for message in messages:
        assert "no effect" in message
        assert "session mode" in message


def test_a_live_option_is_not_reported() -> None:
    config = _config_with_retired_options()
    config["handlers"]["user_prompt_submit"]["failsafe_cron_blockage_suppressor"]["options"] = {}
    messages = StartupValidator.retired_option_messages(config)
    assert all("job_id" not in message for message in messages)
    assert len(messages) == 1


def test_a_config_without_handlers_reports_nothing() -> None:
    assert StartupValidator.retired_option_messages({}) == []
    assert StartupValidator.retired_option_messages({"handlers": {"stop": None}}) == []
