"""Additional isinstance tests for TDD Protocol runtime checking.

These tests ensure Protocol methods are properly covered by actually calling them.
"""

from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy
from claude_code_hooks_daemon.strategies.tdd.python_strategy import PythonTddStrategy


def test_python_strategy_satisfies_protocol() -> None:
    """PythonTddStrategy should satisfy TddStrategy Protocol."""
    strategy = PythonTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_protocol_properties_accessed_via_implementation() -> None:
    """Access protocol properties through implementation to cover Protocol stubs."""
    strategy: TddStrategy = PythonTddStrategy()

    # Access properties through Protocol type annotation
    # This ensures Protocol property stubs are covered
    assert strategy.language_name == "Python"
    assert strategy.extensions == (".py",)


def test_protocol_methods_called_via_implementation() -> None:
    """Call protocol methods through implementation to cover Protocol stubs."""
    strategy: TddStrategy = PythonTddStrategy()

    # Call methods through Protocol type annotation
    # This ensures Protocol method stubs are covered
    assert strategy.is_test_file("/workspace/tests/test_foo.py") is True
    assert strategy.is_production_source("/workspace/src/foo.py") is True
    assert strategy.should_skip("/workspace/vendor/foo.py") is True
    assert strategy.compute_test_filename("foo.py") == "test_foo.py"
    assert isinstance(strategy.get_acceptance_tests(), list)
