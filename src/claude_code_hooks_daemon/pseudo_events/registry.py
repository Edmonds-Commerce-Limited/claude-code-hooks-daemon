"""The one place that knows which handlers belong to which pseudo-event.

A pseudo-event handler is a handler like any other to everything EXCEPT
dispatch. Dispatch is the single place the distinction is real: these handlers
are driven by :class:`PseudoEventDispatcher` on a trigger ratio rather than by
the ``EventRouter`` on a hook event. Every OTHER consumer — CLAUDE.md guidance
injection, the generated active-handler docs, the acceptance playbook, the
daemon's live ``handlers`` introspection — wants "all live handlers" and has no
reason to care how a handler is dispatched.

Before Plan 00237 this mapping lived as a private static method on
``DaemonController``, so the only component that could see it was the one that
dispatches. Each of the four consumers above re-derived the handler set its own
way, and all four derivations silently excluded the whole category:

- two walked the ``EventRouter``'s chains, which these handlers never join;
- two iterated ``EVENT_TYPE_MAPPING``, which has no ``nitpick`` key — correctly,
  because ``nitpick`` is not a dispatchable ``EventType`` and adding one would
  make the router treat it as dispatchable.

Both facts were right and the outcome was wrong, which is why the fix is a
shared source of truth rather than a fourth special case. Add a pseudo-event
here and every surface picks it up; add it in one consumer and you have
recreated the original bug with a smaller blast radius.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.handler import Handler

# Pseudo-event name as it appears under ``pseudo_events:`` in hooks-daemon.yaml.
NITPICK = "nitpick"

# Config keys read from a pseudo-event's config block.
_ENABLED_KEY = "enabled"
_HANDLERS_KEY = "handlers"


def pseudo_event_handler_classes() -> dict[str, dict[str, type[Handler]]]:
    """Map each pseudo-event name to ``{config key: handler class}``.

    Keyed by the key used under ``pseudo_events.<name>.handlers`` in
    ``hooks-daemon.yaml``, which is deliberately NOT the handler's
    ``HandlerID.config_key``: the nitpick handlers already carry two spellings
    (``dismissive_language`` in the config file, ``dismissive_language_nitpick``
    in ``HandlerID``). Anything filtering on config has to match what the
    config file actually says, so that is the key recorded here.

    Classes rather than instances: consumers differ in what they need. Docs and
    playbook generation want metadata available without a live daemon, while
    dispatch wants constructed handlers. Returning classes lets each caller
    decide, and keeps this module free of construction side effects.

    Imports are deferred into the function body to avoid an import cycle —
    handler modules import from ``core``, which imports this package.

    Returns:
        Pseudo-event name -> {config key -> handler class}.
    """
    from claude_code_hooks_daemon.handlers.nitpick.dismissive_language import (
        DismissiveLanguageNitpickHandler,
    )
    from claude_code_hooks_daemon.handlers.nitpick.hedging_language import (
        HedgingLanguageNitpickHandler,
    )

    return {
        NITPICK: {
            "dismissive_language": DismissiveLanguageNitpickHandler,
            "hedging_language": HedgingLanguageNitpickHandler,
        },
    }


def enabled_pseudo_event_handler_classes(
    pseudo_events_config: dict[str, Any] | None,
) -> dict[str, dict[str, type[Handler]]]:
    """As :func:`pseudo_event_handler_classes`, filtered by config.

    Applies BOTH config gates:

    1. the pseudo-event's own ``enabled`` flag (default True, matching
       ``PseudoEventConfig``);
    2. the per-handler ``enabled`` flag under its ``handlers:`` block.

    Gate 2 was documented and parsed (``PseudoEventConfig.handler_configs``)
    but read by NOTHING before Plan 00237 — the dispatcher built its chain from
    the factory list unconditionally, so setting ``enabled: false`` on a nitpick
    handler silently did nothing. Both dispatch and every reporting surface now
    filter through here, so the flag means the same thing everywhere.

    A pseudo-event absent from the config is absent from the result: unlike
    ``handlers:``, an unconfigured pseudo-event is never registered at all.

    Args:
        pseudo_events_config: The ``pseudo_events:`` config section, or None.

    Returns:
        Pseudo-event name -> {config key -> ENABLED handler class}. Names with
        no enabled handlers are omitted entirely, so a caller can treat an
        empty result as "nothing to render".
    """
    if not pseudo_events_config:
        return {}

    result: dict[str, dict[str, type[Handler]]] = {}
    for name, entries in pseudo_event_handler_classes().items():
        config = pseudo_events_config.get(name)
        if not isinstance(config, dict) or not config.get(_ENABLED_KEY, True):
            continue

        handler_configs = config.get(_HANDLERS_KEY)
        enabled = {
            config_key: cls
            for config_key, cls in entries.items()
            if _handler_enabled(handler_configs, config_key)
        }
        if enabled:
            result[name] = enabled
    return result


def _handler_enabled(handler_configs: Any, config_key: str) -> bool:
    """Whether ``config_key`` is enabled, defaulting to True when unlisted.

    Deliberately permissive about the config's shape: this is read by doc and
    playbook generators that run against whatever is on disk, and a malformed
    block must not crash a whole report. An unreadable entry is treated as
    enabled, matching the daemon's own default.
    """
    if not isinstance(handler_configs, dict):
        return True
    entry = handler_configs.get(config_key)
    if not isinstance(entry, dict):
        return True
    return bool(entry.get(_ENABLED_KEY, True))
