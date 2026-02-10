"""CLI functions for config diff, merge, and validate operations.

These functions are designed to be called from the daemon CLI (config-diff,
config-merge, config-validate commands) or from bash scripts via Python.

Each function loads YAML files, performs the operation, and returns
a JSON-serializable dictionary for easy consumption by callers.
"""

from pathlib import Path
from typing import Any

import yaml

from claude_code_hooks_daemon.install.config_differ import ConfigDiffer
from claude_code_hooks_daemon.install.config_merger import ConfigMerger
from claude_code_hooks_daemon.install.config_validator import ConfigValidator


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML config file and return as dict.

    Args:
        path: Path to YAML file

    Returns:
        Parsed dictionary

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is not valid YAML
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open() as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML dictionary: {path}")

    return data


def run_config_diff(
    user_config_path: Path,
    default_config_path: Path,
) -> dict[str, Any]:
    """Diff user config against default config and return structured result.

    Args:
        user_config_path: Path to user's current config YAML
        default_config_path: Path to default/example config YAML for current version

    Returns:
        Dictionary with diff results (JSON-serializable)

    Raises:
        FileNotFoundError: If either config file doesn't exist
    """
    user_config = _load_yaml(user_config_path)
    default_config = _load_yaml(default_config_path)

    differ = ConfigDiffer()
    diff = differ.diff(user_config=user_config, default_config=default_config)

    return diff.to_dict()


def run_config_merge(
    user_config_path: Path,
    old_default_config_path: Path,
    new_default_config_path: Path,
) -> dict[str, Any]:
    """Diff user config against old default, then merge onto new default.

    This is the main upgrade operation:
    1. Diff user config vs old default to extract customizations
    2. Apply customizations onto new default config
    3. Return merged config + any conflicts

    Args:
        user_config_path: Path to user's current config YAML
        old_default_config_path: Path to default config from user's current version
        new_default_config_path: Path to default config from new version

    Returns:
        Dictionary with merged config, conflicts, and is_clean flag

    Raises:
        FileNotFoundError: If any config file doesn't exist
    """
    user_config = _load_yaml(user_config_path)
    old_default_config = _load_yaml(old_default_config_path)
    new_default_config = _load_yaml(new_default_config_path)

    differ = ConfigDiffer()
    diff = differ.diff(user_config=user_config, default_config=old_default_config)

    merger = ConfigMerger()
    result = merger.merge(new_default_config=new_default_config, diff=diff)

    return result.to_dict()


def run_config_validate(
    config_path: Path,
) -> dict[str, Any]:
    """Validate a config file against the Pydantic schema.

    Args:
        config_path: Path to config YAML to validate

    Returns:
        Dictionary with valid flag, errors, warnings, and guidance

    Raises:
        FileNotFoundError: If config file doesn't exist
    """
    config = _load_yaml(config_path)

    validator = ConfigValidator()
    result = validator.validate(config)

    return result.to_dict()
