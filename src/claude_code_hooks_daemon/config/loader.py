"""Configuration file loader."""

import copy
from pathlib import Path
from typing import Any

import yaml


class ConfigLoader:
    """Load and parse hook daemon configuration files.

    Supports YAML and JSON configuration formats.
    """

    @staticmethod
    def load(config_path: str | Path) -> dict[str, Any]:
        """Load configuration from YAML or JSON file.

        Args:
            config_path: Path to configuration file

        Returns:
            Dictionary containing parsed configuration

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If config file format is invalid
        """
        path = Path(config_path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        try:
            with path.open() as f:
                if path.suffix in [".yaml", ".yml"]:
                    config = yaml.safe_load(f)
                elif path.suffix == ".json":
                    import json

                    config = json.load(f)
                else:
                    raise ValueError(
                        f"Unsupported config format: {path.suffix}. Use .yaml, .yml, or .json"
                    )
        except (yaml.YAMLError, ValueError) as e:
            raise ValueError(f"Invalid YAML/JSON syntax in {config_path}: {e}") from e

        if not isinstance(config, dict):
            raise ValueError("Configuration must be a dictionary")

        return config

    @staticmethod
    def find_config(start_dir: str = ".") -> Path:
        """Find configuration file by searching upward from start directory.

        Looks for .claude/hooks-daemon.yaml or .claude/hooks-daemon.yml.

        Args:
            start_dir: Directory to start search from

        Returns:
            Path to configuration file

        Raises:
            FileNotFoundError: If no configuration file found
        """
        current = Path(start_dir).resolve()

        for parent in [current, *list(current.parents)]:
            for filename in ["hooks-daemon.yaml", "hooks-daemon.yml"]:
                config_path = parent / ".claude" / filename
                if config_path.exists():
                    return config_path

        raise FileNotFoundError(
            "No hooks-daemon.yaml configuration found. " "Searched upward from current directory."
        )

    @staticmethod
    def get_default_config() -> dict[str, Any]:
        """Get default configuration values.

        Returns:
            Dictionary containing default configuration
        """
        return {
            "version": "1.0",
            "settings": {
                "logging_level": "INFO",
                "log_file": ".claude/hooks/daemon.log",
            },
            "handlers": {
                "pre_tool_use": {},
                "post_tool_use": {},
                "session_start": {},
            },
            "plugins": [],
        }

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dictionaries, with override values taking precedence.

        Args:
            base: Base dictionary
            override: Dictionary with override values

        Returns:
            Merged dictionary
        """
        result = copy.deepcopy(base)

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigLoader._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)

        return result

    @staticmethod
    def merge_with_defaults(config: dict[str, Any]) -> dict[str, Any]:
        """Merge user configuration with default values.

        User values take precedence over defaults.

        Args:
            config: User configuration dictionary

        Returns:
            Merged configuration with defaults filled in
        """
        defaults = ConfigLoader.get_default_config()
        return ConfigLoader._deep_merge(defaults, config)

    @staticmethod
    def get_handler_settings(
        config: dict[str, Any],
        event_type: str,
        handler_name: str,
        defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Extract settings for a specific handler.

        Args:
            config: Configuration dictionary
            event_type: Event type (e.g., 'pre_tool_use', 'post_tool_use')
            handler_name: Handler name (e.g., 'destructive_git')
            defaults: Optional default values to apply if handler config incomplete

        Returns:
            Handler settings dictionary, or None if handler not configured
        """
        if "handlers" not in config:
            return None

        if event_type not in config["handlers"]:
            return None

        if handler_name not in config["handlers"][event_type]:
            return None

        handler_config = config["handlers"][event_type][handler_name]

        if defaults:
            # Merge with defaults
            merged = copy.deepcopy(defaults)
            if isinstance(handler_config, dict):
                merged.update(handler_config)
                return merged
            return merged

        return handler_config if isinstance(handler_config, dict) else {}
