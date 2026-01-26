"""Configuration validator for hooks-daemon.yaml files.

Provides exhaustive validation of configuration schema including:
- Version format validation
- Daemon settings validation
- Handler configuration validation
- Priority range and uniqueness validation
- Event type validation
- Handler name format validation
"""

import re
from typing import Any, ClassVar


class ValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


class ConfigValidator:
    """Exhaustive configuration validator."""

    # Valid hook event types (10 total)
    VALID_EVENT_TYPES: ClassVar[set[str]] = {
        "pre_tool_use",
        "post_tool_use",
        "permission_request",
        "notification",
        "user_prompt_submit",
        "session_start",
        "session_end",
        "stop",
        "subagent_stop",
        "pre_compact",
    }

    # Valid log levels
    VALID_LOG_LEVELS: ClassVar[set[str]] = {"DEBUG", "INFO", "WARNING", "ERROR"}

    # Priority range (inclusive)
    MIN_PRIORITY = 5
    MAX_PRIORITY = 60

    # Handler name pattern (snake_case with optional numbers)
    HANDLER_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

    # Version format pattern (X.Y)
    VERSION_PATTERN = re.compile(r"^\d+\.\d+$")

    @staticmethod
    def validate(config: dict[str, Any]) -> list[str]:
        """Validate configuration and return list of error messages.

        Args:
            config: Configuration dictionary to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors: list[str] = []

        # Validate version
        errors.extend(ConfigValidator._validate_version(config))

        # Validate daemon section
        errors.extend(ConfigValidator._validate_daemon(config))

        # Validate handlers section
        errors.extend(ConfigValidator._validate_handlers(config))

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

        if "version" not in config:
            errors.append("Missing required field: version")
            return errors

        version = config["version"]

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

        if "daemon" not in config:
            errors.append("Missing required section: daemon")
            return errors

        daemon = config["daemon"]

        if not isinstance(daemon, dict):
            errors.append(f"Section 'daemon' must be dictionary, got {type(daemon).__name__}")
            return errors

        # Validate idle_timeout_seconds
        if "idle_timeout_seconds" not in daemon:
            errors.append("Missing required field: daemon.idle_timeout_seconds")
        else:
            timeout = daemon["idle_timeout_seconds"]
            if not isinstance(timeout, int):
                errors.append(
                    f"Field 'daemon.idle_timeout_seconds' must be integer, got {type(timeout).__name__}"
                )
            elif timeout <= 0:
                errors.append(
                    f"Field 'daemon.idle_timeout_seconds' must be positive integer, got {timeout}"
                )

        # Validate log_level
        if "log_level" not in daemon:
            errors.append("Missing required field: daemon.log_level")
        else:
            log_level = daemon["log_level"]
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
    def _validate_handlers(config: dict[str, Any]) -> list[str]:
        """Validate handlers configuration section.

        Args:
            config: Configuration dictionary

        Returns:
            List of error messages
        """
        errors: list[str] = []

        if "handlers" not in config:
            errors.append("Missing required section: handlers")
            return errors

        handlers = config["handlers"]

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

                if not isinstance(handler_config, dict):
                    errors.append(
                        f"Handler config at '{handler_path}' must be dictionary, "
                        f"got {type(handler_config).__name__}"
                    )
                    continue

                # Validate enabled field (if present)
                if "enabled" in handler_config:
                    enabled = handler_config["enabled"]
                    if not isinstance(enabled, bool):
                        errors.append(
                            f"Field '{handler_path}.enabled' must be boolean, "
                            f"got {type(enabled).__name__}"
                        )

                # Validate priority field (if present)
                if "priority" in handler_config:
                    priority = handler_config["priority"]
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
                        if priority in priorities:
                            other_handler = priorities[priority]
                            errors.append(
                                f"Duplicate priority {priority} in 'handlers.{event_type}': "
                                f"both '{handler_name}' and '{other_handler}' have same priority"
                            )
                        else:
                            priorities[priority] = handler_name

        return errors

    @staticmethod
    def _validate_plugins(config: dict[str, Any]) -> list[str]:
        """Validate plugins configuration section (optional).

        Args:
            config: Configuration dictionary

        Returns:
            List of error messages
        """
        errors: list[str] = []

        if "plugins" not in config:
            return errors  # Plugins section is optional

        plugins = config["plugins"]

        if not isinstance(plugins, list):
            errors.append(f"Section 'plugins' must be list, got {type(plugins).__name__}")
            return errors

        for idx, plugin in enumerate(plugins):
            plugin_path = f"plugins[{idx}]"

            if not isinstance(plugin, dict):
                errors.append(
                    f"Plugin at '{plugin_path}' must be dictionary, " f"got {type(plugin).__name__}"
                )
                continue

            # Validate required 'path' field
            if "path" not in plugin:
                errors.append(f"Missing required field: {plugin_path}.path")

        return errors

    @staticmethod
    def validate_and_raise(config: dict[str, Any]) -> None:
        """Validate configuration and raise ValidationError if invalid.

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValidationError: If configuration is invalid
        """
        errors = ConfigValidator.validate(config)

        if errors:
            error_count = len(errors)
            error_list = "\n  - ".join(errors)
            raise ValidationError(
                f"Configuration validation failed with {error_count} error(s):\n  - {error_list}"
            )
