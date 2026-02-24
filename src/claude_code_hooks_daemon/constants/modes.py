"""Daemon mode constants - Single source of truth for mode identifiers and values.

This module defines the daemon operating modes and related constants.
Modes are runtime-mutable states that change how events are processed.

Usage:
    from claude_code_hooks_daemon.constants import DaemonMode, ModeConstant

    if mode == DaemonMode.UNATTENDED:
        # Block stop events unconditionally
"""

from enum import StrEnum


class DaemonMode(StrEnum):
    """Daemon operating modes.

    DEFAULT: Normal operation - handlers process events as configured.
    UNATTENDED: Blocks Stop events unconditionally to keep Claude working.
    """

    DEFAULT = "default"
    UNATTENDED = "unattended"


class ModeConstant:
    """Constants related to daemon modes.

    Centralises all mode-related strings and values to avoid magic strings.
    """

    # IPC action names
    ACTION_GET_MODE = "get_mode"
    ACTION_SET_MODE = "set_mode"

    # Config keys
    CONFIG_DEFAULT_MODE = "default_mode"

    # IPC request/response keys
    KEY_MODE = "mode"
    KEY_CUSTOM_MESSAGE = "custom_message"
    KEY_STATUS = "status"

    # Status values
    STATUS_CHANGED = "changed"
    STATUS_UNCHANGED = "unchanged"

    # Block reason for unattended mode
    UNATTENDED_BLOCK_REASON = (
        "UNATTENDED MODE: Continue working without stopping. "
        "Do not ask for confirmation. "
        "Proceed with all remaining tasks autonomously."
    )
