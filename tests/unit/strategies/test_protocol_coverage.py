"""Protocol coverage tests - validates Protocol isinstance checks with real implementations.

This test file ensures that Protocol definitions (with ellipsis methods) are properly
covered by testing isinstance checks with actual strategy implementations.

Coverage target: Increase protocol.py files from 63-70% to 95%+

The key insight: Protocol ellipsis methods (...) are only covered when:
1. Protocol is imported directly (not just through strategy)
2. isinstance() check is performed with the Protocol
3. Protocol properties/methods are accessed on an instance

This test file uses real strategy implementations to trigger Protocol coverage.
"""

from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


class TestTddProtocolWithRealImplementation:
    """Test TddStrategy Protocol with a real implementation."""

    def test_python_strategy_satisfies_protocol(self) -> None:
        """Python TDD strategy should satisfy TddStrategy Protocol."""
        from claude_code_hooks_daemon.strategies.tdd.python_strategy import (
            PythonTddStrategy,
        )

        strategy = PythonTddStrategy()
        assert isinstance(strategy, TddStrategy)

    def test_protocol_properties_accessible(self) -> None:
        """Protocol properties should be accessible on real implementation."""
        from claude_code_hooks_daemon.strategies.tdd.python_strategy import (
            PythonTddStrategy,
        )

        strategy = PythonTddStrategy()

        # Access all protocol properties/methods to hit ellipsis lines
        assert isinstance(strategy.language_name, str)
        assert isinstance(strategy.extensions, tuple)
        assert callable(strategy.is_test_file)
        assert callable(strategy.is_production_source)
        assert callable(strategy.should_skip)
        assert callable(strategy.compute_test_filename)
        assert callable(strategy.get_acceptance_tests)

    def test_protocol_methods_callable(self) -> None:
        """Protocol methods should be callable on real implementation."""
        from claude_code_hooks_daemon.strategies.tdd.python_strategy import (
            PythonTddStrategy,
        )

        strategy = PythonTddStrategy()

        # Call all protocol methods to exercise ellipsis definitions
        _ = strategy.is_test_file("/workspace/tests/test_foo.py")
        _ = strategy.is_production_source("/workspace/src/foo.py")
        _ = strategy.should_skip("/workspace/vendor/foo.py")
        _ = strategy.compute_test_filename("foo.py")
        _ = strategy.get_acceptance_tests()


class TestQaSuppressionProtocolWithRealImplementation:
    """Test QaSuppressionStrategy Protocol with a real implementation."""

    def test_python_strategy_satisfies_protocol(self) -> None:
        """Python QA suppression strategy should satisfy QaSuppressionStrategy Protocol."""
        from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
            PythonQaSuppressionStrategy,
        )

        strategy = PythonQaSuppressionStrategy()
        assert isinstance(strategy, QaSuppressionStrategy)

    def test_protocol_properties_accessible(self) -> None:
        """Protocol properties should be accessible on real implementation."""
        from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
            PythonQaSuppressionStrategy,
        )

        strategy = PythonQaSuppressionStrategy()

        # Access all protocol properties to hit ellipsis lines
        assert isinstance(strategy.language_name, str)
        assert isinstance(strategy.extensions, tuple)
        assert isinstance(strategy.forbidden_patterns, tuple)
        assert isinstance(strategy.skip_directories, tuple)
        assert isinstance(strategy.tool_names, tuple)
        assert isinstance(strategy.tool_docs_urls, tuple)
        assert callable(strategy.get_acceptance_tests)

    def test_protocol_methods_callable(self) -> None:
        """Protocol methods should be callable on real implementation."""
        from claude_code_hooks_daemon.strategies.qa_suppression.python_strategy import (
            PythonQaSuppressionStrategy,
        )

        strategy = PythonQaSuppressionStrategy()

        # Call get_acceptance_tests to exercise ellipsis definition
        _ = strategy.get_acceptance_tests()


class TestLintProtocolWithRealImplementation:
    """Test LintStrategy Protocol with a real implementation."""

    def test_python_strategy_satisfies_protocol(self) -> None:
        """Python lint strategy should satisfy LintStrategy Protocol."""
        from claude_code_hooks_daemon.strategies.lint.python_strategy import (
            PythonLintStrategy,
        )

        strategy = PythonLintStrategy()
        assert isinstance(strategy, LintStrategy)

    def test_protocol_properties_accessible(self) -> None:
        """Protocol properties should be accessible on real implementation."""
        from claude_code_hooks_daemon.strategies.lint.python_strategy import (
            PythonLintStrategy,
        )

        strategy = PythonLintStrategy()

        # Access all protocol properties to hit ellipsis lines
        assert isinstance(strategy.language_name, str)
        assert isinstance(strategy.extensions, tuple)
        assert isinstance(strategy.default_lint_command, str)
        assert strategy.extended_lint_command is None or isinstance(
            strategy.extended_lint_command, str
        )
        assert isinstance(strategy.skip_paths, tuple)
        assert callable(strategy.get_acceptance_tests)

    def test_protocol_methods_callable(self) -> None:
        """Protocol methods should be callable on real implementation."""
        from claude_code_hooks_daemon.strategies.lint.python_strategy import (
            PythonLintStrategy,
        )

        strategy = PythonLintStrategy()

        # Call get_acceptance_tests to exercise ellipsis definition
        _ = strategy.get_acceptance_tests()


class TestLintInitLazyImport:
    """Test lazy import in lint/__init__.py."""

    def test_lint_strategy_registry_lazy_import(self) -> None:
        """LintStrategyRegistry should be importable via __getattr__."""
        from claude_code_hooks_daemon.strategies.lint import LintStrategyRegistry

        # Verify it's the correct class
        assert LintStrategyRegistry.__name__ == "LintStrategyRegistry"

    def test_lint_strategy_direct_import(self) -> None:
        """LintStrategy should be directly importable."""
        from claude_code_hooks_daemon.strategies.lint import LintStrategy as LS

        # Verify it's the Protocol
        assert LS.__name__ == "LintStrategy"

    def test_lazy_import_invalid_attribute(self) -> None:
        """Accessing invalid attribute should raise AttributeError."""
        import claude_code_hooks_daemon.strategies.lint as lint_module

        try:
            _ = lint_module.NonExistentClass
            assert False, "Should have raised AttributeError"
        except AttributeError as e:
            assert "NonExistentClass" in str(e)
