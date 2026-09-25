"""Centralised handler registry for discovering and loading handlers.

This module provides functionality for discovering handler classes
in the handlers directory and registering them with the event router.
"""

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeGuard

from claude_code_hooks_daemon.config.models import handler_options
from claude_code_hooks_daemon.constants.config import ConfigKey, resolve_priority
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.handler_scope import resolve_scope
from claude_code_hooks_daemon.utils.vendor_paths import VendorScope

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import (
        Config,
        DocumentationConfig,
        PlanWorkflowConfig,
        ReferenceReposConfig,
        WorktreeConfig,
    )
    from claude_code_hooks_daemon.core.project_layout import ProjectLayout
    from claude_code_hooks_daemon.core.router import EventRouter
    from claude_code_hooks_daemon.core.workspace import ProjectRegistry

logger = logging.getLogger(__name__)

# Mapping from directory name to EventType. Every dispatchable EventType must be
# present so a client can drop a handler dir for it (discovery skips entries with
# no on-disk dir via is_dir guards). Plan 00170 zero-handler-passthrough events
# have no built-in dir yet — they are wired for coverage, not because we ship a
# handler.
EVENT_TYPE_MAPPING: dict[str, EventType] = {
    "pre_tool_use": EventType.PRE_TOOL_USE,
    "post_tool_use": EventType.POST_TOOL_USE,
    "session_start": EventType.SESSION_START,
    "session_end": EventType.SESSION_END,
    "pre_compact": EventType.PRE_COMPACT,
    "user_prompt_submit": EventType.USER_PROMPT_SUBMIT,
    "permission_request": EventType.PERMISSION_REQUEST,
    "notification": EventType.NOTIFICATION,
    "stop": EventType.STOP,
    "subagent_stop": EventType.SUBAGENT_STOP,
    "status_line": EventType.STATUS_LINE,
    # Plan 00170: wired zero-handler-passthrough events (no built-in dir yet).
    "setup": EventType.SETUP,
    "permission_denied": EventType.PERMISSION_DENIED,
    "cwd_changed": EventType.CWD_CHANGED,
    "worktree_create": EventType.WORKTREE_CREATE,
    "worktree_remove": EventType.WORKTREE_REMOVE,
    "user_prompt_expansion": EventType.USER_PROMPT_EXPANSION,
    "post_tool_use_failure": EventType.POST_TOOL_USE_FAILURE,
    "post_tool_batch": EventType.POST_TOOL_BATCH,
    "subagent_start": EventType.SUBAGENT_START,
    "task_created": EventType.TASK_CREATED,
    "task_completed": EventType.TASK_COMPLETED,
    "stop_failure": EventType.STOP_FAILURE,
    "teammate_idle": EventType.TEAMMATE_IDLE,
    "instructions_loaded": EventType.INSTRUCTIONS_LOADED,
    "config_change": EventType.CONFIG_CHANGE,
    "file_changed": EventType.FILE_CHANGED,
    "post_compact": EventType.POST_COMPACT,
    "elicitation": EventType.ELICITATION,
    "elicitation_result": EventType.ELICITATION_RESULT,
    "message_display": EventType.MESSAGE_DISPLAY,
}


#: A private class is a helper or a test double, never a shipped handler.
_PRIVATE_PREFIX = "_"


def event_dir_name_matches_module(event_dir_name: str, module: str) -> bool:
    """True when ``module``'s dotted path belongs to ``event_dir_name``.

    Compares path SEGMENTS (``module.split(".")``), not a raw substring —
    two real ``EVENT_TYPE_MAPPING`` entries are substrings of each other
    (``stop`` in ``subagent_stop``; ``post_tool_use`` in
    ``post_tool_use_failure``), so a plain ``event_dir_name in module`` check
    wrongly claims a ``subagent_stop`` (or ``post_tool_use_failure``)
    handler for the shorter directory too. Plan 00311 follow-up (R2/R4):
    this was fixed at one call site and missed at two others that shared the
    exact same substring bug — extracted once so a fourth copy can't drift.
    """
    if not module:
        return False
    return event_dir_name in module.split(".")


def is_discoverable_handler(attr: object) -> TypeGuard[type[Handler]]:
    """Is this module attribute a handler class discovery should register?

    The single definition of that question. It was previously written out three
    times in this module and twice more in test helpers, and two of those copies
    had drifted: one omitted the abstract check, the other substituted a
    name-based ``"Base" not in attr.__name__`` heuristic. That heuristic cannot
    work — a per-event ALIAS does not change ``__name__``, so
    ``PreCompactHandlerBase`` still reports itself as ``AdvisoryHandler``.

    Neither copy cost anything until a handler module first imported another
    ``Handler`` subclass (its event's base), at which point both began reporting
    an abstract base as a shipped handler.

    ``inspect.isabstract`` is the load-bearing condition: a base that re-declares
    ``handle`` as abstract cannot be instantiated, so it can never be a handler,
    whatever it is called or wherever it is imported.

    Args:
        attr: Any attribute read off a scanned module.

    Returns:
        True if this is a concrete, public ``Handler`` subclass.
    """
    return (
        isinstance(attr, type)
        and issubclass(attr, Handler)
        and attr is not Handler
        and not attr.__name__.startswith(_PRIVATE_PREFIX)
        and not inspect.isabstract(attr)
    )


def _vendor_scopes_for_policy(
    project_registry: "ProjectRegistry | None",
    project_layout: "ProjectLayout | None",
) -> tuple[VendorScope, ...] | None:
    """Vendor scopes for the docs policy, from whichever facade is available.

    The registry is preferred: only it knows each declared project's root, so
    only it can express a monorepo sub-project's vendor truth (Plan 00332).

    Falling back to the ROOT LAYOUT rather than to None is load-bearing.
    ``register_all`` takes the two facades independently, so a caller may
    pass a layout and no registry -- and returning None there would hand the
    policy the canonical built-in set, silently discarding a declared
    ``layout.vendor_dirs``. That is precisely the inert-config defect Plan
    00331 existed to fix, so reintroducing it as a fallback path would undo
    that plan for any such caller.

    Returns:
        Scopes, or None when neither facade was supplied (the caller then
        keeps the canonical default, which is the correct answer for "no
        layout information available at all").
    """
    if project_registry is not None:
        return project_registry.vendor_scopes()
    if project_layout is None:
        return None
    return (
        VendorScope(
            root="",
            vendor_dirs=project_layout.vendor_dirs,
            vendor_exceptions=project_layout.vendor_exceptions,
        ),
    )


@dataclass(frozen=True, slots=True)
class BuiltinHandlerRef:
    """One built-in handler as ``register_all`` would address it.

    ``event_dir`` and ``config_key`` together form the ``handlers.<event>.<key>``
    config path, which is the name every reporting surface must use.
    """

    event_dir: str
    config_key: str
    handler_cls: type[Handler]


def iter_builtin_handler_classes() -> Iterator[BuiltinHandlerRef]:
    """Every built-in handler class, keyed the way ``register_all`` keys it.

    Plan 00330: the config-optimisation checklist is derived from this
    walk, so it enumerates exactly what registration enumerates — the same
    event directories, the same ``*.py`` glob, the same discoverability
    test and the same config-key derivation. A handler visible to one and
    not the other would be a handler that can be registered but never
    reviewed, which is the gap the derivation exists to close.

    Imports fail fast, as they do in ``register_all``: a production handler
    that cannot import is a defect to surface, not to skip.
    """
    handlers_dir = Path(__file__).parent
    for dir_name in EVENT_TYPE_MAPPING:
        event_dir = handlers_dir / dir_name
        # eacces-safe-exempt: the daemon's OWN installed source tree.
        if not event_dir.is_dir():
            continue
        for py_file in sorted(event_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module = importlib.import_module(
                f"claude_code_hooks_daemon.handlers.{dir_name}.{py_file.stem}"
            )
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if is_discoverable_handler(attr):
                    yield BuiltinHandlerRef(
                        event_dir=dir_name,
                        config_key=_get_config_key(attr.__name__),
                        handler_cls=attr,
                    )


def config_skip_reason(
    handler_config: Mapping[str, Any] | None, *, registry_disabled: bool
) -> str | None:
    """Why the pre-construction gates exclude a handler, or None if they do not.

    The first two of :meth:`HandlerRegistry.register_all`'s four enablement
    gates. They are decided BEFORE the handler is built, because a handler
    that is off must never have its constructor run.

    Args:
        handler_config: The ``handlers.<event>.<key>`` block. Absent means
            ENABLED — registration defaults ``enabled`` to True — and so does
            ``None``, which is what a bare ``key:`` parses to in YAML.
        registry_disabled: :meth:`HandlerRegistry.is_disabled` for this
            handler class. Runtime state rather than config, which is why a
            caller that has no registry passes False.

    Returns:
        A short reason naming the gate, or None when neither excludes it.
    """
    block = handler_config if isinstance(handler_config, Mapping) else {}
    if not block.get(ConfigKey.ENABLED, True):
        return "disabled by config"
    if registry_disabled:
        return "disabled in the registry"
    return None


def tag_skip_reason(event_config: Mapping[str, Any] | None, tags: Collection[str]) -> str | None:
    """Why the tag gates exclude a handler carrying ``tags``, or None if they do not.

    The other two gates. These need the INSTANCE's tags, so they are decided
    after construction — which is why this is a second function rather than
    one predicate taking everything.

    ``enable_tags`` is judged TRUTHY, not list-shaped: a scalar
    ``enable_tags: safety`` in YAML is a string, iterates as characters,
    matches no handler and takes the whole event dark. That is what
    registration does, so a reporting surface has to reproduce it rather than
    read the same config more charitably and disagree with the daemon.

    Args:
        event_config: The ``handlers.<event>`` block carrying the tag filters.
        tags: The handler instance's own tags.

    Returns:
        A short reason naming the gate, or None when neither excludes it.
    """
    block = event_config if isinstance(event_config, Mapping) else {}
    enable_tags = block.get(ConfigKey.ENABLE_TAGS)
    if enable_tags and not any(tag in tags for tag in enable_tags):
        return f"no matching tags in enable_tags {enable_tags}"
    disable_tags_raw: Any = block.get(ConfigKey.DISABLE_TAGS, [])
    disable_tags: list[str] = disable_tags_raw if isinstance(disable_tags_raw, list) else []
    if disable_tags and any(tag in tags for tag in disable_tags):
        return f"has tag in disable_tags {disable_tags}"
    return None


def handler_is_enabled(
    event_config: Mapping[str, Any] | None,
    config_key: str,
    tags: Collection[str],
    *,
    registry_disabled: bool = False,
) -> bool:
    """Whether ``register_all`` would register this handler for this config.

    All four gates, in one call, for a caller that already has the handler's
    tags — the config-optimisation checklist, which must report exactly what
    the daemon runs. Registration itself applies the two halves separately
    because it decides the first pair before constructing the handler.
    """
    block = event_config if isinstance(event_config, Mapping) else {}
    return (
        config_skip_reason(block.get(config_key), registry_disabled=registry_disabled) is None
        and tag_skip_reason(block, tags) is None
    )


def apply_handler_options(instance: object, options: Mapping[str, Any]) -> None:
    """Give ``instance`` its options the way ``register_all`` does: ``self._<key>``.

    Handlers are constructed with no arguments and read their options from
    these attributes, so a handler built anywhere else without this call runs
    on its defaults. That is how ``remote-docs add`` scanned captures with no
    public patterns at all (Plan 00466 N15).
    """
    for option_key, option_value in options.items():
        setattr(instance, f"_{option_key}", option_value)


def build_handler_config_mapping(config: "Config") -> dict[str, dict[str, Any]]:
    """Build the per-event handler_config mapping passed to ``register_all``.

    Derived from every field on the ``HandlersConfig`` model rather than a
    hand-maintained list inlined here, so any event type the model declares —
    ``status_line`` included, whose omission from the old inline list was the
    original bug — is covered automatically. A missing event type here makes
    ``register_all`` fall back to ``enabled=True`` for every handler in that
    group, which is exactly what made ``handlers.status_line.<name>.enabled:
    false`` inert.

    ``HandlersConfig`` declares one field per WIRED event and refuses to
    import otherwise (``_check_wired_event_field_coverage``), so iterating its
    fields IS iterating the event registry: config under any wired event
    reaches the registry whether or not a built-in handler directory exists
    for it yet.

    Each event's values are ``HandlerConfig`` instances (coerced by the model);
    they are dumped to plain dicts because the registry reads them with
    ``dict.get(...)``. Tag-filter keys (``enable_tags`` / ``disable_tags``) are
    preserved as-is (lists), not dumped.

    Lives here (RV8-m2), not in ``daemon.cli``, so a handler-side gate (e.g.
    ``plan_status_snapshot``'s ``_goal_injection_enabled``) that needs this
    mapping does not have to import a CLI module to get it — ``daemon.cli``
    itself now delegates to this function rather than the other way round.

    Args:
        config: Loaded daemon configuration.

    Returns:
        Mapping of event-type config key -> {handler_key -> settings dict}.
    """
    from claude_code_hooks_daemon.config.models import HandlerConfig, HandlersConfig

    mapping: dict[str, dict[str, Any]] = {}
    for event_key in HandlersConfig.model_fields:
        event_config = getattr(config.handlers, event_key, {})
        if not isinstance(event_config, dict):
            continue
        mapping[event_key] = {
            handler_key: (value.model_dump() if isinstance(value, HandlerConfig) else value)
            for handler_key, value in event_config.items()
        }
    return mapping


class HandlerRegistry:
    """Registry for discovering and managing handlers.

    Discovers handler classes from the handlers package and
    registers them with the event router.
    """

    __slots__ = ("_disabled_handlers", "_handlers", "_option_failures", "_workspace_root")

    def __init__(self) -> None:
        """Initialise empty registry."""
        self._handlers: dict[str, type[Handler]] = {}
        self._disabled_handlers: set[str] = set()
        self._workspace_root: Path | None = None
        self._option_failures: dict[str, str] = {}

    @property
    def option_failures(self) -> dict[str, str]:
        """Handlers whose configured options could not be collected, and why.

        Keyed ``<EventType>.<config_key>``. Each one was registered on its
        defaults, so ``health`` reports it as degraded protection.
        """
        return dict(self._option_failures)

    def discover(self, package_path: str = "claude_code_hooks_daemon.handlers") -> int:
        """Discover all handler classes in the handlers package.

        Scans all subpackages (pre_tool_use, post_tool_use, etc.) and
        loads all Handler subclasses found.

        Args:
            package_path: Python package path to scan

        Returns:
            Number of handlers discovered
        """
        try:
            package = importlib.import_module(package_path)
        except ImportError:
            logger.warning("Could not import handlers package: %s", package_path)
            return 0

        if not hasattr(package, "__path__"):
            logger.warning("Package %s has no __path__", package_path)
            return 0

        count = 0
        for _importer, modname, ispkg in pkgutil.walk_packages(
            package.__path__,
            prefix=f"{package_path}.",
        ):
            if ispkg:
                continue

            # Skip __init__ modules and test files
            if modname.endswith("__init__") or "test" in modname:
                continue

            try:
                module = importlib.import_module(modname)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if is_discoverable_handler(attr):
                        self._handlers[attr.__name__] = attr
                        count += 1
                        logger.debug("Discovered handler: %s", attr.__name__)
            except Exception as e:
                logger.warning("Failed to load module %s: %s", modname, e)

        logger.info("Discovered %d handlers", count)
        return count

    def disable(self, handler_name: str) -> None:
        """Disable a handler by name.

        Disabled handlers will not be registered with the router.

        Args:
            handler_name: Name of handler class to disable
        """
        self._disabled_handlers.add(handler_name)

    def enable(self, handler_name: str) -> None:
        """Enable a previously disabled handler.

        Args:
            handler_name: Name of handler class to enable
        """
        self._disabled_handlers.discard(handler_name)

    def is_disabled(self, handler_name: str) -> bool:
        """Check if a handler is disabled.

        Args:
            handler_name: Name of handler class

        Returns:
            True if handler is disabled
        """
        return handler_name in self._disabled_handlers

    def get_handler_class(self, name: str) -> type[Handler] | None:
        """Get a handler class by name.

        Args:
            name: Handler class name

        Returns:
            Handler class or None if not found
        """
        return self._handlers.get(name)

    def list_handlers(self) -> list[str]:
        """List all discovered handler class names.

        Returns:
            List of handler class names
        """
        return list(self._handlers.keys())

    def register_all(
        self,
        router: "EventRouter",
        *,
        config: Mapping[str, Mapping[str, Any]] | None = None,
        workspace_root: Path | None = None,
        project_languages: list[str] | None = None,
        project_exclude_paths: list[str] | None = None,
        plan_workflow: "PlanWorkflowConfig | None" = None,
        documentation: "DocumentationConfig | None" = None,
        project_layout: "ProjectLayout | None" = None,
        project_registry: "ProjectRegistry | None" = None,
        worktree: "WorktreeConfig | None" = None,
        reference_repos: "ReferenceReposConfig | None" = None,
    ) -> int:
        """Register all discovered handlers with the router.

        Uses a two-pass algorithm to support handler options inheritance:
        1. First pass: collect all handler options into options_registry
        2. Second pass: instantiate handlers and apply inherited options

        Args:
            router: Event router to register handlers with
            config: Optional handler configuration from hooks-daemon.yaml
            workspace_root: Optional workspace root path for handlers
            project_languages: Project-level language filter from daemon.languages config
            plan_workflow: Optional PlanWorkflowConfig for plan-related handlers
            documentation: Optional DocumentationConfig for documentation-related handlers
            project_layout: Optional ProjectLayout facade (Plan 00288) injected
                onto every handler instance, mirroring project_exclude_paths
            project_registry: Optional ProjectRegistry facade (Plan 00296)
                injected onto every handler instance, mirroring project_layout
            worktree: Optional WorktreeConfig (Plan 00367) for git-tagged
                handlers; its merge-to-main toggle is injected as
                ``_merge_to_main_requires_human_approval``
            reference_repos: Optional ReferenceReposConfig (Plan 00401),
                injected as ``_reference_repos`` onto handlers that DECLARE
                that attribute — attribute-selected rather than tag-selected,
                because the two handlers that want it already carry the broad
                ``git`` tag shared by handlers that do not

        Returns:
            Number of handlers registered
        """
        # Store workspace_root for handler initialization
        if workspace_root:
            self._workspace_root = workspace_root

        # PASS 1: Collect all handler options
        options_registry: dict[str, dict[str, Any]] = {}
        self._option_failures = {}
        handlers_dir = Path(__file__).parent

        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_dir = handlers_dir / dir_name
            # eacces-safe-exempt: the daemon's OWN installed source tree
            # (`Path(__file__).parent`). Unreadable here means it cannot load
            # its own handlers, which must surface rather than be absorbed.
            if not event_dir.is_dir():
                continue

            event_config = (config or {}).get(dir_name) or {}

            # sorted(): ledger 00466 N7/m6 -- os.scandir order (what a bare
            # .glob() yields) is not guaranteed stable across processes or
            # machines, so an unsorted walk here is the actual source of the
            # registration-order nondeterminism the CLAUDE.md/HOOKS-DAEMON.md
            # rendering-layer sorts were compensating for. Matches the
            # existing pattern at line 198 above.
            for py_file in sorted(event_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue

                module_name = f"claude_code_hooks_daemon.handlers.{dir_name}.{py_file.stem}"

                # FAIL FAST: If a production handler fails to import, that's a critical error
                # Test fixtures are loaded separately via plugins, not through this path
                module = importlib.import_module(module_name)

                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if is_discoverable_handler(attr):
                        config_key = _get_config_key(attr.__name__)
                        handler_config = event_config.get(config_key, {})
                        if handler_config.get(ConfigKey.ENABLED, True):
                            registry_key = f"{event_type.value}.{config_key}"
                            # handler_options reads every block shape without
                            # raising, so any exception here is a daemon
                            # defect. Plan 00466 N19: one such defect once
                            # dropped EVERY handler's options behind a
                            # debug-level log line. The handler still runs on
                            # its defaults, and health reports it degraded.
                            try:
                                options = handler_options(handler_config)
                            except Exception as exc:
                                logger.error(
                                    "Options for handler '%s' could not be collected;"
                                    " it runs on its defaults",
                                    registry_key,
                                    exc_info=True,
                                )
                                self._option_failures[registry_key] = f"{type(exc).__name__}: {exc}"
                                continue
                            # Include workspace_root in options if available
                            if self._workspace_root:
                                options["workspace_root"] = self._workspace_root
                            options_registry[registry_key] = options

        # PASS 2: Register handlers with inherited options
        count = 0

        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_dir = handlers_dir / dir_name
            # eacces-safe-exempt: same daemon-owned source tree as PASS 1.
            if not event_dir.is_dir():
                continue

            # Get configuration for this event type
            event_config = (config or {}).get(dir_name) or {}

            # Find all Python files in the directory (sorted(): see PASS 1 above)
            for py_file in sorted(event_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue

                module_name = f"claude_code_hooks_daemon.handlers.{dir_name}.{py_file.stem}"

                # FAIL FAST: same contract as Pass 1's import of this module - a
                # production handler that fails to import is a critical error and
                # must crash the daemon loudly, not be silently disabled. Project
                # handlers use a separate tolerant loader
                # (handlers/project_loader.py) that is unaffected by this.
                module = importlib.import_module(module_name)

                # Find Handler subclasses in the module
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if is_discoverable_handler(attr):
                        # Check handler-specific config (use config key from HandlerID constant)
                        config_key = _get_config_key(attr.__name__)
                        # `or {}`: a bare `key:` in YAML parses to None, and the
                        # options/priority reads below need a mapping either way.
                        handler_config = event_config.get(config_key) or {}

                        # Gates 1 and 2, from the shared predicate the
                        # config-optimisation checklist reports with, so the
                        # report can never disagree with what runs here.
                        skip = config_skip_reason(
                            handler_config, registry_disabled=self.is_disabled(attr.__name__)
                        )
                        if skip is not None:
                            logger.debug("Handler %s skipped - %s", attr.__name__, skip)
                            continue

                        try:
                            # Instantiate and register
                            # Handler subclasses override __init__ with no args
                            instance = attr()

                            # Gates 3 and 4, same shared predicate: they need
                            # the instance's tags, so they run after construction.
                            tag_skip = tag_skip_reason(event_config, instance.tags)
                            if tag_skip is not None:
                                logger.debug("Handler %s skipped - %s", attr.__name__, tag_skip)
                                continue

                            # Override priority from config, falling back to the
                            # handler's own default when absent OR None (PyYAML
                            # parses a bare 'priority:' as None — Plan 00070; a
                            # model_dump() None is Plan 00282). One shared helper
                            # across dispatch + both doc generators.
                            instance.priority = resolve_priority(handler_config, instance.priority)

                            # Where this handler is active (Plan 00423), same
                            # shape as priority: config overrides the handler's
                            # own default, a bare `scope:` (None) keeps it.
                            # resolve_scope still raises on an unknown value
                            # rather than falling back, but that raise lands
                            # inside this method's own `except Exception`
                            # below, which logs a warning and skips the
                            # handler — it does not, by itself, stop a typo
                            # from quietly widening a scope. The real refusal
                            # happens earlier, at config load: pydantic's
                            # `HandlerConfig.scope` field (config/models.py)
                            # rejects an unknown value there, before this
                            # instantiation loop ever runs.
                            instance.scope = resolve_scope(handler_config, instance.scope)

                            # Apply options inheritance if handler shares options with parent
                            registry_key = f"{event_type.value}.{config_key}"
                            own_options = options_registry.get(registry_key, {})

                            if instance.shares_options_with:
                                # Get parent options
                                parent_key = f"{event_type.value}.{instance.shares_options_with}"
                                parent_options = options_registry.get(parent_key, {})
                                # Merge: parent options + child overrides
                                merged_options = {**parent_options, **own_options}
                            else:
                                merged_options = own_options

                            apply_handler_options(instance, merged_options)

                            # Inject project-level language filter (via setattr like other options)
                            instance._project_languages = project_languages

                            # Inject project-level path-exclusion default (Plan 00150) so the
                            # content blockers inherit daemon.exclude_paths on top of their own.
                            instance._project_exclude_paths = project_exclude_paths

                            # Inject the ProjectLayout facade (Plan 00288) so handlers can
                            # read directory-role truths from one API instead of
                            # hardcoding or re-declaring them.
                            instance._project_layout = project_layout

                            # Inject the ProjectRegistry facade (Plan 00296) so handlers can
                            # resolve a file's workspace from declared projects instead of
                            # assuming a single project root.
                            instance._project_registry = project_registry

                            # Inject plan_workflow config for planning-tagged handlers
                            # This overrides any handler-level options (top-level is source of truth)
                            # Uses dynamic setattr pattern (same as handler options) for type safety
                            if plan_workflow is not None and "planning" in instance.tags:
                                # plan_qa (Plan 00144): the nested QA policy rides the
                                # same injection so all plan-QA surfaces share one object.
                                plan_attrs: dict[str, object] = {
                                    "track_plans_in_project": (
                                        plan_workflow.directory if plan_workflow.enabled else None
                                    ),
                                    "plan_workflow_docs": (
                                        plan_workflow.workflow_docs
                                        if plan_workflow.enabled
                                        else None
                                    ),
                                    "enforce_claude_code_sync": (
                                        plan_workflow.enforce_claude_code_sync
                                        if plan_workflow.enabled
                                        else False
                                    ),
                                    "plan_qa": (
                                        plan_workflow.qa if plan_workflow.enabled else None
                                    ),
                                    # Plan 00367: the plan-closing gate's toggle.
                                    "close_requires_human_approval": (
                                        plan_workflow.close_requires_human_approval
                                        if plan_workflow.enabled
                                        else False
                                    ),
                                }
                                for attr_key, attr_val in plan_attrs.items():
                                    setattr(instance, f"_{attr_key}", attr_val)

                            # Inject the reference-repo policy (Plan 00401).
                            # Selected by DECLARED ATTRIBUTE rather than by tag:
                            # the sweep and the backstop are the only handlers
                            # that want it, and they already carry the broad
                            # "git" tag, so tag-matching would hand the block to
                            # every git handler that has no use for it. A
                            # handler opts in by declaring `_reference_repos`.
                            reference_repos_attr_name = "_reference_repos"
                            if reference_repos is not None and hasattr(
                                instance, reference_repos_attr_name
                            ):
                                setattr(instance, reference_repos_attr_name, reference_repos)

                            # Pass-1 option failures (Plan 00466 N19), for the
                            # session-start alert. Same declared-attribute
                            # selection as `_reference_repos` above.
                            option_failures_attr_name = "_option_failures"
                            if hasattr(instance, option_failures_attr_name):
                                setattr(instance, option_failures_attr_name, self.option_failures)

                            # Inject the worktree merge-gate toggle for git-tagged
                            # handlers (Plan 00367 Phase 4) -- same DI idiom as
                            # plan_workflow above; absent config means gate off.
                            if worktree is not None and "git" in instance.tags:
                                merge_attr_name = "_merge_to_main_requires_human_approval"
                                setattr(
                                    instance,
                                    merge_attr_name,
                                    worktree.merge_to_main_requires_human_approval,
                                )

                            # Inject documentation config for documentation-tagged
                            # handlers (Plan 00284) -- same DI idiom as plan_workflow
                            # above. Injects a plain-values policy (built once here,
                            # not per-dispatch) so handlers never touch pydantic.
                            if documentation is not None and "documentation" in instance.tags:
                                from claude_code_hooks_daemon.docs_qa.policy import (
                                    policy_from_config,
                                )
                                from claude_code_hooks_daemon.plan_links import (
                                    plan_tree_layout,
                                )

                                # The vendor truth travels WITH the policy
                                # (Plan 00331). Injecting the two
                                # independently is what left a declared
                                # `layout.vendor_dirs` inert: docs QA's
                                # exclusion reads the policy, so a layout the
                                # handler also holds never reached the check.
                                #
                                # Sourced from the REGISTRY, not the root
                                # layout (Plan 00332): the root layout can
                                # only say what the repository as a whole
                                # calls vendored, so a monorepo sub-project's
                                # declaration was inert here for exactly the
                                # same reason.
                                # setattr via a variable attribute name, not a direct
                                # attribute assignment: unlike `_project_languages` et
                                # al., `_documentation` is not declared on the shared
                                # `Handler` base (each documentation-tagged handler
                                # declares its own), so `instance` (typed `Handler`)
                                # has no such attribute for mypy to check -- the same
                                # reason the `merged_options`/`plan_attrs` blocks
                                # above use `setattr`. Read from a variable, not a
                                # literal, so it is not the constant-attribute form
                                # ruff (B010) flags as a plain assignment in disguise.
                                doc_attr_name = "_documentation"
                                setattr(
                                    instance,
                                    doc_attr_name,
                                    policy_from_config(
                                        documentation,
                                        vendor_scopes=_vendor_scopes_for_policy(
                                            project_registry, project_layout
                                        ),
                                        # Same argument as the vendor truth
                                        # (Plan 00362 Task 2.9): docs QA's
                                        # scope judgement reads the policy,
                                        # so `_project_exclude_paths` on the
                                        # instance alone could never reach it.
                                        exclude_paths=project_exclude_paths,
                                        # The plan tree's shape (Plan 00419
                                        # N2), for the corpus's archive
                                        # exclusion and the archive-aware
                                        # link resolver -- both of which read
                                        # the policy, so the same argument
                                        # applies a third time. No config
                                        # means the shipped defaults, which
                                        # are the config model's own.
                                        plan_tree=(
                                            plan_tree_layout(plan_workflow)
                                            if plan_workflow is not None
                                            else None
                                        ),
                                    ),
                                )

                            router.register(event_type, instance)
                            count += 1
                            logger.debug(
                                "Registered %s for %s (priority=%d, tags=%s)",
                                attr.__name__,
                                event_type.value,
                                instance.priority,
                                instance.tags,
                            )
                        except Exception as e:
                            logger.warning("Failed to instantiate %s: %s", attr.__name__, e)

        logger.info("Registered %d handlers with router", count)
        return count


def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case.

    Args:
        name: CamelCase string

    Returns:
        snake_case string with _handler suffix stripped
    """
    import re

    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    # Strip _handler suffix to match config keys
    if snake.endswith("_handler"):
        snake = snake[:-8]  # Remove "_handler"

    return snake


def _get_config_key_from_constant(class_name: str) -> str | None:
    """Look up config_key from HandlerID constant by class name.

    Args:
        class_name: Handler class name (e.g., "DestructiveGitHandler")

    Returns:
        config_key from HandlerID constant, or None if not found
    """
    from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

    # Build reverse mapping: class_name -> HandlerID constant
    for attr_name in dir(HandlerID):
        if attr_name.startswith("_"):
            continue

        attr = getattr(HandlerID, attr_name)
        if isinstance(attr, HandlerIDMeta) and attr.class_name == class_name:
            return str(attr.config_key)

    return None


def _get_config_key(class_name: str) -> str:
    """Get config key for a handler class.

    Uses HandlerID constants as single source of truth, with fallback to
    auto-generation for backward compatibility.

    Args:
        class_name: Handler class name (e.g., "DestructiveGitHandler")

    Returns:
        config_key for use in YAML config
    """
    # PRIMARY: Look up in HandlerID constants (single source of truth)
    constant_key = _get_config_key_from_constant(class_name)
    if constant_key is not None:
        return constant_key

    # FALLBACK: Auto-generate with deprecation warning
    auto_key = _to_snake_case(class_name)
    logger.warning(
        "Handler %s not found in HandlerID constants, using auto-generated key '%s'. "
        "Add a HandlerID constant for this handler.",
        class_name,
        auto_key,
    )
    return auto_key


# Global registry instance
_registry: HandlerRegistry | None = None


def get_registry() -> HandlerRegistry:
    """Get the global handler registry.

    Creates the registry on first access and discovers handlers.

    Returns:
        Global HandlerRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = HandlerRegistry()
        _registry.discover()
    return _registry
