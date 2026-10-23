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


class SessionModeIPC:
    """The per-session mode IPC actions and their fields (Plan 00501 Task 3.3).

    Separate from :class:`ModeConstant`: those actions get and set the
    daemon-wide mode and stay unchanged; these read and change ONE session's
    session modes (the ``hooks-daemon session-mode`` CLI and ``/mode focus``).
    """

    ACTION_GET_SESSION_MODES = "get_session_modes"
    ACTION_ENTER_FOCUS = "enter_focus"
    ACTION_EXIT_FOCUS = "exit_focus"
    #: Every session's live modes and the recent transitions (Task 4.3).
    ACTION_GET_MODE_HISTORY = "get_mode_history"
    #: End a goal-loop (detector) block; a declared awaiting-human block is refused (Task 6.3).
    ACTION_EXIT_BLOCKED = "exit_blocked"
    ACTIONS = frozenset(
        {
            ACTION_GET_SESSION_MODES,
            ACTION_ENTER_FOCUS,
            ACTION_EXIT_FOCUS,
            ACTION_GET_MODE_HISTORY,
            ACTION_EXIT_BLOCKED,
        }
    )

    KEY_LIMIT = "limit"
    KEY_SESSIONS = "sessions"
    KEY_TRANSITIONS = "transitions"
    #: Transitions ``mode-history`` shows when no limit is given.
    DEFAULT_HISTORY_LIMIT = 20

    KEY_SESSION_ID = "session_id"
    KEY_TASK = "task"
    KEY_MODES = "modes"
    KEY_BADGE = "badge"
    KEY_OUTCOME = "outcome"
    KEY_LINE = "line"
    KEY_LABEL = "label"
    KEY_MODE = "mode"
    KEY_REASON = "reason"
    KEY_SOURCE = "source"
    KEY_DETAIL = "detail"
    KEY_ENTERED_AT = "entered_at"
    KEY_EXPIRES_AT = "expires_at"

    #: Words that end focus when they are the whole argument; the prompt
    #: command, the CLI and the ``/mode`` skill all read this one set.
    FOCUS_OFF_ALIASES = frozenset({"off", "done", "end", "disable"})


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
