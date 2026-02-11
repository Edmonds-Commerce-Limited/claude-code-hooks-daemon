"""Tests for Dart TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.dart_strategy import DartTddStrategy
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


def test_dart_strategy_implements_protocol() -> None:
    """DartTddStrategy should implement TddStrategy protocol."""
    strategy = DartTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'Dart'."""
    strategy = DartTddStrategy()
    assert strategy.language_name == "Dart"


def test_extensions() -> None:
    """Extensions should be ('.dart',)."""
    strategy = DartTddStrategy()
    assert strategy.extensions == (".dart",)


def test_is_test_file_with_test_suffix() -> None:
    """Files ending with '_test.dart' should be recognized as test files."""
    strategy = DartTddStrategy()
    assert strategy.is_test_file("/workspace/lib/widget_test.dart") is True
    assert strategy.is_test_file("/workspace/lib/models/user_test.dart") is True


def test_is_test_file_without_test_suffix() -> None:
    """Files NOT ending with '_test' should NOT be test files (unless in test dir)."""
    strategy = DartTddStrategy()
    assert strategy.is_test_file("/workspace/lib/widget.dart") is False
    assert strategy.is_test_file("/workspace/lib/models/user.dart") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = DartTddStrategy()
    assert strategy.is_test_file("/workspace/tests/unit/widget.dart") is True
    assert strategy.is_test_file("/workspace/test/helpers.dart") is True
    assert strategy.is_test_file("/workspace/__tests__/component.dart") is True
    assert strategy.is_test_file("/workspace/spec/model_spec.dart") is True


def test_is_production_source_in_lib_directory() -> None:
    """Files in /lib/ directory should be production source."""
    strategy = DartTddStrategy()
    assert strategy.is_production_source("/workspace/lib/widget.dart") is True
    assert strategy.is_production_source("/workspace/lib/models/user.dart") is True


def test_is_production_source_outside_lib_directory() -> None:
    """Files outside /lib/ directory should NOT be production source."""
    strategy = DartTddStrategy()
    assert strategy.is_production_source("/workspace/bin/main.dart") is False
    assert strategy.is_production_source("/workspace/scripts/build.dart") is False


def test_should_skip_dart_tool_directory() -> None:
    """Files in .dart_tool/ should be skipped."""
    strategy = DartTddStrategy()
    assert strategy.should_skip("/workspace/.dart_tool/package_config.json") is True


def test_should_skip_build_directory() -> None:
    """Files in build/ should be skipped."""
    strategy = DartTddStrategy()
    assert strategy.should_skip("/workspace/build/app/outputs/flutter.dart") is True


def test_should_skip_pub_cache_directory() -> None:
    """Files in .pub-cache/ should be skipped."""
    strategy = DartTddStrategy()
    assert strategy.should_skip("/workspace/.pub-cache/hosted/package.dart") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = DartTddStrategy()
    assert strategy.should_skip("/workspace/lib/widget.dart") is False
    assert strategy.should_skip("/workspace/test/widget_test.dart") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with '_test' suffix."""
    strategy = DartTddStrategy()
    assert strategy.compute_test_filename("widget.dart") == "widget_test.dart"
    assert strategy.compute_test_filename("user.dart") == "user_test.dart"
    assert strategy.compute_test_filename("my_class.dart") == "my_class_test.dart"
