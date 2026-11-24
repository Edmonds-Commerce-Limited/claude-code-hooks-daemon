# Callout: a usage pause records whether a ceiling or the account's hard limit caused it

**Plan**: 00523
**Audience**: operators

The `<session>.usage-paused` record gains a `cause` field: `ceiling` (this host's usage ceiling, the only cause written today) or `hard_limit` (the account's own limit, where every request fails until the reset). A record without the field, or with a value the reader does not recognise, reads as `ceiling`, so records written before the upgrade keep their meaning and a damaged value never produces more injection than a ceiling pause did.

A `hard_limit` pause is treated differently in two places. The ccy supervisor injects nothing for it, not even the single usage-pause `/compact`, and stops holding at its resume time instead of an hour later. The daemon's prompt gate does not lift it early: neither a reading under the ceiling nor a host with no ceiling ends it before its resume time, and an early resume tick does not re-base it.

Nothing writes a `hard_limit` record yet. Turning a `rate_limit` StopFailure into one is still open in Plan 00523 (Task 2b.1). Until that lands, behaviour is unchanged. The supervisor change takes effect when its worker reloads; no restart and no config change are needed.
