# Callout: A long QA run starts an idled-out daemon instead of failing

**Plan**: 00422
**Audience**: operators

`llm_qa.py` now starts the checkout's own daemon when it is not running, just
before each check that probes it (`tests` and `smoke_test`), and prints a
`DAEMON STARTED` line saying so. A worktree's daemon gets no hook traffic, so
it stopped at `idle_timeout_seconds` partway through a full run and
`smoke_test` failed with "Daemon not running". A daemon that is already
running is never restarted, so a stale one still fails the freshness check.
You no longer need a keep-alive loop feeding hook events to a worktree during
QA.
