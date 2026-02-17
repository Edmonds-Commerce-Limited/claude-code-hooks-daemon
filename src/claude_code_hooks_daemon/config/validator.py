"""Configuration validator for hooks-daemon.yaml files.

Provides exhaustive validation of configuration schema including:
- Version format validation
- Daemon settings validation
- Handler configuration validation
- Priority range and uniqueness validation
- Event type validation
- Handler name format validation
- Handler name typo detection with fuzzy matching
"""

import difflib
import importlib
import logging
import pkgutil
import re
from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import ConfigKey, EventID
from claude_code_hooks_daemon.utils.strict_mode import handle_tier2_error

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


class ConfigValidator:
    """Exhaustive configuration validator."""

    # Valid hook event types (11 total) - derived from EventID constants
    VALID_EVENT_TYPES: ClassVar[set[str]] = {
        EventID.PRE_TOOL_USE.config_key,
        EventID.POST_TOOL_USE.config_key,
        EventID.PERMISSION_REQUEST.config_key,
        EventID.NOTIFICATION.config_key,
        EventID.USER_PROMPT_SUBMIT.config_key,
        EventID.SESSION_START.config_key,
        EventID.SESSION_END.config_key,
        EventID.STOP.config_key,
        EventID.SUBAGENT_STOP.config_key,
        EventID.PRE_COMPACT.config_key,
        EventID.STATUS_LINE.config_key,
    }

    # Valid log levels
    VALID_LOG_LEVELS: ClassVar[set[str]] = {"DEBUG", "INFO", "WARNING", "ERROR"}

    # Priority range (inclusive) - project-specific config constraints
    # NOTE: These are narrower than ValidationLimit.PRIORITY_MIN/MAX (0-100)
    # because the project enforces a tighter range for handler priorities
    MIN_PRIORITY = 5
    MAX_PRIORITY = 60

    # Handler name pattern (snake_case with optional numbers)
    HANDLER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

    # Version format pattern (X.Y)
    VERSION_PATTERN = re.compile(r"^\d+\.\d+$")

    # Cache for discovered handlers (event_type -> set of handler names)
    _handler_cache: ClassVar[dict[str, set[str]]] = {}

    @staticmethod
    def get_available_handlers(event_type: str, strict_mode: bool = False) -> set[str]:
        """Get available handler names for a specific event type.

        Discovers handler classes by scanning the handlers package and
        converting class names to snake_case config keys.

        Args:
            event_type: Event type (e.g., "pre_tool_use")
            strict_mode: If True, FAIL FAST on import errors (TIER 2)

        Returns:
            Set of valid handler names for this event type
        """
        # Return cached result if available
        if event_type in ConfigValidator._handler_cache:
            return ConfigValidator._handler_cache[event_type]

        handlers: set[str] = set()

        try:
            # Import the handlers subpackage for this event type
            package_name = f"claude_code_hooks_daemon.handlers.{event_type}"
            package = importlib.import_module(package_name)

            if not hasattr(package, "__path__"):
                ConfigValidator._handler_cache[event_type] = handlers
                return handlers

            # Import Handler base class for isinstance check
            from claude_code_hooks_daemon.core.handler import Handler

            # Walk through all modules in the package
            for _importer, modname, ispkg in pkgutil.walk_packages(
                package.__path__,
                prefix=f"{package_name}.",
            ):
                if ispkg or modname.endswith("__init__") or "test" in modname:
                    continue

                try:
                    module = importlib.import_module(modname)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, Handler)
                            and attr is not Handler
                            and not attr.__name__.startswith("_")
                        ):
                            # Convert class name to snake_case config key
                            handler_config_name = ConfigValidator._to_snake_case(attr.__name__)
                            handlers.add(handler_config_name)
                except (ImportError, SyntaxError, AttributeError) as e:
                    # TIER 2: Crash in strict_mode, log debug in non-strict
                    handle_tier2_error(
                        error=e,
                        strict_mode=strict_mode,
                        error_message=f"Failed to import handler module {modname} in strict mode",
                        graceful_message=f"Failed to import handler module {modname}",
                    )
                except Exception as e:
                    # TIER 2: Crash in strict_mode, log error in non-strict
                    if strict_mode:
                        raise RuntimeError(
                            f"Unexpected error importing {modname} in strict mode: {e}"
                        ) from e
                    else:
                        # Non-strict: Log error with full traceback
                        logger.error("Unexpected error importing %s: %s", modname, e, exc_info=True)

        except ImportError as e:
            if strict_mode:
                # TIER 2: FAIL FAST in strict mode
                raise RuntimeError(
                    f"Failed to import handlers package for {event_type} in strict mode: {e}"
                ) from e
            # Non-strict: Event type has no handlers package (that's ok)
            # Silent pass - this is legitimate, not an error
            pass

        # Cache the result
        ConfigValidator._handler_cache[event_type] = handlers
        return handlers

    @staticmethod
    def _to_snake_case(name: str) -> str:
        """Convert CamelCase to snake_case.

        Args:
            name: CamelCase string

        Returns:
            snake_case string with _handler suffix stripped
        """
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

        # Strip _handler suffix to match config keys
        if snake.endswith("_handler"):
            snake = snake[:-8]  # Remove "_handler"

        return snake

    @staticmethod
    def _find_similar_names(name: str, valid_names: set[str], threshold: float = 0.6) -> list[str]:
        """Find similar handler names using fuzzy matching.

        Args:
            name: The typo'd handler name
            valid_names: Set of valid handler names
            threshold: Similarity threshold (0.0 to 1.0)

        Returns:
            List of similar names, sorted by similarity
        """
        if not valid_names:
            return []

        # Use difflib for fuzzy matching
        matches = difflib.get_close_matches(name, valid_names, n=3, cutoff=threshold)
        return matches

    @staticmethod
    def validate(config: dict[str, Any], *, validate_handler_names: bool = True) -> list[str]:
        """Validate configuration and return list of error messages.

        Args:
            config: Configuration dictionary to validate
            validate_handler_names: If False, skip handler name validation (for testing)

        Returns:
            List of error messages (empty if valid)
        """
        errors: list[str] = []

        # Extract strict_mode from config (default False)
        strict_mode = config.get("daemon", {}).get("strict_mode", False)

        # Validate version
        errors.extend(ConfigValidator._validate_version(config))

        # Validate daemon section
        errors.extend(ConfigValidator._validate_daemon(config))

        # Validate handlers section
        errors.extend(
            ConfigValidator._validate_handlers(
                config, validate_handler_names=validate_handler_names, strict_mode=strict_mode
            )
        )

        # Validate plugins section (optional)
        errors.extend(ConfigValidator._validate_plugins(config))

        return errors

    @staticmethod
    def _validate_version(config: dict[str, Any]) -> list[str]:
        """Validate version field.

        Args:
            config: Configuration dictionary

        Returns:
            List of error messages
        """
        errors: list[str] = []

        if ConfigKey.VERSION not in config:
            errors.append("Missing required field: version")
            return errors

        version = config[ConfigKey.VERSION]

        if not isinstance(version, str):
            errors.append(f"Field 'version' must be string, got {type(version).__name__}")
            return errors

        if not ConfigValidator.VERSION_PATTERN.match(version):
            errors.append(
                f"Field 'version' has invalid format '{version}'. Expected format: 'X.Y' (e.g., '1.0')"
            )

        return errors

    @staticmethod
    def _validate_daemon(config: dict[str, Any]) -> list[str]:
        """Validate daemon configuration section.

        Args:
            config: Configuration dictionary

        Returns:
            List of error messages
        """
        errors: list[str] = []

        if ConfigKey.DAEMON not in config:
            errors.append("Missing required section: daemon")
            return errors

        daemon = config[ConfigKey.DAEMON]

        if not isinstance(daemon, dict):
            errors.append(f"Section 'daemon' must be dictionary, got {type(daemon).__name__}")
            return errors

        # Validate idle_timeout_seconds
        if ConfigKey.IDLE_TIMEOUT_SECONDS not in daemon:
            errors.append("Missing required field: daemon.idle_timeout_seconds")
        else:
            timeout = daemon[ConfigKey.IDLE_TIMEOUT_SECONDS]
            if not isinstance(timeout, int):
                errors.append(
                    f"Field 'daemon.idle_timeout_seconds' must be integer, got {type(timeout).__name__}"
                )
            elif timeout <= 0:
                errors.append(
                    f"Field 'daemon.idle_timeout_seconds' must be positive integer, got {timeout}"
                )

        # Validate log_level
        if ConfigKey.LOG_LEVEL not in daemon:
            errors.append("Missing required field: daemon.log_level")
        else:
            log_level = daemon[ConfigKey.LOG_LEVEL]
            if not isinstance(log_level, str):
                errors.append(
                    f"Field 'daemon.log_level' must be string, got {type(log_level).__name__}"
                )
            elif log_level not in ConfigValidator.VALID_LOG_LEVELS:
                valid_str = ", ".join(sorted(ConfigValidator.VALID_LOG_LEVELS))
                errors.append(
                    f"Field 'daemon.log_level' has invalid value '{log_level}'. "
                    f"Valid values: {valid_str}"
                )

        return errors

    @staticmethod
    def _validate_handlers(
        config: dict[str, Any], *, validate_handler_names: bool = True, strict_mode: bool = False
    ) -> list[str]:
        """Validate handlers configuration section.

        Args:
            config: Configuration dictionary
            validate_handler_names: If False, skip handler name validation (for testing)
            strict_mode: If True, FAIL FAST on handler discovery errors

        Returns:
            List of error messages
        """
        errors: list[str] = []

        if ConfigKey.HANDLERS not in config:
            errors.append("Missing required section: handlers")
            return errors

        handlers = config[ConfigKey.HANDLERS]

        if not isinstance(handlers, dict):
            errors.append(f"Section 'handlers' must be dictionary, got {type(handlers).__name__}")
            return errors

        # Validate each event type
        for event_type, handler_configs in handlers.items():
            # Check event type is valid
            if event_type not in ConfigValidator.VALID_EVENT_TYPES:
                valid_events_str = ", ".join(sorted(ConfigValidator.VALID_EVENT_TYPES))
                errors.append(
                    f"Invalid event type 'handlers.{event_type}'. "
                    f"Valid types: {valid_events_str}"
                )
                continue

            if not isinstance(handler_configs, dict):
                errors.append(
                    f"Section 'handlers.{event_type}' must be dictionary, "
                    f"got {type(handler_configs).__name__}"
                )
                continue

            # Discover available handlers for this event type (if validation enabled)
            # Pass strict_mode to fail fast on import errors in strict mode
            available_handlers = (
                ConfigValidator.get_available_handlers(event_type, strict_mode=strict_mode)
                if validate_handler_names
                else set()
            )

            # Track priorities for duplicate detection
            priorities: dict[int, str] = {}

            # Validate each handler in this event type
            for handler_name, handler_config in handler_configs.items():
                handler_path = f"handlers.{event_type}.{handler_name}"

                # Validate handler name format
                if not ConfigValidator.HANDLER_NAME_PATTERN.match(handler_name):
                    errors.append(
                        f"Invalid handler name '{handler_name}' at '{handler_path}'. "
                        f"Handler names must be snake_case (lowercase letters, numbers, underscores)"
                    )

                # CRITICAL: Check if handler name exists (catch typos)
                if validate_handler_names and handler_name not in available_handlers:
                    # Find similar names to suggest
                    similar = ConfigValidator._find_similar_names(handler_name, available_handlers)

                    if similar:
                        suggestion = f"Did you mean: {', '.join(similar)}"
                    elif available_handlers:
                        # Show some available handlers
                        available_list = sorted(available_handlers)[:5]
                        available_str = ", ".join(available_list)
                        more = (
                            f" ({len(available_handlers) - 5} more)"
                            if len(available_handlers) > 5
                            else ""
                        )
                        suggestion = f"Available handlers for '{event_type}': {available_str}{more}"
                    else:
                        suggestion = f"No handlers found for event type '{event_type}'"

                    errors.append(
                        f"Unknown handler '{handler_name}' at '{handler_path}'. {suggestion}"
                    )

                if not isinstance(handler_config, dict):
                    errors.append(
                        f"Handler config at '{handler_path}' must be dictionary, "
                        f"got {type(handler_config).__name__}"
                    )
                    continue

                # Validate enabled field (if present)
                if ConfigKey.ENABLED in handler_config:
                    enabled = handler_config[ConfigKey.ENABLED]
                    if not isinstance(enabled, bool):
                        errors.append(
                            f"Field '{handler_path}.enabled' must be boolean, "
                            f"got {type(enabled).__name__}"
                        )

                # Validate priority field (if present)
                if ConfigKey.PRIORITY in handler_config:
                    priority = handler_config[ConfigKey.PRIORITY]
                    if not isinstance(priority, int):
                        errors.append(
                            f"Field '{handler_path}.priority' must be integer, "
                            f"got {type(priority).__name__}"
                        )
                    elif (
                        priority < ConfigValidator.MIN_PRIORITY
                        or priority > ConfigValidator.MAX_PRIORITY
                    ):
                        errors.append(
                            f"Field '{handler_path}.priority' must be in range "
                            f"{ConfigValidator.MIN_PRIORITY}-{ConfigValidator.MAX_PRIORITY}, got {priority}"
                        )
                    else:
                        # Check for duplicate priorities within same event
                        # NOTE: Duplicate priorities are NOT errors - they are handled by HandlerChain
                        # with alphabetical tiebreaker. Just track them for potential warnings.
                        if priority in priorities:
                            other_handler = priorities[priority]
                            # Log warning but don't add to errors (per user feedback)
                            logger.debug(
                                f"Duplicate priority {priority} in 'handlers.{event_type}': "
                                f"'{handler_name}' and '{other_handler}' share priority. "
                                f"Will use alphabetical order for deterministic sorting."
                            )
                        else:
                            priorities[priority] = handler_name

        return errors

    @staticmethod
    def _validate_plugins(config: dict[str, Any]) -> list[str]:
        """Validate plugins configuration section (optional).

        The plugins section follows the PluginsConfig schema:
          plugins:
            paths: list[str]     # Plugin search paths
            plugins: list[dict]  # Plugin configurations

        Args:
            config: Configuration dictionary

        Returns:
            List of error messages
        """
        errors: list[str] = []

        if ConfigKey.PLUGINS not in config:
            return errors  # Plugins section is optional

        plugins = config[ConfigKey.PLUGINS]

        if not isinstance(plugins, dict):
            errors.append(f"Section 'plugins' must be dictionary, got {type(plugins).__name__}")
            return errors

        # Validate paths (optional, defaults to empty list)
        if "paths" in plugins:
            paths = plugins["paths"]
            if not isinstance(paths, list):
                errors.append(f"Field 'plugins.paths' must be list, got {type(paths).__name__}")

        # Validate plugins list (optional, defaults to empty list)
        if "plugins" in plugins:
            plugin_list = plugins["plugins"]
            if not isinstance(plugin_list, list):
                errors.append(
                    f"Field 'plugins.plugins' must be list, got {type(plugin_list).__name__}"
                )
            else:
                for idx, plugin in enumerate(plugin_list):
                    plugin_path = f"plugins.plugins[{idx}]"

                    if not isinstance(plugin, dict):
                        errors.append(
                            f"Plugin at '{plugin_path}' must be dictionary, "
                            f"got {type(plugin).__name__}"
                        )
                        continue

                    # Validate required 'path' field
                    if "path" not in plugin:
                        errors.append(f"Missing required field: {plugin_path}.path")

        return errors

    @staticmethod
    def validate_and_raise(config: dict[str, Any], *, validate_handler_names: bool = True) -> None:
        """Validate configuration and raise ValidationError if invalid.

        Args:
            config: Configuration dictionary to validate
            validate_handler_names: If False, skip handler name validation (for testing)

        Raises:
            ValidationError: If configuration is invalid
        """
        errors = ConfigValidator.validate(config, validate_handler_names=validate_handler_names)

        if errors:
            error_count = len(errors)
            error_list = "\n  - ".join(errors)
            raise ValidationError(
                f"Configuration validation failed with {error_count} error(s):\n  - {error_list}"
            )
