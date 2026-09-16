"""Compare the working-tree guard config against its committed form.

Plan 00412 class 2, `guard-self-disablement-unwatched`: an action that changes
what a future session's guards will do, judged by no gate and recorded nowhere.
F-GAP measured the disabling routes and every one reported `NOTHING DENIES`,
with the compounding property that every deny message names the config key that
would switch off the guard that just fired.

A PreToolUse deny on config writes is owner-gated AND circular -- an agent that
can edit the config can edit the rule guarding it. This module is the
non-circular half: it does not prevent the edit, it makes the edit VISIBLE at
the start of every session.

Pure by design -- YAML text in, findings out, no git and no filesystem -- so the
rules here are the whole behaviour and the handler that supplies the two
documents stays thin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

import yaml

_LOGGER = logging.getLogger(__name__)

_HANDLERS_KEY: Final[str] = "handlers"
_DAEMON_KEY: Final[str] = "daemon"
_ENABLED_KEY: Final[str] = "enabled"
_OPTIONS_KEY: Final[str] = "options"
_EXCLUDE_PATHS_KEY: Final[str] = "exclude_paths"

#: Reported as the owner of a daemon-wide exclusion, which belongs to no handler.
DAEMON_SCOPE: Final[str] = "daemon"


class DriftKind(StrEnum):
    """The weakenings this module can name.

    Deliberately an enumeration of SHAPES, not a claim of completeness -- class 6
    (`outcome-reachable-by-an-unenumerated-spelling`) applies to this rule as
    much as to any other, which is why everything unmatched is still counted by
    :attr:`DriftReport.other_changes` rather than dropped.
    """

    DISABLED = "disabled"
    REMOVED = "removed"
    EXCLUSIONS_WIDENED = "exclusions-widened"


@dataclass(frozen=True)
class GuardChange:
    """One weakening, attributed to the config path that carries it."""

    handler: str
    kind: DriftKind
    detail: str

    def __str__(self) -> str:
        return f"{self.handler}: {self.kind.value} — {self.detail}"


@dataclass(frozen=True)
class DriftReport:
    """What the working tree changed about the guards, relative to HEAD."""

    guard_changes: tuple[GuardChange, ...] = ()
    #: Differences that are real but match no enumerated weakening.
    other_changes: int = 0
    #: True when a document could not be parsed, so nothing could be compared.
    parse_failed: bool = False
    #: True when there is no committed document to compare against.
    no_baseline: bool = field(default=False)

    @property
    def has_drift(self) -> bool:
        """Whether the working tree differs from the committed config at all."""
        return bool(self.guard_changes) or self.other_changes > 0


def _load(document: str) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(document)
    except yaml.YAMLError as exc:
        _LOGGER.debug("guard_config_drift: unparseable config document: %s", exc)
        return None
    return loaded if isinstance(loaded, dict) else None


def _handlers(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten ``handlers.<event>.<name>`` to ``{"event.name": spec}``."""
    flattened: dict[str, dict[str, Any]] = {}
    events = config.get(_HANDLERS_KEY)
    if not isinstance(events, dict):
        return flattened
    for event, entries in events.items():
        if not isinstance(entries, dict):
            continue
        for name, spec in entries.items():
            flattened[f"{event}.{name}"] = spec if isinstance(spec, dict) else {}
    return flattened


def _exclusions(spec: dict[str, Any]) -> list[str]:
    options = spec.get(_OPTIONS_KEY)
    if not isinstance(options, dict):
        return []
    paths = options.get(_EXCLUDE_PATHS_KEY)
    return [str(p) for p in paths] if isinstance(paths, list) else []


def _daemon_exclusions(config: dict[str, Any]) -> list[str]:
    daemon = config.get(_DAEMON_KEY)
    if not isinstance(daemon, dict):
        return []
    paths = daemon.get(_EXCLUDE_PATHS_KEY)
    return [str(p) for p in paths] if isinstance(paths, list) else []


def _is_explicitly_disabled(spec: dict[str, Any]) -> bool:
    """Whether the document SAYS ``enabled: false``.

    Deliberately not "is this guard off": a handler's default-enabled state is a
    property of its class, not of the config, so it cannot be read out of two
    YAML documents. The narrower question is the one that can be answered
    honestly, and it is the one reported.
    """
    return spec.get(_ENABLED_KEY) is False


def compare_guard_config(committed: str, working: str) -> DriftReport:
    """Report how ``working`` weakens the guards relative to ``committed``.

    Args:
        committed: the config as recorded in git, empty when there is none.
        working: the config the daemon will actually load.

    Returns:
        A :class:`DriftReport`. It is empty when the two agree, when there is no
        committed baseline, or when either document is unparseable -- an
        advisory that fires wrongly every session is one that gets switched off.
    """
    if not committed.strip():
        return DriftReport(no_baseline=True)

    before = _load(committed)
    after = _load(working)
    if before is None or after is None:
        return DriftReport(parse_failed=True)

    changes: list[GuardChange] = []
    other = 0

    before_handlers = _handlers(before)
    after_handlers = _handlers(after)

    for name, before_spec in sorted(before_handlers.items()):
        after_spec = after_handlers.get(name)
        if after_spec is None:
            changes.append(
                GuardChange(
                    handler=name,
                    kind=DriftKind.REMOVED,
                    detail="the handler's config block is gone from the working tree",
                )
            )
            continue
        reported_disable = _is_explicitly_disabled(after_spec) and not _is_explicitly_disabled(
            before_spec
        )
        if reported_disable:
            changes.append(
                GuardChange(
                    handler=name,
                    kind=DriftKind.DISABLED,
                    detail="`enabled: false` in the working tree, not in the committed config",
                )
            )
        added = [p for p in _exclusions(after_spec) if p not in _exclusions(before_spec)]
        if added:
            changes.append(
                GuardChange(
                    handler=name,
                    kind=DriftKind.EXCLUSIONS_WIDENED,
                    detail=f"exempts {', '.join(added)}, which the committed config does not",
                )
            )
        # Only a difference that actually PRODUCED a finding is excused. Turning a
        # guard back ON is drift in the safe direction: it earns no weakening, but
        # it is still an uncommitted change to what the guards do, and counting it
        # is the difference between "nothing changed" and "nothing alarming
        # changed".
        if after_spec != before_spec and not _accounted_for(
            before_spec,
            after_spec,
            reported_disable=reported_disable,
            reported_exclusions=bool(added),
        ):
            other += 1

    daemon_added = [p for p in _daemon_exclusions(after) if p not in _daemon_exclusions(before)]
    if daemon_added:
        changes.append(
            GuardChange(
                handler=DAEMON_SCOPE,
                kind=DriftKind.EXCLUSIONS_WIDENED,
                detail=(
                    f"project-wide exclusion of {', '.join(daemon_added)}, "
                    "which the committed config does not carry"
                ),
            )
        )

    other += len(set(after_handlers) - set(before_handlers))
    other += _other_top_level_changes(before, after, reported_daemon_exclusions=bool(daemon_added))

    return DriftReport(guard_changes=tuple(changes), other_changes=other)


def _accounted_for(
    before_spec: dict[str, Any],
    after_spec: dict[str, Any],
    *,
    reported_disable: bool,
    reported_exclusions: bool,
) -> bool:
    """Whether every difference between two handler specs was already reported.

    A key is excused only when a finding was actually emitted for it. Excusing
    `enabled` unconditionally would silently swallow the safe-direction change,
    and this function's whole job is to decide what the caller has NOT said.
    """
    ignored_keys = {_OPTIONS_KEY} | ({_ENABLED_KEY} if reported_disable else set())
    for key in (set(before_spec) | set(after_spec)) - ignored_keys:
        if before_spec.get(key) != after_spec.get(key):
            return False

    # Normalised to {} rather than compared as-is: a handler that had no
    # `options` block until an exclusion was added differs only by the exclusion
    # already reported, and `None != {...}` would count it a second time.
    before_options = before_spec.get(_OPTIONS_KEY) or {}
    after_options = after_spec.get(_OPTIONS_KEY) or {}
    if not (isinstance(before_options, dict) and isinstance(after_options, dict)):
        return before_options == after_options

    ignored_options = {_EXCLUDE_PATHS_KEY} if reported_exclusions else set()
    return all(
        before_options.get(key) == after_options.get(key)
        for key in (set(before_options) | set(after_options)) - ignored_options
    )


def _other_top_level_changes(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    reported_daemon_exclusions: bool,
) -> int:
    """Differing top-level keys other than ``handlers``, counted not named.

    When a daemon-wide exclusion has already been reported as a finding, the
    `daemon` block is compared WITHOUT it -- otherwise the same widening is
    counted once as a named weakening and again as an unnamed difference, and a
    reader cannot tell there is only one thing wrong. The rest of the block is
    still compared, so an unrelated change beside the exclusion is not lost.
    """
    count = 0
    for key in (set(before) | set(after)) - {_HANDLERS_KEY}:
        before_value = before.get(key)
        after_value = after.get(key)
        if key == _DAEMON_KEY and reported_daemon_exclusions:
            before_value = _without_exclusions(before_value)
            after_value = _without_exclusions(after_value)
        if before_value != after_value:
            count += 1
    return count


def _without_exclusions(block: Any) -> Any:
    """``block`` minus its ``exclude_paths`` key, when it has one."""
    if not isinstance(block, dict):
        return block
    return {key: value for key, value in block.items() if key != _EXCLUDE_PATHS_KEY}
