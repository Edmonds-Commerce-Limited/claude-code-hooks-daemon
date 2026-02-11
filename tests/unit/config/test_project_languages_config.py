"""Tests for project-level languages configuration.

Tests that DaemonConfig accepts a `languages` field and that it
flows correctly through config loading.
"""

import yaml

from claude_code_hooks_daemon.config.models import (
    Config,
    DaemonConfig,
)


class TestDaemonConfigLanguagesField:
    """Test DaemonConfig.languages field."""

    def test_languages_defaults_to_none(self) -> None:
        """Languages field should default to None (ALL languages)."""
        config = DaemonConfig()
        assert config.languages is None

    def test_languages_accepts_list(self) -> None:
        """Languages field should accept a list of strings."""
        config = DaemonConfig(languages=["Python", "Go"])
        assert config.languages == ["Python", "Go"]

    def test_languages_accepts_empty_list(self) -> None:
        """Languages field should accept empty list."""
        config = DaemonConfig(languages=[])
        assert config.languages == []

    def test_languages_accepts_none_explicitly(self) -> None:
        """Languages field should accept None explicitly."""
        config = DaemonConfig(languages=None)
        assert config.languages is None


class TestConfigYamlWithLanguages:
    """Test YAML serialization/deserialization with languages."""

    def test_deserialize_config_with_languages(self) -> None:
        """Deserialize config with daemon.languages list."""
        yaml_str = """
version: "2.0"
daemon:
  languages:
    - Python
    - Go
    - JavaScript/TypeScript
"""
        data = yaml.safe_load(yaml_str)
        config = Config.model_validate(data)

        assert config.daemon.languages == ["Python", "Go", "JavaScript/TypeScript"]

    def test_deserialize_config_without_languages(self) -> None:
        """Config without languages field defaults to None."""
        yaml_str = """
version: "2.0"
daemon:
  idle_timeout_seconds: 600
"""
        data = yaml.safe_load(yaml_str)
        config = Config.model_validate(data)

        assert config.daemon.languages is None

    def test_deserialize_config_with_all_eleven_languages(self) -> None:
        """Config with all 11 supported languages."""
        yaml_str = """
version: "2.0"
daemon:
  languages:
    - Python
    - Go
    - JavaScript/TypeScript
    - PHP
    - Rust
    - Java
    - C#
    - Kotlin
    - Ruby
    - Swift
    - Dart
"""
        data = yaml.safe_load(yaml_str)
        config = Config.model_validate(data)

        assert len(config.daemon.languages) == 11
        assert "Python" in config.daemon.languages
        assert "C#" in config.daemon.languages
        assert "Dart" in config.daemon.languages

    def test_serialize_config_with_languages(self) -> None:
        """Serialized config includes languages when set."""
        config = Config(
            daemon=DaemonConfig(languages=["Python", "Go"]),
        )
        yaml_str = config.to_yaml()
        data = yaml.safe_load(yaml_str)

        assert data["daemon"]["languages"] == ["Python", "Go"]

    def test_serialize_config_without_languages_omits_field(self) -> None:
        """Serialized config omits languages when None (exclude_unset)."""
        config = Config()
        yaml_str = config.to_yaml()
        data = yaml.safe_load(yaml_str)

        # Languages should not appear in serialized output when not set
        if "daemon" in data:
            assert "languages" not in data.get("daemon", {})


class TestRegistryLanguageInjection:
    """Test that registry injects _project_languages into handlers."""

    def test_handler_receives_project_languages_from_registry(self) -> None:
        """Handlers should receive _project_languages via setattr from registry."""
        from claude_code_hooks_daemon.core.router import EventRouter
        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

        router = EventRouter()
        registry = HandlerRegistry()

        # register_all does its own directory scanning
        registry.register_all(
            router,
            project_languages=["Python", "Go"],
        )

        # Find handlers - any handler should have _project_languages set
        all_handlers = router.get_all_handlers()
        found_handler = False
        for event_type, handlers in all_handlers.items():
            for handler in handlers:
                assert hasattr(
                    handler, "_project_languages"
                ), f"Handler {handler.name} missing _project_languages"
                assert handler._project_languages == [
                    "Python",
                    "Go",
                ], f"Handler {handler.name} has wrong _project_languages"
                found_handler = True

        assert found_handler, "At least one handler should be registered"

    def test_handler_receives_none_when_no_project_languages(self) -> None:
        """Handlers should receive None when no project languages configured."""
        from claude_code_hooks_daemon.core.router import EventRouter
        from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

        router = EventRouter()
        registry = HandlerRegistry()

        registry.register_all(
            router,
            project_languages=None,
        )

        all_handlers = router.get_all_handlers()
        found_handler = False
        for event_type, handlers in all_handlers.items():
            for handler in handlers:
                assert hasattr(
                    handler, "_project_languages"
                ), f"Handler {handler.name} missing _project_languages"
                assert (
                    handler._project_languages is None
                ), f"Handler {handler.name} has wrong _project_languages"
                found_handler = True

        assert found_handler, "At least one handler should be registered"
