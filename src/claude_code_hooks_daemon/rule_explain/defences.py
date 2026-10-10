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

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from claude_code_hooks_daemon.constants.dbf import DefectClass
from claude_code_hooks_daemon.daemon.docs_generator import CollectedHandler
from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING
from claude_code_hooks_daemon.rule_explain.lookup import HandlerRules

__all__ = [
    "KIND_BATCH_CHECK",
    "KIND_HANDLER",
    "QA_RULES_RELATIVE_PATH",
    "Defence",
    "collect_active_defences",
    "collect_batch_defences",
]

# Behaviour label ``DocsGenerator`` gives a handler tagged ``blocking``.
_BEHAVIOR_BLOCKING = "BLOCKING"

#: ``Defence.kind`` of a row for a write-time handler rule.
KIND_HANDLER = "handler"
#: ``Defence.kind`` of a row for a ``scripts/qa`` checker that is the batch form of a handler.
KIND_BATCH_CHECK = "batch-check"

#: Where a project keeps the QA rule registry that also declares the batch-check rows.
QA_RULES_RELATIVE_PATH = "scripts/qa/qa-rules.json"
#: ``Defence.event`` of a batch-check row: it runs from the QA runner, not on a hook event.
_BATCH_EVENT = "qa"
_BATCH_PRIORITY = 0
_QA_RUNNER = "./scripts/qa/llm_qa.py"


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
        kind: ``handler`` for a write-time handler rule, ``batch-check`` for a
            ``scripts/qa`` checker row. For a batch-check row ``handler`` is the
            ``llm_qa.py`` step, ``handler_class`` the script, ``event`` is ``qa``
            and ``priority`` is 0.
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
    kind: str = KIND_HANDLER

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


def collect_batch_defences(
    qa_rules: Mapping[str, Any], handler_classes: Mapping[str, DefectClass]
) -> list[Defence]:
    """List the batch checkers that are the whole-tree form of an active Defence handler.

    Membership is the ``batch_defences`` map of ``qa-rules.json`` (script ->
    ``step`` and the config key of the ``handler`` it mirrors); rule IDs,
    statements and the docs route are that file's own ``rules``, so no second
    registry exists. One row per rule ID a declared script prints, leaving out
    the rules marked ``meta`` (they report on the checker itself, not on a
    defect). The defect class is the one the active handler's own row carries.

    Args:
        qa_rules: The parsed ``qa-rules.json`` document.
        handler_classes: Defect class by config key of every active Defence handler.
            A script whose handler is not in it is disabled or absent and gets no rows.

    Returns:
        The rows, in the declaration order of the scripts and of their rules;
        empty when the document declares no ``batch_defences``.

    Raises:
        ValueError: A declared script prints no non-meta rule in ``rules``.
    """
    declared: Mapping[str, Mapping[str, Any]] = qa_rules.get("batch_defences", {})
    rules: Mapping[str, Mapping[str, Any]] = qa_rules.get("rules", {})
    records: list[Defence] = []
    for script, entry in declared.items():
        step = entry["step"]
        entry_point = f"{_QA_RUNNER} {step}"
        printed = [
            (rule_id, rule)
            for rule_id, rule in rules.items()
            if script in rule["checks"] and not rule.get("meta", False)
        ]
        if not printed:
            raise ValueError(
                f"batch_defences names {script}, which prints no defect rule in qa-rules.json"
            )
        defect_class = handler_classes.get(entry["handler"])
        if defect_class is None:
            continue
        records.extend(
            Defence(
                rule_id=rule_id,
                handler=step,
                handler_class=script,
                event=_BATCH_EVENT,
                priority=_BATCH_PRIORITY,
                behavior=_BEHAVIOR_BLOCKING,
                statement=rule["statement"],
                defect_class=defect_class,
                docs=f"{_QA_RUNNER} --explain {rule_id}",
                detector_entry_point=entry_point,
                kind=KIND_BATCH_CHECK,
            )
            for rule_id, rule in printed
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
            f"hooks-daemon probe {event} --only {config_key} --json <payload>"
            if event in EVENT_TYPE_MAPPING
            else None
        ),
    )
