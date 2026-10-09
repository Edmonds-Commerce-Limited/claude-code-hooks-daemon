"""Machine-readable enumeration of the active defences (Plan 00484 Task 3.2).

A defence tool needs one row per defence that is switched on, without running
anything. Nothing is listed here that another surface does not already own:
which handlers are active comes from ``DocsGenerator`` (what ``generate-docs``
renders), and each handler's rules from ``discover_handler_rules`` (what
``explain-rule`` reads). This module only joins the two.

Membership follows owner ruling C1: the content and commit gates are the
Defence set and the action guards are outside it. The deciding property is the
handler's own ``defect_class`` declaration, not a list of names kept here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from claude_code_hooks_daemon.constants.dbf import DefectClass
from claude_code_hooks_daemon.daemon.docs_generator import CollectedHandler
from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING
from claude_code_hooks_daemon.rule_explain.lookup import HandlerRules

__all__ = ["Defence", "collect_active_defences"]

# Behaviour label ``DocsGenerator`` gives a handler tagged ``blocking``.
_BEHAVIOR_BLOCKING = "BLOCKING"


@dataclass(frozen=True, slots=True)
class Defence:
    """One active defence: a rule of an enabled Defence handler, or a rule-less blocking one.

    Attributes:
        rule_id: The rule's public ID, or ``None`` for a blocking handler that
            declares no rule (it is still a defence; it has no ID to list).
        handler: Handler config key.
        handler_class: Handler class name.
        event: Event directory name the handler is wired under.
        priority: Effective priority from the loaded config.
        behavior: ``DocsGenerator`` behaviour label (for example ``BLOCKING``).
        statement: The rule's terse ``blocked`` text, or ``None`` without a rule.
        defect_class: The handler's declared ``Handler.defect_class``. Never
            ``None`` in a listing: a handler without one is an action guard,
            which is outside the Defence set and is not listed.
        docs: The command that prints the full documentation.
        detector_entry_point: The command that runs the defence by sending it a
            payload, or ``None`` when its event is not a wired hook event.
    """

    rule_id: str | None
    handler: str
    handler_class: str
    event: str
    priority: int
    behavior: str
    statement: str | None
    defect_class: DefectClass | None
    docs: str
    detector_entry_point: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a JSON-serialisable mapping."""
        return asdict(self)


def collect_active_defences(
    active_handlers: Iterable[CollectedHandler], handlers: Iterable[HandlerRules]
) -> list[Defence]:
    """Join the enabled handlers with their declared rules.

    Args:
        active_handlers: Enabled handlers, as ``DocsGenerator.active_handlers`` returns them.
        handlers: Every discoverable handler's rules, from ``discover_handler_rules``.

    Returns:
        One record per rule of each enabled handler, plus one rule-less record per
        enabled blocking handler that declares none, ordered by event, priority
        and handler.
    """
    by_class = {entry.class_name: entry for entry in handlers}
    records: list[Defence] = []
    for info in sorted(active_handlers, key=lambda info: (info[2], info[3], info[1])):
        entry = by_class.get(info[0])
        if entry is None or entry.defect_class is None:
            continue  # an action guard (owner ruling C1), or a handler that declares nothing
        for rule in entry.rules:
            records.append(
                _defence(
                    info,
                    entry.defect_class,
                    rule.rule_id,
                    rule.blocked,
                    f"hooks-daemon explain-rule {rule.rule_id}",
                )
            )
        if not entry.rules and info[4] == _BEHAVIOR_BLOCKING:
            records.append(
                _defence(
                    info,
                    entry.defect_class,
                    None,
                    None,
                    f"hooks-daemon explain-handler {info[1]}",
                )
            )
    return records


def _defence(
    info: CollectedHandler,
    defect_class: DefectClass,
    rule_id: str | None,
    statement: str | None,
    docs: str,
) -> Defence:
    """Build one record from a ``CollectedHandler`` tuple and the rule fields."""
    class_name, config_key, event, priority, behavior, _description, _enabled = info
    return Defence(
        rule_id=rule_id,
        handler=config_key,
        handler_class=class_name,
        event=event,
        priority=priority,
        behavior=behavior,
        statement=statement,
        defect_class=defect_class,
        docs=docs,
        detector_entry_point=(
            f"hooks-daemon probe {event} --json <payload>" if event in EVENT_TYPE_MAPPING else None
        ),
    )
