# Callout: the cron enforcers stop re-parsing your config on every turn

**Plan**: 00440
**Audience**: operators

`Config.load_or_default` reads `.claude/hooks-daemon.yaml`, parses it and runs
the whole pydantic model over it — measured at **76.3 ms median** on this
repository's config. `cron_stop_enforcer` called it from `matches()` and again
from `handle()`, and `matches()` runs on every Stop event, so roughly **150 ms
went on re-reading an unchanged file at the end of every turn**, before any
other Stop handler was consulted. The SubagentStop twin did the same.

Those handlers — and `remote_docs_routing` — now read through a shared cache
keyed on the file's modification time and size. On an unchanged config a load
costs a `stat`: **23.5 µs median**, so the per-event cost falls from ~153 ms to
about 0.05 ms.

**Editing your config still takes effect on the next event.** The cache
invalidates on `(st_mtime_ns, st_size)` rather than caching for the process
lifetime, which matters because a daemon can be up for days — a config that
quietly stopped taking effect would be a worse bug than a slow one. A config
file that did not exist when first read is also re-checked, so creating one
later is picked up.

Nothing else changed. The CLI, the installer and the session-start handlers
still call `Config.load_or_default` directly: they are one-shot, a cache buys
them nothing, and a stale read there would be a new failure mode.
