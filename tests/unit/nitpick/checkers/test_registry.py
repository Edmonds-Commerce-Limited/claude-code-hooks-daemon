"""Tests for nitpick checker registry."""

from claude_code_hooks_daemon.nitpick.checkers.dismissive import (
    DismissiveLanguageChecker,
)
from claude_code_hooks_daemon.nitpick.checkers.registry import (
    CHECKER_REGISTRY,
    get_checker,
    get_enabled_checkers,
)
from claude_code_hooks_daemon.nitpick.protocol import NitpickChecker


class TestCheckerRegistry:
    """Tests for checker registry."""

    def test_registry_contains_dismissive(self) -> None:
        """Registry contains dismissive_language checker."""
        assert "dismissive_language" in CHECKER_REGISTRY

    def test_registry_contains_hedging(self) -> None:
        """Registry contains hedging_language checker."""
        assert "hedging_language" in CHECKER_REGISTRY

    def test_get_checker_returns_instance(self) -> None:
        """get_checker returns a checker instance by ID."""
        checker = get_checker("dismissive_language")
        assert checker is not None
        assert isinstance(checker, DismissiveLanguageChecker)

    def test_get_checker_unknown_returns_none(self) -> None:
        """get_checker returns None for unknown checker ID."""
        checker = get_checker("nonexistent_checker")
        assert checker is None

    def test_get_enabled_checkers_all_enabled(self) -> None:
        """get_enabled_checkers returns all when all enabled."""
        enabled = {"dismissive_language": True, "hedging_language": True}
        checkers = get_enabled_checkers(enabled)
        assert len(checkers) == 2
        assert all(isinstance(c, NitpickChecker) for c in checkers)

    def test_get_enabled_checkers_some_disabled(self) -> None:
        """get_enabled_checkers skips disabled checkers."""
        enabled = {"dismissive_language": True, "hedging_language": False}
        checkers = get_enabled_checkers(enabled)
        assert len(checkers) == 1
        assert isinstance(checkers[0], DismissiveLanguageChecker)

    def test_get_enabled_checkers_empty_config(self) -> None:
        """get_enabled_checkers returns all when config is empty (default enabled)."""
        checkers = get_enabled_checkers({})
        assert len(checkers) == 2

    def test_all_registry_entries_implement_protocol(self) -> None:
        """All registered checker classes implement NitpickChecker protocol."""
        for checker_id, checker_class in CHECKER_REGISTRY.items():
            instance = checker_class()
            assert isinstance(
                instance, NitpickChecker
            ), f"{checker_id} does not implement NitpickChecker"
            assert instance.checker_id == checker_id
