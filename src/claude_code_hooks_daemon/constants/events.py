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
from enum import StrEnum
from typing import Final, Literal


class EventType(StrEnum):
    """Supported Claude Code hook event types — the WIRE protocol values.

    Lives here (not ``core.event``) so the event-identifier catalogue below
    can type its wire name against it without an import cycle; ``core.event``
    re-exports it for its historical import path. These are the exact strings
    the daemon's ``HookEvent`` model accepts on the socket — note
    ``STATUS_LINE = "Status"``, which differs from the meta's PascalCase
    ``json_key`` (``StatusLine``): the wire name is the ONLY safe value to
    put in a request envelope's ``event`` field.
    """

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    PRE_COMPACT = "PreCompact"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PERMISSION_REQUEST = "PermissionRequest"
    NOTIFICATION = "Notification"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"
    STATUS_LINE = "Status"
    # Plan 00170: events wired for zero-handler passthrough (no built-in handler
    # yet — client projects may attach handlers). Kept in lockstep with the
    # wired EventID catalogue by test_hook_coverage_completeness.
    SETUP = "Setup"
    PERMISSION_DENIED = "PermissionDenied"
    CWD_CHANGED = "CwdChanged"
    WORKTREE_CREATE = "WorktreeCreate"
    WORKTREE_REMOVE = "WorktreeRemove"
    USER_PROMPT_EXPANSION = "UserPromptExpansion"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    POST_TOOL_BATCH = "PostToolBatch"
    SUBAGENT_START = "SubagentStart"
    TASK_CREATED = "TaskCreated"
    TASK_COMPLETED = "TaskCompleted"
    STOP_FAILURE = "StopFailure"
    TEAMMATE_IDLE = "TeammateIdle"
    INSTRUCTIONS_LOADED = "InstructionsLoaded"
    CONFIG_CHANGE = "ConfigChange"
    FILE_CHANGED = "FileChanged"
    POST_COMPACT = "PostCompact"
    ELICITATION = "Elicitation"
    ELICITATION_RESULT = "ElicitationResult"
    MESSAGE_DISPLAY = "MessageDisplay"

    @classmethod
    def from_string(cls, value: str) -> "EventType":
        """Convert string to EventType, case-insensitive.

        Args:
            value: Event type string (e.g., "PreToolUse", "pre_tool_use", "status_line")

        Returns:
            Matching EventType enum member

        Raises:
            ValueError: If no matching event type found
        """
        # Try exact match first
        for member in cls:
            if member.value == value:
                return member

        # Handle special case: "status_line" -> "Status"
        if value.lower() in ("status_line", "statusline"):
            return cls.STATUS_LINE

        # Try snake_case conversion
        normalised = value.lower().replace("_", "")
        for member in cls:
            if member.value.lower().replace("_", "") == normalised:
                return member

        valid_types = ", ".join(m.value for m in cls)
        raise ValueError(f"Unknown event type: {value}. Valid types: {valid_types}")


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
        raw_stdout: True when Claude Code parses this hook's stdout as a RAW
            VALUE (e.g. a path or text) rather than a JSON decision object. For
            such events an empty ``{}`` passthrough is taken literally and
            CORRUPTS the feature (Plan 00188: WorktreeCreate ``{}`` -> the path
            ``/<cwd>/{}``), so a raw_stdout event MUST ship a built-in default
            handler — it can never be a bare fail-open passthrough. Decision /
            context / observe events (the vast majority) are False: ``{}`` is
            their correct "no opinion" response.
    """

    enum_value: str
    config_key: str
    bash_key: str
    json_key: str
    can_block: bool = False
    category: str = ""
    wired: bool = True
    raw_stdout: bool = False

    @property
    def wire_key(self) -> EventType:
        """The typed WIRE protocol event name for this event.

        This is the only value safe to put in a request envelope's ``event``
        field. It is usually identical to ``json_key``, but NOT always —
        ``STATUS_LINE`` has ``json_key="StatusLine"`` while the wire value is
        ``"Status"``, and a consumer that trusts ``json_key`` as the wire
        name fails ``HookEvent`` validation on every status-line request.
        Returning the ``EventType`` MEMBER (not a str) makes the invariant
        type-checked at every consumer: an event whose name cannot resolve
        raises here, at the source, instead of as a stream of
        invalid_request warnings at runtime.
        """
        return EventType.from_string(self.json_key)


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
        # The status line is raw text on stdout — the daemon ships status_line
        # handlers that render it (never a bare {} passthrough).
        raw_stdout=True,
    )

    # -----------------------------------------------------------------------
    # Events catalogued by Plan 00170. As of the Phase 3 burn-down these are ALL
    # wired end-to-end (forwarder + settings + dispatch + schemas), same as the
    # block above — the daemon ships no built-in handler for them, but every one
    # is a fail-open passthrough a client project can attach a handler to. A
    # newly discovered Claude Code event is added here; if it cannot be wired in
    # the same change, set wired=False AND add its json_key to the completeness
    # test's EXPECTED_UNWIRED so the gap is tracked, never silent.
    # Source of truth: https://code.claude.com/docs/en/hooks
    # -----------------------------------------------------------------------

    SETUP = EventIDMeta(
        enum_value="SETUP",
        config_key="setup",
        bash_key="setup",
        json_key="Setup",
        can_block=False,
        category="session",
    )

    USER_PROMPT_EXPANSION = EventIDMeta(
        enum_value="USER_PROMPT_EXPANSION",
        config_key="user_prompt_expansion",
        bash_key="user-prompt-expansion",
        json_key="UserPromptExpansion",
        can_block=True,
        category="prompt",
    )

    PERMISSION_DENIED = EventIDMeta(
        enum_value="PERMISSION_DENIED",
        config_key="permission_denied",
        bash_key="permission-denied",
        json_key="PermissionDenied",
        can_block=False,
        category="permission",
    )

    POST_TOOL_USE_FAILURE = EventIDMeta(
        enum_value="POST_TOOL_USE_FAILURE",
        config_key="post_tool_use_failure",
        bash_key="post-tool-use-failure",
        json_key="PostToolUseFailure",
        can_block=True,
        category="tool",
    )

    POST_TOOL_BATCH = EventIDMeta(
        enum_value="POST_TOOL_BATCH",
        config_key="post_tool_batch",
        bash_key="post-tool-batch",
        json_key="PostToolBatch",
        can_block=True,
        category="tool",
    )

    MESSAGE_DISPLAY = EventIDMeta(
        enum_value="MESSAGE_DISPLAY",
        config_key="message_display",
        bash_key="message-display",
        json_key="MessageDisplay",
        can_block=False,
        category="display",
    )

    SUBAGENT_START = EventIDMeta(
        enum_value="SUBAGENT_START",
        config_key="subagent_start",
        bash_key="subagent-start",
        json_key="SubagentStart",
        can_block=False,
        category="subagent",
    )

    TASK_CREATED = EventIDMeta(
        enum_value="TASK_CREATED",
        config_key="task_created",
        bash_key="task-created",
        json_key="TaskCreated",
        can_block=True,
        category="task",
    )

    TASK_COMPLETED = EventIDMeta(
        enum_value="TASK_COMPLETED",
        config_key="task_completed",
        bash_key="task-completed",
        json_key="TaskCompleted",
        can_block=True,
        category="task",
    )

    STOP_FAILURE = EventIDMeta(
        enum_value="STOP_FAILURE",
        config_key="stop_failure",
        bash_key="stop-failure",
        json_key="StopFailure",
        can_block=False,
        category="stop",
    )

    TEAMMATE_IDLE = EventIDMeta(
        enum_value="TEAMMATE_IDLE",
        config_key="teammate_idle",
        bash_key="teammate-idle",
        json_key="TeammateIdle",
        can_block=True,
        category="team",
    )

    INSTRUCTIONS_LOADED = EventIDMeta(
        enum_value="INSTRUCTIONS_LOADED",
        config_key="instructions_loaded",
        bash_key="instructions-loaded",
        json_key="InstructionsLoaded",
        can_block=False,
        category="instructions",
    )

    CONFIG_CHANGE = EventIDMeta(
        enum_value="CONFIG_CHANGE",
        config_key="config_change",
        bash_key="config-change",
        json_key="ConfigChange",
        can_block=True,
        category="config",
    )

    CWD_CHANGED = EventIDMeta(
        enum_value="CWD_CHANGED",
        config_key="cwd_changed",
        bash_key="cwd-changed",
        json_key="CwdChanged",
        can_block=False,
        category="session",
    )

    DIRECTORY_ADDED = EventIDMeta(
        enum_value="DIRECTORY_ADDED",
        config_key="directory_added",
        bash_key="directory-added",
        json_key="DirectoryAdded",
        can_block=False,
        category="session",
        # Documented (fires after /add-dir or an SDK register_repo_root) but
        # not yet wired end-to-end; tracked in EXPECTED_UNWIRED per this
        # file's tracked-gap rule (Plan 00271 audit item 8).
        wired=False,
    )

    FILE_CHANGED = EventIDMeta(
        enum_value="FILE_CHANGED",
        config_key="file_changed",
        bash_key="file-changed",
        json_key="FileChanged",
        can_block=False,
        category="file",
    )

    WORKTREE_CREATE = EventIDMeta(
        enum_value="WORKTREE_CREATE",
        config_key="worktree_create",
        bash_key="worktree-create",
        json_key="WorktreeCreate",
        can_block=True,
        category="worktree",
        # Claude Code parses stdout as the created worktree PATH — {} corrupts it
        # (Plan 00188). Ships a built-in WorktreeCreateHandler, never a passthrough.
        raw_stdout=True,
    )

    WORKTREE_REMOVE = EventIDMeta(
        enum_value="WORKTREE_REMOVE",
        config_key="worktree_remove",
        bash_key="worktree-remove",
        json_key="WorktreeRemove",
        can_block=False,
        category="worktree",
    )

    POST_COMPACT = EventIDMeta(
        enum_value="POST_COMPACT",
        config_key="post_compact",
        bash_key="post-compact",
        json_key="PostCompact",
        can_block=False,
        category="compaction",
    )

    ELICITATION = EventIDMeta(
        enum_value="ELICITATION",
        config_key="elicitation",
        bash_key="elicitation",
        json_key="Elicitation",
        can_block=True,
        category="mcp",
    )

    ELICITATION_RESULT = EventIDMeta(
        enum_value="ELICITATION_RESULT",
        config_key="elicitation_result",
        bash_key="elicitation-result",
        json_key="ElicitationResult",
        can_block=True,
        category="mcp",
    )


# StatusLine dual-naming — the single source of truth shared by the input and
# response schema builders. Its catalogue json_key is "StatusLine", but its
# schema / EventType / settings key is "Status"; both schema modules used to
# define their own private copies of this pair (Plan 00171 de-dup).
STATUS_LINE_JSON_KEY: Final[str] = EventID.STATUS_LINE.json_key
STATUS_SCHEMA_KEY: Final[str] = "Status"


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


# Type-safe event key literal (for mypy/type checking).
#
# This MUST list the ``config_key`` of every event in the ``EventID`` catalogue
# above, in the same declaration order. A ``Literal`` cannot be built from
# ``all_event_metas()`` at type-check time (mypy needs static members), so the
# two are kept in lockstep by ``test_event_key_literal_matches_catalogue`` —
# adding an event to ``EventID`` without extending this literal fails that test.
EventKey = Literal[
    # Wired-from-the-start events.
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
    # Plan 00170 catalogued events.
    "setup",
    "user_prompt_expansion",
    "permission_denied",
    "post_tool_use_failure",
    "post_tool_batch",
    "message_display",
    "subagent_start",
    "task_created",
    "task_completed",
    "stop_failure",
    "teammate_idle",
    "instructions_loaded",
    "config_change",
    "cwd_changed",
    "directory_added",
    "file_changed",
    "worktree_create",
    "worktree_remove",
    "post_compact",
    "elicitation",
    "elicitation_result",
]
