"""Tests for Handler base class with handler_id parameter.

Tests the handler_id-based Handler initialization.
All handlers MUST use HandlerID constants - no magic strings allowed.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class ConcreteTestHandler(Handler):
    """Concrete test handler for testing Handler base class."""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Simple match implementation."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Simple handle implementation."""
        return HookResult(decision=Decision.ALLOW)


class TestHandlerWithHandlerID:
    """Tests for Handler initialization with handler_id parameter."""

    def test_handler_with_handler_id(self) -> None:
        """Test handler initialization using handler_id."""
        handler = ConcreteTestHandler(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=Priority.DESTRUCTIVE_GIT,
        )

        assert handler.name == "prevent-destructive-git"  # display_name
        assert handler.config_key == "destructive_git"  # config_key
        assert handler.priority == 10

    def test_handler_id_sets_display_name(self) -> None:
        """Test that handler_id sets the correct display name."""
        handler = ConcreteTestHandler(handler_id=HandlerID.SED_BLOCKER)

        assert handler.name == "block-sed-command"
        assert handler.config_key == "sed_blocker"

    def test_handler_id_with_custom_priority(self) -> None:
        """Test that priority can be overridden when using handler_id."""
        handler = ConcreteTestHandler(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=99,  # Override default
        )

        assert handler.config_key == "destructive_git"
        assert handler.priority == 99

    def test_handler_id_sets_handler_id_attribute(self) -> None:
        """Test that handler_id parameter sets the handler_id attribute."""
        handler = ConcreteTestHandler(handler_id=HandlerID.DESTRUCTIVE_GIT)

        assert hasattr(handler, "handler_id")
        assert handler.handler_id == HandlerID.DESTRUCTIVE_GIT
        assert handler.handler_id.class_name == "DestructiveGitHandler"

    def test_different_handlers_have_correct_config_keys(self) -> None:
        """Test that different HandlerIDs produce correct config keys."""
        test_cases = [
            (HandlerID.DESTRUCTIVE_GIT, "destructive_git"),
            (HandlerID.SED_BLOCKER, "sed_blocker"),
            (HandlerID.ABSOLUTE_PATH, "absolute_path"),
            (HandlerID.TDD_ENFORCEMENT, "tdd_enforcement"),
            (HandlerID.MARKDOWN_ORGANIZATION, "markdown_organization"),
            (HandlerID.BRITISH_ENGLISH, "british_english"),
        ]

        for handler_id, expected_config_key in test_cases:
            handler = ConcreteTestHandler(handler_id=handler_id)
            assert handler.config_key == expected_config_key

    def test_handler_id_is_required(self) -> None:
        """Test that handler_id is a required parameter."""
        with pytest.raises(ValueError, match="Either handler_id or name must be provided"):
            ConcreteTestHandler()  # type: ignore[call-arg]

    def test_handler_with_all_parameters(self) -> None:
        """Test handler initialization with all parameters."""
        handler = ConcreteTestHandler(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=15,
            terminal=False,
            tags=["safety", "git"],
            shares_options_with="other_handler",
            depends_on=["dependency1", "dependency2"],
        )

        assert handler.config_key == "destructive_git"
        assert handler.priority == 15
        assert handler.terminal is False
        assert handler.tags == ["safety", "git"]
        assert handler.shares_options_with == "other_handler"
        assert handler.depends_on == ["dependency1", "dependency2"]


class TestHandlerConfigKey:
    """Tests for the config_key attribute."""

    def test_config_key_property_exists(self) -> None:
        """Test that config_key attribute is accessible."""
        handler = ConcreteTestHandler(handler_id=HandlerID.DESTRUCTIVE_GIT)

        assert hasattr(handler, "config_key")
        assert isinstance(handler.config_key, str)

    def test_config_key_matches_handler_id_metadata(self) -> None:
        """Test that config_key matches HandlerIDMeta.config_key."""
        handler = ConcreteTestHandler(handler_id=HandlerID.DESTRUCTIVE_GIT)

        assert handler.config_key == HandlerID.DESTRUCTIVE_GIT.config_key

    def test_config_key_used_for_config_lookups(self) -> None:
        """Test that config_key is suitable for config dictionary lookups."""
        handler = ConcreteTestHandler(handler_id=HandlerID.MARKDOWN_ORGANIZATION)

        # Simulate config lookup
        config = {"markdown_organization": {"enabled": True, "strict_mode": True}}

        assert handler.config_key in config
        assert config[handler.config_key]["enabled"] is True


class TestHandlerRepr:
    """Tests for Handler string representation."""

    def test_repr_with_handler_id(self) -> None:
        """Test __repr__ includes handler information."""
        handler = ConcreteTestHandler(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=10,
        )

        repr_str = repr(handler)
        assert "ConcreteTestHandler" in repr_str
        assert "prevent-destructive-git" in repr_str
        assert "priority=10" in repr_str


class TestHandlerAttributes:
    """Tests for Handler attributes."""

    def test_name_comes_from_display_name(self) -> None:
        """Test that name attribute comes from handler_id.display_name."""
        handler = ConcreteTestHandler(handler_id=HandlerID.BRITISH_ENGLISH)

        assert handler.name == HandlerID.BRITISH_ENGLISH.display_name
        assert handler.name == "enforce-british-english"

    def test_config_key_comes_from_handler_id(self) -> None:
        """Test that config_key comes from handler_id.config_key."""
        handler = ConcreteTestHandler(handler_id=HandlerID.NPM_COMMAND)

        assert handler.config_key == HandlerID.NPM_COMMAND.config_key
        assert handler.config_key == "npm_command"

    def test_handler_id_is_stored(self) -> None:
        """Test that handler_id is stored as-is."""
        handler = ConcreteTestHandler(handler_id=HandlerID.WEB_SEARCH_YEAR)

        assert handler.handler_id is HandlerID.WEB_SEARCH_YEAR
        assert handler.handler_id.class_name == "WebSearchYearHandler"
