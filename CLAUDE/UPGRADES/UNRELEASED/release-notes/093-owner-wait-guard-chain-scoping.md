# Callout: owner_wait_stop_guard judges each stop chain on its own

**Plan**: 00636
**Audience**: operators

Three narrowings of `owner_wait_stop_guard`, no config change. The refusal carries the stand-in cron requirement only where `auto_continue_stop` would ask for it (the declaration sits on a `STOPPING BECAUSE:` line and the stop has a session id). The one-shot pass after the guard's own refusal now counts only a refusal in the current stop chain, that is after the last real user prompt, so an earlier chain's refusal no longer lets a later chain through. A stop whose message cannot be read is still refused where the bus reports notify flags, but on pingbus v1 it no longer gets the "this stop waits on a human" advisory, since nothing showed it did.
