"""Additional isinstance tests for Lint Protocol runtime checking.

These tests ensure Protocol properties are properly covered by isinstance checks.
"""

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.python_strategy import PythonLintStrategy


def test_python_strategy_satisfies_protocol() -> None:
    """PythonLintStrategy should satisfy LintStrategy Protocol."""
    strategy = PythonLintStrategy()
    assert isinstance(strategy, LintStrategy)


def test_protocol_properties_accessed_via_implementation() -> None:
    """Access protocol properties through implementation to cover Protocol stubs."""
    strategy: LintStrategy = PythonLintStrategy()

    # Access properties through Protocol type annotation
    # This ensures Protocol property stubs are covered
    assert strategy.language_name == "Python"
    assert strategy.extensions == (".py",)
    assert isinstance(strategy.default_lint_command, str)
    assert isinstance(strategy.skip_paths, tuple)
    # extended_lint_command can be str or None
    extended = strategy.extended_lint_command
    assert extended is None or isinstance(extended, str)


def test_protocol_methods_called_via_implementation() -> None:
    """Call protocol methods through implementation to cover Protocol stubs."""
    strategy: LintStrategy = PythonLintStrategy()

    # Call method through Protocol type annotation
    # This ensures Protocol method stub is covered
    assert isinstance(strategy.get_acceptance_tests(), list)
