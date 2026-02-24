"""CLI acceptance test definitions.

This module provides the CliAcceptanceTest dataclass for defining acceptance
tests for CLI-level features (not hook handlers). CLI tests verify daemon
CLI commands like restart, repair, mode management, etc.

Unlike handler AcceptanceTests which test hook event processing,
CLI tests verify command-line behaviour: stdout output, exit codes,
and side effects.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CliAcceptanceTest:
    """Defines a single acceptance test for a CLI feature.

    CLI acceptance tests verify daemon CLI commands produce expected
    stdout output and exit codes. They appear in a dedicated section
    of the acceptance test playbook.

    Attributes:
        title: Short descriptive title for the test
        description: Detailed description of what's being tested
        command: The CLI command to execute (relative to daemon CLI)
        expected_stdout_patterns: Regex patterns to match in stdout
        expected_exit_code: Expected process exit code (default 0)
        setup_commands: Commands to run before the test
        cleanup_commands: Commands to run after the test
        safety_notes: Explanation of why the test is safe to execute
    """

    title: str
    description: str
    command: str
    expected_stdout_patterns: list[str]
    expected_exit_code: int = 0
    setup_commands: list[str] | None = None
    cleanup_commands: list[str] | None = None
    safety_notes: str | None = None

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        if not self.title or not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if not self.command or not self.command.strip():
            raise ValueError("command must be a non-empty string")
        if not self.description or not self.description.strip():
            raise ValueError("description must be a non-empty string")
