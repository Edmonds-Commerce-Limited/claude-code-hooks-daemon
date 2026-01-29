"""Formatting constant values - single source of truth.

This module defines constants used for formatting, truncation, and display
throughout the daemon (hash lengths, string truncation, padding, etc.).

Usage:
    from claude_code_hooks_daemon.constants import FormatLimit

    # Truncate hash:
    short_hash = full_hash[:FormatLimit.HASH_LENGTH]

    # Truncate project name:
    display_name = project_name[:FormatLimit.PROJECT_NAME_MAX]
"""

from __future__ import annotations


class FormatLimit:
    """Formatting and display limits - single source of truth.

    These constants define formatting boundaries for display strings,
    truncation limits, padding widths, and other presentation-related values.

    Categories:
        - Hash display: Git commit hash truncation
        - Name truncation: Project names, handler names, etc.
        - Preview lengths: Reason previews, context snippets
        - Display widths: Terminal width assumptions, column widths
    """

    # Hash display lengths
    HASH_LENGTH = 8  # Git short hash (first 8 chars)
    HASH_LENGTH_FULL = 40  # Git full SHA-1 hash

    # Name truncation limits
    PROJECT_NAME_MAX = 20  # Max project name length in displays
    HANDLER_NAME_MAX_DISPLAY = 30  # Max handler name in status displays
    SESSION_ID_DISPLAY = 8  # Session ID truncation for logs

    # Preview and snippet lengths
    REASON_PREVIEW_LENGTH = 50  # Max reason text in logs
    CONTEXT_PREVIEW_LENGTH = 100  # Max context preview in displays
    ERROR_MESSAGE_PREVIEW = 200  # Max error message in logs
    TOOL_INPUT_PREVIEW = 150  # Max tool input preview in logs

    # Display width assumptions
    TERMINAL_WIDTH_DEFAULT = 80  # Default terminal width
    TERMINAL_WIDTH_WIDE = 120  # Wide terminal width
    STATUS_LINE_MAX_WIDTH = 100  # Max status line text width

    # Column widths for tabular displays
    COLUMN_HANDLER_NAME = 30
    COLUMN_PRIORITY = 8
    COLUMN_STATUS = 10
    COLUMN_TAGS = 40

    # Padding and alignment
    INDENT_SPACES = 2  # Number of spaces for indentation
    LIST_INDENT = 4  # Indentation for list items

    # Number formatting
    DURATION_PRECISION = 2  # Decimal places for duration displays
    PERCENTAGE_PRECISION = 1  # Decimal places for percentage displays


__all__ = ["FormatLimit"]
