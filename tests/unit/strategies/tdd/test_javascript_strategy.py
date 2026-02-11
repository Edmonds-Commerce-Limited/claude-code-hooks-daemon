"""Tests for JavaScript/TypeScript TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.javascript_strategy import (
    JavaScriptTddStrategy,
)
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


def test_javascript_strategy_implements_protocol() -> None:
    """JavaScriptTddStrategy should implement TddStrategy protocol."""
    strategy = JavaScriptTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'JavaScript/TypeScript'."""
    strategy = JavaScriptTddStrategy()
    assert strategy.language_name == "JavaScript/TypeScript"


def test_extensions() -> None:
    """Extensions should include .js, .jsx, .ts, .tsx."""
    strategy = JavaScriptTddStrategy()
    assert strategy.extensions == (".js", ".jsx", ".ts", ".tsx")


def test_is_test_file_with_test_pattern() -> None:
    """Files matching *.test.{ext} should be recognized as test files."""
    strategy = JavaScriptTddStrategy()
    assert strategy.is_test_file("/workspace/src/module.test.js") is True
    assert strategy.is_test_file("/workspace/src/Component.test.jsx") is True
    assert strategy.is_test_file("/workspace/src/helpers.test.ts") is True
    assert strategy.is_test_file("/workspace/src/App.test.tsx") is True


def test_is_test_file_with_spec_pattern() -> None:
    """Files matching *.spec.{ext} should be recognized as test files."""
    strategy = JavaScriptTddStrategy()
    assert strategy.is_test_file("/workspace/src/module.spec.js") is True
    assert strategy.is_test_file("/workspace/src/Component.spec.jsx") is True
    assert strategy.is_test_file("/workspace/src/helpers.spec.ts") is True
    assert strategy.is_test_file("/workspace/src/App.spec.tsx") is True


def test_is_test_file_without_test_pattern() -> None:
    """Files NOT matching test patterns should NOT be test files (unless in test dir)."""
    strategy = JavaScriptTddStrategy()
    assert strategy.is_test_file("/workspace/src/module.js") is False
    assert strategy.is_test_file("/workspace/src/Component.tsx") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = JavaScriptTddStrategy()
    assert strategy.is_test_file("/workspace/__tests__/helpers.ts") is True
    assert strategy.is_test_file("/workspace/tests/unit/Component.jsx") is True


def test_is_production_source_in_source_directories() -> None:
    """Files in JS/TS source directories should be production source."""
    strategy = JavaScriptTddStrategy()
    assert strategy.is_production_source("/workspace/src/module.js") is True
    assert strategy.is_production_source("/workspace/lib/helper.ts") is True
    assert strategy.is_production_source("/workspace/app/component.tsx") is True


def test_is_production_source_outside_source_directories() -> None:
    """Files outside source directories should NOT be production source."""
    strategy = JavaScriptTddStrategy()
    assert strategy.is_production_source("/workspace/scripts/build.js") is False
    assert strategy.is_production_source("/workspace/config/webpack.config.js") is False


def test_should_skip_node_modules() -> None:
    """Files in node_modules/ should be skipped."""
    strategy = JavaScriptTddStrategy()
    assert strategy.should_skip("/workspace/node_modules/package/index.js") is True


def test_should_skip_dist_directory() -> None:
    """Files in dist/ should be skipped."""
    strategy = JavaScriptTddStrategy()
    assert strategy.should_skip("/workspace/dist/bundle.js") is True


def test_should_skip_build_directory() -> None:
    """Files in build/ should be skipped."""
    strategy = JavaScriptTddStrategy()
    assert strategy.should_skip("/workspace/build/app.js") is True


def test_should_skip_next_directory() -> None:
    """Files in .next/ should be skipped."""
    strategy = JavaScriptTddStrategy()
    assert strategy.should_skip("/workspace/.next/server/pages/index.js") is True


def test_should_skip_coverage_directory() -> None:
    """Files in coverage/ should be skipped."""
    strategy = JavaScriptTddStrategy()
    assert strategy.should_skip("/workspace/coverage/lcov-report/index.html") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = JavaScriptTddStrategy()
    assert strategy.should_skip("/workspace/src/module.ts") is False
    assert strategy.should_skip("/workspace/lib/helper.js") is False


def test_compute_test_filename_preserves_extension() -> None:
    """Should compute test filename preserving the source file's extension."""
    strategy = JavaScriptTddStrategy()
    assert strategy.compute_test_filename("module.js") == "module.test.js"
    assert strategy.compute_test_filename("Component.jsx") == "Component.test.jsx"
    assert strategy.compute_test_filename("helpers.ts") == "helpers.test.ts"
    assert strategy.compute_test_filename("App.tsx") == "App.test.tsx"
