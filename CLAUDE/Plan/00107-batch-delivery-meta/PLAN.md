# Plan 00107: Batch Delivery Meta Plan — v3.12.0 Release Bundle

**Status**: In Progress
**Owner**: Claude (Opus)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (Opus coordinates; specialised sub-agents per wave)

## Overview

This is a **meta plan**. It does not ship code of its own; it orchestrates the
delivery of every other outstanding plan in the active queue, sequencing them
into waves that respect dependencies and gating each wave on QA + live daemon
restart verification. The end state is a single **v3.12.0 release** that
ships every closeable plan together — no more drip-feed of single-plan
patch releases.

The motivation is concrete: the active plan queue has accumulated ten in-flight
plans (some with overlapping scope, e.g. 00089 and 00106 both touching
`auto_approve_reads`), the README index had drifted out of sync with the
filesystem, and several plans are partially-shipped-but-not-closed
(00101 Phase 4, 00102 Task 5.3). Without a top-level coordinator, the queue
keeps growing while the release treadmill keeps churning out single-plan
patches. This plan stops both.

## Goals

- Reconcile `CLAUDE/Plan/README.md` with the actual filesystem state (Phase 0)
- Sequence every outstanding active plan into a dependency-aware delivery
  order, grouped into six waves
- Gate each wave on full QA suite (`./scripts/qa/run_all.sh`) + daemon
  restart-verification before the next wave starts
- Ship the entire bundle as **v3.12.0** via the `/release` skill following
  `CLAUDE/development/RELEASING.md` end-to-end
- Update each in-flight plan's status as its wave completes, then move the
  plan folder to `Completed/` and refresh the index in the same commit

## Non-Goals

- Restarting plans from scratch — every in-flight plan keeps its existing
  PLAN.md, phase structure, and TDD coverage
- Re-opening On-Hold plans (00032/00034/00035) — they remain blocked on
  upstream Claude Code delegate-mode fixes (GitHub #23447, #25037)
- Touching scope of completed plans (00104 / 00105) — venv-review tasks
  (Wave 5) only audit what 00099 / 00100 still need to ship vs what
  00104 / 00105 already delivered
- Inventing new handlers or features outside the scope of the in-flight plans

## Context & Background

### State at meta-plan creation

The active plan queue, after Phase 0 reconciliation:

| Plan  | Title                                                    | Status       | Pending Work                                   |
| ----- | -------------------------------------------------------- | ------------ | ---------------------------------------------- |
| 00063 | FAIL FAST — Plugin handler & error-hiding audit          | In Progress  | Phase 2: comprehensive error-hiding audit      |
| 00077 | TranscriptReader Enhancement & AskUserQuestion Bug Fix   | In Progress  | Phases 2–5                                     |
| 00081 | Pseudo-Events & Nitpick Handler                          | In Progress  | Phases 2–5 (needs 00077)                       |
| 00085 | Reminder Pseudo-Event System with Adaptive Triggers      | In Progress  | All 8 phases (needs 00081)                     |
| 00086 | Plan Redirect System Improvement                         | Not Started  | 4 phases                                       |
| 00089 | Fix auto_approve_reads schema mismatch + AskUserQuestion | Complete     | Delivered in `eb74e4a`; closed out in Wave 1   |
| 00096 | Live Daemon Smoke Tests in QA Stack                      | Not Started  | Single phase (3 nc-based probes as QA check 9) |
| 00099 | Python-Fingerprint Venv Isolation                        | Needs Review | Audit vs 00104 / 00105 shipped work            |
| 00100 | Venv SSOT Consolidation                                  | Needs Review | Audit vs 00104 / 00105 shipped work            |
| 00101 | Recap-Stoppage Investigation                             | In Progress  | Phase 4 regression verification                |
| 00102 | Hook Executable-Bit Defense                              | In Progress  | Task 5.3 (acceptance gate at release time)     |
| 00106 | Bypass-Permissions-Aware Auto-Approve                    | Not Started  | All 6 phases (queue cleared post v3.11.0)      |

Plus on-hold: 00032 / 00034 / 00035 (out of scope; upstream-blocked).

### Why a meta plan instead of just executing the queue

Three of the in-flight plans **overlap scope** in ways that need explicit
sequencing:

1. **00089 + 00106** — both touch `auto_approve_reads`. 00089 fixes a schema
   mismatch (Bug 1 — handler currently misses real PermissionRequest events
   because it inspects the wrong field). 00106 layers mode-gating on top
   (only auto-approve when `permission_mode == "bypassPermissions"`).
   **Order matters**: 00089 first (otherwise 00106's mode-gating runs on a
   handler that doesn't match in the first place), 00106 second.
2. **00077 → 00081 → 00085** — strict dependency chain. TranscriptReader
   refactor (00077) provides shared utilities that pseudo-events (00081)
   builds on, which reminder pseudo-events (00085) builds on. Skipping ahead
   would force later plans to either re-implement the foundation or back-port
   the refactor — both worse than the linear order.
3. **00099 + 00100** — both written before Plans 00104 (v3.10.0) and 00105
   (v3.11.0) shipped substantial venv-resolution work. They may now be
   partially-or-fully-superseded. **Cannot just execute them** — need an
   audit phase (Wave 5 Task 5.1) before deciding what is still in-scope.

### Dogfooding bugs found during housekeeping

During the README reconciliation (Phase 0), encountered:

1. `validate_instruction_content` (priority 50, TERMINAL) blocks ALL
   timestamps in `CLAUDE/Plan/README.md` even though the README's established
   convention is to record completion dates `(YYYY-MM-DD)` in every entry of
   the Completed section. Pre-existing dates were not removed; only new ones
   are blocked. This is over-fitting — the handler's purpose is preventing
   ephemeral state-of-the-session content in instruction files
   (`CLAUDE.md` / root `README.md`), not policing the project-internal
   plan index where dated entries are intentional and load-bearing.
   **Logged as Wave 3 Task 3.3 — audit and narrow handler scope.**

## Tasks

### Phase 0: Housekeeping (this commit)

- [x] **Task 0.1**: Move `00071-triage-plan-race-report` to `Completed/`
- [x] **Task 0.2**: Remove empty orphan folder `00073-lsp-enforcement-handler/`
  (the real LSP-enforcement plan is `00075` in Completed/)
- [x] **Task 0.3**: Reconcile `CLAUDE/Plan/README.md` Active Plans section
  with actual filesystem state (12 active plans, organised by category)
- [x] **Task 0.4**: Update README plan statistics (107 total, 82 completed,
  12 active, 3 on hold, 5 cancelled)
- [x] **Task 0.5**: Create this meta plan (Plan 00107)
- [ ] **Task 0.6**: Update plan-index convention — **completion dates removed
  from `CLAUDE/Plan/README.md` Completed entries; delivery commit hash(es)
  cited instead** (git is the source of truth for "when"). Update
  `CLAUDE/PlanWorkflow.md` to record the new convention. Bulk-rewrite the
  existing Completed/ entries to drop dates and add commit-hash references
  where the delivery commit is recoverable from `git log -- <plan-folder>`.
  Justification: the `validate_instruction_content` handler correctly
  blocks dated content in instruction files; the index was breaking that
  rule. New convention aligns the index with the handler.

### Phase 1: Wave 1 — Bug Fixes (independent, parallelisable internally)

Goal: ship the highest-value bug fixes first so that downstream waves run
against corrected behaviour.

- [x] **Task 1.1**: Execute **Plan 00089** (auto_approve_reads schema fix +
  AskUserQuestion YOLO blocker) — **Phases 1 + 2 already delivered in
  commit `eb74e4a`** (this Wave 1 task only handles Phase 3 close-out).
  Verified 30/30 tests pass for both handlers. Plan moved to `Completed/`.
- [x] **Task 1.2**: Execute **Plan 00106** (bypass-permissions-aware auto-approve)
  - All 6 phases delivered in commit `e547c63`
  - Sibling-bug fix folded in: `HelloWorldPermissionRequestHandler` was
    silently auto-approving every PermissionRequest via `Decision.ALLOW`
    from a non-terminal observability handler — switched to `Decision.CONTINUE`
  - Plan moved to `Completed/`, README updated
- [x] **Task 1.3**: Execute **Plan 00086** (plan redirect system improvement)
  - Code: `_handle_plan_write` in `markdown_organization.py` switched from
    `Decision.DENY` to `Decision.ALLOW` so the flat plan file goes through and
    `ExitPlanMode` shows full plan content to the user. `plansDirectory` route
    confirmed working empirically (Apr-10 `idempotent-chasing-wadler.md` flat
    file at the configured directory root). Phase 2 sync-check
    (`_check_claude_code_sync` at line 354) already in place from prior work.
  - Tests: `TestPlanWriteDenyBehaviour` class replaced with
    `TestPlanWriteAllowBehaviour` (4 ALLOW-asserting tests covering context
    payload, numbered-folder creation, post-approval rename + flat-file
    cleanup instructions); 5 sibling tests rewired from DENY→ALLOW;
    integration test `test_handler_config_blocking.py` updated to match.
    153/153 markdown_organization + integration tests pass; full QA 12/13
    (deptry wrapper pre-existing false positive); daemon restart verified.
  - Plan 00086 marked Complete, moved to `Completed/`, README index updated.
- [x] **Task 1.4**: Wave 1 gate — verified after Plan 00086 commit `a4b2cfb`:
  full QA 12/13 (deptry wrapper pre-existing false positive, same condition
  as Plan 00106 close-out); daemon restarted and verified RUNNING (PID
  60980). No FAIL-FAST cycle triggered. Wave 1 closed.

### Phase 2: Wave 2 — Quality / Infra (independent, parallelisable)

Goal: harden the QA stack itself so subsequent waves have stronger detection.

- [x] **Task 2.1**: Execute **Plan 00063 Phase 2** (comprehensive error-hiding
  audit + audit-script + fix violations)
  - **Already Shipped (audit decision)** — Wave 2 audit found:
    `scripts/qa/audit_error_hiding.py` + `error_hiding_exclusions.json`
    detect all 7 documented patterns; integrated as one of the 12 QA gates;
    live audit reports zero violations across the codebase;
    `CLAUDE.md:320` codifies `FAIL FAST` as Engineering Principle.
  - Plan 00063 marked Complete (Already Shipped), moved to `Completed/`.
- [x] **Task 2.2**: Execute **Plan 00096** (live daemon smoke tests as QA
  check 9 — 3 nc-based probes)
  - **Already Shipped (audit decision)** — Wave 2 audit found every
    deliverable already in place from commit `bce66248`: 3-probe
    `run_smoke_test.sh`, `llm_qa.py` integration as `smoke_test`,
    `tests/unit/qa/test_smoke_test.py`. No further code action required.
  - Plan 00096 marked Complete (Already Shipped), moved to `Completed/`,
    README index updated.
- [ ] **Task 2.3**: ~~Investigate `validate_instruction_content` over-fit~~ —
  **REJECTED**. User clarified the handler is correct: completion dates do
  not belong in instruction files. Git is authoritative for "when". Plan
  index should cite the delivery commit hash(es) instead. Replaced by
  Task 0.6 (convention update).
- [x] **Task 2.4**: Wave 2 gate — QA + daemon restart verification.
  - Full QA: 12/13 (only deptry wrapper false positive; same condition
    as Waves 1 & pre-bundled releases).
  - Daemon RUNNING (PID 60980, verified post-Wave-1; Wave 2 had no
    handler code changes — both plans audited as Already Shipped — so
    no restart needed).
  - Wave 2 closed.

### Phase 3: Wave 3 — Stop-Quality Stack (strict serial dependency chain)

Goal: complete the chain that has been blocked for weeks because each plan
depends on the previous one's shared utilities.

- [ ] **Task 3.1**: Execute **Plan 00077 Phases 2–5** (TranscriptReader
  enhancement + shared Stop hook utilities + refactor of duplicated
  Stop handlers)
- [ ] **Task 3.2**: Execute **Plan 00081 Phases 2–5** (pseudo-events
  infrastructure + checker protocol + NitpickHandler + integration)
  - Hard-blocked by 00077 — do NOT start until 00077 ships
- [ ] **Task 3.3**: Execute **Plan 00085** (reminder pseudo-event system
  with adaptive triggers — all 8 phases)
  - Hard-blocked by 00081 — do NOT start until 00081 ships
- [ ] **Task 3.4**: Wave 3 gate — QA + daemon restart verification.

### Phase 4: Wave 4 — Venv Plan Audit (decision-first, then execute residue)

Goal: decide whether 00099 / 00100 still have in-scope work after the venv
hardening shipped in v3.10.0 (Plan 00104) and v3.11.0 (Plan 00105).

- [ ] **Task 4.1**: Spawn audit sub-agent to compare 00099 PLAN.md +
  00100 PLAN.md against the shipped state of `scripts/lib/resolve_venv.sh`,
  `scripts/install/venv.sh`, `untracked/venv-py{MM}-{fingerprint}/`,
  `.daemon-metadata.json`, and the H-1 acceptance gate. Output: per-plan
  decision — `Already Shipped` / `Residue Scope` / `Still Required`.
- [ ] **Task 4.2**: For each plan, either:
  - **`Already Shipped`** → mark Complete, move to `Completed/` with a note
    referencing the superseding plan(s)
  - **`Residue Scope`** → trim the PLAN.md to the residue and execute the
    trimmed version
  - **`Still Required`** → execute the full plan
- [ ] **Task 4.3**: Wave 4 gate — QA + daemon restart verification.

### Phase 5: Wave 5 — Carry-Forward Verification (close out partially-shipped plans)

Goal: close out plans whose code-level work shipped in earlier releases but
whose verification-level work was deferred to "next release".

- [ ] **Task 5.1**: Execute **Plan 00101 Phase 4** (recap-stoppage regression
  verification across session-recap scenarios)
- [ ] **Task 5.2**: Execute **Plan 00102 Task 5.3** (hook executable-bit
  defense — acceptance gate at v3.12.0 release time; this is the
  release that gate was deferred to)
- [ ] **Task 5.3**: Wave 5 gate — QA + daemon restart verification.

### Phase 6: Release v3.12.0

Goal: ship the entire bundle as a single release via `/release` skill,
following `CLAUDE/development/RELEASING.md` end-to-end with no shortcuts.

- [ ] **Task 6.1**: Invoke `/release` skill — auto-detect bump
  (expected: **MINOR** — multiple new handlers + features. Plan 00106 is
  a **security bug fix** restoring the intended per-tool approval flow in
  non-YOLO modes; it is NOT a breaking change and does NOT require an
  upgrade guide)
- [ ] **Task 6.2**: Confirm pre-release validation passes (Step 1)
- [ ] **Task 6.3**: Verify Step 6 (UNRELEASED post-upgrade-tasks moved into
  versioned upgrade guide if any)
- [ ] **Task 6.4**: Pass Step 8 QA Verification Gate (12 checks, all green)
- [ ] **Task 6.5**: Pass Step 9 Breaking Changes Check — bundle contains no
  breaking changes (00106 is a bug fix; auto-approving in non-YOLO modes
  was the original bug). Step 9 should pass without an upgrade guide.
- [ ] **Task 6.6**: Pass Step 10 Code Review Gate
- [ ] **Task 6.7**: Pass Step 11 CLAUDE.md Guidance Audit
- [ ] **Task 6.8**: Pass Step 12 Acceptance Testing Gate (includes Step 12.0
  H-1 deterministic install/diagnostic gates — they catch the v3.9.x and
  v3.10.0 SEV-1 regression classes)
- [ ] **Task 6.9**: Commit, push, tag v3.12.0, GitHub release with
  `bootstrap-checksums.txt` + 4 self-bootstrapping skill scripts
- [ ] **Task 6.10**: Post-release verification (Step 15)
- [ ] **Task 6.11**: Plan 00107 housekeeping — mark Complete, move to
  `Completed/`, update README index, update statistics

## Dependencies

```
Phase 0 (housekeeping)  ──┬──→ Wave 1 (00089 → 00106; 00086 parallel)
                          │      │
                          ↓      ↓
                       Wave 2 (00063-P2; 00096; 00097-bug-fix)
                          │
                          ↓
                       Wave 3 (00077 → 00081 → 00085)
                          │
                          ↓
                       Wave 4 (00099 / 00100 audit)
                          │
                          ↓
                       Wave 5 (00101-P4; 00102-T5.3)
                          │
                          ↓
                       Wave 6 (release v3.12.0)
```

- Blocks: every active plan listed in the table above
- Blocked by: none
- On-hold plans (00032 / 00034 / 00035) are explicitly out of scope —
  they remain blocked on upstream Claude Code fixes

## Technical Decisions

### Decision 1: One release, not six

**Context**: each in-flight plan could individually justify a patch release.
That's six-plus releases over the next short period.

**Options Considered**:

1. **Drip-feed**: ship each plan as it lands (one patch release per plan)
   - Pros: smaller diffs per release, faster user-visible iteration
   - Cons: release-pipeline overhead × N, more attack surface for v3.10.0-style
     SEV-1 regressions (each release is a chance to ship a bug), drift between
     plans gets worse not better
2. **One big release**: ship the entire bundle as v3.12.0 (chosen)
   - Pros: single release-pipeline run, all 12 H-1 acceptance gates fire once,
     all 12 QA checks fire once, dependency chains within the bundle can be
     verified end-to-end before any user sees them
   - Cons: bigger diff, longer release window, more to roll back if one plan
     introduces a regression that the gates miss

**Decision**: One big release. The post-v3.10.0 lesson is that release
pipeline overhead is the dominant failure mode — each release adds risk.
Bundling minimises pipeline runs and lets the gates verify the bundle as a
whole. Mitigates "bigger diff" cost via wave-by-wave checkpoint commits
(every wave is independently revertable inside the bundle).

### Decision 2: Wave ordering is dependency-led, not value-led

**Context**: "value-first" would put the biggest user-visible wins first.
But several of the highest-value plans (e.g. 00085 reminder pseudo-events)
are blocked on lower-value foundation work (00077 TranscriptReader refactor).

**Options Considered**:

1. **Value-first**: 00106 → 00085 → 00096 → … (skip foundation work)
   - Pros: highest-impact-first
   - Cons: forces foundation plans to either back-port or be re-implemented
     by the dependent plan; doubles work
2. **Dependency-led** (chosen): foundations first, dependents second
   - Pros: each plan ships against its expected foundation; no back-porting;
     dependency chains finish atomically within a single wave
   - Cons: low-impact plans (00077) ship before high-impact plans (00085)

**Decision**: Dependency-led. The release bundles everything anyway, so
"order within the bundle" only matters for development efficiency, not
user-visible value.

### Decision 3: Audit 00099 / 00100 instead of executing them blind

**Context**: both plans were written before v3.10.0 / v3.11.0 shipped
substantial venv work. Their PLAN.md text predates the shipped state.

**Options Considered**:

1. **Execute as written**: trust the original PLAN.md
   - Pros: no audit overhead
   - Cons: likely duplicates already-shipped work, may regress against
     the canonical resolver library introduced in v3.10.0
2. **Cancel both**: treat v3.10.0 + v3.11.0 as superseding
   - Pros: simplest
   - Cons: throws away potentially in-scope residue
3. **Audit-then-execute** (chosen): explicit `Already Shipped` / `Residue Scope` / `Still Required` decision per plan before execution
   - Pros: ships only the residue that's still needed; explicit closure
     for the rest
   - Cons: one extra sub-agent invocation

**Decision**: Audit-then-execute. The audit is cheap (one Explore sub-agent
diffing PLAN.md against shipped state); the cost of skipping it is duplicate
work or regression.

## Success Criteria

- [ ] Phase 0 housekeeping commit landed (README reconciled, 00071 moved,
  00073 orphan removed, Plan 00107 created)
- [ ] Every plan in Wave 1–5 ends in one of: `Completed/`, cancelled with
  reason, or trimmed-to-residue and executed
- [ ] `./scripts/qa/run_all.sh` passes 12/12 at every wave gate
- [ ] Daemon restart-verified RUNNING at every wave gate
- [ ] v3.12.0 ships via `/release` skill with zero gate bypasses
- [ ] H-1 acceptance gate (Step 12.0) passes — `tests/acceptance/test_diagnostic_scripts.py`
  and `tests/acceptance/test_install_sh_end_to_end.py` combined: 6 passed,
  1 skipped, 0 failed
- [ ] `bootstrap-checksums.txt` published with sha256 entries for all four
  self-bootstrapping skill scripts; sha-match verification passes
- [ ] README index reflects post-release state (this plan in Completed/,
  every bundled plan in Completed/, statistics refreshed)

## Risks & Mitigations

| Risk                                                                          | Impact | Probability | Mitigation                                                                                                                                           |
| ----------------------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| A bundled plan introduces a regression that QA misses                         | High   | Medium      | Wave-by-wave checkpoint commits — each wave is independently revertable; H-1 gate catches integration-level                                          |
| User complaints that "permission prompts came back" after upgrade             | Low    | Medium      | Release notes frame 00106 as a **security fix** restoring intended per-tool approval flow; point complainants at YOLO mode if they want auto-approve |
| 00099 / 00100 audit reveals more residue than expected                        | Medium | Medium      | Wave 4 is its own gated phase — if scope grows, can split into v3.12.0 / v3.13.0 boundary at audit time                                              |
| ~~`validate_instruction_content` over-fit~~ — false alarm; handler is correct | —      | —           | Convention updated in Task 0.6; index no longer carries dates                                                                                        |
| Wave 3 dependency chain stalls if 00077 hits an unexpected blocker            | High   | Low         | Spawn the audit sub-agent for 00077 first to catch any latent issue before the chain commits to it                                                   |
| Release rollback after tag                                                    | High   | Low         | Tag-rollback procedure in RELEASING.md is well-documented; checkpoint commits per wave make revert tractable                                         |

## Notes & Updates

- Phase 0 housekeeping landing in the same commit as this plan's creation.
- After Phase 0 commit, execution moves to Wave 1 (Plan 00089).
- Each subsequent wave's start triggers a checkpoint commit; each wave's
  end triggers a wave-gate commit (QA + daemon-restart verified).
