"""The registry-derived config-optimisation checklist (Plan 00330, Milestone B).

``/hooks-daemon optimise`` used to score a hand-written list of 22 handlers
out of 116. This module replaces that list with a derivation: every
built-in handler (via ``iter_builtin_handler_classes``) and every
pseudo-event handler (via ``pseudo_event_handler_classes``) becomes one
:class:`ChecklistItem`, scored against the project's config and the
handler's own :meth:`Handler.get_relevance` verdict, and grouped into a
computed :class:`Area`.

Decision 1 rules the scoring: the optimal state of a RELEVANT handler is
enabled, whatever its default; an irrelevant one is "not applicable here",
never a shortfall. There is no exemption list anywhere in this module.

Task 2.3 rules the rendering: an area whose relevant handlers are all
enabled collapses to a count, and only shortfalls and not-applicable
handlers are listed in detail, so the report stays readable as the
registry grows.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from claude_code_hooks_daemon.config_optimisation.areas import AREA_ORDER, Area, area_for
from claude_code_hooks_daemon.constants.config import ConfigKey
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.handlers.registry import (
    handler_is_enabled,
    iter_builtin_handler_classes,
)
from claude_code_hooks_daemon.pseudo_events.registry import pseudo_event_handler_classes

_HANDLERS_SECTION: Final[str] = "handlers"
_PSEUDO_EVENTS_SECTION: Final[str] = "pseudo_events"
_PSEUDO_HANDLERS_KEY: Final[str] = "handlers"

_SUMMARY_MAX_CHARS: Final[int] = 72
_RULE_WIDTH: Final[int] = 62

_UNASSESSED_REASON: Final[str] = "could not be constructed, so nothing about it was measured"

_VERDICT_PASS: Final[str] = "PASS"
_VERDICT_WARN: Final[str] = "WARN"
_VERDICT_FAIL: Final[str] = "FAIL"
_VERDICT_NONE: Final[str] = "n/a"


class ItemStatus(StrEnum):
    """What the report says about one handler."""

    OPTIMAL = "optimal"
    SHORTFALL = "shortfall"
    NOT_APPLICABLE = "not-applicable"
    UNASSESSED = "unassessed"


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """One registered handler, scored for one project."""

    config_path: str
    event: str
    config_key: str
    area: Area
    enabled: bool
    default_enabled: bool
    relevance: Relevance
    summary: str
    #: Why this handler could not be asked about itself, or "". Non-empty
    #: means every other field on this item is a placeholder: the handler's
    #: own constructor or verdict raised, so nothing here was measured.
    construction_error: str = ""

    @property
    def status(self) -> ItemStatus:
        """Optimal, shortfall, not applicable, or unassessed."""
        if self.construction_error:
            return ItemStatus.UNASSESSED
        if not self.relevance.applicable:
            return ItemStatus.NOT_APPLICABLE
        return ItemStatus.OPTIMAL if self.enabled else ItemStatus.SHORTFALL


def _summarise(handler_cls: type[Handler]) -> str:
    """The first docstring line, as the one-line description a report shows."""
    doc = (handler_cls.__doc__ or "").strip()
    first = doc.splitlines()[0].strip() if doc else handler_cls.__name__
    first = first.rstrip(".")
    if len(first) > _SUMMARY_MAX_CHARS:
        first = first[: _SUMMARY_MAX_CHARS - 1].rstrip() + "…"
    return first


def _block(section: Mapping[str, Any] | None, key: str) -> Mapping[str, Any]:
    value = section.get(key) if isinstance(section, Mapping) else None
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class _HandlerProbe:
    """What one handler told the checklist about itself, or why it could not.

    Constructing a handler runs arbitrary code, and so does its relevance
    verdict. One raising must not cost the other 113 handlers their verdicts:
    ``register_all`` already contains its own instantiation, and a REPORT is
    the lower-stakes context of the two, which argues for more tolerance
    here rather than less.
    """

    tags: tuple[str, ...]
    default_enabled: bool
    relevance: Relevance
    error: str = ""


def _probe(handler_cls: type[Handler], context: RelevanceContext) -> _HandlerProbe:
    """Ask a handler about itself, turning any failure into a reportable one."""
    try:
        instance = handler_cls()
        return _HandlerProbe(
            tags=tuple(instance.tags),
            default_enabled=instance.get_default_enabled(),
            relevance=instance.get_relevance(context),
        )
    except Exception as exc:
        # Deliberately broad: a handler's constructor and its relevance
        # predicate are both arbitrary code, and this module cannot know what
        # they raise. The error is REPORTED on the item, never swallowed.
        return _HandlerProbe(
            tags=(),
            default_enabled=False,
            relevance=Relevance(applicable=False, reason=_UNASSESSED_REASON),
            error=f"{type(exc).__name__}: {exc}",
        )


def _pseudo_enabled(pseudo_config: Mapping[str, Any] | None, config_key: str) -> bool:
    """Mirror ``enabled_pseudo_event_handler_classes``'s two gates.

    An absent pseudo-event section means the event is never registered, so
    its handlers are disabled; within a present section, an unlisted handler
    defaults to enabled, matching the dispatcher.
    """
    if not isinstance(pseudo_config, Mapping):
        return False
    if not pseudo_config.get(ConfigKey.ENABLED, True):
        return False
    handler_config = _block(pseudo_config.get(_PSEUDO_HANDLERS_KEY), config_key)
    return bool(handler_config.get(ConfigKey.ENABLED, True))


def build_checklist(
    config: Mapping[str, Any],
    context: RelevanceContext,
    *,
    disabled_handlers: Collection[str] = (),
) -> list[ChecklistItem]:
    """Score every registered handler against ``config`` for ``context``.

    Args:
        config: The parsed ``hooks-daemon.yaml`` (a plain mapping, as
            ``ConfigLoader.load`` returns it).
        context: The project view every relevance verdict is decided on.
        disabled_handlers: Handler CLASS names a live registry has disabled
            (``HandlerRegistry.is_disabled``). Registration's fourth gate, and
            runtime state rather than config, so a caller with no registry to
            ask leaves it empty and the gate stays open.

    Returns:
        One item per registered handler, built-ins first in registry order,
        then pseudo-event handlers. Order is stable so two runs diff cleanly.
    """
    handlers_config = _block(config, _HANDLERS_SECTION)
    items: list[ChecklistItem] = []

    for ref in iter_builtin_handler_classes():
        probe = _probe(ref.handler_cls, context)
        event_config = _block(handlers_config, ref.event_dir)
        items.append(
            ChecklistItem(
                config_path=f"{_HANDLERS_SECTION}.{ref.event_dir}.{ref.config_key}",
                event=ref.event_dir,
                config_key=ref.config_key,
                area=area_for(ref.event_dir, probe.tags),
                enabled=handler_is_enabled(
                    event_config,
                    ref.config_key,
                    probe.tags,
                    registry_disabled=ref.handler_cls.__name__ in disabled_handlers,
                ),
                default_enabled=probe.default_enabled,
                relevance=probe.relevance,
                summary=_summarise(ref.handler_cls),
                construction_error=probe.error,
            )
        )

    pseudo_events_config = _block(config, _PSEUDO_EVENTS_SECTION)
    for event_name, entries in pseudo_event_handler_classes().items():
        # Raw, not `_block`: an ABSENT section must stay None so the handlers
        # under it read as disabled, not as "present with defaults".
        raw_pseudo_config = pseudo_events_config.get(event_name)
        pseudo_config = raw_pseudo_config if isinstance(raw_pseudo_config, Mapping) else None
        for config_key, handler_cls in entries.items():
            probe = _probe(handler_cls, context)
            items.append(
                ChecklistItem(
                    config_path=(
                        f"{_PSEUDO_EVENTS_SECTION}.{event_name}.{_PSEUDO_HANDLERS_KEY}.{config_key}"
                    ),
                    event=event_name,
                    config_key=config_key,
                    area=area_for(event_name, probe.tags),
                    enabled=_pseudo_enabled(pseudo_config, config_key),
                    default_enabled=probe.default_enabled,
                    relevance=probe.relevance,
                    summary=_summarise(handler_cls),
                    construction_error=probe.error,
                )
            )
    return items


def _verdict(enabled: int, relevant: int) -> str:
    """PASS: all relevant enabled; WARN: more than half; FAIL: half or fewer."""
    if relevant == 0:
        return _VERDICT_NONE
    if enabled == relevant:
        return _VERDICT_PASS
    return _VERDICT_WARN if enabled * 2 > relevant else _VERDICT_FAIL


def _heading(area: Area, verdict: str, enabled: int, relevant: int) -> str:
    label = f"━━━ {area} "
    tail = f" {verdict} ({enabled}/{relevant})"
    fill = max(1, _RULE_WIDTH - len(label) - len(tail))
    return f"{label}{'━' * fill}{tail}"


def _default_marker(item: ChecklistItem) -> str:
    return "" if item.default_enabled else "  [default off]"


def render_report(items: list[ChecklistItem]) -> str:
    """Render the grouped, collapsed report plus the numbered recommendations.

    Per area: a heading with the verdict and ``enabled/relevant`` count; a
    single line when every relevant handler is enabled; otherwise each
    shortfall with its config path and summary. Not-applicable handlers are
    listed with their reason so a human can see WHY they were not
    recommended, and a handler that could not be constructed is listed with
    its error rather than being silently absent. Optimal handlers are never
    listed by name.
    """
    lines: list[str] = []
    recommendations: list[ChecklistItem] = []
    total_relevant = 0
    total_enabled = 0
    total_not_applicable = 0
    total_unassessed = 0

    for area in AREA_ORDER:
        area_items = [item for item in items if item.area is area]
        if not area_items:
            continue
        enabled = [item for item in area_items if item.status is ItemStatus.OPTIMAL]
        shortfalls = [item for item in area_items if item.status is ItemStatus.SHORTFALL]
        not_applicable = [item for item in area_items if item.status is ItemStatus.NOT_APPLICABLE]
        unassessed = [item for item in area_items if item.status is ItemStatus.UNASSESSED]
        relevant_count = len(enabled) + len(shortfalls)
        total_relevant += relevant_count
        total_enabled += len(enabled)
        total_not_applicable += len(not_applicable)
        total_unassessed += len(unassessed)

        lines.append(
            _heading(area, _verdict(len(enabled), relevant_count), len(enabled), relevant_count)
        )
        if relevant_count and not shortfalls:
            lines.append(f"    all {relevant_count} relevant handlers enabled")
        elif shortfalls:
            lines.append(
                f"    {len(enabled)} relevant handlers enabled; {len(shortfalls)} to enable:"
            )
            for item in shortfalls:
                lines.append(f"    ✗ {item.config_path}{_default_marker(item)}")
                lines.append(f"        {item.summary}")
                recommendations.append(item)
        if not_applicable:
            lines.append(f"    not applicable here ({len(not_applicable)}):")
            for item in not_applicable:
                lines.append(f"    ○ {item.config_path}")
                lines.append(f"        {item.relevance.reason}")
        if unassessed:
            lines.append(f"    could not be assessed ({len(unassessed)}):")
            for item in unassessed:
                lines.append(f"    ! {item.config_path}")
                lines.append(f"        {item.construction_error}")
        lines.append("")

    lines.append("━" * _RULE_WIDTH)
    percent = round(total_enabled * 100 / total_relevant) if total_relevant else 100
    overall = (
        f"Overall: {total_enabled}/{total_relevant} relevant handlers enabled ({percent}%)"
        f" · {total_not_applicable} not applicable here"
    )
    if total_unassessed:
        overall += f" · {total_unassessed} could not be assessed"
    lines.append(overall)
    lines.append("")

    if not recommendations:
        lines.append("No recommendations — every relevant handler is enabled.")
        return "\n".join(lines) + "\n"

    lines.append(f"Recommendations ({len(recommendations)} improvements available):")
    for number, item in enumerate(recommendations, start=1):
        lines.append(f"  [{number}] {item.area}: enable {item.config_path} — {item.summary}")
    return "\n".join(lines) + "\n"


def report_as_json(items: list[ChecklistItem]) -> dict[str, Any]:
    """The same data as :func:`render_report`, machine-readable."""
    relevant = [item for item in items if item.relevance.applicable]
    enabled = [item for item in relevant if item.enabled]
    not_applicable = [item for item in items if item.status is ItemStatus.NOT_APPLICABLE]
    unassessed = [item for item in items if item.status is ItemStatus.UNASSESSED]
    return {
        "summary": {
            "total": len(items),
            "relevant": len(relevant),
            "enabled": len(enabled),
            "shortfall": len(relevant) - len(enabled),
            "not_applicable": len(not_applicable),
            "unassessed": len(unassessed),
        },
        "items": [
            {
                "config_path": item.config_path,
                "event": item.event,
                "config_key": item.config_key,
                "area": str(item.area),
                "enabled": item.enabled,
                "default_enabled": item.default_enabled,
                "applicable": item.relevance.applicable,
                "reason": item.relevance.reason,
                "status": str(item.status),
                "summary": item.summary,
                "construction_error": item.construction_error,
            }
            for item in items
        ],
    }
