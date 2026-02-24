"""CLI acceptance test definitions for daemon CLI features.

Each CLI feature that warrants acceptance testing registers its tests here.
The PlaybookGenerator collects these and renders them in a dedicated
"CLI Feature Tests" section of the playbook.
"""

from __future__ import annotations

from claude_code_hooks_daemon.core.cli_acceptance_test import CliAcceptanceTest

# CLI base command prefix used in playbook instructions
_CLI_PREFIX = "$PYTHON -m claude_code_hooks_daemon.daemon.cli"


def get_cli_acceptance_tests() -> list[CliAcceptanceTest]:
    """Return all CLI acceptance tests.

    Returns:
        List of CliAcceptanceTest objects for all testable CLI features.
    """
    return [
        _restart_mode_advisory_non_default(),
        _restart_mode_advisory_default(),
    ]


def _restart_mode_advisory_non_default() -> CliAcceptanceTest:
    """Test: restart prints advisory when non-default mode was active."""
    return CliAcceptanceTest(
        title="Restart mode advisory (non-default mode)",
        description=(
            "When daemon restarts with a non-default mode active (e.g. unattended), "
            "it should print an advisory showing the lost mode and the exact "
            "command to restore it."
        ),
        command=f"{_CLI_PREFIX} restart",
        expected_stdout_patterns=[
            "Mode before restart",
            "unattended",
            "set-mode",
        ],
        expected_exit_code=0,
        setup_commands=[
            f"{_CLI_PREFIX} set-mode unattended -m 'acceptance test'",
        ],
        cleanup_commands=[
            f"{_CLI_PREFIX} set-mode default",
        ],
        safety_notes="Safe: only changes daemon mode, restored by cleanup",
    )


def _restart_mode_advisory_default() -> CliAcceptanceTest:
    """Test: restart prints no advisory when default mode was active."""
    return CliAcceptanceTest(
        title="Restart mode advisory (default mode - no output)",
        description=(
            "When daemon restarts with default mode active, no mode advisory "
            "should be printed. This is the common case and should be silent."
        ),
        command=f"{_CLI_PREFIX} restart",
        expected_stdout_patterns=[
            "Daemon started successfully|Daemon already running",
        ],
        expected_exit_code=0,
        setup_commands=[
            f"{_CLI_PREFIX} set-mode default",
        ],
        safety_notes="Safe: default mode, no state change",
    )
