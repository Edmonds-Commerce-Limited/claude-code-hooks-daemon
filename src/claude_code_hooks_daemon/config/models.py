"""Pydantic configuration models for the hooks daemon.

This module provides strongly-typed configuration models with
validation, serialisation, and sensible defaults.
"""

import logging
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from claude_code_hooks_daemon.constants import wired_event_metas
from claude_code_hooks_daemon.utils.repo_relative_path import (
    normalise_repo_relative_path as _normalise_repo_relative_path,
)

logger = logging.getLogger(__name__)

# Single source of truth for the hook event-type config keys handled by the
# daemon, derived from the WIRED EventID entries (constants/events.py). Used by
# HandlersConfig's dependency-validation loop so the iterated event list cannot
# drift from the declared event-type fields (Finding #30, DRY-SSoT). Deriving
# from wired_event_metas() means a newly-wired event (Plan 00170) is accepted as
# a config section automatically — no edit here.
_EVENT_TYPE_CONFIG_KEYS: tuple[str, ...] = tuple(meta.config_key for meta in wired_event_metas())


class LogLevel(StrEnum):
    """Log level options."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class HandlerConfig(BaseModel):
    """Configuration for an individual handler.

    Attributes:
        enabled: Whether the handler is enabled
        priority: Override priority (None uses handler default)
        options: Handler-specific options (e.g., track_plans_in_project, plan_workflow_docs)
    """

    model_config = ConfigDict(extra="forbid")  # CRITICAL: No arbitrary fields allowed!

    enabled: bool = Field(default=True, description="Whether handler is enabled")
    priority: int | None = Field(default=None, description="Override priority")
    options: dict[str, Any] = Field(default_factory=dict, description="Handler-specific options")

    @field_validator("options", mode="before")
    @classmethod
    def normalise_null_options(cls, v: dict[str, Any] | None) -> dict[str, Any]:
        """Treat a null `options:` as empty, not a schema error.

        A comments-only `options:` YAML block (all lines are `#`-comments)
        parses to `None`, not `{}` -- that is legal YAML, not a malformed
        config, so it must not hard-fail startup (Plan 00304).
        """
        if v is None:
            return {}
        return v


class EventHandlersConfig(BaseModel):
    """Configuration for handlers of a specific event type.

    Attributes are handler names with their configurations.
    """

    model_config = ConfigDict(extra="allow")

    def get_handler(self, name: str) -> HandlerConfig:
        """Get configuration for a specific handler.

        Args:
            name: Handler name (snake_case)

        Returns:
            Handler configuration (defaults if not specified)
        """
        value = getattr(self, name, None)
        if value is None:
            return HandlerConfig()
        if isinstance(value, dict):
            return HandlerConfig.model_validate(value)
        if isinstance(value, HandlerConfig):
            return value
        return HandlerConfig()


class HandlersConfig(BaseModel):
    """Configuration for all handler event types.

    Each event type configuration can include:
    - enable_tags: List of tags to enable (only handlers with these tags will run)
    - disable_tags: List of tags to disable (handlers with these tags won't run)
    - Individual handler configs by name
    """

    model_config = ConfigDict(extra="allow")

    pre_tool_use: dict[str, Any] = Field(default_factory=dict)
    post_tool_use: dict[str, Any] = Field(default_factory=dict)
    session_start: dict[str, Any] = Field(default_factory=dict)
    session_end: dict[str, Any] = Field(default_factory=dict)
    pre_compact: dict[str, Any] = Field(default_factory=dict)
    user_prompt_submit: dict[str, Any] = Field(default_factory=dict)
    permission_request: dict[str, Any] = Field(default_factory=dict)
    notification: dict[str, Any] = Field(default_factory=dict)
    stop: dict[str, Any] = Field(default_factory=dict)
    subagent_stop: dict[str, Any] = Field(default_factory=dict)
    status_line: dict[str, Any] = Field(default_factory=dict)
    # Worktree lifecycle events with built-in handlers (Plan 00188). Declared so
    # _build_handler_config_mapping covers them and handlers.worktree_*.enabled
    # is honoured (an undeclared field would silently fall back to enabled=True).
    worktree_create: dict[str, Any] = Field(default_factory=dict)
    worktree_remove: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_handler_dependencies(self) -> Self:
        """Validate handler dependencies (shares_options_with relationships).

        Ensures that if a child handler is enabled and shares options with a parent,
        the parent handler must also be enabled.

        Returns:
            Self for method chaining

        Raises:
            ValueError: If child handler is enabled but parent is disabled
        """
        # Import here to avoid circular dependency
        import re

        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

        def _to_snake_case(name: str) -> str:
            """Convert class name to snake_case config key."""
            s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
            return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower().removesuffix("_handler")

        # Discover all handlers to check their shares_options_with attribute
        registry = HandlerRegistry()
        registry.discover()

        # Get all discovered handler classes (flat dict keyed by class name)
        all_handlers = registry._handlers

        # Check each event type (SSoT: derived from EventID, includes status_line)
        for event_type in _EVENT_TYPE_CONFIG_KEYS:
            event_config = getattr(self, event_type, {})
            if not isinstance(event_config, dict):
                continue

            # Check all handlers to see if they belong to this event type
            # We check by instantiating and seeing if they're configured for this event
            for handler_cls in all_handlers.values():
                # Convert class name to config key (snake_case)
                config_key = _to_snake_case(handler_cls.__name__)

                # Get config for this handler in this event type
                handler_config = event_config.get(config_key)
                if handler_config is None:
                    # Handler not configured for this event type
                    continue

                # Check if handler is enabled
                if isinstance(handler_config, HandlerConfig):
                    is_enabled = handler_config.enabled
                elif isinstance(handler_config, dict):
                    is_enabled = handler_config.get("enabled", True)
                else:
                    is_enabled = True

                # If enabled, check if it has parent dependency
                if is_enabled:
                    # Instantiate to check shares_options_with attribute
                    try:
                        handler_instance = handler_cls()
                    except Exception as e:
                        # Some handlers require runtime context (ProjectContext, etc.)
                        # Skip validation for these handlers
                        logger.debug(
                            f"Could not instantiate handler '{config_key}' for validation: {e}"
                        )
                        continue

                    if handler_instance.shares_options_with:
                        parent_key = handler_instance.shares_options_with
                        parent_config = event_config.get(parent_key)

                        # Determine if parent is enabled
                        parent_enabled = True  # Default is enabled
                        if isinstance(parent_config, HandlerConfig):
                            parent_enabled = parent_config.enabled
                        elif isinstance(parent_config, dict):
                            parent_enabled = parent_config.get("enabled", True)
                        elif parent_config is None:
                            parent_enabled = True  # Not in config = use defaults (enabled)

                        if not parent_enabled:
                            raise ValueError(
                                f"Configuration error in '{event_type}' handlers:\n"
                                f"  Handler '{config_key}' requires '{parent_key}' to be enabled.\n"
                                f"  Reason: '{config_key}' shares configuration options with '{parent_key}'.\n"
                                f"\n"
                                f"To fix this issue, choose one of:\n"
                                f"  1. Enable the parent handler '{parent_key}'\n"
                                f"  2. Disable the dependent handler '{config_key}'\n"
                                f"\n"
                                f"Example configuration:\n"
                                f"  {event_type}:\n"
                                f"    {parent_key}:\n"
                                f"      enabled: true\n"
                                f"    {config_key}:\n"
                                f"      enabled: true"
                            )

        return self

    @field_validator("*", mode="before")
    @classmethod
    def coerce_handler_configs(cls, v: dict[str, Any] | None) -> dict[str, Any]:
        """Coerce raw dicts to HandlerConfig instances, preserving tag filter keys.

        Special keys 'enable_tags' and 'disable_tags' are preserved as-is.
        Other keys are converted to HandlerConfig instances.
        """
        if v is None:
            return {}
        result: dict[str, Any] = {}
        for name, config in v.items():
            # Preserve tag filter keys as-is
            if name in ("enable_tags", "disable_tags") or isinstance(config, HandlerConfig):
                result[name] = config
            elif isinstance(config, dict):
                result[name] = HandlerConfig.model_validate(config)
            else:
                result[name] = HandlerConfig()
        return result

    def get_enable_tags(self, event_type: str) -> list[str] | None:
        """Get enable_tags for a specific event type.

        Args:
            event_type: Event type (e.g., 'pre_tool_use')

        Returns:
            List of tags to enable, or None if not specified
        """
        event_config = getattr(self, event_type, {})
        return event_config.get("enable_tags")

    def get_disable_tags(self, event_type: str) -> list[str]:
        """Get disable_tags for a specific event type.

        Args:
            event_type: Event type (e.g., 'pre_tool_use')

        Returns:
            List of tags to disable (empty list if not specified)
        """
        event_config = getattr(self, event_type, {})
        result: list[str] = event_config.get("disable_tags", [])
        return result

    def get_handler_config(self, event_type: str, handler_name: str) -> HandlerConfig:
        """Get configuration for a specific handler.

        Args:
            event_type: Event type (e.g., 'pre_tool_use')
            handler_name: Handler name (snake_case)

        Returns:
            Handler configuration (defaults if not specified)
        """
        event_config = getattr(self, event_type, {})
        handler_config = event_config.get(handler_name)
        if handler_config is None or handler_name in ("enable_tags", "disable_tags"):
            return HandlerConfig()
        if isinstance(handler_config, HandlerConfig):
            return handler_config
        if isinstance(handler_config, dict):
            return HandlerConfig.model_validate(handler_config)
        return HandlerConfig()


class PluginConfig(BaseModel):
    """Configuration for a plugin.

    Attributes:
        path: Path to plugin module or package
        event_type: Event type this plugin handles
        handlers: List of handler class names to load (None = all)
        enabled: Whether the plugin is enabled
    """

    model_config = ConfigDict(extra="allow")

    path: str = Field(
        description=(
            "Path to plugin module or package. EXEMPT from the "
            "repository-relative rule (Plan 00303): a plugin loads external "
            "code that may legitimately live outside the repository -- the "
            "same category as TransportConfig.relay_binary -- and the "
            "loader's absolute-path resolution is an explicitly tested "
            "feature (tests/unit/test_plugin_loader.py). A leading "
            "{REPO_ROOT} token (Plan 00302 extension) expands against the "
            "project root at load time -- the portable alternative to a "
            "genuine absolute path when the plugin ships inside the repo."
        )
    )
    event_type: Literal[
        "pre_tool_use",
        "post_tool_use",
        "session_start",
        "session_end",
        "pre_compact",
        "user_prompt_submit",
        "permission_request",
        "notification",
        "stop",
        "subagent_stop",
        "status_line",
    ] = Field(description="Event type this plugin handles")
    handlers: list[str] | None = Field(default=None, description="Handler classes to load")
    enabled: bool = Field(default=True, description="Whether plugin is enabled")


class PluginsConfig(BaseModel):
    """Configuration for the plugin system.

    Attributes:
        paths: Additional paths to search for plugins. EXEMPT from the
            repository-relative rule for the same reason as
            ``PluginConfig.path`` -- see that field's docstring. Also
            supports the ``{REPO_ROOT}`` token.
        plugins: List of plugin configurations
    """

    model_config = ConfigDict(extra="allow")

    paths: list[str] = Field(default_factory=list, description="Plugin search paths")
    plugins: list[PluginConfig] = Field(default_factory=list, description="Plugin configs")


class InputValidationConfig(BaseModel):
    """Configuration for input validation.

    Input validation catches malformed events and wrong field names (e.g., tool_output
    vs tool_response) at the server layer before dispatching to handlers.

    Note: Fail-closed vs fail-open behavior is controlled by daemon.strict_mode.

    Attributes:
        enabled: Enable input schema validation
        log_validation_errors: Log validation failures
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=True,
        description="Enable input validation to catch wrong field names",
    )
    log_validation_errors: bool = Field(
        default=True,
        description="Log validation errors to daemon logs",
    )


class ProjectHandlersConfig(BaseModel):
    """Configuration for project-level handlers.

    Project handlers are discovered from a convention-based directory structure
    within the project, mirroring the built-in handler event-type subdirectories.

    Attributes:
        enabled: Master switch for project handler loading
        path: Path to project handlers directory (relative to workspace root)
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="Enable project handler loading",
    )
    path: str = Field(
        default=".claude/project-handlers",
        description=(
            "Path to project handlers directory (relative to workspace root). "
            "EXEMPT from the repository-relative rule (Plan 00303): the "
            "controller explicitly supports and tests an absolute override "
            "(tests/unit/daemon/test_controller_project_handlers.py) for a "
            "project-owned handler directory that may legitimately live "
            "outside the repository, the same category as a plugin path. A "
            "leading {REPO_ROOT} token (Plan 00302 extension) expands "
            "against the workspace root at load time -- the portable "
            "alternative to a genuine absolute path."
        ),
    )


class PlanWorkflowQaJournalConfig(BaseModel):
    """Per-plan journalling policy (Plan 00163).

    Nested under ``plan_workflow.qa.journal``. Journalling rides the existing
    three plan_qa surfaces (edit / commit / sweep) rather than a new handler,
    so its knobs live beside the rest of the plan QA policy. Every journal
    check governed by ``mode`` ships ADVISE; only ``journal-dayfile-naming``
    may ever ratchet to block via ``mode: block`` after a clean dogfood
    period. ``journal-dayfile-is-today`` (Plan 00197) is the one exception:
    it has its OWN ``today_only_mode`` knob and ships BLOCK by default,
    because write-time recency is not given the same rollout grace period.

    SUBORDINATE TO THE SURFACE MODE (Plan 00190). ``mode: block`` is a
    CEILING, not a guarantee: the edit surface re-gates every blocker on
    ``plan_workflow.qa.edit_mode``, so ``mode: block`` only denies when
    ``edit_mode`` is ALSO ``block``. Under the documented ``edit_mode: warn``
    rollout posture it degrades to an advisory, and ``edit_mode: off``
    disables both journal edit checks outright regardless of ``enabled``.
    This sub-block cannot keep itself alive. Pinned by
    ``tests/unit/handlers/pre_tool_use/test_plan_qa_edit.py``.

    Attributes:
        enabled: Master switch for all journal checks — subject to
            ``edit_mode``/``commit_gate_mode``/``sweep_mode`` still being on
        mode: Enforcement mode for journal checks (advise | block | off) —
            ships as advise; only naming honours block, and only when the
            owning surface mode is block too
        dir_name: Journal sub-directory name inside a plan folder
        freshness_days: Sweep nag threshold for a plan whose newest day-file
            is older than this (deliberately shorter than plan staleness_days)
        enforce_on_completion: Whether a terminal status flip should advise a
            closing journal entry (Phase 3 commit coupling)
        grandfather_before: Plans numbered below this are never nagged to grow
            a JOURNAL/ (no backfill); model default 0, set to 163 in this repo
        today_only_mode: Enforcement mode for ``journal-dayfile-is-today``
            (advise | block | off; Plan 00197) — independent of ``mode``,
            because write-time recency ships BLOCK by default rather than
            advise-first: an agent appending to a stale day-file is exactly
            the confusion this check exists to prevent, so it is not given a
            rollout grace period the way the original journalling checks were
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Enable journal checks")
    mode: Literal["advise", "block", "off"] = Field(
        default="advise",
        description="Journal check enforcement mode (only naming honours block)",
    )
    dir_name: str = Field(
        default="JOURNAL",
        description="Journal sub-directory name inside each plan folder",
    )
    freshness_days: Annotated[int, Field(ge=1)] = Field(
        default=3,
        description="Days before a plan with a JOURNAL/ is nagged as stale-journalled",
    )
    enforce_on_completion: bool = Field(
        default=False,
        description="Advise a closing journal entry on terminal status flips",
    )
    grandfather_before: Annotated[int, Field(ge=0)] = Field(
        default=0,
        description="Plans numbered below this are never nagged to grow a JOURNAL/",
    )
    today_only_mode: Literal["advise", "block", "off"] = Field(
        default="block",
        description=(
            "journal-dayfile-is-today enforcement mode — a Write/Edit to a "
            "journal day-file dated anything other than today is blocked"
        ),
    )


class PlanWorkflowQaPlanDocSizeConfig(BaseModel):
    """Tiered size limits for plan DOCUMENTS only (Plan 00190).

    Nested under ``plan_workflow.qa.plan_doc_size``. A ``PLAN.md`` is read in
    full at the start of every session that touches the plan, so its size is a
    recurring context-budget cost. A ``JOURNAL/`` day-file is not read whole —
    it is tailed, grepped, or handed to a sub-agent — so it is UNBOUNDED by
    design and no threshold here ever applies to it.

    Thresholds are derived from READ COST, not from percentiles of any one
    repository: the canonical unit is tokens, with bytes and lines as the
    runtime proxy. Both axes are checked (``bytes > B OR lines > L``) because
    a long thin plan and a short dense one cost the same to read.

    Tiers escalate in WORDING; only the top tier denies, and even then a
    shrinking edit, a grandfathered plan number, or a declared
    ``MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason>`` in the file downgrades it to
    advice — so an oversized plan can always be refactored back down.

    Attributes:
        enabled: Master switch for the size check
        advisory_bytes/advisory_lines: First nudge (~4,500 tokens)
        warning_bytes/warning_lines: Escalated wording (~6,300 tokens)
        block_bytes/block_lines: Hard limit (~8,800 tokens)
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Enable the plan-document size check")
    advisory_bytes: Annotated[int, Field(ge=1)] = Field(
        default=18_000, description="Bytes above which a plan document is advised as large"
    )
    advisory_lines: Annotated[int, Field(ge=1)] = Field(
        default=350, description="Lines above which a plan document is advised as large"
    )
    warning_bytes: Annotated[int, Field(ge=1)] = Field(
        default=25_000, description="Bytes above which the advisory wording escalates"
    )
    warning_lines: Annotated[int, Field(ge=1)] = Field(
        default=500, description="Lines above which the advisory wording escalates"
    )
    block_bytes: Annotated[int, Field(ge=1)] = Field(
        default=35_000, description="Bytes above which plan-document edits are blocked"
    )
    block_lines: Annotated[int, Field(ge=1)] = Field(
        default=900, description="Lines above which plan-document edits are blocked"
    )

    @model_validator(mode="after")
    def _validate_tiers_are_monotonic(self) -> "PlanWorkflowQaPlanDocSizeConfig":
        """FAIL FAST on tiers that cannot escalate.

        Non-monotonic thresholds silently disable a tier (a block limit below
        the advisory limit means the advisory can never be reached), which is
        far worse than a startup error.
        """
        for axis, tiers in (
            ("bytes", (self.advisory_bytes, self.warning_bytes, self.block_bytes)),
            ("lines", (self.advisory_lines, self.warning_lines, self.block_lines)),
        ):
            advisory, warning, block = tiers
            if not advisory < warning < block:
                raise ValueError(
                    f"plan_doc_size {axis} tiers must increase strictly "
                    f"(advisory < warning < block); got {advisory} < {warning} < {block}"
                )
        return self


class PlanWorkflowQaConfig(BaseModel):
    """Configuration for the plan QA subsystem (Plan 00144).

    One policy shared by all three enforcement surfaces (edit-time handler,
    commit gate, sweep) plus the ``plan-qa`` CLI — nested here rather than
    fragmented across per-handler options because the checks span handlers.

    Attributes:
        enabled: Master switch for all plan QA surfaces
        completed_dir: Archive dir name for completed plans (some projects use Done)
        cancelled_dir: Archive dir name for cancelled plans (None = cancelled
            plans are archived in completed_dir)
        edit_mode: Stage 1 edit-time enforcement (block | warn | off)
        commit_gate_mode: Stage 2 git-commit gate (block | warn | off) — ships
            as warn; flip to block after a clean dogfooding period
        sweep_mode: Stage 3 SessionStart sweep (advise | off)
        require_terminal_date: Require ``(YYYY-MM-DD)`` on terminal statuses
            (off by default: git history is the source of truth for "when")
        staleness_days: Sweep staleness-nag threshold for active plans
        legacy_plan_allowlist: Plan numbers held to advise-only (grandfathered)
        collision_allowlist: Historic duplicate plan numbers to tolerate
        extra_root_files: Extra non-plan filenames permitted at the plan root,
            layered ADDITIVELY on top of the built-in accepted set
            ({README.md, CLAUDE.md, mkplan.bash, _TEMPLATE_.md,
            _JOURNAL_TEMPLATE_.md, _planlib.inc.bash}); default empty = today's
            behaviour. Use for a project's OWN legitimately-placed shared file
            (e.g. a bespoke sourced helper script) that the daemon does not
            already know about. `_planlib.inc.bash` -- the motivating example
            for this option before the daemon shipped it -- is now built in
            (Plan 00213 Phase 2) precisely so a client project no longer has
            to configure this for it.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Enable plan QA checks")
    completed_dir: str = Field(
        default="Completed",
        description="Archive directory name for completed plans",
    )
    cancelled_dir: str | None = Field(
        default="Cancelled",
        description="Archive directory name for cancelled plans (None = use completed_dir)",
    )
    edit_mode: Literal["block", "warn", "off"] = Field(
        default="block",
        description="Stage 1 edit-time enforcement mode",
    )
    commit_gate_mode: Literal["block", "warn", "off"] = Field(
        default="warn",
        description="Stage 2 commit-gate enforcement mode",
    )
    sweep_mode: Literal["advise", "off"] = Field(
        default="advise",
        description="Stage 3 SessionStart sweep mode",
    )
    require_terminal_date: bool = Field(
        default=False,
        description="Require (YYYY-MM-DD) qualifier on terminal statuses",
    )
    staleness_days: Annotated[int, Field(ge=1)] = Field(
        default=30,
        description="Days without a commit before an active plan is nagged as stale",
    )
    legacy_plan_allowlist: list[int] = Field(
        default_factory=list,
        description="Plan numbers held to advise-only (grandfathered legacy plans)",
    )
    collision_allowlist: list[int] = Field(
        default_factory=list,
        description="Historic duplicate plan numbers tolerated by collision checks",
    )
    extra_root_files: list[str] = Field(
        default_factory=list,
        description=(
            "Extra non-plan filenames allowed at the plan root, in addition to the "
            "built-in {README.md, CLAUDE.md, mkplan.bash, _TEMPLATE_.md}"
        ),
    )
    journal: PlanWorkflowQaJournalConfig = Field(
        default_factory=PlanWorkflowQaJournalConfig,
        description="Per-plan journalling policy (Plan 00163)",
    )
    plan_doc_size: PlanWorkflowQaPlanDocSizeConfig = Field(
        default_factory=PlanWorkflowQaPlanDocSizeConfig,
        description="Tiered read-cost size limits for plan documents (Plan 00190)",
    )


_DOT_GIT: Final = ".git"


class PlanWorkflowScriptsConfig(BaseModel):
    """Configuration for the `planlib` operator-script safety library (Plan 00213 Phase 2).

    Nested under ``plan_workflow.scripts``. `_planlib.inc.bash` is a sourced
    bash library of safety-critical primitives for plan-folder orchestrator
    scripts (deploy/verify/triage scripts an operator runs from their own
    terminal): script-relative boundary-bounded repo-root resolution, a
    tee'd run log with a deterministic drain, ssh-agent key loading, and the
    state-change gate. Deploying it is a SEPARATE decision from writing
    orchestrator scripts against it — this config only controls whether the
    daemon deploys the library at all (via the same idempotent seam that
    deploys `mkplan.bash`, see `install/plan_workflow.py`).

    Ships OFF by default, and ``root_marker`` has NO default: a wrong default
    silently resolves to *some* directory, and a deployed orchestrator then
    operates on the wrong repository without complaint — the exact incident
    class the library exists to prevent (see the library's own
    `_plan_find_repo_root`/`plan_init`). Requiring it at config-validation
    time surfaces a missing value at daemon-restart, not at first live run.

    Attributes:
        enabled: Master switch. Deploys `_planlib.inc.bash` into the plan
            directory when true (requires `plan_workflow.enabled` too, since
            the library is deployed alongside `mkplan.bash`).
        root_marker: Filename marking this project's repository root for the
            library's boundary-bounded upward walk. REQUIRED when `enabled`
            — deliberately no default. Must not be `.git`: `.git` is the
            walk's BOUNDARY (nested-checkout protection), and using it as the
            marker too means the boundary check can never fire.
        delegate: Optional project-relative command runner a leg delegates
            to (e.g. a wrapper script that resolves credentials/targeting).
            Empty = legs call commands directly.
        check_flag: The dry-run flag threaded into delegated commands by the
            orchestrator's own `--check` flag.
        force_color_var: Optional env var forced to `1` when the console is a
            TTY, so a colour-suppressing tool still colours the console while
            the run log (which strips ANSI) stays clean. Empty disables this.
        scrubber: Optional project-relative secret scrubber invoked on the
            finished run log as `<scrubber> <file>`. Required in practice
            when `track_run_logs` is true.
        track_run_logs: When true, a run without a working scrubber
            quarantines its log to `.unscrubbed` (gitignored) rather than
            leaving an uncommitted-but-unmarked log lying around.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Deploy the planlib operator-script safety library",
    )
    root_marker: str = Field(
        default="",
        description="Filename marking the repo root boundary; REQUIRED when enabled, no default",
    )
    delegate: str = Field(
        default="",
        description="Project-relative command runner a leg delegates to (optional)",
    )
    check_flag: str = Field(
        default="--check",
        description="Dry-run flag threaded into delegated commands by --check",
    )
    force_color_var: str = Field(
        default="",
        description="Env var forced to 1 when the console is a TTY (optional)",
    )
    scrubber: str = Field(
        default="",
        description="Project-relative secret scrubber for run logs (optional)",
    )
    track_run_logs: bool = Field(
        default=False,
        description="Require a working scrubber; quarantine unscrubbed logs to .unscrubbed",
    )

    @model_validator(mode="after")
    def _validate_root_marker(self) -> "PlanWorkflowScriptsConfig":
        """FAIL FAST on the two ways `root_marker` can silently misresolve.

        Both checks only apply when ``enabled`` — a disabled config never
        deploys anything, so an unset/invalid marker is harmless until the
        library would actually be deployed.
        """
        if not self.enabled:
            return self
        if not self.root_marker:
            raise ValueError(
                "plan_workflow.scripts.root_marker is required when "
                "plan_workflow.scripts.enabled is true — there is deliberately "
                "no default (a wrong default silently resolves to the wrong "
                "repository; see _plan_find_repo_root in _planlib.inc.bash)"
            )
        if self.root_marker == _DOT_GIT:
            raise ValueError(
                "plan_workflow.scripts.root_marker must not be '.git' — .git is "
                "the walk's BOUNDARY (nested-checkout protection); using it as "
                "the marker too means the boundary check can never fire"
            )
        return self


class PlanWorkflowConfig(BaseModel):
    """Configuration for plan workflow system.

    Centralises plan-related configuration that was previously scattered
    across handler options (track_plans_in_project, plan_workflow_docs).

    Attributes:
        enabled: Whether plan workflow tracking is enabled
        directory: Path to plan folder relative to workspace root
        workflow_docs: Path to workflow documentation file
        enforce_claude_code_sync: Whether to enforce plansDirectory sync
        qa: Plan QA subsystem policy (Plan 00144)
        scripts: `planlib` operator-script safety library policy (Plan 00213)
    """

    model_config = ConfigDict(extra="forbid")

    # F-PLANDEF (Plan 00137): default False so the shipped default matches the
    # shipped opt-in plan handlers. A stock install no longer deploys CLAUDE/Plan/
    # + mkplan while plan_number_helper et al. ship disabled. Legacy clients that
    # opted in via the per-handler track_plans_in_project option are preserved by
    # migrate_plan_handler_options (which only runs when no explicit top-level
    # plan_workflow block is present); opting in is a single field:
    # `plan_workflow: { enabled: true }`.
    enabled: bool = Field(default=False, description="Enable plan workflow tracking")
    directory: str = Field(
        default="CLAUDE/Plan",
        description="Path to plan folder relative to workspace root",
    )
    workflow_docs: str = Field(
        default="CLAUDE/PlanWorkflow.md",
        description="Path to workflow documentation file",
    )

    @field_validator("directory", "workflow_docs")
    @classmethod
    def validate_paths_are_repo_relative(cls, value: str) -> str:
        """Plan directory / workflow docs are repository-relative (Plan 00303)."""
        return _repo_relative_path(value, "plan_workflow path")

    enforce_claude_code_sync: bool = Field(
        default=False,
        description="Enforce plansDirectory sync with .claude/settings.json",
    )
    qa: PlanWorkflowQaConfig = Field(
        default_factory=PlanWorkflowQaConfig,
        description="Plan QA subsystem policy (Plan 00144)",
    )
    scripts: PlanWorkflowScriptsConfig = Field(
        default_factory=PlanWorkflowScriptsConfig,
        description="`planlib` operator-script safety library policy (Plan 00213)",
    )


class DocumentationTreesConfig(BaseModel):
    """Names of the two audience-split documentation trees (Plan 00284).

    Nested under ``documentation.trees``. The tree NAMES are per-project
    configuration; the SPLIT itself is not optional once
    ``documentation.enabled`` is true — see
    ``CLAUDE/DocumentationStrategy.md`` R2/R3.

    Attributes:
        agent: Root directory of the agent-facing tree (verbose, owns depth)
        human: Root directory of the human-facing tree (terse, may point at
            the agent tree for full depth)
    """

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(default="CLAUDE", description="Root directory of the agent-facing tree")
    human: str = Field(default="docs", description="Root directory of the human-facing tree")

    @field_validator("agent", "human")
    @classmethod
    def validate_trees_are_repo_relative(cls, value: str) -> str:
        """Documentation tree roots are repository-relative (Plan 00303)."""
        return _repo_relative_path(value, "documentation tree root")


class DocumentationGeneratedDocEntry(BaseModel):
    """One entry in the generated-docs manifest (R10).

    Attributes:
        glob: Path glob identifying the generated file(s)
        generator: The command that regenerates them, shown in advisories
    """

    model_config = ConfigDict(extra="forbid")

    glob: str = Field(description="Path glob identifying the generated file(s)")
    generator: str = Field(description="Command that regenerates the file(s)")


def _default_generated_docs() -> list[DocumentationGeneratedDocEntry]:
    """Pre-seed the manifest with the daemon's own generated artefact (R10).

    Deliberately does NOT declare the ``<hooksdaemon>...</hooksdaemon>``
    block the daemon also regenerates inside root ``CLAUDE.md`` on every
    restart (see ``ClaudeMdInjector``). That block is generated content
    living inside an otherwise hand-edited file — the manifest here is
    glob-addressable at file granularity only, and a whole-file glob on
    ``CLAUDE.md`` would wrongly flag every legitimate hand-edit to the rest
    of the file. Section-level generation needs a different mechanism
    (marker-bounded diffing, not a path glob) that this manifest does not
    attempt; the omission is a decision, not an oversight (Plan 00284
    Task 3.1b).
    """
    return [
        DocumentationGeneratedDocEntry(
            glob=".claude/HOOKS-DAEMON.md",
            generator="bin/hooks-daemon generate-docs",
        )
    ]


class DocumentationQaConfig(BaseModel):
    """Documentation QA subsystem policy (Plan 00284).

    One policy shared by the three enforcement surfaces (edit-time handler,
    commit gate, sweep) plus the ``docs-qa`` CLI, mirroring
    ``plan_workflow.qa`` (Plan 00144).

    Attributes:
        edit_mode: Stage 1 (EDIT) enforcement mode — the default for
            block-eligible checks that do not have their own
            ``check_modes`` override
        commit_gate_mode: Stage 2 (STAGED) git-commit gate enforcement mode
        sweep_mode: Stage 3 (SWEEP) SessionStart sweep mode — never blocks
        check_modes: Per-check override of ``edit_mode``/``commit_gate_mode``,
            keyed by check id (e.g. ``rules-file-shape: block``)
        grandfather_allowlist: File globs held to advise-only forever (R12)
        generated_docs: Manifest of generated docs (R10), pre-seeded with the
            daemon's own artefact
        registered_module_docs: Registry of sub-``CLAUDE.md`` files that ARE
            a canonical home rather than a routing table (R7d)
        resident_at_imports: The ``@``-import allowlist (R6) — files permitted
            to be resident-imported outside the deliberate root set
        scope_exclude_globs: File globs excluded from the doc corpus
            entirely (Plan 00289) — for FROZEN historical records (a
            versioned upgrade guide, a self-labelled archived draft) whose
            links and structured blocks are never re-verified against
            current truth, unlike ``grandfather_allowlist`` (which still
            indexes the file and merely caps its severity at ADVISE). A
            scope-excluded file is invisible to ``pointer-resolves``,
            ``duplicate-block`` and every other corpus-driven check.
    """

    model_config = ConfigDict(extra="forbid")

    edit_mode: Literal["warn", "block"] = Field(
        default="warn", description="Stage 1 (EDIT) enforcement mode"
    )
    commit_gate_mode: Literal["warn", "block"] = Field(
        default="warn", description="Stage 2 (STAGED) commit-gate enforcement mode"
    )
    sweep_mode: Literal["advise", "off"] = Field(
        default="advise", description="Stage 3 (SWEEP) SessionStart sweep mode"
    )
    check_modes: dict[str, Literal["warn", "block"]] = Field(
        default_factory=dict, description="Per-check override of edit_mode/commit_gate_mode"
    )
    grandfather_allowlist: list[str] = Field(
        default_factory=list, description="File globs held to advise-only forever (R12)"
    )
    generated_docs: list[DocumentationGeneratedDocEntry] = Field(
        default_factory=_default_generated_docs,
        description="Manifest of generated docs (R10), pre-seeded with the daemon's own artefact",
    )
    registered_module_docs: list[str] = Field(
        default_factory=list,
        description="Registry of sub-CLAUDE.md files that ARE a canonical home (R7d)",
    )
    resident_at_imports: list[str] = Field(
        default_factory=lambda: ["CLAUDE.md"],
        description="The @-import allowlist (R6)",
    )
    scope_exclude_globs: list[str] = Field(
        default_factory=list,
        description="File globs excluded from the doc corpus entirely (frozen historical records)",
    )


class DocumentationConfig(BaseModel):
    """Configuration for the documentation SSoT enforcement system (Plan 00284).

    Ships OFF by default upstream (``enabled: false``); this repository turns
    it on to dogfood it. Mirrors the ``plan_workflow`` precedent: one shared
    top-level config block so the three enforcement surfaces (edit-time
    handler, commit gate, sweep) and the CLI cannot fragment policy.

    Attributes:
        enabled: Master switch for the documentation QA HANDLERS. The
            ``docs-qa`` CLI runs regardless — an explicit invocation is
            consent.
        trees: Names of the two audience-split documentation trees
        qa: Documentation QA subsystem policy
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False, description="Enable the documentation QA handlers (CLI always runs)"
    )
    trees: DocumentationTreesConfig = Field(default_factory=DocumentationTreesConfig)
    qa: DocumentationQaConfig = Field(default_factory=DocumentationQaConfig)


class LayoutConfig(BaseModel):
    """Project directory-layout truths that have no other config home (Plan 00288).

    Sibling truths that DO already have a home — doc tree names
    (``documentation.trees``), the plan directory
    (``plan_workflow.directory``) and its archive dir names
    (``plan_workflow.qa.completed_dir``/``cancelled_dir``) — are
    deliberately NOT duplicated here; the ``ProjectLayout`` runtime facade
    (``core/project_layout.py``) composes this block WITH those homes into
    one handler-facing API (DESIGN-layout-ssot.md §2a, decision D2).

    Every list is empty by default (byte-identical zero-config behaviour) and
    ADDITIVE onto the relevant built-in convention/constant unless ``mode``
    is ``replace`` — in which case a list the project actually SET stands
    alone, while a list left unset still falls back to the built-in (DESIGN
    §2c; mirrors how ``secret_file_guard`` scopes its own ``mode`` to the
    option it governs).

    Attributes:
        source_dirs: Extra source directory names/globs, e.g. ``["backend/src"]``
        test_dirs: Extra test directory names/globs, e.g. ``["e2e"]``
        config_dirs: Extra config directory names, extending the built-in ``config``
        vendor_dirs: Extra vendored/build directory names, extending the
            canonical vendored/build set
        mode: ``additive`` (default — declared lists extend built-ins) or
            ``replace`` (a SET list stands alone; an unset list keeps its
            built-in)
    """

    model_config = ConfigDict(extra="forbid")

    source_dirs: list[str] = Field(
        default_factory=list, description="Extra source directory names/globs"
    )
    test_dirs: list[str] = Field(
        default_factory=list, description="Extra test directory names/globs"
    )
    config_dirs: list[str] = Field(
        default_factory=list,
        description="Extra config directory names, extending the built-in 'config'",
    )
    vendor_dirs: list[str] = Field(
        default_factory=list,
        description="Extra vendored/build directory names, extending the canonical set",
    )
    mode: Literal["additive", "replace"] = Field(
        default="additive", description="additive: extend built-ins; replace: SET lists stand alone"
    )


def _repo_relative_path(value: str, label: str) -> str:
    """Validate and normalise a repository-relative config path (Plan 00296).

    **Config carries ZERO absolute paths.** A repository is mounted at
    different places on different machines -- a container bind mount, a
    developer's home directory, a CI checkout -- so an absolute path in
    committed config is correct on exactly one of them and silently wrong
    everywhere else. Relative-to-the-repo-root is the only form that
    survives being checked out somewhere new.

    Escapes (``..``) are rejected for the same reason: a path that leaves the
    repository is by definition describing something the repository does not
    carry, so it cannot be portable either.

    Normalisation makes ``web/``, ``./web`` and ``web`` one declaration.
    Without that, an equality check (the duplicate-root guard) and a
    path-containment check can disagree about the same directory.

    Args:
        value: The raw configured path.
        label: What is being validated, for the error message.

    Returns:
        The normalised relative path; ``.`` for the repository root itself.

    Raises:
        ValueError: If the path is absolute or escapes the repository.
    """
    return _normalise_repo_relative_path(value, label)


# Public alias (Plan 00303): other modules resolving a config-declared path at
# RUNTIME (outside a pydantic field validator, e.g. an options dict a handler
# reads by hand) reuse this SAME validator rather than growing a copy. Kept as
# an alias rather than a rename so every existing in-module call site stays
# untouched.
validate_repo_relative_path = _repo_relative_path


class ProjectConfig(BaseModel):
    """One declared project within the repository (Plan 00296).

    A project is CONFIGURED, never inferred. The daemon will report that a
    repository looks like a monorepo, but it will not act on that: a wrongly
    guessed boundary leaves enforcement looking healthy while pointing at the
    wrong tree, which is the same silent failure this whole mechanism exists
    to remove.

    ``kind`` and ``bin_dirs`` are optional because they can be filled in by
    convention once the boundary is known -- a declared root containing a
    ``package.json`` is ``node`` with ``node_modules/.bin``. That is
    convention INSIDE a line the user drew, not a guess about where the line
    is. State either explicitly to override.

    Attributes:
        name: Identifier for this project, unique within the block. Used in
            advisory and diagnostic output.
        root: Repository-relative directory, e.g. ``apps/web``. ``.`` declares
            the repository root itself as a project. A declared project need
            NOT contain a manifest -- a config-driven toolchain directory is
            exactly the case declaration exists for.
        kind: Ecosystem name. Unset means infer from the manifest at ``root``.
        bin_dirs: Root-relative tool binary directories. Unset means infer
            from ``kind``; an explicitly EMPTY list declares that this project
            has none, which is a different statement from staying silent.
        layout: This project's OWN directory-layout truths (Plan 00300). Unset
            means this project uses convention/built-in defaults for ITS OWN
            root -- it never inherits the top-level ``layout:`` block, which
            is the ROOT project's layout only, not a global fallback. Same
            declared-not-inferred philosophy as ``root``/``kind``: one
            project's layout must never leak into another's.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Unique identifier for this project")
    root: str = Field(min_length=1, description="Repository-relative project root directory")
    kind: str | None = Field(
        default=None, description="Ecosystem name; unset infers from the manifest at root"
    )
    bin_dirs: list[str] | None = Field(
        default=None, description="Root-relative tool bin dirs; unset infers from kind"
    )
    layout: LayoutConfig | None = Field(
        default=None,
        description="This project's own directory-layout truths; unset uses built-in defaults",
    )

    @field_validator("root")
    @classmethod
    def validate_root_is_repo_relative(cls, value: str) -> str:
        """Roots are repository-relative, normalised, and may not escape."""
        return _repo_relative_path(value, "project root")

    @field_validator("bin_dirs")
    @classmethod
    def validate_bin_dirs_are_repo_relative(cls, value: list[str] | None) -> list[str] | None:
        """Bin dirs are relative to the PROJECT root, under the same rule.

        An absolute ``bin_dirs`` entry would pin a machine-specific toolchain
        path into shared config -- the same portability failure as an absolute
        project root, and easier to miss because it looks like a plausible
        thing to write.
        """
        if value is None:
            return None
        return [_repo_relative_path(entry, "project bin_dirs entry") for entry in value]


class AgentAssetGateConfig(BaseModel):
    """Gating config for one daemon-shipped agent asset (Plan 00279).

    Attributes:
        enabled: Whether the agent is deployed/maintained in
            ``.claude/agents/``. Ships False — every agent asset is opt-in
            unless its spec is gated on another subsystem's key.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Deploy and maintain this daemon-shipped agent asset",
    )


class AgentsConfig(BaseModel):
    """Configuration for daemon-shipped agent assets (Plan 00279).

    Each entry gates one agent deployed into the client's ``.claude/agents/``
    namespace by the agent-asset subsystem (``install/agent_assets.py``).
    The plan-dedupe scout is gated on ``plan_workflow.enabled`` rather than
    here, preserving its pre-subsystem behaviour.

    Attributes:
        opus_security: Quarantine executor for safeguard-flaggable security
            work (``hooks-daemon-opus-security``). Ships disabled.
        docs_qa: Read-only documentation-SSoT auditor
            (``hooks-daemon-docs-qa``, Plan 00284). Ships disabled.
    """

    model_config = ConfigDict(extra="forbid")

    opus_security: AgentAssetGateConfig = Field(
        default_factory=AgentAssetGateConfig,
        description="hooks-daemon-opus-security quarantine agent (ships disabled)",
    )
    docs_qa: AgentAssetGateConfig = Field(
        default_factory=AgentAssetGateConfig,
        description="hooks-daemon-docs-qa documentation auditor agent (ships disabled)",
    )


class PayloadCaptureConfig(BaseModel):
    """Configuration for daemon-side hook-payload capture (Plan 00158).

    A dogfooding aid: when enabled, the daemon appends the raw ``hook_input`` it
    receives for each event to ``<dir>/<event>.jsonl``. It is toggled here (in
    the tracked config) and applied by a daemon restart — never a Claude Code
    relaunch, since the forwarder is dumb transport and the daemon sees every
    payload.

    Attributes:
        enabled: Master toggle. Default False so the feature ships dormant.
        dir: Directory for capture files. None = ``<untracked>/payload-capture``.
        events: Optional allow-list of event names (e.g. ``["Status"]``). Empty
            = capture every event.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=False,
        description="Capture raw hook payloads to <dir>/<event>.jsonl for dogfooding",
    )
    dir: str | None = Field(
        default=None,
        description="Capture directory. None = <daemon untracked>/payload-capture",
    )
    events: list[str] = Field(
        default_factory=list,
        description="Only capture these event names (e.g. ['Status']). Empty = all events.",
    )


class VerdictLogConfig(BaseModel):
    """Configuration for the daemon's verdict log (Plan 00209).

    Field report background: the daemon makes hundreds of handler decisions
    per session and persisted none of them, so "which handlers earn their
    keep?" and "what is the real false-positive rate per handler?" were
    answerable only by anecdote. When enabled, every matched handler's
    decision is appended to ``verdicts.jsonl`` — ``{ts, session, event,
    tool, handler, verdict, rule, mode, overridden}`` — with no per-handler
    opt-in required (the write happens once in the daemon controller).

    Default-on (Task 2.6): the log records handler/rule/verdict metadata
    only — never tool payloads or file contents — so there is no privacy
    reason to ship it dormant, unlike ``payload_capture`` which DOES record
    raw payloads and is therefore default-off.

    Retention (Task 2.4): ``verdicts.jsonl`` is a bounded ROLLING SAMPLE,
    capped the same way as every other daemon JSONL log (Plan 00181's
    ``cap_log_file``) — NOT a durable lifetime counter. See
    ``daemon/verdict_log.py`` for the full rationale; the `hooks-daemon
    verdicts` report is explicit that its statistics describe the retained
    window, not lifetime totals.

    Status events are excluded (Plan 00234). A status handler RENDERS and can
    only ever return ``allow``, so its records carry no information — yet they
    arrive at the status line's refresh rate. Measured on this project's own
    log, 43,929 of 44,180 retained records were status renders (99.43%),
    filling the 10 MiB cap in **65 minutes**: the log built to answer "which
    handlers earn their keep?" could see one hour of one session. Excluding
    them stretches the same cap to roughly 8 days.

    Attributes:
        enabled: Master toggle. Default True (metadata-only, no payloads).
        max_bytes: Retention cap in bytes before the oldest half is trimmed.
        record_status_events: Opt back in to Status renders, for debugging the
            status line itself. Default False.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(
        default=True,
        description="Record every handler decision to verdicts.jsonl (metadata only, no payloads)",
    )
    max_bytes: Annotated[int, Field(gt=0)] = Field(
        default=10 * 1024 * 1024,
        description="Retention cap in bytes for verdicts.jsonl (rolling sample, oldest half trimmed on breach)",
    )
    record_status_events: bool = Field(
        default=False,
        description="Record Status (status-line) renders too. Off by default: they are ~99% of all records, always 'allow', and drown the retained window (Plan 00234)",
    )


class TransportConfig(BaseModel):
    """Per-event socket + Rust relay transport rungs (Plan 00290).

    Governs the whole transport-choice fallback ladder documented in
    ``CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md``
    §4-§5: relay binary -> ``nc -U`` -> the permanent bash+python3 rung.
    Defaults produce behaviour BYTE-IDENTICAL to today — no per-event
    listeners are bound, no relay is deployed, forwarders are unchanged.

    Attributes:
        relay_enabled: Rung 1 opt-in — exec the static Rust relay binary.
        nc_enabled: Rung 2 opt-in — the bash ``nc -U`` path, tried before the
            python3 transport.
        timeout_seconds: Relay ``--timeout-ms`` source (converted at deploy
            time); also the ``nc -w`` budget. Mirrors the python3 transport's
            30s default (``CLAUDE_HOOKS_SOCKET_TIMEOUT`` keeps overriding it).
        relay_binary: Absolute-path override for the relay binary. ``None``
            means ``{untracked}/bin/hooks-relay``. EXEMPT from the
            repository-relative rule (Plan 00303): like a system binary
            path, this names an executable that may legitimately live
            outside the repository (a machine-wide install), and the
            override exists precisely to point at one.
        relay_source: How the relay binary at ``relay_binary`` gets there —
            ``"build"`` (compile from source with plain ``rustc``, preferred
            whenever a musl-capable toolchain is present), ``"download"``
            (fetch the digest-verified precompiled asset from the matching
            GitHub release), or ``None`` (default — neither route runs; the
            relay rung stays opt-in on top of an explicit distribution
            choice, per Plan 00290 Phase 5's owner ruling: nothing implicit).
    """

    model_config = ConfigDict(extra="forbid")

    relay_enabled: bool = Field(
        default=False,
        description="Rung 1: exec the static relay binary (opt-in)",
    )
    nc_enabled: bool = Field(
        default=False,
        description="Rung 2: bash nc -U path (opt-in)",
    )
    timeout_seconds: Annotated[int, Field(gt=0)] = Field(
        default=30,
        description="Relay --timeout-ms source; also nc -w budget",
    )
    relay_binary: str | None = Field(
        default=None,
        description="Absolute-path override; null = {untracked}/bin/hooks-relay",
    )
    relay_source: Literal["build", "download"] | None = Field(
        default=None,
        description=(
            "How the relay binary is provisioned at install/upgrade time: "
            "'build' (plain rustc, no cargo, preferred when a musl-capable "
            "toolchain is present) or 'download' (digest-verified GitHub "
            "release asset). Default null = neither route runs — an "
            "explicit, deliberate choice, never an implicit side effect of "
            "relay_enabled."
        ),
    )

    @property
    def per_event_sockets_needed(self) -> bool:
        """True when any rung requires the daemon's per-event listeners (§1.3)."""
        return self.relay_enabled or self.nc_enabled


class DaemonConfig(BaseModel):
    """Configuration for the daemon server.

    Attributes:
        idle_timeout_seconds: Seconds of inactivity before shutdown
        log_level: Logging level
        socket_path: Custom socket path (None = auto). EXEMPT from the
            repository-relative rule (Plan 00303): an AF_UNIX socket is
            RUNTIME state, not a repository artefact -- it commonly needs to
            live under ``/tmp`` or similar to stay under the platform's short
            socket-path length limit, which a repo-nested path cannot
            guarantee.
        pid_file_path: Custom PID file path (None = auto). Same exemption as
            ``socket_path``: daemon runtime state, not a repository artefact.
        log_buffer_size: Size of in-memory log buffer
        request_timeout_seconds: Request processing timeout
        self_install_mode: Whether daemon runs from project root (vs .claude/hooks-daemon/)
        strict_mode: Fail-fast on ALL errors (handler exceptions, validation errors, etc.)
        input_validation: Input validation configuration
    """

    model_config = ConfigDict(extra="allow")

    idle_timeout_seconds: Annotated[int, Field(ge=1)] = Field(
        default=600,
        description="Idle timeout in seconds",
    )
    log_level: LogLevel = Field(default=LogLevel.INFO, description="Log level")
    socket_path: str | Path | None = Field(default=None, description="Custom socket path")
    pid_file_path: str | Path | None = Field(default=None, description="Custom PID file path")
    log_buffer_size: Annotated[int, Field(ge=100, le=100000)] = Field(
        default=1000,
        description="In-memory log buffer size",
    )
    request_timeout_seconds: Annotated[int, Field(ge=1, le=300)] = Field(
        default=30,
        description="Request timeout in seconds",
    )
    self_install_mode: bool = Field(
        default=False,
        description="Self-install mode: daemon runs from project root instead of .claude/hooks-daemon/",
    )
    strict_mode: bool = Field(
        default=False,
        description="Strict mode: FAIL FAST on ALL errors - handler exceptions, validation errors, etc. (fail-closed vs fail-open)",
    )
    input_validation: InputValidationConfig = Field(
        default_factory=InputValidationConfig,
        description="Input validation configuration",
    )
    payload_capture: PayloadCaptureConfig = Field(
        default_factory=PayloadCaptureConfig,
        description="Dogfooding: daemon-side raw hook-payload capture configuration",
    )
    verdict_log: VerdictLogConfig = Field(
        default_factory=VerdictLogConfig,
        description="Verdict log configuration (Plan 00209): per-decision audit trail",
    )
    transport: TransportConfig = Field(
        default_factory=TransportConfig,
        description="Per-event socket + Rust relay transport rungs (Plan 00290)",
    )
    languages: list[str] | None = Field(
        default=None,
        description="Project-level language filter. When set, only handlers for these languages are active. None = ALL languages.",
    )
    exclude_paths: list[str] = Field(
        default_factory=list,
        description="Project-level glob patterns exempted from every handler that supports path exclusion, in addition to that handler's own exclude_paths option and its built-in defaults — the three sources are additive and none overrides another. Gitignore-style globs (*, ?, **). The handler set is deliberately not enumerated here: this description named four while six consumed it, and Plan 00251 made it eight; grep for handler_excludes_path to see the current callers.",
    )
    enforce_single_daemon_process: bool = Field(
        default=False,
        description="Enforce single daemon process per project. When enabled, checks for multiple daemon processes and cleans them up. Auto-enabled in container environments. Requires process verification to prevent killing wrong processes.",
    )
    default_mode: str = Field(
        default="default",
        description="Default daemon mode on startup. Values: 'default' (normal operation), 'unattended' (blocks Stop events to keep Claude working).",
    )
    stale_file_days: Annotated[int, Field(ge=1, le=365)] = Field(
        default=7,
        description="Number of days before daemon runtime files (sock, pid, socket-path) are considered stale and removed on startup. Active daemons touch their files periodically to stay fresh.",
    )

    @field_validator("socket_path", "pid_file_path", mode="before")
    @classmethod
    def convert_path_to_str(cls, v: str | Path | None) -> str | None:
        """Convert Path objects to strings for storage."""
        if isinstance(v, Path):
            return str(v)
        return v

    @property
    def socket_path_obj(self) -> Path | None:
        """Get socket_path as Path object."""
        return Path(self.socket_path) if self.socket_path else None

    @property
    def pid_file_path_obj(self) -> Path | None:
        """Get pid_file_path as Path object."""
        return Path(self.pid_file_path) if self.pid_file_path else None

    def get_socket_path(self, workspace_root: Path) -> Path:
        """Get the socket path, using default if not specified.

        Args:
            workspace_root: Workspace root directory

        Returns:
            Path to socket file
        """
        if self.socket_path:
            return Path(self.socket_path)
        # Use paths.py for consistent path generation with init.sh
        from claude_code_hooks_daemon.daemon.paths import get_socket_path as gen_socket_path

        return gen_socket_path(workspace_root)

    def get_pid_file_path(self, workspace_root: Path) -> Path:
        """Get the PID file path, using default if not specified.

        Args:
            workspace_root: Workspace root directory

        Returns:
            Path to PID file
        """
        if self.pid_file_path:
            return Path(self.pid_file_path)
        # Use paths.py for consistent path generation with init.sh
        from claude_code_hooks_daemon.daemon.paths import get_pid_path

        return get_pid_path(workspace_root)


class CcyConfig(BaseModel):
    """Configuration for the ccy (claude-yolo) container workflow (Plan 00147).

    A single tri-state flag governing whether the daemon deploys AND arms the
    standalone PTY supervisor (``claude-supervise.py``) into a project's
    ``.claude/ccy/`` directory on install/upgrade. "Arm" means writing the
    ``CCY_CLAUDE_WRAPPER`` export into ``.claude/ccy/ccy.env`` that the ccy
    launcher sources — without it the deployed script is inert (Plan 00148).

    Attributes:
        deploy_supervisor: Tri-state deploy+arm gate.

            - ``True``  — deploy/refresh AND arm the supervisor when a
              ``.claude/ccy/`` directory exists in the target project.
            - ``False`` — never deploy or arm (explicit opt-out).
            - ``None``  — (key absent) deploy AND arm anyway when ``.claude/ccy/``
              exists, AND recommend setting the flag ``True`` via the
              config-changes advisory. Deliberately ``bool | None`` so an absent
              key is distinguishable from an explicit ``False``.

            Arming is idempotent and respects the user: an existing
            ``CCY_CLAUDE_WRAPPER`` in ``ccy.env`` (set OR commented out) is left
            untouched.
    """

    model_config = ConfigDict(extra="forbid")

    deploy_supervisor: bool | None = Field(
        default=None,
        description=(
            "Tri-state: True = deploy/refresh AND arm the ccy PTY supervisor in "
            ".claude/ccy/ on install/upgrade; False = never deploy/arm; "
            "absent (None) = deploy + arm + recommend enabling."
        ),
    )


class NeverWantToolConfig(BaseModel):
    """One project-declared never-want tool (Plan 00293).

    Attributes:
        tool: The tool name as Claude Code knows it (e.g. ``Artifact``).
        reason: Why the project never wants it — surfaced verbatim in the
            tool-report and any advisory, so write it for a human reader.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, description="Tool name as Claude Code knows it")
    reason: str = Field(default="", description="Why the project never wants this tool")


class ToolPolicyConfig(BaseModel):
    """Project tool policy for the tools-vs-tokens report (Plan 00293).

    Ships empty: the daemon must never assert a never-want the project did
    not declare. Declaring one only changes what the REPORT recommends (and,
    where a handler offers its own enforcement option, what an advisory may
    point at) — nothing is ever disabled automatically from here.

    Attributes:
        never_want: Tools this project has decided it never wants.
        low_use_max_calls: Highest total observed call count the report still
            classes as ``low-use`` (above it a tool is ``keep``).
    """

    model_config = ConfigDict(extra="forbid")

    never_want: list[NeverWantToolConfig] = Field(
        default_factory=list, description="Project-declared never-want tools"
    )
    low_use_max_calls: int = Field(
        default=2, ge=0, description="Highest total call count still classed as low-use"
    )

    def never_want_map(self) -> dict[str, str]:
        """The declarations as ``{tool: reason}`` for report building."""
        return {entry.tool: entry.reason for entry in self.never_want}


class PromotionConfig(BaseModel):
    """Data-driven handler promotion policy (Plan 00116 Decision I).

    Records which BLOCKING handlers keep their full ``get_claude_md()``
    guidance resident in the injected ``<hooksdaemon>`` block, based on
    real transcript block frequency, rather than every handler paying the
    always-on token cost. Ships empty: a fresh install has no history yet,
    so the safe default is pure progressive disclosure (every blocking
    handler reduced to a rule-table row, verbose only on first fire).

    ``bin/hooks-daemon block-report`` re-derives a RECOMMENDED promoted set
    from this project's own transcripts using ``min_blocks``/
    ``min_sessions`` as its threshold — the recommendation is advisory; the
    committed ``promoted_handlers`` list is the contract the injector
    actually reads.

    Attributes:
        promoted_handlers: Handler config keys whose guidance stays fully
            resident in the injected block.
        min_blocks: Total block count ``block-report`` uses as its
            promotion-recommendation threshold.
        min_sessions: Distinct-session count ``block-report`` uses as its
            promotion-recommendation threshold.
    """

    model_config = ConfigDict(extra="forbid")

    promoted_handlers: list[str] = Field(
        default_factory=list,
        description="Handler config keys whose guidance stays fully resident",
    )
    min_blocks: int = Field(
        default=5, ge=0, description="Block-count threshold for the promotion recommendation"
    )
    min_sessions: int = Field(
        default=2,
        ge=0,
        description="Distinct-session threshold for the promotion recommendation",
    )


class ClaudeMdConfig(BaseModel):
    """Injected-``CLAUDE.md``-block configuration (Plan 00116).

    Attributes:
        promotion: Data-driven handler promotion policy (Decision I).
    """

    model_config = ConfigDict(extra="forbid")

    promotion: PromotionConfig = Field(default_factory=PromotionConfig)


class Config(BaseModel):
    """Root configuration model for hooks daemon.

    Attributes:
        version: Configuration version string
        daemon: Daemon server configuration
        handlers: Handler configurations by event type
        plugins: Plugin system configuration
        project_handlers: Project-level handler configuration
        ccy: ccy container-workflow configuration (Plan 00147)
        layout: Project directory-layout truths with no other config home
            (Plan 00288); composed with other homes by the ``ProjectLayout``
            facade (``core/project_layout.py``)
        claude_md: Injected ``<hooksdaemon>`` block configuration, currently
            the handler-promotion policy (Plan 00116 Decision I)
    """

    model_config = ConfigDict(extra="allow")

    version: str = Field(default="2.0", pattern=r"^\d+\.\d+$")
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    handlers: HandlersConfig = Field(default_factory=HandlersConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    project_handlers: ProjectHandlersConfig = Field(default_factory=ProjectHandlersConfig)
    plan_workflow: PlanWorkflowConfig = Field(default_factory=PlanWorkflowConfig)
    documentation: DocumentationConfig = Field(default_factory=DocumentationConfig)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    projects: list[ProjectConfig] = Field(
        default_factory=list,
        description="Declared projects; empty means one project at the repository root",
    )
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    ccy: CcyConfig = Field(default_factory=CcyConfig)
    tool_policy: ToolPolicyConfig = Field(default_factory=ToolPolicyConfig)
    claude_md: ClaudeMdConfig = Field(default_factory=ClaudeMdConfig)
    pseudo_events: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Pseudo-event configurations keyed by pseudo-event name",
    )

    # Legacy field mapping
    settings: dict[str, Any] | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_projects_are_distinct(self) -> Self:
        """Reject duplicate project names and duplicate roots (Plan 00296).

        A duplicate NAME makes advisory and diagnostic output ambiguous -- two
        different trees reported under one label. A duplicate ROOT is worse:
        resolution picks the nearest declared root containing a file, and two
        entries at the same root have no defensible winner, so the answer
        would depend on config ordering.

        Nesting is NOT a duplicate and stays legal: a package inside a
        workspace is a real shape, and nearest-wins resolves it unambiguously.
        """
        seen_names: set[str] = set()
        seen_roots: set[str] = set()
        for project in self.projects:
            if project.name in seen_names:
                raise ValueError(f"duplicate project name {project.name!r} in 'projects'")
            if project.root in seen_roots:
                raise ValueError(f"duplicate project root {project.root!r} in 'projects'")
            seen_names.add(project.name)
            seen_roots.add(project.root)
        return self

    @model_validator(mode="after")
    def migrate_legacy_settings(self) -> Self:
        """Migrate legacy 'settings' to 'daemon' config."""
        if self.settings and "logging_level" in self.settings:
            self.daemon.log_level = LogLevel(self.settings["logging_level"])
        return self

    @model_validator(mode="after")
    def migrate_plan_handler_options(self) -> Self:
        """Migrate handler-level plan options to top-level plan_workflow.

        If plan_workflow was not explicitly set in the config file but
        handler options contain track_plans_in_project, create plan_workflow
        from the handler options. Top-level plan_workflow always takes
        precedence over handler options.
        """
        # If plan_workflow was explicitly set, no migration needed
        if "plan_workflow" in self.model_fields_set:
            return self

        # Check for old-format options in markdown_organization handler
        pre_tool_use = self.handlers.pre_tool_use
        md_org = pre_tool_use.get("markdown_organization")
        if md_org is None:
            return self

        if isinstance(md_org, HandlerConfig):
            options = md_org.options
        elif isinstance(md_org, dict):
            options = md_org.get("options", {})
        else:
            return self

        track_plans = options.get("track_plans_in_project")
        if track_plans:
            self.plan_workflow = PlanWorkflowConfig(
                enabled=True,
                directory=track_plans,
                workflow_docs=options.get("plan_workflow_docs", "CLAUDE/PlanWorkflow.md"),
            )
            logger.info("Migrated plan config from handler options to top-level plan_workflow")

        return self

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        """Load configuration from file.

        Args:
            path: Path to YAML or JSON config file

        Returns:
            Validated Config instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format is invalid
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with path.open() as f:
            if path.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(f) or {}
            elif path.suffix == ".json":
                import json

                data = json.load(f)
            else:
                raise ValueError(f"Unsupported format: {path.suffix}")

        return cls.model_validate(data)

    @classmethod
    def load_or_default(cls, path: str | Path | None = None) -> "Config":
        """Load configuration from file or return defaults.

        Args:
            path: Optional path to config file

        Returns:
            Config instance (from file or defaults)
        """
        if path:
            try:
                return cls.load(path)
            except FileNotFoundError:
                pass
        return cls()

    @classmethod
    def find_and_load(cls, start_dir: str | Path = ".") -> "Config":
        """Find and load configuration by searching upward.

        Looks for .claude/hooks-daemon.yaml or .claude/hooks-daemon.yml.

        Args:
            start_dir: Directory to start search from

        Returns:
            Config instance (from file or defaults)
        """
        current = Path(start_dir).resolve()

        for parent in [current, *current.parents]:
            for filename in ("hooks-daemon.yaml", "hooks-daemon.yml"):
                config_path = parent / ".claude" / filename
                if config_path.exists():
                    return cls.load(config_path)

        # Return default config if not found
        return cls()

    def to_yaml(self) -> str:
        """Serialise configuration to YAML string.

        Returns:
            YAML string representation
        """
        return yaml.safe_dump(
            self.model_dump(exclude_none=True, exclude_unset=True, mode="json"),
            default_flow_style=False,
            sort_keys=False,
        )

    def save(self, path: str | Path) -> None:
        """Save configuration to file.

        Args:
            path: Path to save configuration to
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w") as f:
            if path.suffix in (".yaml", ".yml"):
                f.write(self.to_yaml())
            elif path.suffix == ".json":
                import json

                json.dump(
                    self.model_dump(exclude_none=True, mode="json"),
                    f,
                    indent=2,
                )
            else:
                raise ValueError(f"Unsupported format: {path.suffix}")

    def get_handler_config(self, event_type: str, handler_name: str) -> HandlerConfig:
        """Get configuration for a specific handler.

        Args:
            event_type: Event type (e.g., 'pre_tool_use')
            handler_name: Handler name (snake_case)

        Returns:
            Handler configuration (defaults if not specified)
        """
        return self.handlers.get_handler_config(event_type, handler_name)
