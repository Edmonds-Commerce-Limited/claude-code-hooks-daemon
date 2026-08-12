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

    path: str = Field(description="Path to plugin")
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
        paths: Additional paths to search for plugins
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
        description="Path to project handlers directory (relative to workspace root)",
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
            ({README.md, CLAUDE.md, mkplan.bash, _TEMPLATE_.md}); default empty
            = today's behaviour. Use for a legitimately-placed shared file such
            as a sourced ``_planlib.bash`` shell library.
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


class DaemonConfig(BaseModel):
    """Configuration for the daemon server.

    Attributes:
        idle_timeout_seconds: Seconds of inactivity before shutdown
        log_level: Logging level
        socket_path: Custom socket path (None = auto)
        pid_file_path: Custom PID file path (None = auto)
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
    enable_hello_world_handlers: bool = Field(
        default=False,
        description="Enable hello world test handlers",
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
    languages: list[str] | None = Field(
        default=None,
        description="Project-level language filter. When set, only handlers for these languages are active. None = ALL languages.",
    )
    exclude_paths: list[str] = Field(
        default_factory=list,
        description="Project-level glob patterns exempted from the content-scanning blockers (security_antipattern, qa_suppression, error_hiding_blocker, sensitive_content). Gitignore-style globs (*, ?, **). Inherited by all four handlers in addition to their own exclude_paths option and built-in defaults.",
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


class Config(BaseModel):
    """Root configuration model for hooks daemon.

    Attributes:
        version: Configuration version string
        daemon: Daemon server configuration
        handlers: Handler configurations by event type
        plugins: Plugin system configuration
        project_handlers: Project-level handler configuration
        ccy: ccy container-workflow configuration (Plan 00147)
    """

    model_config = ConfigDict(extra="allow")

    version: str = Field(default="2.0", pattern=r"^\d+\.\d+$")
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    handlers: HandlersConfig = Field(default_factory=HandlersConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    project_handlers: ProjectHandlersConfig = Field(default_factory=ProjectHandlersConfig)
    plan_workflow: PlanWorkflowConfig = Field(default_factory=PlanWorkflowConfig)
    ccy: CcyConfig = Field(default_factory=CcyConfig)
    pseudo_events: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Pseudo-event configurations keyed by pseudo-event name",
    )

    # Legacy field mapping
    settings: dict[str, Any] | None = Field(default=None, exclude=True)

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
