"""Tests for build asset watcher handler."""

from collections.abc import Callable
from typing import Any

from build_asset_watcher import BuildAssetWatcherHandler

from claude_code_hooks_daemon.core.hook_result import Decision

# The hook-input factory fixtures are supplied by the conftest the daemon
# generates for project handlers (`hooks-daemon test-project-handlers`).
# Each returns a callable that builds a hook_input dict.
HookInputFactory = Callable[..., dict[str, Any]]


class TestBuildAssetWatcherHandler:
    """Tests for BuildAssetWatcherHandler."""

    def setup_method(self) -> None:
        self.handler = BuildAssetWatcherHandler()

    def test_init(self) -> None:
        assert self.handler.name == "build-asset-watcher"
        assert self.handler.priority == 50
        assert self.handler.terminal is False

    def test_matches_ts_file(self, write_hook_input: HookInputFactory) -> None:
        hook_input = write_hook_input("/project/assets/ts/component.ts")
        assert self.handler.matches(hook_input) is True

    def test_matches_scss_file(self, write_hook_input: HookInputFactory) -> None:
        hook_input = write_hook_input("/project/assets/scss/styles.scss")
        assert self.handler.matches(hook_input) is True

    def test_matches_css_file(self, write_hook_input: HookInputFactory) -> None:
        hook_input = write_hook_input("/project/assets/css/base.css")
        assert self.handler.matches(hook_input) is True

    def test_no_match_php_file(self, write_hook_input: HookInputFactory) -> None:
        hook_input = write_hook_input("/project/src/Service/OrderService.php")
        assert self.handler.matches(hook_input) is False

    def test_no_match_bash_command(self, bash_hook_input: HookInputFactory) -> None:
        hook_input = bash_hook_input("yarn build")
        assert self.handler.matches(hook_input) is False

    def test_handle_returns_advisory(self, write_hook_input: HookInputFactory) -> None:
        hook_input = write_hook_input("/project/assets/ts/component.ts")
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert any("ASSET BUILD REMINDER" in ctx for ctx in result.context)

    def test_acceptance_tests_defined(self) -> None:
        tests = self.handler.get_acceptance_tests()
        assert len(tests) >= 1
