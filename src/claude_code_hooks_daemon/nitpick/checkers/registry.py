"""Nitpick checker registry - maps checker_id to checker class.

Central registry for all available nitpick checkers. Adding a new checker
requires only creating a class and registering it here.
"""

from claude_code_hooks_daemon.nitpick.checkers.dismissive import (
    DismissiveLanguageChecker,
)
from claude_code_hooks_daemon.nitpick.checkers.hedging import (
    HedgingLanguageChecker,
)
from claude_code_hooks_daemon.nitpick.protocol import NitpickChecker

# Registry mapping checker_id -> checker class
CHECKER_REGISTRY: dict[str, type] = {
    "dismissive_language": DismissiveLanguageChecker,
    "hedging_language": HedgingLanguageChecker,
}


def get_checker(checker_id: str) -> NitpickChecker | None:
    """Get a checker instance by ID.

    Args:
        checker_id: Registered checker identifier

    Returns:
        Checker instance, or None if not found
    """
    checker_class = CHECKER_REGISTRY.get(checker_id)
    if checker_class is None:
        return None
    return checker_class()


def get_enabled_checkers(
    config: dict[str, bool],
) -> list[NitpickChecker]:
    """Get instances of all enabled checkers.

    Checkers not mentioned in config default to enabled.

    Args:
        config: Dict mapping checker_id -> enabled (True/False)

    Returns:
        List of enabled checker instances
    """
    checkers: list[NitpickChecker] = []
    for checker_id, checker_class in CHECKER_REGISTRY.items():
        if config.get(checker_id, True):
            checkers.append(checker_class())
    return checkers
