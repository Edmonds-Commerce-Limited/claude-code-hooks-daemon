"""Pydantic configuration models for the hooks daemon.

This module provides strongly-typed configuration models with
validation, serialisation, and sensible defaults.
"""

import logging
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)


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

        # Check each event type
        for event_type in [
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
        ]:
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
    languages: list[str] | None = Field(
        default=None,
        description="Project-level language filter. When set, only handlers for these languages are active. None = ALL languages.",
    )
    enforce_single_daemon_process: bool = Field(
        default=False,
        description="Enforce single daemon process per project. When enabled, checks for multiple daemon processes and cleans them up. Auto-enabled in container environments. Requires process verification to prevent killing wrong processes.",
    )
    default_mode: str = Field(
        default="default",
        description="Default daemon mode on startup. Values: 'default' (normal operation), 'unattended' (blocks Stop events to keep Claude working).",
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


class Config(BaseModel):
    """Root configuration model for hooks daemon.

    Attributes:
        version: Configuration version string
        daemon: Daemon server configuration
        handlers: Handler configurations by event type
        plugins: Plugin system configuration
        project_handlers: Project-level handler configuration
    """

    model_config = ConfigDict(extra="allow")

    version: str = Field(default="2.0", pattern=r"^\d+\.\d+$")
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    handlers: HandlersConfig = Field(default_factory=HandlersConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    project_handlers: ProjectHandlersConfig = Field(default_factory=ProjectHandlersConfig)

    # Legacy field mapping
    settings: dict[str, Any] | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def migrate_legacy_settings(self) -> Self:
        """Migrate legacy 'settings' to 'daemon' config."""
        if self.settings and "logging_level" in self.settings:
            self.daemon.log_level = LogLevel(self.settings["logging_level"])
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
