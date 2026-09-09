"""Audit ``handlers.<event>.<key>`` entries against the handler registry.

The registry — what the daemon can actually discover for each event, plus the
pseudo-event handler map — is the only truth about which keys do anything. The
reference config is a rendering of that truth and can lag it, so nothing here
consults the reference config.

A key that is not registered for its event is one of four things:

- ``relocated``: retired under this event, live under a pseudo-event
  (``RELOCATED_HANDLERS``). The upgrade merge moves it there.
- ``wrong_event``: registered, but for a different event. The finding names the
  event it belongs to.
- ``retired``: the daemon used to ship it and deliberately removed it
  (``RETIRED_HANDLERS``). Accepted silently at startup, so it needs saying here.
- ``unknown``: a typo or a handler this daemon has never had. Startup treats
  this as a hard error, and so does ``config-validate``.

Plan 00362, report §2: a client carried ``stop.hedging_language_detector`` and
``stop.dismissive_language_detector`` through an upgrade to a version where both
lived only under ``pseudo_events.nitpick.handlers``. ``config-validate`` called
the config valid, the upgrade said "no config changes", and neither detector
ran.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal

from claude_code_hooks_daemon.config.validator import ConfigValidator
from claude_code_hooks_daemon.constants.handlers import (
    RELOCATED_HANDLERS,
    RETIRED_HANDLERS,
    HandlerRelocation,
)
from claude_code_hooks_daemon.pseudo_events.registry import pseudo_event_handler_classes

FindingKind = Literal["relocated", "wrong_event", "retired", "unknown"]
MigrationAction = Literal["moved", "dropped_duplicate"]

_HANDLERS = "handlers"
_PSEUDO_EVENTS = "pseudo_events"
_ENABLED = "enabled"
_TRIGGERS = "triggers"

# The block written when a relocated key is migrated and the config has no
# ``pseudo_events.<name>`` yet. An unconfigured pseudo-event is never
# registered at all (``pseudo_events.registry``), so moving a handler under a
# block that does not exist would retire it a second time. Triggers match the
# reference config.
_DEFAULT_PSEUDO_EVENT_BLOCKS: dict[str, dict[str, Any]] = {
    "nitpick": {
        _ENABLED: True,
        _TRIGGERS: ["pre_tool_use:1/5", "stop:1/1"],
    },
}


@dataclass(frozen=True)
class HandlerKeyFinding:
    """One ``handlers.<event>.<key>`` entry the registry does not know for that event."""

    path: str
    event: str
    key: str
    kind: FindingKind
    message: str
    target_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form."""
        return {
            "path": self.path,
            "event": self.event,
            "key": self.key,
            "kind": self.kind,
            "message": self.message,
            "target_path": self.target_path,
        }


@dataclass(frozen=True)
class HandlerKeyMigration:
    """One relocated entry the migration acted on."""

    source_path: str
    target_path: str
    action: MigrationAction

    @property
    def summary(self) -> str:
        """``source -> target`` for a one-line upgrade summary."""
        return f"{self.source_path} -> {self.target_path}"

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable form."""
        return {
            "source_path": self.source_path,
            "target_path": self.target_path,
            "action": self.action,
            "summary": self.summary,
        }


def _registered_keys_by_event() -> dict[str, set[str]]:
    """Event -> config keys the registry discovers for it (real events only)."""
    return {
        event: ConfigValidator.get_available_handlers(event)
        for event in sorted(ConfigValidator.VALID_EVENT_TYPES)
    }


def _pseudo_event_keys() -> dict[str, set[str]]:
    """Pseudo-event name -> config keys under its ``handlers:`` block."""
    return {name: set(keys) for name, keys in pseudo_event_handler_classes().items()}


def _other_home(
    key: str,
    event: str,
    by_event: dict[str, set[str]],
    by_pseudo_event: dict[str, set[str]],
) -> str | None:
    """Dotted path of the section that DOES register ``key``, if any."""
    for other_event, keys in by_event.items():
        if other_event != event and key in keys:
            return f"{_HANDLERS}.{other_event}.{key}"
    for name, keys in by_pseudo_event.items():
        if key in keys:
            return f"{_PSEUDO_EVENTS}.{name}.{_HANDLERS}.{key}"
    return None


def _classify(
    event: str,
    key: str,
    by_event: dict[str, set[str]],
    by_pseudo_event: dict[str, set[str]],
) -> HandlerKeyFinding | None:
    path = f"{_HANDLERS}.{event}.{key}"

    relocation: HandlerRelocation | None = RELOCATED_HANDLERS.get(key)
    if relocation is not None:
        return HandlerKeyFinding(
            path=path,
            event=event,
            key=key,
            kind="relocated",
            target_path=relocation.target_path,
            message=(
                f"{path}: '{key}' is no longer a {event} handler; it lives at "
                f"{relocation.target_path} now. The upgrade moves this entry there "
                f"(enabled/priority preserved); until then it does nothing here."
            ),
        )

    other_home = _other_home(key, event, by_event, by_pseudo_event)
    if other_home is not None:
        return HandlerKeyFinding(
            path=path,
            event=event,
            key=key,
            kind="wrong_event",
            target_path=other_home,
            message=(
                f"{path}: '{key}' is not a {event} handler; it is registered under "
                f"{other_home.rsplit('.', 1)[0]} — move it to {other_home}."
            ),
        )

    retired_reason = RETIRED_HANDLERS.get(key)
    if retired_reason is not None:
        return HandlerKeyFinding(
            path=path,
            event=event,
            key=key,
            kind="retired",
            message=f"{path}: '{key}' no longer exists — {retired_reason}",
        )

    similar = ConfigValidator.find_similar_names(key, by_event.get(event, set()))
    hint = f" Did you mean: {', '.join(similar)}?" if similar else ""
    return HandlerKeyFinding(
        path=path,
        event=event,
        key=key,
        kind="unknown",
        message=f"{path}: '{key}' is not a handler registered for any event.{hint}",
    )


def audit_handler_keys(config: dict[str, Any]) -> list[HandlerKeyFinding]:
    """Report every ``handlers.<event>.<key>`` the registry does not know for that event.

    Sections that are not mappings, and event names the schema does not
    recognise, are skipped: both are reported by the schema validation that
    runs alongside this audit, and repeating them here would double-count.

    Args:
        config: Parsed hooks-daemon.yaml.

    Returns:
        Findings in config order; empty when every key is registered for its event.
    """
    handlers = config.get(_HANDLERS)
    if not isinstance(handlers, dict):
        return []

    by_event = _registered_keys_by_event()
    by_pseudo_event = _pseudo_event_keys()

    findings: list[HandlerKeyFinding] = []
    for event, entries in handlers.items():
        if event not in by_event or not isinstance(entries, dict):
            continue
        registered = by_event[event]
        for key in entries:
            if not isinstance(key, str) or key in registered:
                continue
            finding = _classify(event, key, by_event, by_pseudo_event)
            if finding is not None:
                findings.append(finding)
    return findings


def format_findings(findings: list[HandlerKeyFinding]) -> list[str]:
    """One human-readable line per finding."""
    return [finding.message for finding in findings]


def migrate_relocated_handler_keys(
    config: dict[str, Any],
    *,
    scaffold: bool = True,
) -> tuple[dict[str, Any], list[HandlerKeyMigration]]:
    """Move every ``RELOCATED_HANDLERS`` entry to its pseudo-event home.

    The entry's whole mapping (``enabled``, ``priority``, ``options``) travels
    with it. When the target already exists the target is kept as written —
    the live entry is the one the user has been editing — and the stale copy
    is dropped.

    With ``scaffold`` (the default) a ``pseudo_events.<name>`` block missing
    ``enabled``/``triggers`` has them filled from ``_DEFAULT_PSEUDO_EVENT_BLOCKS``
    so the moved handler is actually registered; keys already present are
    kept. Pass ``scaffold=False`` when the result feeds a merge whose new
    default supplies those keys — the merge would otherwise take a fabricated
    trigger list for the user's own choice and let it win over the default.

    Args:
        config: Parsed hooks-daemon.yaml. Not mutated.
        scaffold: Fill a block's missing ``enabled``/``triggers`` from defaults.

    Returns:
        ``(migrated config, records)``; the config is returned unchanged (as a
        copy) with no records when there was nothing to move.
    """
    migrated = copy.deepcopy(config)
    records: list[HandlerKeyMigration] = []

    handlers = migrated.get(_HANDLERS)
    if not isinstance(handlers, dict):
        return migrated, records

    for event, entries in handlers.items():
        if not isinstance(entries, dict):
            continue
        for key in [k for k in entries if k in RELOCATED_HANDLERS]:
            relocation = RELOCATED_HANDLERS[key]
            entry = entries.pop(key)
            source_path = f"{_HANDLERS}.{event}.{key}"
            target_block = _ensure_pseudo_event_handlers(
                migrated, relocation.pseudo_event, scaffold=scaffold
            )
            if relocation.config_key in target_block:
                action: MigrationAction = "dropped_duplicate"
            else:
                target_block[relocation.config_key] = (
                    entry if isinstance(entry, dict) else {_ENABLED: bool(entry)}
                )
                action = "moved"
            records.append(
                HandlerKeyMigration(
                    source_path=source_path,
                    target_path=relocation.target_path,
                    action=action,
                )
            )

    return migrated, records


def _ensure_pseudo_event_handlers(
    config: dict[str, Any], name: str, *, scaffold: bool
) -> dict[str, Any]:
    """Return ``pseudo_events.<name>.handlers``, creating what is missing."""
    pseudo_events = config.get(_PSEUDO_EVENTS)
    if not isinstance(pseudo_events, dict):
        pseudo_events = {}
        config[_PSEUDO_EVENTS] = pseudo_events

    block = pseudo_events.get(name)
    if not isinstance(block, dict):
        block = {}
        pseudo_events[name] = block
    if scaffold:
        _fill_block_defaults(block, name)

    handlers = block.get(_HANDLERS)
    if not isinstance(handlers, dict):
        handlers = {}
        block[_HANDLERS] = handlers
    return handlers


def _fill_block_defaults(block: dict[str, Any], name: str) -> None:
    """Add ``enabled``/``triggers`` a pseudo-event block lacks; keep what it has.

    Raises:
        ValueError: when ``name`` has no entry in
            :data:`_DEFAULT_PSEUDO_EVENT_BLOCKS`. The old fallback wrote
            ``{enabled: True}`` and no triggers, and a block with handlers
            but no triggers never fires -- so a relocation aimed at an
            unknown pseudo-event would silently retire the handler a second
            time, which is the failure this whole module exists to stop.
            Failing during the upgrade says so; an enabled empty block does
            not (Plan 00364 Task 2.3).
    """
    defaults = _DEFAULT_PSEUDO_EVENT_BLOCKS.get(name)
    if defaults is None:
        raise ValueError(
            f"pseudo-event '{name}' has no default block, so scaffolding it would "
            f"produce an enabled block with no triggers, which never fires. Add an "
            f"entry to _DEFAULT_PSEUDO_EVENT_BLOCKS matching the reference config."
        )
    for key, value in defaults.items():
        block.setdefault(key, copy.deepcopy(value))


def scaffold_pseudo_event_blocks(config: dict[str, Any]) -> dict[str, Any]:
    """Fill ``enabled``/``triggers`` into every configured pseudo-event block that lacks them.

    An unconfigured pseudo-event is never registered, and a block with
    handlers but no triggers never fires; both are the moved handler retired a
    second time. Existing keys are kept as written.

    A block this module has no defaults for is left exactly as the user wrote
    it: there is nothing to complete it FROM, and inventing an ``enabled: true``
    with no triggers would assert a block fires when it cannot. Unlike the
    relocation path, an unknown name here is not a bug -- a project may
    configure a pseudo-event this constant never had to scaffold.

    Args:
        config: Parsed hooks-daemon.yaml. Not mutated.

    Returns:
        A copy with every KNOWN ``pseudo_events.<name>`` mapping completed.
    """
    result = copy.deepcopy(config)
    pseudo_events = result.get(_PSEUDO_EVENTS)
    if not isinstance(pseudo_events, dict):
        return result
    for name, block in pseudo_events.items():
        if isinstance(block, dict) and name in _DEFAULT_PSEUDO_EVENT_BLOCKS:
            _fill_block_defaults(block, name)
    return result


def _has_path(config: dict[str, Any], dotted: str) -> bool:
    current: Any = config
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def applied_relocations(before: dict[str, Any], after: dict[str, Any]) -> list[HandlerKeyMigration]:
    """Relocations that ``after`` shows as done relative to ``before``.

    Used by the upgrade summary, which sees only the pre-upgrade backup and the
    written config: a relocated key present in ``before``, absent from
    ``after``, whose target exists in ``after``, was moved.

    Args:
        before: Config as it was (the backup).
        after: Config as written.

    Returns:
        One ``moved`` record per relocation performed, in ``before`` order.
    """
    handlers = before.get(_HANDLERS)
    if not isinstance(handlers, dict):
        return []

    applied: list[HandlerKeyMigration] = []
    for event, entries in handlers.items():
        if not isinstance(entries, dict):
            continue
        for key in entries:
            relocation = RELOCATED_HANDLERS.get(key)
            if relocation is None:
                continue
            source_path = f"{_HANDLERS}.{event}.{key}"
            if _has_path(after, source_path) or not _has_path(after, relocation.target_path):
                continue
            applied.append(
                HandlerKeyMigration(
                    source_path=source_path,
                    target_path=relocation.target_path,
                    action="moved",
                )
            )
    return applied
