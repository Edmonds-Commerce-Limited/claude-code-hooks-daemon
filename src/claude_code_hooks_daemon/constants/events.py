"""Event type identifier constants - Single source of truth for all event types.

This module defines the canonical identifiers for all hook event types.
Each event type has four name formats:
- enum_value: SCREAMING_SNAKE_CASE (Python enum value)
- config_key: snake_case (YAML config key)
- bash_key: kebab-case (bash script names)
- json_key: PascalCase (JSON protocol format)

Usage:
    from claude_code_hooks_daemon.constants import EventID

    # Use in event type matching
    if event_type == EventID.PRE_TOOL_USE.config_key:
        # Handle pre-tool-use event
        pass
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class EventIDMeta:
    """Metadata for an event type identifier.

    Attributes:
        enum_value: Python enum value (SCREAMING_SNAKE_CASE)
        config_key: YAML config key (snake_case)
        bash_key: Bash script name (kebab-case)
        json_key: JSON protocol format (PascalCase)
        can_block: True if Claude Code lets this event block/deny the action
            (from the hooks spec). Drives the response contract for handlers.
        category: Coarse grouping (tool/session/prompt/permission/stop/subagent/
            task/team/compaction/worktree/mcp/notification/display/instructions/
            file/config/status). Documentation + rollout batching only.
        wired: True when the daemon wires this event end-to-end (forwarder +
            settings registration + dispatch + schemas). False for catalogued-
            but-not-yet-wired events (Plan 00170 burn-down). Unwired events are
            excluded from the settings-registration requirement so the live
            hook_registration_checker does not demand a forwarder that does not
            exist yet.
    """

    enum_value: str
    config_key: str
    bash_key: str
    json_key: str
    can_block: bool = False
    category: str = ""
    wired: bool = True


class EventID:
    """Single source of truth for all event type identifiers.

    Each constant provides all four naming formats for an event type.
    Use these instead of hardcoding event type names anywhere in the codebase.
    """

    # -----------------------------------------------------------------------
    # Wired events: the daemon forwards, dispatches, and schema-validates these
    # end-to-end today.
    # -----------------------------------------------------------------------

    PRE_TOOL_USE = EventIDMeta(
        enum_value="PRE_TOOL_USE",
        config_key="pre_tool_use",
        bash_key="pre-tool-use",
        json_key="PreToolUse",
        can_block=True,
        category="tool",
    )

    POST_TOOL_USE = EventIDMeta(
        enum_value="POST_TOOL_USE",
        config_key="post_tool_use",
        bash_key="post-tool-use",
        json_key="PostToolUse",
        can_block=True,
        category="tool",
    )

    SESSION_START = EventIDMeta(
        enum_value="SESSION_START",
        config_key="session_start",
        bash_key="session-start",
        json_key="SessionStart",
        can_block=False,
        category="session",
    )

    SESSION_END = EventIDMeta(
        enum_value="SESSION_END",
        config_key="session_end",
        bash_key="session-end",
        json_key="SessionEnd",
        can_block=False,
        category="session",
    )

    STOP = EventIDMeta(
        enum_value="STOP",
        config_key="stop",
        bash_key="stop",
        json_key="Stop",
        can_block=True,
        category="stop",
    )

    SUBAGENT_STOP = EventIDMeta(
        enum_value="SUBAGENT_STOP",
        config_key="subagent_stop",
        bash_key="subagent-stop",
        json_key="SubagentStop",
        can_block=True,
        category="subagent",
    )

    USER_PROMPT_SUBMIT = EventIDMeta(
        enum_value="USER_PROMPT_SUBMIT",
        config_key="user_prompt_submit",
        bash_key="user-prompt-submit",
        json_key="UserPromptSubmit",
        can_block=True,
        category="prompt",
    )

    PRE_COMPACT = EventIDMeta(
        enum_value="PRE_COMPACT",
        config_key="pre_compact",
        bash_key="pre-compact",
        json_key="PreCompact",
        can_block=True,
        category="compaction",
    )

    NOTIFICATION = EventIDMeta(
        enum_value="NOTIFICATION",
        config_key="notification",
        bash_key="notification",
        json_key="Notification",
        can_block=False,
        category="notification",
    )

    PERMISSION_REQUEST = EventIDMeta(
        enum_value="PERMISSION_REQUEST",
        config_key="permission_request",
        bash_key="permission-request",
        json_key="PermissionRequest",
        can_block=True,
        category="permission",
    )

    STATUS_LINE = EventIDMeta(
        enum_value="STATUS_LINE",
        config_key="status_line",
        bash_key="status-line",
        json_key="StatusLine",
        can_block=False,
        category="status",
    )

    # -----------------------------------------------------------------------
    # Catalogued-but-not-yet-wired events (Plan 00170 burn-down, wired=False).
    # Present so the daemon KNOWS every Claude Code hook event exists and the
    # completeness gate can enforce coverage. As each is wired end-to-end, flip
    # wired=True and remove it from the test's EXPECTED_UNWIRED set in the same
    # change. Source of truth: https://code.claude.com/docs/en/hooks
    # -----------------------------------------------------------------------

    SETUP = EventIDMeta(
        enum_value="SETUP",
        config_key="setup",
        bash_key="setup",
        json_key="Setup",
        can_block=False,
        category="session",
        wired=False,
    )

    USER_PROMPT_EXPANSION = EventIDMeta(
        enum_value="USER_PROMPT_EXPANSION",
        config_key="user_prompt_expansion",
        bash_key="user-prompt-expansion",
        json_key="UserPromptExpansion",
        can_block=True,
        category="prompt",
        wired=False,
    )

    PERMISSION_DENIED = EventIDMeta(
        enum_value="PERMISSION_DENIED",
        config_key="permission_denied",
        bash_key="permission-denied",
        json_key="PermissionDenied",
        can_block=False,
        category="permission",
        wired=False,
    )

    POST_TOOL_USE_FAILURE = EventIDMeta(
        enum_value="POST_TOOL_USE_FAILURE",
        config_key="post_tool_use_failure",
        bash_key="post-tool-use-failure",
        json_key="PostToolUseFailure",
        can_block=True,
        category="tool",
        wired=False,
    )

    POST_TOOL_BATCH = EventIDMeta(
        enum_value="POST_TOOL_BATCH",
        config_key="post_tool_batch",
        bash_key="post-tool-batch",
        json_key="PostToolBatch",
        can_block=True,
        category="tool",
        wired=False,
    )

    MESSAGE_DISPLAY = EventIDMeta(
        enum_value="MESSAGE_DISPLAY",
        config_key="message_display",
        bash_key="message-display",
        json_key="MessageDisplay",
        can_block=False,
        category="display",
        wired=False,
    )

    SUBAGENT_START = EventIDMeta(
        enum_value="SUBAGENT_START",
        config_key="subagent_start",
        bash_key="subagent-start",
        json_key="SubagentStart",
        can_block=False,
        category="subagent",
        wired=False,
    )

    TASK_CREATED = EventIDMeta(
        enum_value="TASK_CREATED",
        config_key="task_created",
        bash_key="task-created",
        json_key="TaskCreated",
        can_block=True,
        category="task",
        wired=False,
    )

    TASK_COMPLETED = EventIDMeta(
        enum_value="TASK_COMPLETED",
        config_key="task_completed",
        bash_key="task-completed",
        json_key="TaskCompleted",
        can_block=True,
        category="task",
        wired=False,
    )

    STOP_FAILURE = EventIDMeta(
        enum_value="STOP_FAILURE",
        config_key="stop_failure",
        bash_key="stop-failure",
        json_key="StopFailure",
        can_block=False,
        category="stop",
        wired=False,
    )

    TEAMMATE_IDLE = EventIDMeta(
        enum_value="TEAMMATE_IDLE",
        config_key="teammate_idle",
        bash_key="teammate-idle",
        json_key="TeammateIdle",
        can_block=True,
        category="team",
        wired=False,
    )

    INSTRUCTIONS_LOADED = EventIDMeta(
        enum_value="INSTRUCTIONS_LOADED",
        config_key="instructions_loaded",
        bash_key="instructions-loaded",
        json_key="InstructionsLoaded",
        can_block=False,
        category="instructions",
        wired=False,
    )

    CONFIG_CHANGE = EventIDMeta(
        enum_value="CONFIG_CHANGE",
        config_key="config_change",
        bash_key="config-change",
        json_key="ConfigChange",
        can_block=True,
        category="config",
        wired=False,
    )

    CWD_CHANGED = EventIDMeta(
        enum_value="CWD_CHANGED",
        config_key="cwd_changed",
        bash_key="cwd-changed",
        json_key="CwdChanged",
        can_block=False,
        category="session",
        wired=False,
    )

    FILE_CHANGED = EventIDMeta(
        enum_value="FILE_CHANGED",
        config_key="file_changed",
        bash_key="file-changed",
        json_key="FileChanged",
        can_block=False,
        category="file",
        wired=False,
    )

    WORKTREE_CREATE = EventIDMeta(
        enum_value="WORKTREE_CREATE",
        config_key="worktree_create",
        bash_key="worktree-create",
        json_key="WorktreeCreate",
        can_block=True,
        category="worktree",
        wired=False,
    )

    WORKTREE_REMOVE = EventIDMeta(
        enum_value="WORKTREE_REMOVE",
        config_key="worktree_remove",
        bash_key="worktree-remove",
        json_key="WorktreeRemove",
        can_block=False,
        category="worktree",
        wired=False,
    )

    POST_COMPACT = EventIDMeta(
        enum_value="POST_COMPACT",
        config_key="post_compact",
        bash_key="post-compact",
        json_key="PostCompact",
        can_block=False,
        category="compaction",
        wired=False,
    )

    ELICITATION = EventIDMeta(
        enum_value="ELICITATION",
        config_key="elicitation",
        bash_key="elicitation",
        json_key="Elicitation",
        can_block=True,
        category="mcp",
        wired=False,
    )

    ELICITATION_RESULT = EventIDMeta(
        enum_value="ELICITATION_RESULT",
        config_key="elicitation_result",
        bash_key="elicitation-result",
        json_key="ElicitationResult",
        can_block=True,
        category="mcp",
        wired=False,
    )


def all_event_metas() -> tuple[EventIDMeta, ...]:
    """Return every :class:`EventIDMeta` declared on :class:`EventID`.

    Order follows declaration order because a class ``__dict__`` (``vars``) is
    insertion-ordered on Python 3.7+. This is the single reflection point the
    rest of the codebase builds on (config validation, schema registries,
    hook-registration, the completeness gate) so those surfaces can never drift
    from the catalogue.
    """
    return tuple(v for v in vars(EventID).values() if isinstance(v, EventIDMeta))


def wired_event_metas() -> tuple[EventIDMeta, ...]:
    """Return the events the daemon wires end-to-end today (``wired=True``).

    Catalogued-but-not-yet-wired events (Plan 00170 burn-down) are excluded so
    derived requirement sets never demand a forwarder / settings entry / schema
    for a hook that deliberately does not exist yet.
    """
    return tuple(m for m in all_event_metas() if m.wired)


# Type-safe event key literal (for mypy/type checking)
EventKey = Literal[
    "pre_tool_use",
    "post_tool_use",
    "session_start",
    "session_end",
    "stop",
    "subagent_stop",
    "user_prompt_submit",
    "pre_compact",
    "notification",
    "permission_request",
    "status_line",
]
