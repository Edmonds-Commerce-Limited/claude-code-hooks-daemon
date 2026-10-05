"""Which handlers an upgrade starts or stops running for ONE project (Plan 00493).

The v3.68.0 resolution rule (an opt-in handler with no block under
``handlers.<event>`` no longer runs) changed what a project runs while leaving
its config file byte-identical, so neither a file diff nor a manifest entry
without a ``recommended_value`` could say so. This module answers the question
directly: it resolves the project's ACTUAL config under the rules of the old
version and of the new one, through the same ``handler_is_enabled`` the daemon
dispatches with, and reports every handler on which the two differ.

A future change to how an absent block resolves is recorded in
:func:`_absent_block_defers_to_default` and shows up in the report with no
other change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal

from claude_code_hooks_daemon.handlers.registry import (
    handler_is_enabled,
    iter_builtin_handler_classes,
)
from claude_code_hooks_daemon.install.version_parse import parse_version_tuple

#: First release whose resolution defers an ABSENT block to the handler's
#: declared ``default_enabled`` (Plan 00483 N55). Earlier releases enabled it.
_ABSENT_BLOCK_DEFERS_SINCE: Final[tuple[int, ...]] = (3, 68, 0)

#: Handlers that did not exist before that release. They never ran under the
#: old rule, so they cannot "stop".
_ADDED_WITH_DEFERRING_RULE: Final[frozenset[str]] = frozenset({"plan_fact_check_feed"})

_HANDLERS_SECTION: Final[str] = "handlers"
_ENABLED_KEY: Final[str] = "enabled"
_INDENT: Final[str] = "  "

ChangeKind = Literal["stops", "starts"]


@dataclass(frozen=True, slots=True)
class HandlerChange:
    """One handler whose effective state differs between two versions."""

    event: str
    config_key: str
    change: ChangeKind

    @property
    def config_path(self) -> str:
        """The ``handlers.<event>.<key>`` path naming this handler in config."""
        return f"{_HANDLERS_SECTION}.{self.event}.{self.config_key}"

    def to_dict(self) -> dict[str, str]:
        """JSON-serialisable form, including the derived config path."""
        return {**asdict(self), "config_path": self.config_path}


def _version(version: str) -> tuple[int, ...]:
    """Parse a release or branch-install version, ignoring a ``+build`` suffix."""
    return parse_version_tuple(version.split("+", 1)[0])


def _absent_block_defers_to_default(version: str) -> bool:
    """Whether ``version`` resolves an absent block to ``default_enabled``."""
    return _version(version) >= _ABSENT_BLOCK_DEFERS_SINCE


def _event_block(config: Mapping[str, Any], event: str) -> Mapping[str, Any]:
    handlers = config.get(_HANDLERS_SECTION)
    block = handlers.get(event) if isinstance(handlers, Mapping) else None
    return block if isinstance(block, Mapping) else {}


def effective_handler_changes(
    config: Mapping[str, Any], from_version: str, to_version: str
) -> list[HandlerChange]:
    """Handlers whose effective state differs between the two versions' rules.

    Args:
        config: The project's parsed ``hooks-daemon.yaml``.
        from_version: Version the project upgrades from (``v`` prefix allowed).
        to_version: Version it upgrades to (a ``+build`` suffix is ignored).

    Returns:
        One entry per handler that stops or starts running, in registry order.

    Raises:
        ValueError: If either version string is not dot-separated integers.
    """
    old_defers = _absent_block_defers_to_default(from_version)
    new_defers = _absent_block_defers_to_default(to_version)

    changes: list[HandlerChange] = []
    for ref in iter_builtin_handler_classes():
        if not old_defers and new_defers and ref.config_key in _ADDED_WITH_DEFERRING_RULE:
            continue
        event_block = _event_block(config, ref.event_dir)
        declared = ref.handler_cls.default_enabled
        # Tags are not passed: both sides apply the same tag gates, so they
        # cannot make the two answers differ.
        was = handler_is_enabled(
            event_block, ref.config_key, (), default_enabled=declared if old_defers else True
        )
        now = handler_is_enabled(
            event_block, ref.config_key, (), default_enabled=declared if new_defers else True
        )
        if was != now:
            changes.append(
                HandlerChange(
                    event=ref.event_dir,
                    config_key=ref.config_key,
                    change="starts" if now else "stops",
                )
            )
    return changes


def restore_snippet(changes: list[HandlerChange]) -> str:
    """YAML that re-enables every handler that STOPPED, grouped by event.

    Naming a handler, even by a bare key, enables it, so ``enabled: true`` is
    the explicit form. Handlers that started are not in the snippet: nothing
    was lost, and the project can disable them by name if it did not want them.
    """
    by_event: dict[str, list[str]] = {}
    for change in changes:
        if change.change == "stops":
            by_event.setdefault(change.event, []).append(change.config_key)
    if not by_event:
        return ""
    lines = [f"{_HANDLERS_SECTION}:"]
    for event, keys in by_event.items():
        lines.append(f"{_INDENT}{event}:")
        for key in keys:
            lines.append(f"{_INDENT * 2}{key}:")
            lines.append(f"{_INDENT * 3}{_ENABLED_KEY}: true")
    return "\n".join(lines) + "\n"


def format_changes(changes: list[HandlerChange], from_version: str, to_version: str) -> str:
    """The loud, human- and agent-readable report for an upgrade summary."""
    stopped = [c for c in changes if c.change == "stops"]
    started = [c for c in changes if c.change == "starts"]
    lines = [
        f"Effective handler set changes for THIS project's config "
        f"(v{from_version.lstrip('vV')} -> v{to_version.lstrip('vV')}).",
    ]
    if stopped:
        lines.append(
            f"{len(stopped)} handler(s) STOP running: their block is absent from "
            "your config and they are now off unless named."
        )
        lines.extend(f"  - {c.config_path}" for c in stopped)
    if started:
        lines.append(f"{len(started)} handler(s) START running:")
        lines.extend(f"  - {c.config_path}" for c in started)
    snippet = restore_snippet(changes)
    if snippet:
        lines.append("")
        lines.append("To keep the ones you want, add them to .claude/hooks-daemon.yaml")
        lines.append("(name only the handlers you want; several are noisy and four deny tool calls):")
        lines.append("")
        lines.extend(f"    {line}" for line in snippet.splitlines())
    return "\n".join(lines)
