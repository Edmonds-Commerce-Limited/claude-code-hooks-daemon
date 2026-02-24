"""DaemonController for managing the hooks daemon lifecycle.

This module provides the DaemonController class that manages the
event router, handler registration, and request processing.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.config.validator import ConfigValidator
from claude_code_hooks_daemon.constants.modes import DaemonMode, ModeConstant
from claude_code_hooks_daemon.core.chain import ChainExecutionResult
from claude_code_hooks_daemon.core.data_layer import get_data_layer
from claude_code_hooks_daemon.core.event import EventType, HookEvent
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.core.mode import ModeManager
from claude_code_hooks_daemon.core.mode_interceptor import get_interceptor_for_mode
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import (
        DaemonConfig,
        PluginsConfig,
        ProjectHandlersConfig,
    )

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DaemonStats:
    """Statistics for daemon operation.

    Attributes:
        start_time: When daemon started
        requests_processed: Total requests processed
        requests_by_event: Requests grouped by event type
        total_processing_time_ms: Cumulative processing time
        errors: Total errors encountered
        last_request_time: Time of last request
    """

    start_time: datetime = field(default_factory=datetime.now)
    requests_processed: int = 0
    requests_by_event: dict[str, int] = field(default_factory=dict)
    total_processing_time_ms: float = 0.0
    errors: int = 0
    last_request_time: datetime | None = None

    def record_request(self, event_type: str, processing_time_ms: float) -> None:
        """Record a processed request.

        Args:
            event_type: Event type that was processed
            processing_time_ms: Processing time in milliseconds
        """
        self.requests_processed += 1
        self.requests_by_event[event_type] = self.requests_by_event.get(event_type, 0) + 1
        self.total_processing_time_ms += processing_time_ms
        self.last_request_time = datetime.now()

    def record_error(self) -> None:
        """Record an error."""
        self.errors += 1

    @property
    def uptime_seconds(self) -> float:
        """Get daemon uptime in seconds."""
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def avg_processing_time_ms(self) -> float:
        """Get average processing time in milliseconds."""
        if self.requests_processed == 0:
            return 0.0
        return self.total_processing_time_ms / self.requests_processed

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary.

        Returns:
            Dictionary representation of stats
        """
        return {
            "start_time": self.start_time.isoformat(),
            "uptime_seconds": round(self.uptime_seconds, 2),
            "requests_processed": self.requests_processed,
            "requests_by_event": self.requests_by_event,
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
            "errors": self.errors,
            "last_request_time": (
                self.last_request_time.isoformat() if self.last_request_time else None
            ),
        }


class DaemonController:
    """Controller for the hooks daemon.

    Manages the event router, handler registration, and request processing.
    Provides a single entry point for processing hook events.
    """

    __slots__ = (
        "_config",
        "_config_errors",
        "_degraded",
        "_initialised",
        "_mode_manager",
        "_registry",
        "_router",
        "_stats",
    )

    def __init__(self, config: "DaemonConfig | None" = None) -> None:
        """Initialise daemon controller.

        Args:
            config: Optional daemon configuration
        """
        self._router = EventRouter()
        self._registry = HandlerRegistry()
        self._config = config
        self._stats = DaemonStats()
        self._initialised = False
        self._degraded = False
        self._config_errors: list[str] = []
        self._mode_manager = self._init_mode_manager(config)

    def initialise(
        self,
        handler_config: dict[str, dict[str, dict[str, Any]]] | None = None,
        workspace_root: Path | None = None,
        plugins_config: "PluginsConfig | None" = None,
        project_handlers_config: "ProjectHandlersConfig | None" = None,
        project_languages: list[str] | None = None,
    ) -> None:
        """Initialise the controller with handlers.

        Discovers and registers all handlers with the event router,
        then loads any configured plugins and project handlers.

        Args:
            handler_config: Optional handler configuration from hooks-daemon.yaml
            workspace_root: Optional workspace root path (FAIL FAST if None)
            plugins_config: Optional plugin configuration from hooks-daemon.yaml
            project_handlers_config: Optional project handlers configuration
            project_languages: Project-level language filter from daemon.languages config

        Raises:
            ValueError: If workspace_root is None (FAIL FAST requirement)
        """
        if self._initialised:
            logger.warning("DaemonController already initialised")
            return

        # FAIL FAST: workspace_root is required
        if workspace_root is None:
            raise ValueError(
                "workspace_root is required for DaemonController initialization. "
                "This indicates a bug in daemon startup."
            )

        logger.info("Initialising DaemonController")

        # Initialize ProjectContext singleton (single source of truth for project-level constants)
        # May already be initialized from CLI config validation
        config_path = workspace_root / ".claude" / "hooks-daemon.yaml"
        if not ProjectContext._initialized:
            ProjectContext.initialize(config_path)
            logger.info("ProjectContext initialized from config: %s", config_path)
        else:
            logger.info("ProjectContext already initialized")

        # Discover and register built-in handlers
        self._registry.discover()
        count = self._registry.register_all(
            self._router,
            config=handler_config,
            workspace_root=workspace_root,
            project_languages=project_languages,
        )

        logger.info("Registered %d built-in handlers", count)

        # Load and register plugin handlers
        plugin_count = 0
        if plugins_config is not None:
            plugin_count = self._load_plugins(plugins_config, workspace_root)
            logger.info("Loaded %d plugin handlers", plugin_count)

        # Load and register project handlers
        project_count = 0
        if project_handlers_config is not None:
            project_count = self._load_project_handlers(
                project_handlers_config=project_handlers_config,
                workspace_root=workspace_root,
            )
            logger.info("Loaded %d project handlers", project_count)

        total_count = count + plugin_count + project_count
        logger.info("DaemonController initialised with %d total handlers", total_count)
        self._initialised = True

        # Validate configuration at startup (fail-open: degraded mode on errors)
        self._validate_config(config_path)

    def _load_plugins(self, plugins_config: "PluginsConfig", workspace_root: Path) -> int:
        """Load and register plugin handlers.

        Loads handlers from plugin configuration and registers them with
        the appropriate event type's handler chain.

        Args:
            plugins_config: Plugin configuration from hooks-daemon.yaml
            workspace_root: Workspace root path for resolving relative paths

        Returns:
            Number of plugin handlers loaded and registered
        """
        from claude_code_hooks_daemon.plugins.loader import PluginLoader

        # Load all handlers from plugins config
        handlers = PluginLoader.load_from_plugins_config(plugins_config, workspace_root)

        if not handlers:
            logger.debug("No plugin handlers loaded")
            return 0

        # Build mapping from plugin path to event_type for registration
        # PluginConfig has event_type field that tells us where to register
        path_to_event_type: dict[str, str] = {}
        for plugin in plugins_config.plugins:
            if plugin.enabled:
                # Use the path as key (snake_case module name)
                path_to_event_type[plugin.path] = plugin.event_type

        registered_count = 0
        for handler in handlers:
            # Determine which event type to register this handler for
            # The handler.name comes from the Handler.__init__(name=...) call
            # We need to find which plugin config matches this handler
            event_type_str: str | None = None

            # Try to find matching plugin config by checking all paths
            for plugin in plugins_config.plugins:
                if not plugin.enabled:
                    continue

                # Check if this handler came from this plugin
                # The handler name is set by the handler itself, so we need to
                # match based on the plugin path (module name)
                plugin_module = Path(plugin.path).stem
                # The handler class name would be PascalCase of the module name
                expected_class = PluginLoader.snake_to_pascal(plugin_module)
                expected_class_with_suffix = f"{expected_class}Handler"

                # Check both base class name and with Handler suffix
                # This mirrors the logic in PluginLoader.load_handler() which tries both variants
                if handler.__class__.__name__ in (expected_class, expected_class_with_suffix):
                    event_type_str = plugin.event_type
                    break

            if event_type_str is None:
                # FAIL FAST: If a configured plugin handler can't be registered, CRASH
                # Users MUST know their protection is down - silent failures are unacceptable
                raise RuntimeError(
                    f"Failed to register plugin handler '{handler.name}' "
                    f"(class: {handler.__class__.__name__}). "
                    f"Could not match handler class to any plugin configuration entry. "
                    f"This indicates a mismatch between the loaded handler and the plugin config. "
                    f"Check your plugin configuration in .claude/hooks-daemon.yaml."
                )

            # Convert event type string to EventType enum
            try:
                event_type = EventType.from_string(event_type_str)
            except ValueError as e:
                # FAIL FAST: Invalid event type in config is a fatal error
                raise RuntimeError(
                    f"Invalid event type '{event_type_str}' for plugin handler '{handler.name}'. "
                    f"Event type must be one of: {', '.join(et.value for et in EventType)}. "
                    f"Check your plugin configuration in .claude/hooks-daemon.yaml."
                ) from e

            # Register handler with the router
            self._router.register(event_type, handler)
            logger.info(
                "Registered plugin handler '%s' for %s (priority=%d, terminal=%s)",
                handler.name,
                event_type.value,
                handler.priority,
                handler.terminal,
            )
            registered_count += 1

        return registered_count

    def _load_project_handlers(
        self,
        *,
        project_handlers_config: "ProjectHandlersConfig",
        workspace_root: Path,
    ) -> int:
        """Load and register project-level handlers.

        Discovers handlers from a convention-based directory structure
        and registers them with the appropriate event type's handler chain.

        Args:
            project_handlers_config: Project handlers configuration
            workspace_root: Workspace root path for resolving relative paths

        Returns:
            Number of project handlers loaded and registered
        """
        if not project_handlers_config.enabled:
            logger.info("Project handlers are disabled")
            return 0

        from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader

        # Resolve path: relative paths are resolved against workspace_root
        handlers_path = Path(project_handlers_config.path)
        if not handlers_path.is_absolute():
            handlers_path = workspace_root / handlers_path

        # Discover handlers from convention-based directory structure
        discovered = ProjectHandlerLoader.discover_handlers(handlers_path)

        if not discovered:
            logger.info("No project handlers discovered from %s", handlers_path)
            return 0

        # Register each discovered handler with the router (with conflict detection)
        registered_count = 0
        for event_type, handler in discovered:
            # Check for handler_id conflict with existing handlers in the same event type
            existing_chain = self._router.get_chain(event_type)
            existing_names = [h.name for h in existing_chain.handlers]

            if handler.name in existing_names:
                logger.warning(
                    "Project handler '%s' conflict: handler with same ID already registered "
                    "for %s. Preferring built-in handler, skipping project handler.",
                    handler.name,
                    event_type.value,
                )
                continue

            # Check for priority collision (warn but still register)
            existing_priorities = [h.priority for h in existing_chain.handlers]
            if handler.priority in existing_priorities:
                logger.warning(
                    "Project handler '%s' priority collision: priority %d already used "
                    "by another handler for %s",
                    handler.name,
                    handler.priority,
                    event_type.value,
                )

            self._router.register(event_type, handler)
            logger.info(
                "Registered project handler '%s' for %s (priority=%d, terminal=%s)",
                handler.name,
                event_type.value,
                handler.priority,
                handler.terminal,
            )
            registered_count += 1

        logger.info(
            "Loaded %d project handlers from %s",
            registered_count,
            handlers_path,
        )
        return registered_count

    def _validate_config(self, config_path: Path) -> None:
        """Validate configuration at startup, entering degraded mode on errors.

        Fail-open: If validation fails or the validator itself crashes,
        the daemon still starts but enters degraded mode.

        Args:
            config_path: Path to the configuration file
        """
        try:
            from claude_code_hooks_daemon.config.loader import ConfigLoader

            config_dict = ConfigLoader.load(config_path)
            errors = ConfigValidator.validate(config_dict)
            if errors:
                self._degraded = True
                self._config_errors = errors
                logger.warning(
                    "Configuration validation failed with %d error(s). "
                    "Daemon is running in DEGRADED mode.",
                    len(errors),
                )
                for error in errors:
                    logger.warning("Config error: %s", error)
            else:
                logger.info("Configuration validation passed")
        except Exception as e:
            # Validator itself crashed or config file unreadable -
            # still enter degraded mode (fail-open)
            self._degraded = True
            self._config_errors = [f"Config validator error: {type(e).__name__}: {e}"]
            logger.warning(
                "Configuration validator crashed: %s. " "Daemon is running in DEGRADED mode.",
                e,
            )

    @staticmethod
    def _init_mode_manager(config: "DaemonConfig | None") -> ModeManager:
        """Initialize ModeManager from config.

        Args:
            config: Optional daemon configuration with default_mode field.

        Returns:
            Initialized ModeManager (falls back to DEFAULT on invalid mode).
        """
        if config is None:
            return ModeManager()

        mode_str = getattr(config, "default_mode", DaemonMode.DEFAULT.value)
        try:
            mode = DaemonMode(mode_str)
        except ValueError:
            logger.warning(
                "Invalid default_mode '%s' in config, falling back to '%s'",
                mode_str,
                DaemonMode.DEFAULT.value,
            )
            mode = DaemonMode.DEFAULT

        return ModeManager(initial_mode=mode)

    def get_mode(self) -> dict[str, Any]:
        """Get current daemon mode as dictionary.

        Returns:
            Dictionary with mode and custom_message fields.
        """
        return self._mode_manager.to_dict()

    def set_mode(
        self,
        mode: DaemonMode,
        custom_message: str | None = None,
    ) -> bool:
        """Set daemon mode.

        Args:
            mode: New daemon mode.
            custom_message: Optional custom message.

        Returns:
            True if mode changed, False if unchanged.
        """
        return self._mode_manager.set_mode(mode, custom_message)

    def process_event(self, event: HookEvent) -> ChainExecutionResult:
        """Process a hook event.

        Routes the event to the appropriate handler chain.
        In degraded mode, returns configuration error for every request.

        Args:
            event: Hook event to process

        Returns:
            Chain execution result
        """
        if not self._initialised:
            self.initialise()

        # In degraded mode, return config error for every request
        if self._degraded:
            config_error_result = HookResult.configuration_error(self._config_errors)
            return ChainExecutionResult(
                result=config_error_result,
                execution_time_ms=0.0,
            )

        start_time = time.perf_counter()
        try:
            # Convert HookInput to dict for handlers (use Python field names, not camelCase aliases)
            hook_input_dict = event.hook_input.model_dump(by_alias=False)

            # Mode interceptor: short-circuit before handler chain
            interceptor = get_interceptor_for_mode(
                self._mode_manager.current_mode,
                self._mode_manager.custom_message,
            )
            if interceptor is not None:
                intercept_result = interceptor.intercept(event.event_type, hook_input_dict)
                if intercept_result is not None:
                    processing_time = (time.perf_counter() - start_time) * 1000
                    self._stats.record_request(event.event_type.value, processing_time)
                    logger.info(
                        "Mode interceptor short-circuited %s event (mode=%s)",
                        event.event_type.value,
                        self._mode_manager.current_mode.value,
                    )
                    return ChainExecutionResult(
                        result=intercept_result,
                        execution_time_ms=processing_time,
                    )

            # Update data layer SessionState on StatusLine events
            if event.event_type == EventType.STATUS_LINE:
                logger.debug("StatusLine raw hook_input: %s", hook_input_dict)
                get_data_layer().session.update_from_status_event(hook_input_dict)

            # Get strict_mode from config (default to False if no config)
            strict_mode = self._config.strict_mode if self._config else False

            result = self._router.route(event.event_type, hook_input_dict, strict_mode=strict_mode)
            processing_time = (time.perf_counter() - start_time) * 1000
            self._stats.record_request(event.event_type.value, processing_time)

            # Record handler decisions in data layer history
            data_layer = get_data_layer()
            for handler_name in result.handlers_matched:
                tool_name = event.hook_input.tool_name or ""
                data_layer.history.record(
                    handler_id=handler_name,
                    event_type=event.event_type.value,
                    decision=result.result.decision.value,
                    tool_name=tool_name,
                    reason=result.result.reason,
                )

            # Check if a handler crashed (strict mode creates error result with context)
            if any("Handler exception:" in ctx for ctx in result.result.context):
                self._stats.record_error()

            return result
        except Exception as e:
            processing_time = (time.perf_counter() - start_time) * 1000
            self._stats.record_request(event.event_type.value, processing_time)
            self._stats.record_error()
            logger.exception("Error processing event")

            # Return error result
            error_result = HookResult.error(
                error_type="internal_error",
                error_details=f"{type(e).__name__}: {e}",
            )
            return ChainExecutionResult(
                result=error_result,
                execution_time_ms=processing_time,
            )

    def process_request(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Process a raw request from the socket server.

        Parses the request, routes to handler chain, and formats response.

        Args:
            request_data: Raw request dictionary

        Returns:
            Response dictionary per PRD 3.2.2 format
        """
        try:
            event = HookEvent.model_validate(request_data)
        except Exception as e:
            logger.warning("Invalid request data: %s", e)
            error_result = HookResult.error(
                error_type="invalid_request",
                error_details=str(e),
            )
            return error_result.to_response_dict("Unknown", 0.0)

        result = self.process_event(event)

        # Use to_json() for Claude Code hook format, not to_response_dict()
        return result.result.to_json(event.event_type.value)

    def get_stats(self) -> DaemonStats:
        """Get daemon statistics.

        Returns:
            Current daemon statistics
        """
        return self._stats

    def get_health(self) -> dict[str, Any]:
        """Get health check information.

        Returns:
            Health status dictionary
        """
        health: dict[str, Any] = {
            "status": "degraded" if self._degraded else "healthy",
            "initialised": self._initialised,
            "stats": self._stats.to_dict(),
            "handlers": self._router.get_handler_count(),
            ModeConstant.KEY_MODE: self._mode_manager.current_mode.value,
        }

        if self._degraded:
            health["config_errors"] = self._config_errors

        return health

    def get_handlers(self) -> dict[str, list[dict[str, Any]]]:
        """Get all registered handlers with details.

        Returns:
            Dictionary mapping event type to handler details
        """
        result: dict[str, list[dict[str, Any]]] = {}
        for event_type, handlers in self._router.get_all_handlers().items():
            result[event_type] = [
                {
                    "name": h.name,
                    "class": h.__class__.__name__,
                    "priority": h.priority,
                    "terminal": h.terminal,
                }
                for h in handlers
            ]
        return result

    def get_router(self) -> EventRouter:
        """Get the event router.

        Returns:
            Event router instance
        """
        return self._router

    def get_registry(self) -> HandlerRegistry:
        """Get the handler registry.

        Returns:
            Handler registry instance
        """
        return self._registry

    @property
    def is_initialised(self) -> bool:
        """Check if controller is initialised."""
        return self._initialised

    @property
    def is_degraded(self) -> bool:
        """Check if controller is in degraded mode due to config errors."""
        return self._degraded

    @property
    def config_errors(self) -> list[str]:
        """Get configuration validation errors (empty if valid)."""
        return self._config_errors


# Global controller instance
_controller: DaemonController | None = None


def get_controller() -> DaemonController:
    """Get the global daemon controller.

    Creates the controller on first access.

    Returns:
        Global DaemonController instance
    """
    global _controller
    if _controller is None:
        _controller = DaemonController()
    return _controller


def reset_controller() -> None:
    """Reset the global controller (for testing)."""
    global _controller
    _controller = None
