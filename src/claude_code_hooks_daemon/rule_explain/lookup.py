"""Rule/handler lookup for on-demand explanation (Plan 00116 Task 6.1).

Collects every discoverable handler's ``get_rules()`` output plus its
``get_claude_md()`` text into ``HandlerRules`` entries, then answers two
questions: "what handler and rule does this rule ID belong to?" and "what
does this handler declare?". Matching is tolerant (case-insensitive, with or
without the ``R-`` prefix) because a human or an LLM typing an ID from
memory is the primary caller.
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry, _to_snake_case

logger = logging.getLogger(__name__)

__all__ = [
    "HandlerRules",
    "collect_handler_rules",
    "discover_handler_rules",
    "find_handler",
    "find_rule",
    "near_handler_matches",
    "near_rule_matches",
]

# difflib.get_close_matches cutoff/limit — loose enough to catch a typo'd
# rule/handler name, tight enough not to suggest something unrelated.
_NEAR_MATCH_CUTOFF = 0.5
_NEAR_MATCH_LIMIT = 5


@dataclass(frozen=True, slots=True)
class HandlerRules:
    """One discovered handler's config key, class name, rules and docs.

    Attributes:
        config_key: Snake-case config key (as used in ``hooks-daemon.yaml``
            and ``get_claude_md()`` cross-references), e.g. ``destructive_git``.
        class_name: The handler's Python class name, e.g. ``DestructiveGitHandler``.
        rules: This handler's declared ``Rule`` objects (empty for handlers
            that have not migrated onto ``get_rules()``).
        claude_md: This handler's ``get_claude_md()`` text, or ``None``.
    """

    config_key: str
    class_name: str
    rules: tuple[Rule, ...]
    claude_md: str | None


def _normalise_id(value: str) -> str:
    """Uppercase and add the ``R-`` prefix if missing, for tolerant matching."""
    candidate = value.strip().upper()
    if not candidate or candidate.startswith("R-"):
        return candidate
    return f"R-{candidate}"


def collect_handler_rules(handler_classes: Iterable[type[Handler]]) -> list[HandlerRules]:
    """Instantiate each handler class and collect its rules + docs.

    A handler that fails to instantiate, or whose ``get_rules()``/
    ``get_claude_md()`` raises, is logged and skipped rather than aborting
    the whole collection — one broken handler must not hide every other
    rule from ``explain-rule``.

    Args:
        handler_classes: Handler classes to instantiate and inspect.

    Returns:
        One ``HandlerRules`` per handler that inspected successfully,
        sorted by config key for stable output.
    """
    collected: list[HandlerRules] = []
    for handler_class in handler_classes:
        try:
            instance = handler_class()
            rules = tuple(instance.get_rules())
            claude_md = instance.get_claude_md()
        except Exception:
            logger.exception("Failed to inspect handler %s for rule lookup", handler_class.__name__)
            continue
        collected.append(
            HandlerRules(
                config_key=_to_snake_case(handler_class.__name__),
                class_name=handler_class.__name__,
                rules=rules,
                claude_md=claude_md,
            )
        )

    collected.sort(key=lambda entry: entry.config_key)
    return collected


def discover_handler_rules(
    package_path: str = "claude_code_hooks_daemon.handlers",
) -> list[HandlerRules]:
    """Discover every handler under ``package_path`` and collect its rules.

    Walks the handlers package directly via ``HandlerRegistry`` — the same
    machinery ``DocsGenerator`` uses — so this never requires a running
    daemon. New rules from sibling handler migrations appear automatically
    on the next call.

    Args:
        package_path: Python package path to scan (override only for tests).

    Returns:
        One ``HandlerRules`` per handler that instantiated and inspected
        successfully, sorted by config key.
    """
    registry = HandlerRegistry()
    registry.discover(package_path)

    handler_classes = (
        handler_class
        for handler_class in (registry.get_handler_class(name) for name in registry.list_handlers())
        if handler_class is not None
    )
    return collect_handler_rules(handler_classes)


def find_rule(handlers: list[HandlerRules], rule_id: str) -> tuple[HandlerRules, Rule] | None:
    """Find a ``Rule`` by ID, case-insensitively and tolerant of a missing ``R-``.

    Args:
        handlers: Handlers to search (typically from ``discover_handler_rules``).
        rule_id: The rule ID to look up, in any case, with or without ``R-``.

    Returns:
        The owning ``HandlerRules`` and matched ``Rule``, or ``None``.
    """
    target = _normalise_id(rule_id)
    for handler in handlers:
        for rule in handler.rules:
            if rule.rule_id.upper() == target:
                return handler, rule
    return None


def near_rule_matches(
    handlers: list[HandlerRules], rule_id: str, limit: int = _NEAR_MATCH_LIMIT
) -> list[str]:
    """Suggest close-spelling rule IDs for an unknown lookup.

    Args:
        handlers: Handlers to search.
        rule_id: The unmatched rule ID the caller typed.
        limit: Maximum number of suggestions to return.

    Returns:
        Close-spelling rule IDs, best match first; empty if nothing is close.
    """
    target = _normalise_id(rule_id)
    all_ids = [rule.rule_id for handler in handlers for rule in handler.rules]
    return difflib.get_close_matches(target, all_ids, n=limit, cutoff=_NEAR_MATCH_CUTOFF)


def find_handler(handlers: list[HandlerRules], name: str) -> HandlerRules | None:
    """Find a handler by config key or class name, case-insensitively.

    Args:
        handlers: Handlers to search.
        name: The handler name to look up — a config key (e.g.
            ``destructive_git``) or a class name (e.g. ``DestructiveGitHandler``).

    Returns:
        The matched ``HandlerRules``, or ``None``.
    """
    target = name.strip().lower()
    for handler in handlers:
        if handler.config_key.lower() == target or handler.class_name.lower() == target:
            return handler
    return None


def near_handler_matches(
    handlers: list[HandlerRules], name: str, limit: int = _NEAR_MATCH_LIMIT
) -> list[str]:
    """Suggest close-spelling handler config keys for an unknown lookup.

    Args:
        handlers: Handlers to search.
        name: The unmatched handler name the caller typed.
        limit: Maximum number of suggestions to return.

    Returns:
        Close-spelling config keys, best match first; empty if nothing is close.
    """
    target = name.strip().lower()
    candidates = [handler.config_key for handler in handlers]
    return difflib.get_close_matches(target, candidates, n=limit, cutoff=_NEAR_MATCH_CUTOFF)
