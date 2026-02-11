"""Tests for Swift TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy
from claude_code_hooks_daemon.strategies.tdd.swift_strategy import SwiftTddStrategy


def test_swift_strategy_implements_protocol() -> None:
    """SwiftTddStrategy should implement TddStrategy protocol."""
    strategy = SwiftTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'Swift'."""
    strategy = SwiftTddStrategy()
    assert strategy.language_name == "Swift"


def test_extensions() -> None:
    """Extensions should be ('.swift',)."""
    strategy = SwiftTddStrategy()
    assert strategy.extensions == (".swift",)


def test_is_test_file_with_tests_suffix() -> None:
    """Files ending with 'Tests.swift' should be recognized as test files."""
    strategy = SwiftTddStrategy()
    assert strategy.is_test_file("/workspace/Sources/UserServiceTests.swift") is True
    assert strategy.is_test_file("/workspace/src/HandlerTests.swift") is True


def test_is_test_file_without_tests_suffix() -> None:
    """Files NOT ending with 'Tests' should NOT be test files (unless in test dir)."""
    strategy = SwiftTddStrategy()
    assert strategy.is_test_file("/workspace/Sources/UserService.swift") is False
    assert strategy.is_test_file("/workspace/src/Handler.swift") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = SwiftTddStrategy()
    assert strategy.is_test_file("/workspace/tests/unit/Service.swift") is True
    assert strategy.is_test_file("/workspace/test/Helpers.swift") is True
    assert strategy.is_test_file("/workspace/__tests__/Component.swift") is True
    assert strategy.is_test_file("/workspace/spec/ModelSpec.swift") is True


def test_is_production_source_in_sources_directory() -> None:
    """Files in /Sources/ directory should be production source."""
    strategy = SwiftTddStrategy()
    assert strategy.is_production_source("/workspace/Sources/UserService.swift") is True
    assert strategy.is_production_source("/workspace/Sources/Models/User.swift") is True


def test_is_production_source_in_src_directory() -> None:
    """Files in /src/ directory should be production source."""
    strategy = SwiftTddStrategy()
    assert strategy.is_production_source("/workspace/src/UserService.swift") is True
    assert strategy.is_production_source("/workspace/src/Models/User.swift") is True


def test_is_production_source_outside_sources_src_directories() -> None:
    """Files outside /Sources/ and /src/ directories should NOT be production source."""
    strategy = SwiftTddStrategy()
    assert strategy.is_production_source("/workspace/lib/Helper.swift") is False
    assert strategy.is_production_source("/workspace/scripts/Build.swift") is False


def test_should_skip_build_directory() -> None:
    """Files in .build/ should be skipped."""
    strategy = SwiftTddStrategy()
    assert strategy.should_skip("/workspace/.build/debug/Package.swift") is True


def test_should_skip_pods_directory() -> None:
    """Files in Pods/ should be skipped."""
    strategy = SwiftTddStrategy()
    assert strategy.should_skip("/workspace/Pods/Alamofire/Source.swift") is True


def test_should_skip_carthage_directory() -> None:
    """Files in Carthage/ should be skipped."""
    strategy = SwiftTddStrategy()
    assert strategy.should_skip("/workspace/Carthage/Build/Framework.swift") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = SwiftTddStrategy()
    assert strategy.should_skip("/workspace/Sources/UserService.swift") is False
    assert strategy.should_skip("/workspace/tests/unit/UserServiceTests.swift") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with 'Tests' suffix."""
    strategy = SwiftTddStrategy()
    assert strategy.compute_test_filename("UserService.swift") == "UserServiceTests.swift"
    assert strategy.compute_test_filename("Handler.swift") == "HandlerTests.swift"
    assert strategy.compute_test_filename("MyClass.swift") == "MyClassTests.swift"
