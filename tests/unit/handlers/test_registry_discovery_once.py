"""Handler registry discovery runs once per process and is shared.

Phase 1 of Plan 00495 measured four ``discover`` calls on the daemon start path
(three config validations and the controller), three of which cost 1.63 s of
the 1.70 s total: each walked and re-inspected every handler module.
"""

import pkgutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.daemon.cli import _build_initialised_controller
from claude_code_hooks_daemon.handlers import registry as registry_module
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

HANDLERS_PACKAGE = "claude_code_hooks_daemon.handlers"


@pytest.fixture(autouse=True)
def fresh_discovery_cache() -> Iterator[None]:
    """Each test starts, and leaves, with nothing discovered."""
    registry_module.clear_discovery_cache()
    yield
    registry_module.clear_discovery_cache()


@pytest.fixture
def walk_count() -> Iterator[list[str]]:
    """Record the package path of every module walk ``discover`` starts.

    ``pkgutil.walk_packages`` calls itself for each subpackage, so only the
    outermost call of each walk is recorded.
    """
    walked: list[str] = []
    real_walk = pkgutil.walk_packages
    depth = 0

    def counting_walk(path: Any, prefix: str = "", *args: Any, **kwargs: Any) -> Iterator[Any]:
        nonlocal depth
        if depth == 0:
            walked.append(prefix.rstrip("."))
        depth += 1
        try:
            yield from real_walk(path, prefix, *args, **kwargs)
        finally:
            depth -= 1

    with patch.object(registry_module.pkgutil, "walk_packages", counting_walk):
        yield walked


class TestDiscoverySharing:
    """A second registry gets the first one's result without walking again."""

    def test_second_discover_does_not_walk_the_package(self, walk_count: list[str]) -> None:
        """Only the first ``discover`` of a package walks it."""
        HandlerRegistry().discover()
        HandlerRegistry().discover()
        assert walk_count == [HANDLERS_PACKAGE]

    def test_second_registry_sees_the_same_handlers_and_count(self) -> None:
        """The shared result is the same set of classes, with the same count."""
        first, second = HandlerRegistry(), HandlerRegistry()
        first_count = first.discover()
        second_count = second.discover()
        assert second_count == first_count > 0
        assert second.list_handlers() == first.list_handlers()
        assert second.get_handler_class("DestructiveGitHandler") is first.get_handler_class(
            "DestructiveGitHandler"
        )

    def test_registries_do_not_share_state(self) -> None:
        """Changing one registry's handlers leaves the shared result alone."""
        first = HandlerRegistry()
        first.discover()
        first._handlers.pop("DestructiveGitHandler")

        later = HandlerRegistry()
        later.discover()

        assert first.get_handler_class("DestructiveGitHandler") is None
        assert later.get_handler_class("DestructiveGitHandler") is not None

    def test_each_package_path_is_discovered_separately(self, walk_count: list[str]) -> None:
        """A different package is not answered from another package's result."""
        subpackage = f"{HANDLERS_PACKAGE}.pre_tool_use"
        HandlerRegistry().discover()
        HandlerRegistry().discover(subpackage)
        assert walk_count == [HANDLERS_PACKAGE, subpackage]

    def test_unimportable_package_is_retried_not_remembered(self) -> None:
        """A package that failed to import is not cached as an empty result."""
        missing = "claude_code_hooks_daemon.no_such_handlers_package"
        assert HandlerRegistry().discover(missing) == 0
        assert missing not in registry_module._DISCOVERY_CACHE

    def test_clear_discovery_cache_forces_a_new_walk(self, walk_count: list[str]) -> None:
        """Clearing the cache makes the next discovery walk again."""
        HandlerRegistry().discover()
        registry_module.clear_discovery_cache()
        HandlerRegistry().discover()
        assert walk_count == [HANDLERS_PACKAGE, HANDLERS_PACKAGE]


class TestStartPathDiscoversOnce:
    """Config load plus controller build walks the handlers package once."""

    def test_start_path_walks_the_handlers_package_once(
        self, tmp_path: Path, walk_count: list[str]
    ) -> None:
        """Every ``discover`` on the start path after the first reuses its result."""
        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        (config_dir / "hooks-daemon.yaml").write_text(
            "version: '2.0'\ndaemon:\n  idle_timeout_seconds: 600\n  log_level: INFO\n"
            "handlers: {}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:example/example.git"],
            cwd=tmp_path,
            check=True,
        )

        config = Config.find_and_load(tmp_path)
        _build_initialised_controller(config, tmp_path)

        assert walk_count.count(HANDLERS_PACKAGE) == 1
