# Plan 00155: performance tuning wave 1 (daemon-side, safe)

**Status**: In Progress
**Created**: 2026-07-12
**Owner**: joseph
**Priority**: Medium
**Themes**: performance
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (small, sequential, TDD)

## Overview

First implementation wave off the back of the Plan 00154 performance research.
This wave takes only the **pure-Python, daemon-side** tuning wins that carry no
forwarder-contract or distribution risk — the changes that cannot regress the
safety-critical hook transport and are fully unit-testable. The larger win
(dropping `jq` from the wrappers, T2) and the `init.sh` slimming (T3) touch the
transport and are deliberately deferred to a later, more heavily gated wave.

Grounding evidence: [Plan 00154 RESEARCH.md](../Completed/00154-daemon-performance-rust-vs-python-research/RESEARCH.md),
tuning catalogue [PYTHON-TUNING.md](../Completed/00154-daemon-performance-rust-vs-python-research/PYTHON-TUNING.md).
Durable hub: [CLAUDE/Performance/README.md](../../Performance/README.md).

Prime directive (from the user): **meaningful performance improvements without
any loss of functionality or stability.** Every change ships with tests proving
behaviour is unchanged, and the daemon-restart + full QA gates must stay green.

## Goals

- **T1** — memoise `is_hooks_daemon_repo` so `daemon_restart_verifier` stops
  forking `git remote get-url origin` on every Bash event (measured ~1.4 ms p50
  per Bash command; ~75% of the Bash-event daemon-side cost).
- **T4** — cut the status-line git subprocess churn: one combined
  `git status --porcelain=v2 --branch` call and/or a short TTL cache keyed by
  repo toplevel, so streaming renders (~every 300 ms) don't fork ~5 git
  processes each time. CPU-churn win (battery/fan), not a latency win.
- **Cleanup** — resolve the legacy one-shot entry
  `src/claude_code_hooks_daemon/hooks/pre_tool_use.py` that crashes against the
  current plugins config schema (a `str` is passed to
  `PluginLoader.load_handlers_from_config`). Dead-or-broken either way.

## Non-Goals

- No `jq` removal (T2), no `init.sh` slimming (T3) — deferred to wave 2; they
  touch the transport contract and need the forwarder acceptance gates.
- No content-scanner rework (T5) — only worth it if large writes are shown to be
  common; not demonstrated.
- No new compiled dependencies (orjson T6), no Rust.
- No behaviour changes to any handler's block/allow decisions.

## Tasks

### Phase 1: T1 — cache is_hooks_daemon_repo

- [ ] ⬜ **Task 1.1**: RED — failing test asserting `is_hooks_daemon_repo`
  resolves the git remote at most once per workspace root across repeated calls
  (spy/patch the subprocess boundary; assert call count).
- [ ] ⬜ **Task 1.2**: GREEN — memoise per resolved workspace root (module-level
  cache keyed by path; named constant for any sentinel). One fork per daemon
  lifetime.
- [ ] ⬜ **Task 1.3**: Verify behaviour unchanged for the positive and negative
  detection cases; verify a distinct workspace root is cached separately.
- [ ] ⬜ **Task 1.4**: Full QA + daemon restart RUNNING; live probe that a Bash
  PreToolUse still dispatches correctly.

### Phase 2: T4 — status-line git subprocess reduction

- [ ] ⬜ **Task 2.1**: RED — characterise current `git_branch.py` fork behaviour
  in tests (which git calls, how many) so the reduction is provably equivalent.
- [ ] ⬜ **Task 2.2**: GREEN — combine into fewer git calls and/or add a short
  TTL cache keyed by repo toplevel (named-constant TTL), following the
  handler's existing default-branch/TTL cache pattern.
- [ ] ⬜ **Task 2.3**: Prove branch name, ahead/behind, dirty, and stash-count
  outputs are unchanged for representative repo states.
- [ ] ⬜ **Task 2.4**: Full QA + daemon restart; live status render sanity check.

### Phase 3: legacy one-shot entry cleanup

- [ ] ⬜ **Task 3.1**: Confirm the crash and whether the one-shot path is still
  referenced anywhere (hooks wrappers, docs, tests). Decide fix-vs-delete.
- [ ] ⬜ **Task 3.2**: Apply the decision with tests (fix the schema call, or
  remove the dead path and any references) — no silent behaviour change.
- [ ] ⬜ **Task 3.3**: Full QA + daemon restart RUNNING.

### Phase 4: measure & record

- [ ] ⬜ **Task 4.1**: Re-run the relevant Plan 00154 harness probes
  (verifier matches() timing; status render) and record before/after in
  `CLAUDE/Performance/README.md` (and BASELINE if numbers move).

## Success Criteria

- [ ] T1 forks the remote at most once per daemon lifetime; measured Bash-event
  daemon-side p50 drops toward ~0.4 ms.
- [ ] T4 reduces git forks per status render (combined call and/or TTL);
  outputs identical for representative states.
- [ ] Legacy one-shot entry no longer crashes (fixed or removed cleanly).
- [ ] Full QA green (13/13), 95%+ coverage, daemon restarts RUNNING after every
  change, no handler decision behaviour changed.

## Notes & Updates

### 2026-07-12

- Plan scaffolded on branch `feature/performance-tuning`. Wave 1 = safe
  daemon-side wins only (T1, T4, legacy-entry cleanup); T2/T3 deferred to wave 2.
  Reusing the session's existing failsafe recovery cron `d4cb559d` (still live
  from the 00154 session) rather than creating a duplicate.
