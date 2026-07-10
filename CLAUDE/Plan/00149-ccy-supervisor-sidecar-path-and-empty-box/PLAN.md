# Plan 00149: ccy supervisor — sidecar path resolution + empty-box injection guard

**Status**: In Progress
**Created**: 2026-07-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Two field-reported bugs in the Plan 00135 PTY supervisor (`.claude/ccy/claude-supervise.py`),
both surfacing after the v3.34.0 deploy/arm work made the supervisor actually run
in client projects. They ship together as patch **v3.34.1**.

**Bug A — sidecar path mismatch (High).** The daemon writes the context sidecar
to `daemon_untracked_dir()/context-sidecar`, which is install-mode-aware:
`{project}/.claude/hooks-daemon/untracked/context-sidecar` in a **normal** client
install, `{project}/untracked/context-sidecar` in **self-install**. But the
supervisor's `_default_sidecar_dir()` hardcodes the self-install layout
(`{project}/untracked/context-sidecar`). The two only coincide in the daemon's
own repo — so in **every normal client install** the supervisor polls a
directory the daemon never writes, `load_freshest_sidecar()` returns `None` every
tick, and the compact-trigger loop is permanently inert (armed or dry-run). It
failed silently and was masked because all prior testing ran in self-install/dogfood.

**Bug B — injection into a non-empty input box (High).** The supervisor was
observed pasting its injection (`/compact` / `continue` / dry-run marker) into an
input box the human had partially typed into, then submitting — corrupting and
submitting the human's in-progress message. The supervisor must only inject into
an **empty** input box. Delegated to a Fable subagent (worktree-isolated).

## Goals

- Bug A: the supervisor resolves the SAME sidecar dir the daemon writes to, in
  both install modes, by mirroring the daemon's install-mode detection
  (`{project}/src/claude_code_hooks_daemon` present ⇒ self-install). Stdlib-only;
  robust at startup before any sidecar exists.
- Bug B: injection is gated on an empty input box; a non-empty box defers the
  injection tick (logged), never corrupts human input. (Fable subagent.)
- Both land in patch v3.34.1 with full QA + daemon restart verification.

## Non-Goals

- No change to the daemon's sidecar WRITE location — it is correct (runtime
  artifact belongs in the daemon untracked dir alongside socket/PID/log).
- No new CLI flag / env plumbing for Bug A — mode detection is self-contained.

## Tasks

### Phase 1: Bug A — sidecar path resolution (this thread)

- [x] ✅ **Task 1.1**: RED — added `test_sidecar_dir_resolution.py` (normal vs
  self-install vs env-unset); 3 RED, 1 pass (self-install coincidence).
- [x] ✅ **Task 1.2**: GREEN — `_default_sidecar_dir()` mirrors the daemon's
  `self_install_mode` detection; returns `{daemon_untracked}/context-sidecar`.
- [x] ✅ **Task 1.3**: 95 supervise tests pass; mypy clean; verified live —
  dogfood → `{project}/untracked/context-sidecar` (matches daemon write), normal
  client → `.claude/hooks-daemon/untracked/context-sidecar`. Delivered `c0e7209`.

### Phase 2: Bug B — empty-box injection guard (Fable subagent, worktree)

- [ ] 🔄 **Task 2.1**: Fable subagent implements input-line state tracking from
  forwarded human stdin + guards every injection path; TDD; commits to worktree.
- [ ] ⬜ **Task 2.2**: Merge the subagent's branch into main; reconcile with Bug A.

### Phase 3: Release v3.34.1

- [ ] ⬜ **Task 3.1**: `./scripts/qa/llm_qa.py all` → 13/13; daemon restart RUNNING.
- [ ] ⬜ **Task 3.2**: release patch → v3.34.1.

## Success Criteria

- [ ] In a normal-install layout, `_default_sidecar_dir()` points at
  `.claude/hooks-daemon/untracked/context-sidecar` (the daemon's real write dir).
- [ ] Self-install resolution unchanged (dogfood still works).
- [ ] Non-empty input box defers injection; empty box injects; human bytes vs
  supervisor-injected bytes are distinguished.
- [ ] QA 13/13, daemon RUNNING, v3.34.1 released.

## Notes & Updates

### 2026-07-10

- Reused existing failsafe recovery cron `26b41693` (hourly :37, non-durable).
- Bug A root cause confirmed from field report `untracked/hooks-daemon-sidecar-path.md`
  (live evidence: daemon writes `.claude/hooks-daemon/untracked/context-sidecar/<sid>.json`;
  supervisor `decision.log` polls `{project}/untracked/context-sidecar`, which is absent).
- Bug B delegated to Fable subagent `textbox-guard` in an isolated worktree.
- v3.34.0 already shipped the arm/track fixes (Plan 00148); v3.34.1 completes the
  supervisor so it actually observes context and injects safely.
