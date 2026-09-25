# Callout: `HooksDaemon` now exposes a deterministic `started_event`

**Plan**: 00466
**Audience**: handler authors

`HooksDaemon.start()` now sets a new `self.started_event` (`asyncio.Event`)
once both the legacy socket and the per-event listeners have finished
binding. A test or embedding harness that previously guessed readiness with
a fixed `asyncio.sleep(...)` after `create_task(daemon.start())` can instead
`await asyncio.wait_for(daemon.started_event.wait(), timeout=...)` for a
result that does not race under host load.
