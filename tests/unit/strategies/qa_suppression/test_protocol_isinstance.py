"""Additional isinstance tests for QA Suppression Protocol runtime checking.

These tests ensure Protocol properties are properly covered by actually accessing them.
"""

from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
    PythonQaSuppressionStrategy,
)


def test_python_strategy_satisfies_protocol() -> None:
    """PythonQaSuppressionStrategy should satisfy QaSuppressionStrategy Protocol."""
    strategy = PythonQaSuppressionStrategy()
    assert isinstance(strategy, QaSuppressionStrategy)


def test_protocol_properties_accessed_via_implementation() -> None:
    """Access protocol properties through implementation to cover Protocol stubs."""
    strategy: QaSuppressionStrategy = PythonQaSuppressionStrategy()

    # Access properties through Protocol type annotation
    # This ensures Protocol property stubs are covered
    assert strategy.language_name == "Python"
    assert strategy.extensions == (".py",)
    assert isinstance(strategy.forbidden_patterns, tuple)
    assert isinstance(strategy.skip_directories, tuple)
    assert isinstance(strategy.tool_names, tuple)
    assert isinstance(strategy.tool_docs_urls, tuple)


def test_protocol_methods_called_via_implementation() -> None:
    """Call protocol methods through implementation to cover Protocol stubs."""
    strategy: QaSuppressionStrategy = PythonQaSuppressionStrategy()

    # Call method through Protocol type annotation
    # This ensures Protocol method stub is covered
    assert isinstance(strategy.get_acceptance_tests(), list)
