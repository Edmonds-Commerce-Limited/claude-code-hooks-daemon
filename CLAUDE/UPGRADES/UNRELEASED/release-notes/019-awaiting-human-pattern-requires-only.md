# Callout: a stop that only mentions "waiting on the owner's decision" no longer declares you blocked on the human

**Plan**: 00474
**Issue**: #149
**Audience**: operators

The Stop handler's last legacy prose pattern used to arm the awaiting-human mode on any "waiting on/for the owner's (user's, human's) decision, input, response or answer". A stop that merely noted parked issues while other work remained (for example a CI run still going) was read as blocked-only-on-human, was denied for the missing stand-in cron, and would have silenced the failsafe and declared crons.

The pattern now requires "only", before or after the target: `waiting only on the user's decision`, or `waiting on human response only`. The advertised example in the generated guidance is `waiting only on the user's decision`.

Nothing to do on upgrade unless you relied on the bare phrase to arm the mode. In that case write `[awaiting-human]` after `STOPPING BECAUSE:`, which is the supported declaration and is unchanged.
