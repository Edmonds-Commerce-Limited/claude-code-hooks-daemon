"""Tests for lint strategy package __init__.py lazy import."""

import pytest


def test_lazy_import_lint_strategy_registry() -> None:
    """Test that LintStrategyRegistry can be imported via __getattr__."""
    from claude_code_hooks_daemon.strategies.lint import LintStrategyRegistry

    # Should successfully import the class
    assert LintStrategyRegistry is not None
    assert hasattr(LintStrategyRegistry, "create_default")


def test_lazy_import_invalid_attribute_raises_attribute_error() -> None:
    """Test that importing non-existent attribute raises AttributeError."""
    with pytest.raises(
        AttributeError,
        match="module 'claude_code_hooks_daemon.strategies.lint' has no attribute 'NonExistent'",
    ):
        # Import will fail at runtime, which is what we're testing
        from claude_code_hooks_daemon.strategies import lint

        _ = lint.NonExistent


def test_lint_strategy_protocol_is_directly_imported() -> None:
    """Test that LintStrategy protocol is directly imported (not lazy)."""
    from claude_code_hooks_daemon.strategies.lint import LintStrategy

    # Should be available immediately
    assert LintStrategy is not None


def test_all_exports() -> None:
    """Test that __all__ contains expected exports."""
    from claude_code_hooks_daemon.strategies import lint

    assert hasattr(lint, "__all__")
    assert "LintStrategy" in lint.__all__
    assert "LintStrategyRegistry" in lint.__all__
    assert len(lint.__all__) == 2
