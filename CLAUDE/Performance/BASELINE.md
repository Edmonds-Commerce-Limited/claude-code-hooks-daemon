# Performance Baseline

The current canonical baseline for daemon performance. Seeded from the Plan
00154 research (measured on a 22-core Linux box, warm daemon, stdlib timing
harness). This is the **living** baseline — update it here when surfaces are
re-measured, and note the hardware, because absolute numbers are hardware-bound
(the budget in [README.md](README.md) is what's portable, not the raw ms).

Provenance / method:
[Plan 00154 RESEARCH.md §4](../Plan/Completed/00154-daemon-performance-rust-vs-python-research/RESEARCH.md)
and
[BENCHMARK-METHODOLOGY.md](../Plan/Completed/00154-daemon-performance-rust-vs-python-research/BENCHMARK-METHODOLOGY.md).

## p50 latency

| Stage                             | p50                                         | Notes                                                                                                                                                                                            |
| --------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| PreToolUse event, end-to-end      | ~45 ms                                      | human-gated; tool turns are multi-second                                                                                                                                                         |
| bash forwarder (total spawns)     | ~43 ms                                      | 95% of the typical path                                                                                                                                                                          |
| — `jq` spawn                      | ~22-24 ms                                   | once per wrapper; twice on status line                                                                                                                                                           |
| — `python3` transport spawn       | ~19-21 ms                                   | irreducible CPython start per event                                                                                                                                                              |
| — `source init.sh`                | ~13.2 ms                                    | before any daemon traffic                                                                                                                                                                        |
| — bash itself                     | ~2 ms                                       |                                                                                                                                                                                                  |
| daemon dispatch (Bash event)      | 7.4 ms (47 handlers), 10.2 ms (80 handlers) | re-measured by Plan 00495, see "Plan 00495 re-measurement" below. The ~1.8 ms of Plan 00154 is superseded: the chain has more than doubled and every request now runs in a bounded worker thread |
| — rest of dispatch chain          | ~7.7 ms (80 handlers)                       | 80 `matches()` calls, 0.1 ms each on average; the largest are the secret-file guard 1.07 ms, project containment 0.97 ms and write-protected paths 0.84 ms                                       |
| socket round-trip, no dispatch    | ~0.12 ms                                    | nothing to win here                                                                                                                                                                              |
| Status event (daemon-side render) | ~15.75 ms                                   | ~5 git forks/render, ~2-3 ms each                                                                                                                                                                |

## CPU / memory

| Metric                | Value                                                       | Notes                                                                                                                                    |
| --------------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Daemon CPU under load | 74% in `re.search`                                          | content scanners; rest is noise                                                                                                          |
| Content scan cost     | ~48 µs/KB (security), ~2.4 (error-hiding), ~1.6 (QA-suppr.) | ~40 ms per 1 MB Write (Plan 00154). Plan 00495 re-measured it, and found the secret-file guard at about 9 ms/KB: ~1.2 s per 115 KB Write |
| RSS (fresh)           | 51 MB                                                       | settled 51 → 76 MB during a benchmark flood; no session-scale leak signature                                                             |
| Cold restart          | 1.26 s                                                      | once per session/upgrade; `import` alone 141 ms. Plan 00495 re-measured the start at 1.0-1.1 s CPU, 1.2-1.3 s wall (below)               |
| JSON round-trip       | 5-40 µs typical, 3.4 ms at 1 MB                             | pydantic validate+dump ~4 µs, flat to 1 MB                                                                                               |

## Budget check (Rule 0)

Against the [README.md](README.md) budget, the system **passes for a typical
event**: hook overhead is ~1% of a median tool turn, no Bash or small-Write
event exceeds 100 ms, and the status-line CPU is a churn concern (battery/fan)
not a latency one. **One path fails Rule 0(a)**: a Write or Edit of more than
about 11 KB spends over 100 ms in the secret-file guard alone (see "Plan 00495
re-measurement"). Start-up has its own budget, in [README.md](README.md#start-up-budget).

## Plan 00495 re-measurement

Measured on `main` after the Phase 2 fixes (all of Tasks 2.2 to 2.7 merged), on an 8-core Linux box, host load average
3 to 8 throughout, Python 3.11, no external network. The method is Plan 00495 Phase 1's
([startup profile report](../Plan/Completed/00495-performance-improvement-programme/subagent-reports/261006-startup-profile-sonnet.md)):
a fresh process per sample on a throwaway git project, `process_time` CPU seconds (the load-robust metric), runs
interleaved, median reported. The two configs are the shipped `hooks-daemon.yaml.example` (62 KB, 47 PreToolUse
handlers) and this repository's own (92 KB, 80 PreToolUse handlers).

### Daemon start (what the status bar waits on)

| Config  | Variant                                                | Phase 1 (v3.68/main) CPU | Now: CPU median [min-max], 7 runs | Now: wall |
| ------- | ------------------------------------------------------ | ------------------------ | --------------------------------- | --------- |
| example | Phase 1 steps (inline start-up work, then index warm)  | 2.55 s [2.22-2.74]       | 1.03 s [0.91-2.05]                | 1.27 s    |
| example | what `cmd_start` runs before the bind (Task 2.5 split) | not applicable           | 0.98 s [0.87-1.20]                | 1.22 s    |
| repo    | Phase 1 steps                                          | 2.7-3.1 s                | 1.12 s [0.90-1.49]                | 1.65 s    |
| repo    | what `cmd_start` runs before the bind                  | not applicable           | 1.06 s [0.93-1.12]                | 1.30 s    |

Of the 0.98 s before the bind (example config): importing the CLI 0.40, loading and validating the config 0.46, building
and registering the handlers 0.11. `scripts/release/check_startup_budget.py` measures the "before the bind" work as one
fresh process's total CPU; its 9-sample medians over three runs were 1.10, 1.12 and 1.10 s on this host. That is a little
above the 0.98 s here, which sums the phases and so leaves out the interpreter's own start.

### Daemon dispatch (the figure this file marked "not re-measured")

`DaemonController.process_request` in-process, JSON decode and encode included, one request after 20 warm-ups, 300
requests per row, shipped example config / this repository's config. It excludes the socket accept, measured at ~0.12 ms
in Plan 00154 and not affected by Phase 2.

| Event                                | p50 (example, 47 handlers) | p95  | p50 (repo, 80 handlers) | p95     |
| ------------------------------------ | -------------------------- | ---- | ----------------------- | ------- |
| PreToolUse Bash, benign              | 7.4 ms                     | 9.4  | 10.2 ms                 | 12.5 ms |
| PreToolUse Bash, denied early        | 7.9 ms                     | 12.3 | 7.6 ms                  | 9.6 ms  |
| PreToolUse Write of a 1 KB test file | 20.3 ms                    | 28.4 | 19.7 ms                 | 23.1 ms |

Plan 00154 measured 1.8 ms for 38 handlers. The chain has since grown to 47 to 80 handlers, and each request now runs the
chain in a bounded worker thread (about 1 ms of thread start and wake-up). Summing each handler's own `matches()` time on
the 80-handler chain gives 7.7 ms of the 8.9 ms request, so the cost is spread (0.1 ms on average) and not one hot
handler, except for Writes: of the 20 ms for a 1 KB Write, about 9 ms is the secret-file guard.

### Content scanners, per Write of 115 KB (2,500 lines; this repository's config, 80 handlers)

| Handler (`matches()` time)   | 115 KB Write | per KB     |
| ---------------------------- | ------------ | ---------- |
| block-secret-file-read       | 1208 ms      | 10.5 ms    |
| block-security-antipatterns  | 12.0 ms      | 0.10 ms    |
| block-sensitive-content      | 11.1 ms      | 0.10 ms    |
| error-hiding-blocker         | 6.1 ms       | 0.05 ms    |
| block-comment-changelog      | 5.9 ms       | 0.05 ms    |
| block-comment-size           | 5.0 ms       | 0.04 ms    |
| every other handler together | under 5 ms   | negligible |

The secret-file guard is linear, and the cost is not in a regex: `_shell_words` in
`utils/secret_file_matching.py` runs `shlex` over every line of the content (375,000 tokens and 5 s of profiled time for
a 1.15 MB Write). Standalone `matches()` on Writes of 11.5 KB, 115 KB and 1.15 MB took 102 ms, 1.17 s and 9.3 s. The
shipped example config shows the same (1.25 s for 115 KB). The other scanners cost 0.04 to 0.10 ms/KB, about 0.35 s per
MB for all five. Plan 00154 recorded 0.048 ms/KB for the security scanner (now about twice that) and 0.0024 for error
hiding (now about twenty times that); this host was loaded and the handler set has changed, so read the comparison as an
order of magnitude.

### Status bar and sweeps (Phase 2, taken from the plan's before and after rows)

These were measured by the Phase 2 tasks with the Phase 1 method on the commits that are now `main`, and are not
re-measured here: time to first status-line output with the daemon stopped 3.65 s and 5.32 s -> 0.46 s and 0.21 s
(Task 2.7); first request answered by a cold daemon 1.94 s -> 1.51 s (Task 2.5); SessionStart chain on this repository
5.8 to 12.7 s -> 1.9 to 2.2 s on a sweep-cache hit and 5.0 s on a miss (Task 2.6).

### Not re-measured

The bash forwarder spawns (`python3` transport 18.2 ms, `init.sh` 11.3 ms) and the Rust relay (4.3 ms p50 against 34.1 ms
for the Python transport, Plan 00290) are as recorded above: the forwarder harness drives the live daemon on the
project's own socket, which a measurement run must not touch, and Phase 2 did not change the event path. Dispatch was
measured in-process rather than over a socket for the same reason.
