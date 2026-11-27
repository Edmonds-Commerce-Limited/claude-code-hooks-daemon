# Callout: the housekeeping scratch apply removes expired scratch without asking

**Plan**: 00474
**Audience**: everyone

The housekeeping step `scratch-sweep-apply` is now a mutating step that acts without confirmation, run by `hooks-daemon housekeeping --run scratch-sweep-apply`. It uses the same apply core as `scratch-sweep --apply`: it archives then removes only the entries the sweep finds due, never an entry with a `.scratch-keep` marker, a live entry or one inside its TTL, and every removal is restorable with `scratch-sweep restore <archive id>`. A store refusal or an incomplete classification removes nothing and says why. It prints the count, entry paths and archive ids, never contents.

`scratch-sweep --apply` itself is unchanged: it still needs a human to type the confirmation at a terminal.

A new standing-authorisation id, `scratch-expired-cleanup`, tells the agent it may run that step without asking each time, by that step only. Like every standing authorisation it ships disabled; enable it in `.claude/hooks-daemon.yaml` only where the owner has asked for it.
