# Callout: the session advice counter is shared and locked

**Plan**: 00437
**Audience**: operators

`teammate_reap_advisor` and `background_process_tracker` each rate-limit their
advisory to the first qualifying event in a session and every Nth after it.
Both carried their own copy of the counter that does it — the same eight lines,
the same two constants — and neither copy guarded its mutation.

**The concurrency is real, and that was checked rather than assumed.** The
daemon is asyncio and has no thread pool of its own, but it dispatches through
`loop.run_in_executor(None, ...)`, and the default executor IS a
`ThreadPoolExecutor`. Handlers are daemon-lifetime singletons, so two
concurrent hook requests share one counter map across two worker threads.

The eviction that bounds the map was the part that could raise: two threads
reaching a full map can select the same key, and the second delete raises
`KeyError`; taking the first key of a dict that changes size mid-iteration can
raise `RuntimeError` instead. Either one surfaces as an advisory handler
failing on a hook request that had nothing to do with advice.

Both handlers now use one `SessionAdviceCounter` with a lock around the
read-modify-write. **Nothing about either advisory changes** — same interval,
same wording, same eviction bound; their existing rate-limit tests pass
unchanged, which is the behaviour-preservation check. There is no
configuration to set and nothing to migrate.

The duplication and the missing lock were one defect, not two: there were two
unlocked copies *because* there were two copies.
