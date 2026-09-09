"""The config package exposes exactly one validation path.

``ConfigValidator`` (backed by the Pydantic ``Config`` model) is what the
daemon runs at startup, and its event-type set is derived from
``wired_event_metas()``. A second, hand-maintained JSON-schema validator
would be a parallel enumeration of the same config surface that nothing
executes -- the drift class Plan 00172 exists to close -- so the package
must not re-grow one.
"""

from __future__ import annotations

import importlib.util

import claude_code_hooks_daemon.config as config_package


class TestSingleValidationPath:
    """No legacy JSON-schema validator sits beside ``ConfigValidator``."""

    def test_config_package_does_not_export_a_json_schema_validator(self) -> None:
        assert "ConfigSchema" not in config_package.__all__
        assert not hasattr(config_package, "ConfigSchema")

    def test_config_schema_module_is_absent(self) -> None:
        assert importlib.util.find_spec("claude_code_hooks_daemon.config.schema") is None

    def test_config_validator_remains_the_exported_validation_path(self) -> None:
        assert "ConfigValidator" in config_package.__all__
        assert "Config" in config_package.__all__
