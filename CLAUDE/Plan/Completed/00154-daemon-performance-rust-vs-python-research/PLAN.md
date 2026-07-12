# Plan 00154: daemon performance rust vs python research

**Status**: Complete
**Created**: 2026-07-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Fable (research)
**Execution Strategy**: Single-Threaded (dedicated research agent)

## Overview

An open question raised by the maintainer: how much runtime cost does the
all-Python hooks daemon actually impose, and would moving hot paths to Rust be
worth the loss of transparency (a client project can currently read the daemon's
Python source to understand exactly what a hook does; a compiled blob cannot be
introspected the same way)? This plan is a **research and decision-framing**
effort — no production code changes. It exists to quantify the real cost, list
the Python-level tuning wins available today, honestly weigh a Rust move
(full rewrite vs PyO3 hybrid vs status-quo), and produce a defensible
recommendation.

The daemon's design already avoids the dominant cost of naive hooks — per-event
Python process spawn — by keeping a warm daemon behind a Unix socket (bash
forwarder → socket → FrontController → handler chain). The research must
establish whether, given that, the remaining per-event latency is already below
the human-perceptible / workflow-relevant threshold, or whether specific
surfaces (e.g. the status line, which renders very frequently, or content
scanners that regex large files) are hot enough to matter.

## Goals

- Quantify the real per-event cost of the daemon path with a reproducible
  benchmark harness: p50/p95/p99 latency per hook event type, warm-daemon
  round-trip vs cold, RSS/memory footprint, and where the time goes
  (bash forwarder, socket I/O, JSON encode/decode, dispatch, per-handler work).
- Identify the genuinely hot surfaces (status line render cadence, content
  scanners on large files, subprocess-heavy handlers) vs the cold ones.
- Enumerate Python-level tuning wins available WITHOUT a rewrite (lazy imports,
  import-time reduction, regex precompilation, caching, faster JSON, `__slots__`,
  reducing subprocess forks, profiling-guided hotspot fixes) with expected
  magnitude for each.
- Honestly frame the Rust option(s): full socket-server + dispatch rewrite,
  PyO3 hybrid (Rust core, Python handlers), or targeted native extensions for
  only the hottest primitives — each with a performance-upside estimate AND the
  transparency/introspection, build-complexity, cross-platform-binary, and
  ecosystem costs.
- Produce a clear decision framework and recommendation: does this warrant work
  now, later, or never — and if ever, which increment first.

## Non-Goals

- No production code changes, no Rust code, no dependency additions in this plan.
- Not committing to a rewrite — this is the evidence base a later plan would cite.
- Not a micro-optimisation sprint; concrete tuning work would be its own plan.

## Method (delegated to a Fable research agent)

A dedicated **Fable** agent performs the investigation and writes ALL artifacts
directly into this plan folder (`CLAUDE/Plan/00154-.../`). Nothing is passed back
to the orchestrator for writing. The agent should, where the container allows:

- Read the daemon hot path: `daemon/server.py`, `core/front_controller.py`,
  `hooks/` entry modules, `init.sh` / bash forwarder, the status-line handler
  chain, and the heaviest content scanners.
- Build a small, reproducible benchmark harness (e.g. drive the live socket with
  `nc`/a Python client, `timeit`/`hyperfine` the bash forwarder, `py-spy`/
  `cProfile` a representative dispatch) and record real numbers — clearly
  labelling anything it could not measure and why.
- Compare against a defensible "budget": hooks fire on tool calls and are
  human-gated, so what latency is actually perceptible vs noise?

## Tasks

### Phase 1: Baseline & instrumentation

- [x] ✅ **Task 1.1**: Map the hot path end-to-end and document each stage's
  expected cost class.
- [x] ✅ **Task 1.2**: Build a reproducible benchmark harness; capture p50/p95/p99
  per event type, warm vs cold, and RSS.

### Phase 2: Hotspot analysis

- [x] ✅ **Task 2.1**: Profile representative events; attribute time to
  forwarder / socket / JSON / dispatch / per-handler.
- [x] ✅ **Task 2.2**: Identify the hot surfaces (status line cadence, big-file
  scanners, subprocess-heavy handlers).

### Phase 3: Options analysis

- [x] ✅ **Task 3.1**: Python-tuning catalogue with per-item expected magnitude.
- [x] ✅ **Task 3.2**: Rust options (full / PyO3 hybrid / targeted) with
  upside estimates AND opacity/build/portability/ecosystem costs.

### Phase 4: Synthesis

- [x] ✅ **Task 4.1**: Decision framework + recommendation (now / later / never;
  which increment first).

## Deliverables (all written by the Fable agent into this folder)

- `RESEARCH.md` — findings, measured numbers, hot-path map.
- `BENCHMARK-METHODOLOGY.md` — how to reproduce every number (+ any harness
  scripts under `assets/`).
- `PYTHON-TUNING.md` — the no-rewrite tuning catalogue with magnitudes.
- `RUST-TRADEOFFS.md` — options, upside estimates, and the opacity/complexity cost.
- `RECOMMENDATION.md` — the decision framework and a clear call.

## Success Criteria

- [ ] Real, reproducible per-event latency + memory numbers exist (or the exact
  reason a number could not be measured is documented).
- [ ] Every claimed benefit is quantified or explicitly labelled an estimate.
- [ ] The Rust tradeoff is presented honestly (transparency cost named, not glossed).
- [ ] A clear now/later/never recommendation with a first increment if applicable.

## Notes & Updates

### 2026-07-12

- Plan scaffolded. Research delegated to a Fable agent that writes all artifacts
  directly into this folder. Session recovery cron: `d4cb559d`.
- Research complete. The Fable agent produced all five write-ups (`RESEARCH.md`,
  `BENCHMARK-METHODOLOGY.md`, `PYTHON-TUNING.md`, `RUST-TRADEOFFS.md`,
  `RECOMMENDATION.md`) plus a reproducible benchmark harness and captured results
  under `assets/`. **Headline call**: the daemon is already lightweight (~85 ms
  per tool call against multi-second turns, ~51 MB RSS) — no user-visible cost.
  Full Rust rewrite = **never** (≤4% end-to-end ceiling, paid for with the
  project's auditability). The only Rust increment that could ever pay is a
  policy-free transport forwarder, and **not yet** (half its win is free by
  dropping `jq`). Concrete no-rewrite tuning wins T1–T4 (cache the per-Bash git
  fork, fold `jq` into the python3 transport, TTL-cache status-line git forks,
  slim `init.sh`) will drive future dev work. Delivered alongside the plan
  closure in this commit.
  </content>
