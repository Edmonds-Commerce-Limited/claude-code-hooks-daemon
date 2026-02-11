"""Tests for Go TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.go_strategy import GoTddStrategy
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


def test_go_strategy_implements_protocol() -> None:
    """GoTddStrategy should implement TddStrategy protocol."""
    strategy = GoTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'Go'."""
    strategy = GoTddStrategy()
    assert strategy.language_name == "Go"


def test_extensions() -> None:
    """Extensions should be ('.go',)."""
    strategy = GoTddStrategy()
    assert strategy.extensions == (".go",)


def test_is_test_file_with_test_suffix() -> None:
    """Files ending with '_test.go' should be recognized as test files."""
    strategy = GoTddStrategy()
    assert strategy.is_test_file("/workspace/src/module_test.go") is True
    assert strategy.is_test_file("/workspace/pkg/server_test.go") is True


def test_is_test_file_without_test_suffix() -> None:
    """Files NOT ending with '_test.go' should NOT be test files (unless in test dir)."""
    strategy = GoTddStrategy()
    assert strategy.is_test_file("/workspace/src/module.go") is False
    assert strategy.is_test_file("/workspace/pkg/server.go") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = GoTddStrategy()
    assert strategy.is_test_file("/workspace/tests/helpers.go") is True
    assert strategy.is_test_file("/workspace/test/utils.go") is True


def test_is_production_source_in_source_directories() -> None:
    """Files in Go source directories should be production source."""
    strategy = GoTddStrategy()
    assert strategy.is_production_source("/workspace/src/module.go") is True
    assert strategy.is_production_source("/workspace/cmd/app/main.go") is True
    assert strategy.is_production_source("/workspace/pkg/lib/helper.go") is True
    assert strategy.is_production_source("/workspace/internal/service/handler.go") is True


def test_is_production_source_outside_source_directories() -> None:
    """Files outside Go source directories should NOT be production source."""
    strategy = GoTddStrategy()
    assert strategy.is_production_source("/workspace/scripts/build.go") is False
    assert strategy.is_production_source("/workspace/tools/generate.go") is False


def test_should_skip_vendor_directory() -> None:
    """Files in vendor/ should be skipped."""
    strategy = GoTddStrategy()
    assert strategy.should_skip("/workspace/vendor/github.com/pkg/module.go") is True


def test_should_skip_testdata_directory() -> None:
    """Files in testdata/ should be skipped."""
    strategy = GoTddStrategy()
    assert strategy.should_skip("/workspace/testdata/fixtures.go") is True
    assert strategy.should_skip("/workspace/pkg/testdata/sample.go") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = GoTddStrategy()
    assert strategy.should_skip("/workspace/src/module.go") is False
    assert strategy.should_skip("/workspace/cmd/app/main.go") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with '_test.go' suffix."""
    strategy = GoTddStrategy()
    assert strategy.compute_test_filename("server.go") == "server_test.go"
    assert strategy.compute_test_filename("handler.go") == "handler_test.go"
    assert strategy.compute_test_filename("parser.go") == "parser_test.go"
