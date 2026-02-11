"""Tests for Kotlin TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.kotlin_strategy import KotlinTddStrategy
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


def test_kotlin_strategy_implements_protocol() -> None:
    """KotlinTddStrategy should implement TddStrategy protocol."""
    strategy = KotlinTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'Kotlin'."""
    strategy = KotlinTddStrategy()
    assert strategy.language_name == "Kotlin"


def test_extensions() -> None:
    """Extensions should be ('.kt',)."""
    strategy = KotlinTddStrategy()
    assert strategy.extensions == (".kt",)


def test_is_test_file_with_test_suffix() -> None:
    """Files ending with 'Test.kt' should be recognized as test files."""
    strategy = KotlinTddStrategy()
    assert strategy.is_test_file("/workspace/src/ServiceTest.kt") is True
    assert strategy.is_test_file("/workspace/handlers/HandlerTest.kt") is True


def test_is_test_file_without_test_suffix() -> None:
    """Files NOT ending with 'Test' should NOT be test files (unless in test dir)."""
    strategy = KotlinTddStrategy()
    assert strategy.is_test_file("/workspace/src/Service.kt") is False
    assert strategy.is_test_file("/workspace/handlers/MyHandler.kt") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = KotlinTddStrategy()
    assert strategy.is_test_file("/workspace/tests/unit/Service.kt") is True
    assert strategy.is_test_file("/workspace/test/Helpers.kt") is True
    assert strategy.is_test_file("/workspace/__tests__/Component.kt") is True
    assert strategy.is_test_file("/workspace/spec/ModelSpec.kt") is True


def test_is_production_source_in_src_main_directory() -> None:
    """Files in /src/main/ directory should be production source."""
    strategy = KotlinTddStrategy()
    assert strategy.is_production_source("/workspace/src/main/kotlin/Service.kt") is True
    assert strategy.is_production_source("/workspace/src/main/kotlin/models/User.kt") is True


def test_is_production_source_outside_src_main_directory() -> None:
    """Files outside /src/main/ directory should NOT be production source."""
    strategy = KotlinTddStrategy()
    assert strategy.is_production_source("/workspace/lib/Helper.kt") is False
    assert strategy.is_production_source("/workspace/scripts/Build.kt") is False


def test_should_skip_build_directory() -> None:
    """Files in build/ should be skipped."""
    strategy = KotlinTddStrategy()
    assert strategy.should_skip("/workspace/build/classes/Service.class") is True


def test_should_skip_gradle_directory() -> None:
    """Files in .gradle/ should be skipped."""
    strategy = KotlinTddStrategy()
    assert strategy.should_skip("/workspace/.gradle/caches/Temp.kt") is True


def test_should_skip_vendor_directory() -> None:
    """Files in vendor/ should be skipped."""
    strategy = KotlinTddStrategy()
    assert strategy.should_skip("/workspace/vendor/package/Module.kt") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = KotlinTddStrategy()
    assert strategy.should_skip("/workspace/src/main/kotlin/Service.kt") is False
    assert strategy.should_skip("/workspace/tests/unit/ServiceTest.kt") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with 'Test' suffix."""
    strategy = KotlinTddStrategy()
    assert strategy.compute_test_filename("Service.kt") == "ServiceTest.kt"
    assert strategy.compute_test_filename("Handler.kt") == "HandlerTest.kt"
    assert strategy.compute_test_filename("MyClass.kt") == "MyClassTest.kt"
