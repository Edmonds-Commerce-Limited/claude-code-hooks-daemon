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

| Stage                                 | p50       | Notes                                            |
| ------------------------------------- | --------- | ------------------------------------------------ |
| PreToolUse event, end-to-end          | ~45 ms    | human-gated; tool turns are multi-second         |
| bash forwarder (total spawns)         | ~43 ms    | 95% of the typical path                          |
| — `jq` spawn                          | ~22-24 ms | once per wrapper; twice on status line           |
| — `python3` transport spawn           | ~19-21 ms | irreducible CPython start per event              |
| — `source init.sh`                    | ~13.2 ms  | before any daemon traffic                        |
| — bash itself                         | ~2 ms     |                                                  |
| daemon dispatch (Bash event)          | ~1.8 ms   | socket + JSON + pydantic + 38-handler chain      |
| — `daemon_restart_verifier.matches()` | ~1.4 ms   | forks `git remote get-url origin` per Bash event |
| — rest of dispatch chain              | ~30 µs    | 35 of 38 `matches()` < 2 µs each                 |
| socket round-trip, no dispatch        | ~0.12 ms  | nothing to win here                              |
| Status event (daemon-side render)     | ~15.75 ms | ~5 git forks/render, ~2-3 ms each                |

## CPU / memory

| Metric                | Value                                                       | Notes                                                                        |
| --------------------- | ----------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Daemon CPU under load | 74% in `re.search`                                          | content scanners; rest is noise                                              |
| Content scan cost     | ~48 µs/KB (security), ~2.4 (error-hiding), ~1.6 (QA-suppr.) | ~40 ms per 1 MB Write                                                        |
| RSS (fresh)           | 51 MB                                                       | settled 51 → 76 MB during a benchmark flood; no session-scale leak signature |
| Cold restart          | 1.26 s                                                      | once per session/upgrade; `import` alone 141 ms                              |
| JSON round-trip       | 5-40 µs typical, 3.4 ms at 1 MB                             | pydantic validate+dump ~4 µs, flat to 1 MB                                   |

## Budget check (Rule 0)

Against the [README.md](README.md) budget, the system **passes today**: hook
overhead is ~1% of a median tool turn, no typical event exceeds 100 ms, and the
status-line CPU is a churn concern (battery/fan) not a latency one. Tuning here
is about reducing waste, not fixing a user-visible regression.
