"""Tests for Ruby TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy
from claude_code_hooks_daemon.strategies.tdd.ruby_strategy import RubyTddStrategy


def test_ruby_strategy_implements_protocol() -> None:
    """RubyTddStrategy should implement TddStrategy protocol."""
    strategy = RubyTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'Ruby'."""
    strategy = RubyTddStrategy()
    assert strategy.language_name == "Ruby"


def test_extensions() -> None:
    """Extensions should be ('.rb',)."""
    strategy = RubyTddStrategy()
    assert strategy.extensions == (".rb",)


def test_is_test_file_with_spec_suffix() -> None:
    """Files ending with '_spec.rb' should be recognized as test files."""
    strategy = RubyTddStrategy()
    assert strategy.is_test_file("/workspace/lib/user_spec.rb") is True
    assert strategy.is_test_file("/workspace/app/models/post_spec.rb") is True


def test_is_test_file_with_test_suffix() -> None:
    """Files ending with '_test.rb' should be recognized as test files."""
    strategy = RubyTddStrategy()
    assert strategy.is_test_file("/workspace/lib/user_test.rb") is True
    assert strategy.is_test_file("/workspace/app/models/post_test.rb") is True


def test_is_test_file_without_test_suffix() -> None:
    """Files NOT ending with '_spec' or '_test' should NOT be test files (unless in test dir)."""
    strategy = RubyTddStrategy()
    assert strategy.is_test_file("/workspace/lib/user.rb") is False
    assert strategy.is_test_file("/workspace/app/models/post.rb") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = RubyTddStrategy()
    assert strategy.is_test_file("/workspace/tests/unit/user.rb") is True
    assert strategy.is_test_file("/workspace/test/helpers.rb") is True
    assert strategy.is_test_file("/workspace/__tests__/component.rb") is True
    assert strategy.is_test_file("/workspace/spec/models/user.rb") is True


def test_is_production_source_in_lib_directory() -> None:
    """Files in /lib/ directory should be production source."""
    strategy = RubyTddStrategy()
    assert strategy.is_production_source("/workspace/lib/user.rb") is True
    assert strategy.is_production_source("/workspace/lib/models/post.rb") is True


def test_is_production_source_in_app_directory() -> None:
    """Files in /app/ directory should be production source."""
    strategy = RubyTddStrategy()
    assert strategy.is_production_source("/workspace/app/models/user.rb") is True
    assert strategy.is_production_source("/workspace/app/controllers/posts_controller.rb") is True


def test_is_production_source_outside_lib_app_directories() -> None:
    """Files outside /lib/ and /app/ directories should NOT be production source."""
    strategy = RubyTddStrategy()
    assert strategy.is_production_source("/workspace/scripts/helper.rb") is False
    assert strategy.is_production_source("/workspace/config/database.rb") is False


def test_should_skip_vendor_directory() -> None:
    """Files in vendor/ should be skipped."""
    strategy = RubyTddStrategy()
    assert strategy.should_skip("/workspace/vendor/bundle/gems/rails.rb") is True


def test_should_skip_bundle_directory() -> None:
    """Files in .bundle/ should be skipped."""
    strategy = RubyTddStrategy()
    assert strategy.should_skip("/workspace/.bundle/gems/rspec.rb") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = RubyTddStrategy()
    assert strategy.should_skip("/workspace/lib/user.rb") is False
    assert strategy.should_skip("/workspace/app/models/post.rb") is False
    assert strategy.should_skip("/workspace/spec/user_spec.rb") is False


def test_compute_test_filename() -> None:
    """Should compute test filename with '_spec' suffix."""
    strategy = RubyTddStrategy()
    assert strategy.compute_test_filename("user.rb") == "user_spec.rb"
    assert strategy.compute_test_filename("post.rb") == "post_spec.rb"
    assert strategy.compute_test_filename("my_class.rb") == "my_class_spec.rb"
