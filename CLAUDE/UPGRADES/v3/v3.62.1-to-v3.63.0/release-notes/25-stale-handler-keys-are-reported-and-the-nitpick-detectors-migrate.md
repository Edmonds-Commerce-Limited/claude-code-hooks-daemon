# Callout: a handler key that no longer exists for its event is reported, and the nitpick detectors move themselves

**Plan**: 00362
**Audience**: client projects

`config-validate`, `check-config-migrations` and the new
`hooks-daemon audit-handler-keys` now check every `handlers.<event>.<key>`
against the handler registry: a retired key says "no longer exists" with the
reason, a key registered under another event names that event, and a key
whose handler moved to a pseudo-event names its new home. The upgrade moves
`stop.hedging_language_detector` and `stop.dismissive_language_detector` into
`pseudo_events.nitpick.handlers` for you (keeping `enabled` and `priority`),
lists the move in its config summary, and the reference config now carries
the `pseudo_events.nitpick` block, so a config that upgraded past v3.62.1
with the two detectors silently switched off is repaired rather than
reported valid.
