# Callout: the housekeeping scratch apply removes expired scratch without asking

**Plan**: 00474
**Audience**: everyone

The housekeeping step `scratch-sweep-apply` is now a mutating step that acts without confirmation, run by `hooks-daemon housekeeping --run scratch-sweep-apply`. It uses the same apply core as `scratch-sweep --apply`: it archives then removes only the entries the sweep finds due, never an entry with a `.scratch-keep` marker, one inside its TTL or one in use, and every removal is restorable with `scratch-sweep restore <archive id>` until its retention ends. In use means a process has its working directory there or a recorded background command names it, so an old, quiet session directory can be archived while its owner still runs elsewhere. Like `scratch-sweep --apply`, the step also permanently deletes archives past their retention. It reads the project's config as the daemon does (`.claude/hooks-daemon.yaml`, then `.yml`) and removes nothing if that config cannot be read. It never uses the sweep's pressure mode, so a scratch cap at block does not widen it to idle entries still inside their TTL; that stays behind the human confirmation of `scratch-sweep --apply`. It needs an explicit `--project-root` (the `bin/hooks-daemon` wrapper passes one) and never acts on a project found from the working directory. It cannot be combined with `--list` or `--apply`. A store refusal or an incomplete classification removes nothing and says why. It prints the count, entry paths and archive ids, never contents.

`scratch-sweep --apply` itself is unchanged: it still needs a human to type the confirmation at a terminal.

A new standing-authorisation id, `scratch-expired-cleanup`, tells the agent it may run that step without asking each time, by that step only. Like every standing authorisation it ships disabled; enable it in `.claude/hooks-daemon.yaml` only where the owner has asked for it.
