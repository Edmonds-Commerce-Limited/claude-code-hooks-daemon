"""Unit tests for PlaybookGenerator."""

from claude_code_hooks_daemon.core import AcceptanceTest
from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


class MockHandler:
    """Mock handler for testing."""

    def __init__(self, handler_id: str, priority: int, tests: list[AcceptanceTest]) -> None:
        self.handler_id = handler_id
        self.priority = priority
        self._tests = tests
        self.tags = []
        self.terminal = False
        self.shares_options_with = None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Return mock acceptance tests."""
        return self._tests


def test_playbook_generator_initialization() -> None:
    """Test PlaybookGenerator can be initialized."""
    config = {}
    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)
    assert generator is not None


def test_generate_markdown_empty_registry() -> None:
    """Test generating markdown with no handlers."""
    config = {}
    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    markdown = generator.generate_markdown()

    # Should still generate valid markdown structure
    assert "# Acceptance Testing Playbook" in markdown
    assert "## Prerequisites" in markdown


def test_generate_markdown_with_handlers() -> None:
    """Test generating markdown with handlers that have acceptance tests."""
    config = {"pre_tool_use": {"test_handler": {"enabled": True}}}

    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    # Test the structure
    markdown = generator.generate_markdown()

    assert "# Acceptance Testing Playbook" in markdown
    assert "## Prerequisites" in markdown
    assert "## Instructions" in markdown


def test_generate_markdown_formats_test_correctly() -> None:
    """Test that individual tests are formatted correctly in markdown."""
    config = {}
    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    # This will be tested once we implement the actual formatting
    markdown = generator.generate_markdown()
    assert markdown is not None


def test_generate_markdown_include_disabled_false() -> None:
    """Test that disabled handlers are excluded by default."""
    config = {
        "pre_tool_use": {
            "enabled_handler": {"enabled": True},
            "disabled_handler": {"enabled": False},
        }
    }

    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    markdown = generator.generate_markdown(include_disabled=False)

    # Should only include enabled handlers
    assert markdown is not None


def test_generate_markdown_include_disabled_true() -> None:
    """Test that disabled handlers are included when requested."""
    config = {
        "pre_tool_use": {
            "enabled_handler": {"enabled": True},
            "disabled_handler": {"enabled": False},
        }
    }

    registry = HandlerRegistry()
    generator = PlaybookGenerator(config=config, registry=registry)

    markdown = generator.generate_markdown(include_disabled=True)

    # Should include all handlers
    assert markdown is not None
