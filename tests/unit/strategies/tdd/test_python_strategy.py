"""Tests for Python TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy
from claude_code_hooks_daemon.strategies.tdd.python_strategy import PythonTddStrategy


def test_python_strategy_implements_protocol() -> None:
    """PythonTddStrategy should implement TddStrategy protocol."""
    strategy = PythonTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'Python'."""
    strategy = PythonTddStrategy()
    assert strategy.language_name == "Python"


def test_extensions() -> None:
    """Extensions should be ('.py',)."""
    strategy = PythonTddStrategy()
    assert strategy.extensions == (".py",)


def test_is_test_file_with_test_prefix() -> None:
    """Files starting with 'test_' should be recognized as test files."""
    strategy = PythonTddStrategy()
    assert strategy.is_test_file("/workspace/src/test_module.py") is True
    assert strategy.is_test_file("/workspace/handlers/test_handler.py") is True


def test_is_test_file_without_test_prefix() -> None:
    """Files NOT starting with 'test_' should NOT be test files (unless in test dir)."""
    strategy = PythonTddStrategy()
    assert strategy.is_test_file("/workspace/src/module.py") is False
    assert strategy.is_test_file("/workspace/handlers/my_handler.py") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = PythonTddStrategy()
    assert strategy.is_test_file("/workspace/tests/unit/module.py") is True
    assert strategy.is_test_file("/workspace/test/helpers.py") is True
    assert strategy.is_test_file("/workspace/__tests__/component.py") is True
    assert strategy.is_test_file("/workspace/spec/model_spec.py") is True


def test_is_production_source_in_src_directory() -> None:
    """Files in /src/ directory should be production source."""
    strategy = PythonTddStrategy()
    assert strategy.is_production_source("/workspace/src/module.py") is True
    assert strategy.is_production_source("/workspace/src/package/submodule.py") is True


def test_is_production_source_outside_src_directory() -> None:
    """Files outside /src/ directory should NOT be production source."""
    strategy = PythonTddStrategy()
    assert strategy.is_production_source("/workspace/lib/helper.py") is False
    assert strategy.is_production_source("/workspace/scripts/run.py") is False


def test_is_production_source_excludes_init_files() -> None:
    """Python __init__.py files should be excluded from production source."""
    strategy = PythonTddStrategy()
    assert strategy.is_production_source("/workspace/src/__init__.py") is False
    assert strategy.is_production_source("/workspace/src/package/__init__.py") is False


def test_should_skip_fixtures_directory() -> None:
    """Files in tests/fixtures/ should be skipped."""
    strategy = PythonTddStrategy()
    assert strategy.should_skip("/workspace/tests/fixtures/sample_data.py") is True


def test_should_skip_migrations_directory() -> None:
    """Files in migrations/ should be skipped."""
    strategy = PythonTddStrategy()
    assert strategy.should_skip("/workspace/migrations/001_initial.py") is True


def test_should_skip_vendor_directory() -> None:
    """Files in vendor/ should be skipped."""
    strategy = PythonTddStrategy()
    assert strategy.should_skip("/workspace/vendor/package/module.py") is True


def test_should_skip_venv_directories() -> None:
    """Files in .venv/ or venv/ should be skipped."""
    strategy = PythonTddStrategy()
    assert strategy.should_skip("/workspace/.venv/lib/python/site-packages/module.py") is True
    assert strategy.should_skip("/workspace/venv/lib/python/site-packages/module.py") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = PythonTddStrategy()
    assert strategy.should_skip("/workspace/src/module.py") is False
    assert strategy.should_skip("/workspace/tests/unit/test_module.py") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with 'test_' prefix."""
    strategy = PythonTddStrategy()
    assert strategy.compute_test_filename("module.py") == "test_module.py"
    assert strategy.compute_test_filename("handler.py") == "test_handler.py"
    assert strategy.compute_test_filename("my_class.py") == "test_my_class.py"
