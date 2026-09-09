# Callout: the ccy supervisor now says when its decision worker dies

**Plan**: 00361
**Audience**: operators

The supervisor's decision brain runs in a `--worker` subprocess that is
respawned from the on-disk file whenever that file's content changes. Until
now a worker that died was respawned on every tick and the host quietly
decided in-process with its own, older code, with nothing in `decision.log`
to show it. A supervisor file mid-edit (a method removed before its call
site) therefore crash-looped invisibly for as long as the edit took.

`decision.log` now carries `worker died (exit N, source <hash>) -> respawned`,
a single `worker crash-looping on source <hash> ...` line when the same source
dies again (respawns are then held to a ten-second backoff until the file
changes), `worker recovered (source <hash>)`, and the two edges of a stretch
the worker did not answer (`host deciding in-process` / `worker answering again`). The worker's own error log records a crash as a dated
`worker crashed (source <hash>)` entry with the traceback, so it can be
matched to a version of the file. The host-side half takes effect at the next
ccy session start; the worker-side crash record is live on reload.
