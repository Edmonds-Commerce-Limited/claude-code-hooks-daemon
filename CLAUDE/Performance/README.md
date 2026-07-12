# Performance

The durable hub for daemon performance work. This is a **recurring** area — new
measurements, tuning waves, and decisions land here over time. One source of
truth for: what the numbers are, what the budget is, what's on the backlog, and
which plans have touched it.

**Prime directive**: meaningful performance improvements **without any loss of
functionality or stability**. Every tuning change ships with tests proving
behaviour is unchanged; the daemon-restart and full-QA gates stay green.

## Theme tagging

Performance plans carry a `**Themes**: performance` header line so they can be
found across the plan tree (`grep -rl 'Themes:.*performance' CLAUDE/Plan`). This
hub is the curated index; the `Themes:` line is the queryable tag. (Kept as a
lightweight in-repo convention rather than GitHub issue labels so plans remain
the single source of truth with the full plan-QA lifecycle; revisit if external
contributor triage ever becomes the primary mode.)

## Decision framework (from Plan 00154)

Do not optimise on instinct. Hooks are human-gated and model-paced, so overhead
is only a problem when it crosses a budget:

- **Rule 0 — budget before benchmarks.** A cost matters only if (a) a single
  event exceeds ~100 ms p95 for typical payloads, (b) aggregate hook overhead
  exceeds ~1% of median tool-turn latency, or (c) background CPU (status line)
  exceeds ~10% of one core. Measure on the *complaining* hardware.
- **Rule 1 — never compile policy.** Handlers/strategies stay readable Python,
  unconditionally. Client-side introspectability is the product.
- **Rule 2 — compile only policy-free layers, only on evidence** (transport
  forwarder; at most a regex engine behind declarative pattern tables), and only
  after the free Python/bash win has landed and re-measurement still shows a
  budget violation.
- **Rule 3 — quantify both sides.** ms saved × events/hour on real telemetry vs
  named costs (binary matrix, supply-chain surface, second toolchain). Under a
  few seconds saved per user-hour loses to the distribution tax automatically.

## Baseline (measured, Plan 00154)

See [BASELINE.md](BASELINE.md) for the full measured baseline and how to
reproduce it. Headline p50 figures:

| Surface                                              | Measured             | Where the time goes                                                                |
| ---------------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------- |
| PreToolUse event, end-to-end                         | ~45 ms               | daemon side 1.8 ms (4%); rest is forwarder process spawns                          |
| — bash forwarder spawns                              | ~43 ms               | `jq` ~22-24 ms, `python3` transport ~19-21 ms, `init.sh` source ~13 ms, bash ~2 ms |
| — daemon dispatch (socket+JSON+pydantic+38 handlers) | 1.8 ms               | ~1.4 ms of it is one handler forking `git remote` per Bash event (T1)              |
| Status-line render (daemon side)                     | 15.75 ms             | ~5 git forks per render (T4)                                                       |
| Content scanners                                     | ~48 µs/KB (security) | 74% of daemon CPU under load is `re.search` (T5)                                   |
| RSS (fresh) / cold restart                           | 51 MB / 1.26 s       | one-off per session/upgrade                                                        |

**Takeaway**: the Python daemon is not the cost. The forwarder's per-event
process spawns are. No Rust rewrite is justified; the free Python/bash wins
below beat any daemon rewrite's ceiling.

## Tuning backlog

Ordered by measured impact. Full detail + magnitudes:
[Plan 00154 PYTHON-TUNING.md](../Plan/Completed/00154-daemon-performance-rust-vs-python-research/PYTHON-TUNING.md).

| ID  | Change                                                         | Expected                        | Risk                    | Status                                           | Plan  |
| --- | -------------------------------------------------------------- | ------------------------------- | ----------------------- | ------------------------------------------------ | ----- |
| T1  | Cache `is_hooks_daemon_repo` (stop per-Bash `git remote` fork) | −1.4 ms/Bash event              | near-zero               | Landed (1076→2.1 µs)                             | 00155 |
| T4  | Status-line git: short per-cwd TTL cache                       | render 10.4 ms → ~4 µs (cached) | low                     | Landed                                           | 00155 |
| —   | Delete broken legacy one-shot `hooks/*.py` package             | correctness                     | low                     | Landed (deleted)                                 | 00155 |
| T2  | Drop `jq` from hook wrappers (transport does JSON wrap/unwrap) | −22 ms/event                    | medium (transport)      | Deferred → wave 2                                | —     |
| T3  | Slim `init.sh` hot path (subshells, mkdir, tr pipelines)       | est. −5-8 ms/event              | medium (edge cases)     | Deferred → wave 2                                | —     |
| T5  | Single-pass/combined-alternation content scanning              | est. 2-5× on ≥100 KB writes     | medium                  | Deferred (only if large writes common)           | —     |
| T6  | `orjson` socket encode/decode                                  | −1-3 ms at MB payloads only     | low (adds compiled dep) | Not recommended                                  | —     |
| —   | Compiled transport forwarder (Rust, policy-free)               | 45 → ~3-5 ms                    | high (distribution)     | Never, until free wins land + budget still fails | —     |

## Waves

- **Wave 1 — [Plan 00155](../Plan/Completed/00155-performance-tuning-wave-1-daemon-side/PLAN.md)** (landed):
  T1 + T4 + legacy-entry deletion. Pure-Python, daemon-side, no transport-contract
  risk, fully unit-testable. Measured results below.
- **Wave 2 — TBD**: T2 (drop `jq`) + T3 (slim `init.sh`). Touch the safety-critical
  transport; require the forwarder acceptance gates + control-character review.

## Measured results (before → after)

Populated as waves land. Re-run the Plan 00154 harness on the same box for
comparability. (Micro-benchmarks below measured in-process on the same box;
`p50`, cold = cache cleared each iteration, cached = warm hit.)

### Wave 1 (Plan 00155)

| Change                    | Cold (before)                 | Cached (after) | Effect                                                                                                                                                               |
| ------------------------- | ----------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1 `is_hooks_daemon_repo` | ~1076 µs (forks `git remote`) | ~2.1 µs        | forks once per daemon lifetime instead of once per **Bash event** → ~1.07 ms saved per Bash event after the first                                                    |
| T4 status git render      | ~10.4 ms (~4 git forks)       | ~4.0 µs        | under output streaming (~every 300 ms, TTL 2 s) ~85% of renders hit cache → ~10 ms of git-fork CPU churn saved per hit (async render — battery/fan win, not latency) |

Both are safe daemon-side wins: no transport-contract change, handler decision
behaviour unchanged, QA 13/13, coverage 95.6%. The larger typical-event win
(dropping `jq`, T2) is Wave 2.

## Reproduce

The Plan 00154 harness lives in
[assets/](../Plan/Completed/00154-daemon-performance-rust-vs-python-research/assets/)
(`bench_socket.py`, `bench_components.py`, `bench_forwarder.sh`) with raw
results under `assets/results/`. Method:
[BENCHMARK-METHODOLOGY.md](../Plan/Completed/00154-daemon-performance-rust-vs-python-research/BENCHMARK-METHODOLOGY.md).
