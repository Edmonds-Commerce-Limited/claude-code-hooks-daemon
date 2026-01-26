"""Configuration schema validation."""

from typing import Any, ClassVar

from jsonschema import ValidationError, validate


class ConfigSchema:
    """Validate hook daemon configuration against schema."""

    # JSON Schema for configuration validation
    SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["version"],
        "additionalProperties": True,  # Forward compatibility
        "properties": {
            "version": {"type": "string", "pattern": r"^\d+\.\d+$"},
            "settings": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "logging_level": {
                        "type": "string",
                        "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                    },
                    "log_file": {"type": "string"},
                },
            },
            "handlers": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "pre_tool_use": {
                        "type": "object",
                        "additionalProperties": True,
                        "patternProperties": {
                            "^[a-z_]+$": {  # Handler names
                                "type": "object",
                                "additionalProperties": True,
                                "properties": {
                                    "enabled": {"type": "boolean"},
                                    "priority": {"type": "integer"},
                                },
                            }
                        },
                    },
                    "post_tool_use": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    "session_start": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
            },
            "daemon": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "idle_timeout_seconds": {"type": "integer", "minimum": 1},
                    "log_level": {
                        "type": "string",
                        "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                    },
                    "enable_hello_world_handlers": {"type": "boolean"},
                },
            },
            "plugins": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path"],
                    "additionalProperties": True,
                    "properties": {
                        "path": {"type": "string"},
                        "handlers": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }

    @staticmethod
    def get_config_schema() -> dict[str, Any]:
        """Get the JSON schema used for configuration validation.

        Returns:
            JSON Schema dictionary
        """
        return ConfigSchema.SCHEMA

    @staticmethod
    def validate_config(config: dict[str, Any]) -> None:
        """Validate configuration against schema.

        Args:
            config: Configuration dictionary to validate

        Raises:
            ValueError: If configuration is invalid
        """
        try:
            validate(instance=config, schema=ConfigSchema.SCHEMA)
        except ValidationError as e:
            raise ValueError(f"Invalid configuration: {e.message}") from e
