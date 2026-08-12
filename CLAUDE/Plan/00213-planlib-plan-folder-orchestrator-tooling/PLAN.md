# Plan 00213: planlib plan folder orchestrator tooling

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

An upstream proposal arrived from a client project: promote its plan-folder
orchestrator tooling (`planlib`) into the hooks daemon, so that every project
using the plan workflow gets the same bash library rather than each one growing
its own. The proposal is a **generic extraction** of code already running in a
private infrastructure repository — project-specific facts were pulled out into
a configuration seam, and the library is presented complete and self-contained
rather than excerpted.

The proposal arrived verified rather than sketched, which is why it is worth
holding: the library was concatenated and checked with `bash -n` (asserting
empty stderr, because `bash -n` prints a diagnostic and still exits 0 on a
malformed conditional, so the exit code alone is not the signal), passed
`shellcheck -x -S style`, and had every called function cross-referenced against
every defined one. The `§5` skeletons are explicitly marked as templates
containing placeholders, not runnable code.

This plan exists so the proposal is TRACKED rather than lingering in
`untracked/`. Phase 1 (evaluation only) is complete — see Technical Decisions
for the recorded ADAPT recommendation. Phase 2 (adoption) remains gated on a
human scope decision: adopting a ~62KB bash library into the daemon is not
something to begin because the document happens to be well written, or
because an evaluation recommends it.

## Goals

- Preserve the proposal as tracked source with its provenance and verification
  claims intact, so a later evaluation starts from the document rather than from
  a re-derivation.
- Reach an explicit accept / adapt / decline decision on promoting `planlib`
  into the daemon, recorded under Technical Decisions.
- If accepted, land it behind the daemon's existing conventions rather than as a
  foreign body: config-driven seams, the deploy-assets path already used by
  `mkplan.bash`, and QA coverage equal to the rest of the shell surface.

## Non-Goals

- Adopting the library as-is without review. It is a proposal, not a patch.
- Re-verifying the author's claims as a precondition for filing this plan — the
  verification table is recorded as an assertion to be checked at evaluation
  time, not as something this plan takes on trust or on faith.
- Any change to `mkplan.bash` or the plan workflow before a decision is made.

## Context & Background

Supporting documents in this folder (the EXTRACT remedy from Plan 00211 —
durable detail belongs in named files, not inflating PLAN.md):

- `PROPOSAL.md` — the current proposal (v2), self-contained and verified.
- `PROPOSAL-v1-SUPERSEDED.md` — the earlier draft, kept because the daemon's
  own convention is to preserve superseded versions rather than delete them.
- `../Cancelled/00199-hooks-daemon-plan-lib/PROPOSAL-ASSESSMENT.md` — an
  independent integration analysis of this same proposal from a duplicate
  plan (Plan 00199, filed 5 days before this one against the same source
  document, unaware of each other). Plan 00199 was superseded by this plan
  once the duplication was found; its assessment reached the same ADAPT
  conclusion independently and is relied on directly in Phase 2 rather than
  re-derived (deploy-mode 0644 vs 0755, `_EXPECTED_ROOT_FILES` inclusion, no
  default `root_marker`, neutral config examples, the `bash -n` stderr
  assertion, and `plan_script_qa` deferral all trace back to it).

## Tasks

### Phase 1: Evaluation

- [x] ✅ **Task 1.1**: Read `PROPOSAL.md` and independently re-run its stated
  verification (`bash -n` with an empty-stderr assertion, `shellcheck -x -S style`, defined-vs-called function cross-reference). Confirmed all three claims exactly as stated — see `EVALUATION.md` §1.
- [x] ✅ **Task 1.2**: Assess overlap with what the daemon already ships —
  `mkplan.bash`, `deploy-plan-workflow`, the `plan_qa` check catalogue — and
  identify what `planlib` adds beyond them. Overlap is minimal; different lifecycle stage — see `EVALUATION.md` §2.
- [x] ✅ **Task 1.3**: Record an accept / adapt / decline decision with rationale
  under Technical Decisions. Recorded: ADAPT.

### Phase 2: Adoption (only if Task 1.3 accepts)

- [x] ✅ **Task 2.1**: Define the configuration seam in `.claude/hooks-daemon.yaml`
  and its schema validation. Landed as `PlanWorkflowScriptsConfig` nested at
  `plan_workflow.scripts` (`src/claude_code_hooks_daemon/config/models.py`): `enabled` (default `false`),
  `root_marker` (no default — a `model_validator` FAILS FAST if `enabled` is
  true and `root_marker` is empty or `.git`), `delegate`, `check_flag`,
  `force_color_var`, `scrubber`, `track_run_logs`.
- [x] ✅ **Task 2.2**: Wire deployment through the existing idempotent
  plan-workflow asset deploy path. `_planlib.inc.bash` (byte-identical to the
  independently re-verified extraction) lives at
  `install/templates/_planlib.inc.bash` and deploys through
  `deploy_plan_workflow_if_enabled` → `bootstrap_plan_workflow` (a new
  `deploy_scripts_library` parameter, gated on `plan_workflow.scripts.enabled`
  AND the parent `plan_workflow.enabled`) — the SAME seam `mkplan.bash` uses,
  not a parallel path. Daemon-owned (overwritten every deploy), but mode
  `0o644` via its own `_PLANLIB_MODE` constant — deliberately NOT
  `_MKPLAN_MODE` (`0o755`), since the library is sourced, never executed.
  `_planlib.inc.bash` also joined `plan_qa`'s built-in `_EXPECTED_ROOT_FILES`
  so the SessionStart sweep never flags it as a stray root file.
- [x] ✅ **Task 2.3**: Bring shell QA coverage up to the standard the rest of the
  shell surface is held to (`shell_audit`, `shellcheck`). Verified at landing:
  `bash -n` (stderr asserted empty), `shellcheck -x -S style` (stricter than
  the project's own `-S warning` gate) both clean; the project's own
  `scripts/qa/run_shell_check.sh` passes with the file included (55 scripts,
  0 issues). A 47-case pytest suite
  (`tests/unit/install/test_planlib_library.py`) exercises the library as
  real bash via subprocess — see Technical Decisions for what it covers and
  what it deliberately does not.
- [x] ✅ **Task 2.4**: Stage `config-changes` so the feature does not ship
  dormant and undocumented. Appended (not rewrote) an entry to
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.53.0.yaml` for
  `plan_workflow.scripts` (`recommended: false`, `dormant: true` — this is
  not a universally-beneficial feature). A `truth-changes` entry was assessed
  and judged NOT applicable: truth-changes reconciles an EXISTING documented
  workflow that changed, and this is a wholly new opt-in with no prior
  documented truth to reconcile.

## Dependencies

- Related: Plan 00211 (plan-size guidance / supporting-docs concept) — this plan
  folder is itself an application of that plan's EXTRACT remedy.

## Technical Decisions

### Decision 1: planlib — ADAPT, not full accept, not decline

**Context**: Phase 1 independently re-ran the proposal's stated verification
and assessed overlap with existing daemon tooling. Full detail (verification
transcripts, per-artefact overlap table, architectural analysis) is in
`EVALUATION.md`; this records the decision and the load-bearing reasons.

**Verification (Task 1.1)**: all three of the proposal's stated claims about
`_planlib.inc.bash` (§3) were independently reproduced and confirmed exactly
as stated — `bash -n` with empty stdout/stderr, `shellcheck -x -S style`
clean (stricter than the daemon's own shell QA gate requires), and a
zero-dangling-reference cross-check across all 24 `plan_*`/`_plan_*`
functions. A bonus dynamic smoke test (not claimed by the proposal, done for
extra confidence) confirmed the pure/testable primitives behave as documented,
including the specific incident-class fix in §1.1 (script-relative,
boundary-bounded root resolution correctly refuses to walk past a nested
repo). However, of the proposal's three named artefacts
(`_planlib.inc.bash`, `plan_script_qa`, `test-planlib.bash`), **only the
library is delivered as complete, runnable code** — the QA handler is a
rules table plus two illustrative snippets, and the test suite is four
stated principles with no runnable file. The proposal itself scopes its
verification table to the library only, but a skim can read it as covering
"the proposal."

**Overlap (Task 1.2)**: minimal, and mostly additive rather than duplicative.
`mkplan.bash`, `deploy-plan-workflow`, and all 30 `plan_qa` checks across its
3 enforcement surfaces operate at plan **creation** and `PLAN.md` **hygiene**
— none inspect executable content. `planlib` addresses a different lifecycle
stage entirely: safe **execution** of operator-run scripts filed inside a
plan folder. The one real new-capability claim (`plan_script_qa` linting
script structural safety) holds up — the daemon has nothing like it today.
The honest answer to "does most of this already exist here" is **no**.

**Options considered**:

1. **Decline** — reject the proposal outright. Rejected: the verified library
   solves a real, previously-encountered incident class with primitives that
   are easy to get subtly wrong if reinvented (named-pipe-vs-`>()` drain
   determinism, the `BASH_SUBSHELL` leg guard, TTY-vs-stdin prompt-ordering).
   Declining would discard genuinely solid, independently-verified work.
2. **Full accept** — land all three artefacts as "Phase 2" per the plan's
   original task list. Rejected: only 1 of 3 artefacts is actually finished
   code. Treating the QA handler and test suite as a four-task polish step
   understates the work — this project's TDD discipline has no RED phase to
   start from for either, since neither exists yet as runnable code.
3. **Adapt** (chosen) — accept the library alone, behind config, on the
   existing `deploy_plan_workflow_if_enabled` seam (already reusable,
   already idempotent, already the mechanism this plan's own Goals section
   names); treat `plan_script_qa` + `test-planlib.bash` as a **separate**,
   honestly-scoped follow-up plan rather than folding them into this one.

**Decision**: ADAPT. If a human authorises Phase 2, re-scope it to land the
library only, then open a new plan for the QA handler and test suite once a
human has also weighed the open architectural question below — this decision
does not resolve it, only surfaces it.

**Open question for the human, not resolved here**: `planlib` is explicitly
operator-invoked (§9 of the proposal) with zero runtime coupling to Claude
Code hook events or anything the daemon governs — unlike `mkplan.bash`, which
manipulates daemon-owned state (the plan counter, `PLAN.md` shape). Whether a
general-purpose, plan-system-agnostic bash safety library belongs inside a
**Claude Code hooks daemon**, versus being a separate vendored library the
daemon merely helps distribute, is a scope call this plan's own Non-Goals
section already reserves for a human.

**Date**: 2026-08-12

## Success Criteria

- [x] ✅ An explicit, recorded decision exists on whether `planlib` is adopted
  (ADAPT — Decision 1)
- [x] ✅ No proposal document remains in `untracked/` (filed into this plan
  folder at plan creation)
- [x] ✅ Targeted tests pass and QA-equivalent checks pass in the worktree:
  `pytest` for the new config/install/plan_qa/library-behaviour tests (all
  green, 100% coverage on `install/plan_workflow.py`), `mypy`/`ruff`/`black`
  clean on every touched Python file, `shellcheck -x -S style` +
  `bash -n` (stderr-asserted-empty) clean on `_planlib.inc.bash`, and the
  project's own `scripts/qa/run_shell_check.sh` passing with the file
  included.
- [ ] ⬜ **OUTSTANDING (cannot verify from this worktree)**: full
  `./scripts/qa/run_all.sh`, a daemon restart + `status` showing `RUNNING`,
  and client-mode verification (`scripts/dummy-client-repo.sh`) against the
  merged tree — this worktree agent cannot restart the shared daemon; the
  merging session must run these before treating Phase 2 as done.
- [x] ✅ The feature ships with an upgrade manifest rather than silently
  (`config-changes/v3.53.0.yaml` entry, Task 2.4)

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00213-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Proposal filed out of `untracked/` and into tracked source at plan creation

- Phase 2 landed in worktree `agent-a5ec3d0f3519739e1-e3a4a2e0`: config seam
  (Task 2.1), deploy path + `_planlib.inc.bash` (Task 2.2), 47-case
  behavioural test suite + shell QA verification (Task 2.3), config-changes
  manifest (Task 2.4), and dogfooding the deploy mechanism in this repo's own
  config — see the plan's `JOURNAL/` for the commit list.

- Proposal filed out of `untracked/` and into tracked source at plan creation
