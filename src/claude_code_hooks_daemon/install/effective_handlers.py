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

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Literal

import yaml

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


def _handlers_section(config: Mapping[str, Any]) -> Mapping[str, Any]:
    handlers = config.get(_HANDLERS_SECTION)
    return handlers if isinstance(handlers, Mapping) else {}


def _event_block(config: Mapping[str, Any], event: str) -> Mapping[str, Any]:
    block = _handlers_section(config).get(event)
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


_UNIT_INDENT: Final[int] = 2
#: ``handlers:`` on its own line, or with an empty inline mapping (what `init minimal` writes).
_HANDLERS_LINE: Final[re.Pattern[str]] = re.compile(r"^handlers:[ \t]*(\{\}[ \t]*)?(#.*)?$")
_EMPTY_INLINE_MAPPING: Final[re.Pattern[str]] = re.compile(r":[ \t]*\{\}")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _section_end(lines: list[str], start: int, parent_indent: int) -> int:
    """Index of the first content line after ``start`` that is not nested under it."""
    for index in range(start + 1, len(lines)):
        if _is_content(lines[index]) and _indent_of(lines[index]) <= parent_indent:
            return index
    return len(lines)


def _child_indent(lines: list[str], start: int, end: int, default: int) -> int:
    for index in range(start + 1, end):
        if _is_content(lines[index]):
            return _indent_of(lines[index])
    return default


def _insert_block(lines: list[str], at: int, indent: int, rows: list[tuple[int, str]]) -> None:
    lines[at:at] = [f"{' ' * (indent + offset)}{text}\n" for offset, text in rows]


def _add_handler_text(lines: list[str], event: str, keys: list[str], event_declared: bool) -> bool:
    """Insert ``enabled: true`` blocks for ``keys`` under ``handlers.<event>``; False if unsafe.

    ``event_declared`` says the parsed config already has that event, so a text
    search that fails to find it means a layout this editor does not handle.
    """
    handlers_at = next((i for i, ln in enumerate(lines) if _HANDLERS_LINE.match(ln.rstrip())), None)
    if handlers_at is None:
        return False
    end = _section_end(lines, handlers_at, 0)
    unit = _child_indent(lines, handlers_at, end, _UNIT_INDENT)
    lines[handlers_at] = _EMPTY_INLINE_MAPPING.sub(":", lines[handlers_at], count=1)
    event_line = re.compile(rf"^{' ' * unit}{re.escape(event)}:[ \t]*(\{{\}}[ \t]*)?(#.*)?$")
    event_at = next((i for i in range(handlers_at + 1, end) if event_line.match(lines[i])), None)
    block = [row for key in keys for row in ((0, f"{key}:"), (unit, f"{_ENABLED_KEY}: true"))]
    if event_at is None:
        if event_declared:
            return False
        nested = [(offset + unit, text) for offset, text in block]
        _insert_block(lines, handlers_at + 1, unit, [(0, f"{event}:"), *nested])
        return True
    lines[event_at] = _EMPTY_INLINE_MAPPING.sub(":", lines[event_at], count=1)
    event_end = _section_end(lines, event_at, unit)
    child = _child_indent(lines, event_at, event_end, unit * 2)
    _insert_block(lines, event_at + 1, child, block)
    return True


def apply_restore(config_path: Path, changes: list[HandlerChange]) -> bool:
    """Write ``enabled: true`` into the config for every handler that STOPPED.

    N360 (owner ruling C6): a project's real configuration carries across an
    upgrade, so a handler that ran before keeps running. The edit is textual,
    so comments and layout survive, and it is verified before anything is
    written: the edited text must parse and every restored handler must resolve
    as enabled.

    Args:
        config_path: The project's ``hooks-daemon.yaml``.
        changes: The upgrade's handler changes; only ``stops`` entries are written.

    Returns:
        True when the config now keeps every stopped handler running (including
        when nothing needed writing); False, with the file untouched, when the
        file's shape (for example an inline ``handlers: {}``) is not one that
        can be edited safely.
    """
    original = config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(original)
    if not isinstance(config, Mapping):
        return False
    wanted: dict[str, list[str]] = {}
    for change in changes:
        if change.change == "stops" and change.config_key not in _event_block(config, change.event):
            wanted.setdefault(change.event, []).append(change.config_key)
    if not wanted:
        return True

    lines = original.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if _HANDLERS_SECTION not in config:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(f"{_HANDLERS_SECTION}:\n")
    for event, keys in wanted.items():
        declared = event in _handlers_section(config)
        if not _add_handler_text(lines, event, keys, declared):
            return False

    edited = "".join(lines)
    try:
        reloaded = yaml.safe_load(edited)
    except yaml.YAMLError:
        return False
    if not isinstance(reloaded, Mapping):
        return False
    for event, keys in wanted.items():
        block = _event_block(reloaded, event)
        if any(block.get(key) != {_ENABLED_KEY: True} for key in keys):
            return False
    config_path.write_text(edited, encoding="utf-8")
    return True


def format_changes(
    changes: list[HandlerChange],
    from_version: str,
    to_version: str,
    applied: bool | None = None,
) -> str:
    """The loud, human- and agent-readable report for an upgrade summary.

    Args:
        changes: The handlers that stop or start running.
        from_version: Version upgraded from.
        to_version: Version upgraded to.
        applied: ``None`` when no write was attempted; ``True`` when the upgrade
            wrote ``enabled: true`` for the stopped handlers; ``False`` when it
            tried and could not.
    """
    stopped = [c for c in changes if c.change == "stops"]
    started = [c for c in changes if c.change == "starts"]
    lines = [
        f"Effective handler set changes for THIS project's config "
        f"(v{from_version.lstrip('vV')} -> v{to_version.lstrip('vV')}).",
    ]
    if stopped and applied:
        lines.append(
            f"{len(stopped)} handler(s) STOP running by default under the new rules: their "
            "block is absent from your config."
        )
        lines.extend(f"  - {c.config_path}" for c in stopped)
        lines.append(
            "The upgrade wrote `enabled: true` for each of them in .claude/hooks-daemon.yaml, "
            "so the handlers that ran before keep running and your real configuration can "
            "carry across upgrades."
        )
        lines.append(
            "To stop one, set its `enabled: false` or delete its block "
            "(several are noisy and four deny tool calls)."
        )
    elif stopped:
        if applied is False:
            lines.append(
                "The upgrade could not edit .claude/hooks-daemon.yaml automatically "
                "(its layout is not one that can be changed safely)."
            )
        lines.append(
            f"{len(stopped)} handler(s) STOP running: their block is absent from "
            "your config and they are now off unless named."
        )
        lines.extend(f"  - {c.config_path}" for c in stopped)
    if started:
        lines.append(f"{len(started)} handler(s) START running:")
        lines.extend(f"  - {c.config_path}" for c in started)
    snippet = "" if applied else restore_snippet(changes)
    if snippet:
        lines.append("")
        lines.append("To keep the ones you want, add them to .claude/hooks-daemon.yaml")
        lines.append(
            "(name only the handlers you want; several are noisy and four deny tool calls):"
        )
        lines.append("")
        lines.extend(f"    {line}" for line in snippet.splitlines())
    return "\n".join(lines)
