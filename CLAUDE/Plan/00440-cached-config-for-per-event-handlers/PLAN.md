# Plan 00440: cached config for per event handlers

**Status**: In Progress
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

`Config.load_or_default` reads `.claude/hooks-daemon.yaml`, parses it and runs
the whole pydantic model over it. Measured on this repository's config, 15
consecutive loads in a warm process gave a median of **76.3 ms** (min 74.3, max
313.8).

`cron_stop_enforcer` calls it from `matches()` and again from `handle()`, and
`matches()` runs on every Stop event — so roughly **150 ms is spent re-parsing
an unchanged file at the end of every turn**, before any other Stop handler has
been consulted. The subagent twin does the same on every SubagentStop. For
scale: this project measured the entire native-hook round trip at ~1.2 s
against the daemon's ~51 ms, and this one handler spends three times that whole
dispatch budget on a file it already read.

The fix is a shared accessor that caches the parsed `Config` and invalidates on
the file's `st_mtime_ns` and `st_size`, so an operator editing their config
still gets the new values on the next event without restarting a long-lived
daemon. It must be locked: dispatch runs on the default `ThreadPoolExecutor`
(`daemon/server.py:1443` does `run_in_executor(None, ...)`), which is exactly
the hazard Plan 00437 measured for a daemon-lifetime singleton.

This is niggle N5 row (b) of the ledger in Plan 00422.

Adjacent but orthogonal: Plan 00415 asks whether the config has changed since
the daemon loaded it. This plan asks how to avoid re-parsing it when it has
not. The two would share the same `stat` reading if 00415 ever lands.

## Goals

- One shared, locked, mtime-invalidated config accessor in `utils/`.
- `cron_stop_enforcer`, `cron_subagent_stop_enforcer` and
  `remote_docs_routing` read through it instead of `Config.load_or_default`.
- A test proves a second load of an unchanged file does not re-parse, and that
  a touched file does.

## Non-Goals

- No change to `Config.load_or_default` itself: the CLI and installer call
  sites are one-shot processes where a cache buys nothing and a stale read
  would be a new failure mode.
- No retrofit of `secret_file_matching` / `secret_redaction`. They already
  cache, with a module-level resolved flag that never invalidates — a real but
  separate question (a config edit is invisible to them until restart), and
  they are correct as regards cost, which is what this plan is about.
- No caching of anything derived from the config (resolved patterns, job
  lists); the parse is the expense.

## Tasks

### Phase 1: measure, then guard

- [x] ✅ **Task 1.1**: Record the baseline in `JOURNAL/` — the 76.3 ms median
  above, and the call count per Stop event. Also audited every
  `Config.load_or_default` call site so the scope is measured rather than
  assumed: the hot `secret_*` ones already cache, the CLI/install ones are
  one-shot, and the row named its two handlers correctly.
- [x] ✅ **Task 1.2**: Write `tests/unit/utils/test_config_cache.py`: a second
  load of an unchanged file returns without re-parsing, a `st_mtime_ns` or
  `st_size` change forces a re-parse, a missing file behaves as
  `load_or_default` does, and concurrent callers get one parse. RED: the
  module does not exist.
- [x] ✅ **Task 1.3**: Confirm the concurrency test is not vacuous. It needed
  no artificial replica — the first implementation parsed OUTSIDE the lock and
  the test failed `assert 16 == 1` on sixteen threads each parsing the same
  file. The parse moved back inside the lock, which is also the simpler code.

### Phase 2: the accessor

- [x] ✅ **Task 2.1**: `utils/config_cache.py` — `load_config_cached(path)`,
  keyed on the resolved path plus `(st_mtime_ns, st_size)`, guarded by a
  `threading.Lock`, delegating to `Config.load_or_default` on a miss. An
  absent file caches under a sentinel signature, so one appearing later is a
  miss rather than a pinned default.
- [x] ✅ **Task 2.2**: Repoint the three per-event callers. Each keeps its own
  `except`: a config the daemon already reports as invalid must still degrade
  the handler to silent, never raise out of the Stop chain. The cache
  deliberately re-raises — "this config is broken" is a decision about the
  handler, not about the cache.

### Phase 3: gate

- [x] ✅ **Task 3.1**: Re-measure and record the after figure in `JOURNAL/`.
  Warm path 23.5 µs median (a `stat` and a dict lookup), so ~153 ms per Stop
  event becomes ~0.05 ms while the config is unchanged.
- [x] ✅ **Task 3.2**: `scripts/qa/llm_qa.py all` green — 35/35, 25190 tests
  passed, coverage 95.3%. Ran `llm_qa format` first this time and restarted the
  daemon before starting: Plan 00439's run came back 32/35 purely because black
  rewrote a file mid-run and moved the tree past the pre-run restart.
- [ ] ⬜ **Task 3.3**: Release note; record the outcome on row (b) of Plan
  00422's `NIGGLES.md`; archive.

## Success Criteria

- [ ] A Stop event parses the config at most once, and zero times when it has
  not changed since the previous event.
- [ ] Editing `.claude/hooks-daemon.yaml` changes the next event's behaviour
  with no daemon restart — proved by a test, not by inspection.
- [ ] The concurrency test was seen RED against an unlocked replica.
- [ ] `llm_qa.py all` green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00440-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
