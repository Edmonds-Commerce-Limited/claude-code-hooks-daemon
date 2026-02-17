"""Tests for lint module lazy import functionality.

The lint/__init__.py uses __getattr__ for lazy importing LintStrategyRegistry
to avoid circular imports.
"""

import pytest


def test_lazy_import_lint_strategy_registry() -> None:
    """Test that LintStrategyRegistry is lazily imported via __getattr__."""
    from claude_code_hooks_daemon.strategies.lint import LintStrategyRegistry

    # Verify it imported successfully
    assert LintStrategyRegistry is not None
    assert hasattr(LintStrategyRegistry, "create_default")


def test_lazy_import_raises_attribute_error_for_invalid_name() -> None:
    """Test that __getattr__ raises AttributeError for invalid attribute."""
    from claude_code_hooks_daemon.strategies import lint

    with pytest.raises(AttributeError, match="has no attribute 'InvalidAttribute'"):
        lint.InvalidAttribute


def test_lint_strategy_protocol_is_directly_importable() -> None:
    """Test that LintStrategy is directly importable (not lazy)."""
    from claude_code_hooks_daemon.strategies.lint import LintStrategy

    # Verify it's available immediately
    assert LintStrategy is not None
    assert hasattr(LintStrategy, "__protocol_attrs__") or hasattr(
        LintStrategy, "__abstractmethods__"
    )


def test_module_all_exports() -> None:
    """Test that __all__ contains expected exports."""
    from claude_code_hooks_daemon.strategies import lint

    assert hasattr(lint, "__all__")
    assert "LintStrategy" in lint.__all__
    assert "LintStrategyRegistry" in lint.__all__
