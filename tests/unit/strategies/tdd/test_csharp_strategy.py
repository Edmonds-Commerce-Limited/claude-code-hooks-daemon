"""Tests for C# TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.csharp_strategy import CSharpTddStrategy
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


def test_csharp_strategy_implements_protocol() -> None:
    """CSharpTddStrategy should implement TddStrategy protocol."""
    strategy = CSharpTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'C#'."""
    strategy = CSharpTddStrategy()
    assert strategy.language_name == "C#"


def test_extensions() -> None:
    """Extensions should be ('.cs',)."""
    strategy = CSharpTddStrategy()
    assert strategy.extensions == (".cs",)


def test_is_test_file_with_tests_suffix() -> None:
    """Files ending with 'Tests.cs' should be recognized as test files."""
    strategy = CSharpTddStrategy()
    assert strategy.is_test_file("/workspace/src/UserServiceTests.cs") is True
    assert strategy.is_test_file("/workspace/handlers/HandlerTests.cs") is True


def test_is_test_file_with_test_suffix() -> None:
    """Files ending with 'Test.cs' should be recognized as test files."""
    strategy = CSharpTddStrategy()
    assert strategy.is_test_file("/workspace/src/UserServiceTest.cs") is True
    assert strategy.is_test_file("/workspace/handlers/HandlerTest.cs") is True


def test_is_test_file_without_test_suffix() -> None:
    """Files NOT ending with 'Tests' or 'Test' should NOT be test files (unless in test dir)."""
    strategy = CSharpTddStrategy()
    assert strategy.is_test_file("/workspace/src/UserService.cs") is False
    assert strategy.is_test_file("/workspace/handlers/MyHandler.cs") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = CSharpTddStrategy()
    assert strategy.is_test_file("/workspace/tests/unit/Service.cs") is True
    assert strategy.is_test_file("/workspace/test/Helpers.cs") is True
    assert strategy.is_test_file("/workspace/__tests__/Component.cs") is True
    assert strategy.is_test_file("/workspace/spec/ModelSpec.cs") is True


def test_is_production_source_in_src_directory() -> None:
    """Files in /src/ directory should be production source."""
    strategy = CSharpTddStrategy()
    assert strategy.is_production_source("/workspace/src/UserService.cs") is True
    assert strategy.is_production_source("/workspace/src/Models/User.cs") is True


def test_is_production_source_outside_src_directory() -> None:
    """Files outside /src/ directory should NOT be production source."""
    strategy = CSharpTddStrategy()
    assert strategy.is_production_source("/workspace/lib/Helper.cs") is False
    assert strategy.is_production_source("/workspace/scripts/Build.cs") is False


def test_should_skip_bin_directory() -> None:
    """Files in bin/ should be skipped."""
    strategy = CSharpTddStrategy()
    assert strategy.should_skip("/workspace/bin/Debug/Assembly.dll") is True


def test_should_skip_obj_directory() -> None:
    """Files in obj/ should be skipped."""
    strategy = CSharpTddStrategy()
    assert strategy.should_skip("/workspace/obj/Debug/Temp.cs") is True


def test_should_skip_packages_directory() -> None:
    """Files in packages/ should be skipped."""
    strategy = CSharpTddStrategy()
    assert (
        strategy.should_skip("/workspace/packages/Newtonsoft.Json/lib/net45/Newtonsoft.Json.dll")
        is True
    )


def test_should_skip_nuget_directory() -> None:
    """Files in .nuget/ should be skipped."""
    strategy = CSharpTddStrategy()
    assert strategy.should_skip("/workspace/.nuget/packages/Package.cs") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = CSharpTddStrategy()
    assert strategy.should_skip("/workspace/src/UserService.cs") is False
    assert strategy.should_skip("/workspace/tests/unit/UserServiceTests.cs") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with 'Tests' suffix."""
    strategy = CSharpTddStrategy()
    assert strategy.compute_test_filename("UserService.cs") == "UserServiceTests.cs"
    assert strategy.compute_test_filename("Handler.cs") == "HandlerTests.cs"
    assert strategy.compute_test_filename("MyClass.cs") == "MyClassTests.cs"
