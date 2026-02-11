"""Tests for Java TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.java_strategy import JavaTddStrategy
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


def test_java_strategy_implements_protocol() -> None:
    """JavaTddStrategy should implement TddStrategy protocol."""
    strategy = JavaTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'Java'."""
    strategy = JavaTddStrategy()
    assert strategy.language_name == "Java"


def test_extensions() -> None:
    """Extensions should be ('.java',)."""
    strategy = JavaTddStrategy()
    assert strategy.extensions == (".java",)


def test_is_test_file_with_test_suffix() -> None:
    """Files with stem ending in 'Test' should be recognized as test files."""
    strategy = JavaTddStrategy()
    assert strategy.is_test_file("/workspace/src/UserTest.java") is True
    assert strategy.is_test_file("/workspace/src/ServiceTest.java") is True


def test_is_test_file_without_test_suffix() -> None:
    """Files without 'Test' suffix should NOT be test files (unless in test dir)."""
    strategy = JavaTddStrategy()
    assert strategy.is_test_file("/workspace/src/User.java") is False
    assert strategy.is_test_file("/workspace/src/Service.java") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = JavaTddStrategy()
    assert strategy.is_test_file("/workspace/tests/integration/Helper.java") is True
    assert strategy.is_test_file("/workspace/test/unit/Util.java") is True


def test_is_production_source_in_src_main_directory() -> None:
    """Files in /src/main/ directory should be production source."""
    strategy = JavaTddStrategy()
    assert strategy.is_production_source("/workspace/src/main/java/User.java") is True
    assert strategy.is_production_source("/workspace/src/main/java/com/app/Service.java") is True


def test_is_production_source_outside_src_main_directory() -> None:
    """Files outside /src/main/ directory should NOT be production source."""
    strategy = JavaTddStrategy()
    assert strategy.is_production_source("/workspace/src/test/java/UserTest.java") is False
    assert strategy.is_production_source("/workspace/scripts/Build.java") is False


def test_should_skip_target_directory() -> None:
    """Files in target/ should be skipped."""
    strategy = JavaTddStrategy()
    assert strategy.should_skip("/workspace/target/classes/User.class") is True


def test_should_skip_build_directory() -> None:
    """Files in build/ should be skipped."""
    strategy = JavaTddStrategy()
    assert strategy.should_skip("/workspace/build/libs/app.jar") is True


def test_should_skip_gradle_directory() -> None:
    """Files in .gradle/ should be skipped."""
    strategy = JavaTddStrategy()
    assert strategy.should_skip("/workspace/.gradle/caches/module.jar") is True


def test_should_skip_vendor_directory() -> None:
    """Files in vendor/ should be skipped."""
    strategy = JavaTddStrategy()
    assert strategy.should_skip("/workspace/vendor/lib/dependency.java") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = JavaTddStrategy()
    assert strategy.should_skip("/workspace/src/main/java/User.java") is False
    assert strategy.should_skip("/workspace/src/main/java/Service.java") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with 'Test' suffix before extension."""
    strategy = JavaTddStrategy()
    assert strategy.compute_test_filename("User.java") == "UserTest.java"
    assert strategy.compute_test_filename("Service.java") == "ServiceTest.java"
    assert strategy.compute_test_filename("Controller.java") == "ControllerTest.java"
