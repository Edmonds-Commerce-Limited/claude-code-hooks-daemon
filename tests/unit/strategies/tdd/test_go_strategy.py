"""Tests for Go TDD Strategy."""

from pathlib import Path

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


def _module(root: Path) -> Path:
    """Make ``root`` a Go module and return it."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "go.mod").write_text("module example.com/app\n")
    return root


def test_is_production_source_inside_module_any_layout(tmp_path: Path) -> None:
    """Any .go file inside a module is production source, whatever its directory."""
    strategy = GoTddStrategy()
    mod = _module(tmp_path / "app")
    for rel in (
        "main.go",  # root-level package
        "api/handler.go",  # other top-level package dirs
        "server/routes.go",
        "src/module.go",
        "cmd/app/helper.go",
        "pkg/lib/helper.go",
        "internal/service/handler.go",
    ):
        assert strategy.is_production_source(str(mod / rel)) is True, rel


def test_is_production_source_outside_module_is_false(tmp_path: Path) -> None:
    """A .go file with no go.mod at or above it is not gated."""
    strategy = GoTddStrategy()
    (tmp_path / "scripts").mkdir()
    assert strategy.is_production_source(str(tmp_path / "scripts" / "build.go")) is False


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
