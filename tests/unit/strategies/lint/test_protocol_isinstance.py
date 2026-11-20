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


def test_existing_strategies_declare_neither_exit_codes_nor_an_optional_tool() -> None:
    """Plan 00621: the two capabilities are opt-in, so no existing strategy changes."""
    from claude_code_hooks_daemon.strategies.lint.protocol import (
        DeclaresFindingsExitCodes,
        DeclaresOptionalTool,
    )
    from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

    for strategy in LintStrategyRegistry.create_default().strategies():
        if strategy.language_name == "GitHub Workflow":
            continue
        assert not isinstance(strategy, DeclaresFindingsExitCodes), strategy.language_name
        assert not isinstance(strategy, DeclaresOptionalTool), strategy.language_name


def test_is_findings_exit_defaults_to_every_non_zero_exit() -> None:
    from claude_code_hooks_daemon.strategies.lint.common import is_findings_exit

    strategy = PythonLintStrategy()
    assert is_findings_exit(strategy, 1) is True
    assert is_findings_exit(strategy, 2) is True
    assert is_findings_exit(None, 3) is True


def test_is_findings_exit_honours_declared_codes() -> None:
    from claude_code_hooks_daemon.strategies.lint.common import is_findings_exit
    from claude_code_hooks_daemon.strategies.lint.github_workflow_strategy import (
        GitHubWorkflowLintStrategy,
    )

    strategy = GitHubWorkflowLintStrategy()
    assert is_findings_exit(strategy, 1) is True
    assert is_findings_exit(strategy, 2) is False
    assert is_findings_exit(strategy, 4) is False


def test_lint_tool_is_optional_helper() -> None:
    from claude_code_hooks_daemon.strategies.lint.common import lint_tool_is_optional
    from claude_code_hooks_daemon.strategies.lint.github_workflow_strategy import (
        GitHubWorkflowLintStrategy,
    )

    assert lint_tool_is_optional(GitHubWorkflowLintStrategy()) is True
    assert lint_tool_is_optional(PythonLintStrategy()) is False
    assert lint_tool_is_optional(None) is False
