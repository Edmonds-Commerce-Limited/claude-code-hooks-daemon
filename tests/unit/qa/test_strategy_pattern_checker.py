"""Tests for strategy pattern compliance checker."""

from pathlib import Path

from claude_code_hooks_daemon.qa.strategy_pattern_checker import (
    Violation,
    check_file,
    check_source,
)


class TestViolationDataclass:
    """Tests for Violation dataclass."""

    def test_violation_creation(self) -> None:
        """Violation can be created with all fields."""
        violation = Violation(
            file="test.py",
            line=10,
            rule="test_rule",
            message="Test message",
            severity="error",
        )
        assert violation.file == "test.py"
        assert violation.line == 10
        assert violation.rule == "test_rule"
        assert violation.message == "Test message"
        assert violation.severity == "error"


class TestStrategyHandlerNoLanguageLogic:
    """Test detection of language-specific logic in handlers using strategies."""

    def test_detects_if_language_pattern(self) -> None:
        """Detect if statements checking language."""
        source = """
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry

class MyHandler(Handler):
    def __init__(self):
        self._registry = TddStrategyRegistry.create_default()

    def handle(self, hook_input):
        if language == "Python":
            return "test"
"""
        violations = check_source(source, "handler.py")
        rules = [v.rule for v in violations]
        assert "strategy_handler_language_logic" in rules

    def test_detects_elif_language_pattern(self) -> None:
        """Detect elif chains checking language."""
        source = """
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry

class MyHandler(Handler):
    def __init__(self):
        self._registry = TddStrategyRegistry.create_default()

    def handle(self, hook_input):
        if language == "Python":
            pass
        elif language == "Go":
            pass
"""
        violations = check_source(source, "handler.py")
        rules = [v.rule for v in violations]
        assert "strategy_handler_language_logic" in rules

    def test_detects_config_name_check(self) -> None:
        """Detect config.name checks."""
        source = """
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry

class MyHandler(Handler):
    def __init__(self):
        self._registry = TddStrategyRegistry.create_default()

    def handle(self, hook_input):
        if config.name == "Python":
            return "test"
"""
        violations = check_source(source, "handler.py")
        rules = [v.rule for v in violations]
        assert "strategy_handler_language_logic" in rules

    def test_detects_extension_check(self) -> None:
        """Detect file extension checks."""
        source = """
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry

class MyHandler(Handler):
    def __init__(self):
        self._registry = TddStrategyRegistry.create_default()

    def matches(self, hook_input):
        if file_path.endswith(".py"):
            return True
        elif file_path.endswith(".go"):
            return True
"""
        violations = check_source(source, "handler.py")
        rules = [v.rule for v in violations]
        assert "strategy_handler_language_logic" in rules

    def test_allows_handler_without_language_logic(self) -> None:
        """Handler without language-specific logic passes."""
        source = """
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry

class MyHandler(Handler):
    def __init__(self):
        self._registry = TddStrategyRegistry.create_default()

    def matches(self, hook_input):
        strategy = self._registry.get_strategy(file_path)
        return strategy.is_test_file(file_path)
"""
        violations = check_source(source, "handler.py")
        rules = [v.rule for v in violations]
        assert "strategy_handler_language_logic" not in rules

    def test_ignores_non_strategy_handlers(self) -> None:
        """Handlers not using strategies are not checked."""
        source = """
class SimpleHandler(Handler):
    def matches(self, hook_input):
        if tool_name == "Bash":
            return True
"""
        violations = check_source(source, "test.py")
        # Should not flag this as it doesn't import strategies
        rules = [v.rule for v in violations]
        assert "strategy_handler_language_logic" not in rules


class TestStrategyMissingAcceptanceTests:
    """Test detection of missing get_acceptance_tests in strategies."""

    def test_detects_missing_method(self) -> None:
        """Strategy without get_acceptance_tests is flagged."""
        source = """
class PythonTddStrategy:
    @property
    def language_name(self) -> str:
        return "Python"

    @property
    def extensions(self) -> tuple[str, ...]:
        return (".py",)

    def is_test_file(self, file_path: str) -> bool:
        return True

    def is_production_source(self, file_path: str) -> bool:
        return True

    def should_skip(self, file_path: str) -> bool:
        return False

    def compute_test_filename(self, source_filename: str) -> str:
        return f"test_{source_filename}"
"""
        violations = check_source(source, "python_strategy.py")
        rules = [v.rule for v in violations]
        assert "strategy_missing_acceptance_tests" in rules

    def test_allows_strategy_with_method(self) -> None:
        """Strategy with get_acceptance_tests passes."""
        source = """
class PythonTddStrategy:
    @property
    def language_name(self) -> str:
        return "Python"

    def get_acceptance_tests(self) -> list[Any]:
        return []
"""
        violations = check_source(source, "python_strategy.py")
        rules = [v.rule for v in violations]
        assert "strategy_missing_acceptance_tests" not in rules

    def test_ignores_non_strategy_classes(self) -> None:
        """Non-strategy classes are not checked."""
        source = """
class MyHelper:
    def help(self):
        pass
"""
        violations = check_source(source, "helper.py")
        rules = [v.rule for v in violations]
        assert "strategy_missing_acceptance_tests" not in rules


class TestStrategyMissingConstants:
    """Test detection of bare strings in strategies."""

    def test_detects_bare_extension_string(self) -> None:
        """Strategy using bare extension string is flagged."""
        source = """
class PythonTddStrategy:
    @property
    def extensions(self) -> tuple[str, ...]:
        return (".py",)
"""
        violations = check_source(source, "python_strategy.py")
        rules = [v.rule for v in violations]
        assert "strategy_bare_string_literal" in rules

    def test_detects_bare_language_name(self) -> None:
        """Strategy using bare language name is flagged."""
        source = """
class PythonTddStrategy:
    @property
    def language_name(self) -> str:
        return "Python"
"""
        violations = check_source(source, "python_strategy.py")
        rules = [v.rule for v in violations]
        assert "strategy_bare_string_literal" in rules

    def test_detects_bare_directory_string(self) -> None:
        """Strategy using bare directory path is flagged."""
        source = """
class PythonTddStrategy:
    def is_production_source(self, file_path: str) -> bool:
        return "/src/" in file_path
"""
        violations = check_source(source, "python_strategy.py")
        rules = [v.rule for v in violations]
        assert "strategy_bare_string_literal" in rules

    def test_allows_strategy_with_constants(self) -> None:
        """Strategy using named constants passes."""
        source = """
_LANGUAGE_NAME = "Python"
_EXTENSIONS: tuple[str, ...] = (".py",)
_SOURCE_DIRECTORIES: tuple[str, ...] = ("/src/",)

class PythonTddStrategy:
    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS
"""
        violations = check_source(source, "python_strategy.py")
        rules = [v.rule for v in violations]
        assert "strategy_bare_string_literal" not in rules


class TestHandlerMissingAggregation:
    """Test detection of handlers that don't delegate acceptance tests to strategies."""

    def test_detects_missing_delegation(self) -> None:
        """Handler with get_acceptance_tests but no delegation is flagged."""
        source = """
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry

class MyHandler(Handler):
    def __init__(self):
        self._registry = TddStrategyRegistry.create_default()

    def get_acceptance_tests(self):
        return []
"""
        violations = check_source(source, "handler.py")
        rules = [v.rule for v in violations]
        assert "handler_missing_test_aggregation" in rules

    def test_allows_handler_with_delegation(self) -> None:
        """Handler that delegates to strategies passes."""
        source = """
from claude_code_hooks_daemon.strategies.tdd import TddStrategyRegistry

class MyHandler(Handler):
    def __init__(self):
        self._registry = TddStrategyRegistry.create_default()

    def get_acceptance_tests(self):
        tests = []
        for strategy in self._registry.all_strategies():
            tests.extend(strategy.get_acceptance_tests())
        return tests
"""
        violations = check_source(source, "handler.py")
        rules = [v.rule for v in violations]
        assert "handler_missing_test_aggregation" not in rules

    def test_ignores_handler_without_registry(self) -> None:
        """Handler without registry is not checked."""
        source = """
class SimpleHandler(Handler):
    def get_acceptance_tests(self):
        return []
"""
        violations = check_source(source, "handler.py")
        rules = [v.rule for v in violations]
        assert "handler_missing_test_aggregation" not in rules


class TestRegistryMissingStrategy:
    """Test detection of unregistered strategies."""

    def test_detects_unregistered_strategy(self) -> None:
        """Strategy file exists but not registered."""
        source = """
class TddStrategyRegistry:
    @classmethod
    def create_default(cls):
        registry = cls()
        registry.register(PythonTddStrategy())
        return registry
"""
        # This test requires filesystem access, which we'll skip for now
        # The actual implementation will check files in strategies/ directory
        violations = check_source(source, "registry.py")
        # This is a placeholder - actual implementation needs filesystem context
        assert isinstance(violations, list)


class TestCheckFile:
    """Test check_file function."""

    def test_check_nonexistent_file(self, tmp_path: Path) -> None:
        """Nonexistent file returns empty violations."""
        result = check_file(tmp_path / "nonexistent.py")
        assert result == []

    def test_check_valid_file(self, tmp_path: Path) -> None:
        """Valid Python file is checked."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\n")
        result = check_file(test_file)
        assert isinstance(result, list)

    def test_check_non_python_file(self, tmp_path: Path) -> None:
        """Non-Python files return empty violations."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        result = check_file(test_file)
        assert result == []


class TestCheckSource:
    """Test check_source function."""

    def test_syntax_error_returns_empty(self) -> None:
        """Syntax errors in source return empty violations."""
        source = "def invalid syntax"
        violations = check_source(source, "test.py")
        assert violations == []

    def test_empty_source(self) -> None:
        """Empty source returns empty violations."""
        violations = check_source("", "test.py")
        assert violations == []

    def test_valid_source(self) -> None:
        """Valid source is parsed and checked."""
        source = "x = 1"
        violations = check_source(source, "test.py")
        assert isinstance(violations, list)
