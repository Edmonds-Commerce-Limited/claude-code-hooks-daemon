"""Tests for Rust TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy
from claude_code_hooks_daemon.strategies.tdd.rust_strategy import RustTddStrategy


def test_rust_strategy_implements_protocol() -> None:
    """RustTddStrategy should implement TddStrategy protocol."""
    strategy = RustTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'Rust'."""
    strategy = RustTddStrategy()
    assert strategy.language_name == "Rust"


def test_extensions() -> None:
    """Extensions should be ('.rs',)."""
    strategy = RustTddStrategy()
    assert strategy.extensions == (".rs",)


def test_is_test_file_with_test_suffix() -> None:
    """Files with stem ending in '_test' should be recognized as test files."""
    strategy = RustTddStrategy()
    assert strategy.is_test_file("/workspace/src/parser_test.rs") is True
    assert strategy.is_test_file("/workspace/src/lib_test.rs") is True


def test_is_test_file_without_test_suffix() -> None:
    """Files without '_test' suffix should NOT be test files (unless in test dir)."""
    strategy = RustTddStrategy()
    assert strategy.is_test_file("/workspace/src/parser.rs") is False
    assert strategy.is_test_file("/workspace/src/lib.rs") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = RustTddStrategy()
    assert strategy.is_test_file("/workspace/tests/integration.rs") is True
    assert strategy.is_test_file("/workspace/test/helpers.rs") is True


def test_is_production_source_in_src_directory() -> None:
    """Files in /src/ directory should be production source."""
    strategy = RustTddStrategy()
    assert strategy.is_production_source("/workspace/src/parser.rs") is True
    assert strategy.is_production_source("/workspace/src/lib/module.rs") is True


def test_is_production_source_outside_src_directory() -> None:
    """Files outside /src/ directory should NOT be production source."""
    strategy = RustTddStrategy()
    assert strategy.is_production_source("/workspace/examples/demo.rs") is False
    assert strategy.is_production_source("/workspace/benches/benchmark.rs") is False


def test_should_skip_target_directory() -> None:
    """Files in target/ should be skipped."""
    strategy = RustTddStrategy()
    assert strategy.should_skip("/workspace/target/debug/build/crate.rs") is True
    assert strategy.should_skip("/workspace/target/release/app") is True


def test_should_skip_vendor_directory() -> None:
    """Files in vendor/ should be skipped."""
    strategy = RustTddStrategy()
    assert strategy.should_skip("/workspace/vendor/crate/lib.rs") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = RustTddStrategy()
    assert strategy.should_skip("/workspace/src/parser.rs") is False
    assert strategy.should_skip("/workspace/src/lib.rs") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with '_test' suffix before extension."""
    strategy = RustTddStrategy()
    assert strategy.compute_test_filename("parser.rs") == "parser_test.rs"
    assert strategy.compute_test_filename("lib.rs") == "lib_test.rs"
    assert strategy.compute_test_filename("module.rs") == "module_test.rs"
