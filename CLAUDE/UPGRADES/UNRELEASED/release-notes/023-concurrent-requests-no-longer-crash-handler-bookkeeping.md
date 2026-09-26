# Callout: concurrent requests no longer crash ten handlers' bookkeeping

**Plan**: 00449
**Audience**: everyone

The daemon handles concurrent hook requests on a thread pool, and ten
handlers kept a bounded per-session map that evicted in two unlocked steps.
When two requests reached a full map together, both could pick the same entry
to evict and the second raised `KeyError`, or `RuntimeError` when iterating a
map that had just changed size. The exception escaped the handler. Under the
default `strict_mode: false` the handler was skipped for that request. For
`write_clobber_guard` and `reference_repo_freshness` that meant the guard
simply wasn't there. Under `strict_mode: true` a harmless call, such as a
`Read`, was denied. Every such map is now a locked FIFO map, including the maps
in `goal_injection`, `flaggable_work_advisor`, `model_fallback_detector`,
`idle_housekeeping_advisory`, `command_hints`, `recovery_cron_advisor`,
`git_context_injector` and `standing_authorisations`.

The undo journal behind `command_hints` and `recovery_cron_advisor` now keeps
each request's records separately. Before, one request's commit or rollback
could keep or undo another request's rate-limit state, so a hint fired twice
or was silenced. It could also raise `IndexError`. A new semgrep rule,
`unlocked-select-then-evict`, fails QA if the unlocked pattern returns. Nothing
to configure and nothing to act on.
