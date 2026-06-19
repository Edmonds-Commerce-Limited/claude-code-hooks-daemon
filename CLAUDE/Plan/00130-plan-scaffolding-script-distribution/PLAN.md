# Plan 00130: Plan-Scaffolding Script Distribution (`mkplan.bash`)

**Status**: In Progress
**Created**: 2026-06-19
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (audit fan-out)

## Overview

A candidate helper script — `mkplan.bash` — has been proposed for distribution into
client projects' plan folders (conventionally `CLAUDE/Plan/`). The script scaffolds the
next sequentially-numbered plan folder + a skeleton `PLAN.md`, resolving the next number
from the same git-anchored counter (`hooksdaemon.latestPlanNumber`) that the daemon's
`plan_numbering` / `validate_plan_number` handlers use (Plan 00112). The intent is to give
both humans and agents a single, foolproof "make the next plan" command so nobody hand-rolls
a folder name, scans `ls` for the next number, or collides on a number across branches.

The proposal has three legs:

1. **Distribute** the script into client plan folders (via the installer / upgrade flow).
2. **Configure hooks** so the daemon's plan-numbering machinery and the script agree and
   never double-increment the counter.
3. **Guide agents** toward the script (handler guidance / `get_claude_md()` / docs) so the
   "create a plan" path is discoverable and preferred over ad-hoc folder creation.

This plan does NOT rubber-stamp the script. The first deliverable is a **full hostile audit**
of both the script and the proposal — correctness, portability, security, daemon-integration
coherence, and distribution mechanics — captured as versioned `AUDIT-vN.md` documents, with the
script refined iteration-by-iteration and committed on each pass.

## Goals

- Capture the candidate script verbatim in this plan folder (`mkplan.bash`) as the audit baseline.
- Produce a rigorous, adversarial audit of the script (correctness, portability, security,
  concurrency, daemon-integration) and the surrounding distribution proposal.
- Refine the script until the audit findings are resolved, tracking every iteration as a
  committed `AUDIT-vN.md` + script revision.
- Decide (with evidence) whether/how to wire distribution into the installer/upgrade flow and
  how the daemon's counter ownership must interact with the script.
- Keep the script genuinely dual-audience: safe and legible for humans, deterministic and
  machine-parseable for agents.

## Non-Goals

- Shipping a release. Distribution wiring, tests, and release are downstream of a passing audit.
- Rewriting the daemon's existing plan-numbering handlers (Plan 00112 is the SSOT for counter logic).
- Building a general-purpose plan-management CLI. This is a single scaffolding command, by design (YAGNI).

## Context & Background

- **Plan 00112 (Completed)** made `git config --local hooksdaemon.latestPlanNumber` the authoritative
  next-plan source, trusted on read (`counter + 1`), bootstrapped from a filesystem scan only when
  absent, with a high-water-mark write on real plan creation. The script must mirror this exactly or
  it will fight the daemon.
- **`plan_number_helper`** handler guidance already tells agents the git counter is the source of truth
  and NOT to scan `CLAUDE/Plan/` with `ls`/`find`. The script operationalises that guidance.
- **`validate_plan_number`** (ADVISORY) and **`markdown_organization`** plan-redirect logic also touch
  plan creation; the counter-ownership question (who increments, when) is the crux of the integration audit.
- The script is self-locating (`BASH_SOURCE`, symlink-safe) so it needs no config — "wherever it lives is
  the plan dir". This is elegant but couples correctness to deployment location; the audit must test that.

## Tasks

### Phase 1: Baseline + Audit Infrastructure

- [x] ✅ **Task 1.1**: Create plan folder `00130-plan-scaffolding-script-distribution/`.
- [x] ✅ **Task 1.2**: Copy candidate `mkplan.bash` into the plan folder verbatim (audit baseline).
- [x] ✅ **Task 1.3**: Write this `PLAN.md` and add the plan to `CLAUDE/Plan/README.md`.

### Phase 2: Hostile Audit (iteration 1) — `AUDIT-v1.md`

- [x] ✅ **Task 2.1**: Static review — shellcheck **clean**; constructs bash-3.2/BSD-safe.
- [x] ✅ **Task 2.2**: Adversarial correctness audit — drift/bootstrap/gap guards verified; name
  normalisation robust. **C1 (CRITICAL)** found: concurrent runs make duplicate numbers.
- [x] ✅ **Task 2.3**: Portability audit — no `readlink -f` / GNU-only flags; `date +%F` POSIX. Pass.
- [x] ✅ **Task 2.4**: Daemon-integration audit — script avoids Write-tool double-increment by design;
  **M1** guidance-collision + **M2** `set`-vs-`max` divergence from Plan 00112 logged.
- [x] ✅ **Task 2.5**: Security audit — injection/traversal all rejected (no exec). **H1 (HIGH)**:
  reverse-symlink scaffolds plans in the wrong directory.
- [x] ✅ **Task 2.6**: `AUDIT-v1.md` written (1 CRITICAL, 3 HIGH, 4 MEDIUM, 4 LOW + passed list); committed.

### Phase 3: Refinement Iterations — `AUDIT-v2.md`

- [x] ✅ **Task 3.1**: v2 applied — C1 portable `mkdir` lock, H1 `MKPLAN_PLAN_DIR` override + contract
  docs, M2 high-water-mark counter, M3 friendly `mkdir` die, L4 softened drift wording. `AUDIT-v2.md`
  records the before/after. All script-side High/Medium findings closed.
- [x] ✅ **Task 3.2**: Re-ran full suite — **12-way concurrency now yields 12 distinct numbers**
  (was five `00001-*`); shellcheck clean; all v1 guards regression-pass.

### Phase 4: Distribution & Integration Design (proposal audit)

- [ ] ⬜ **Task 4.1**: Decide counter ownership contract (script vs daemon) and document it.
- [ ] ⬜ **Task 4.2**: Decide distribution mechanism (installer/upgrade deploy target, idempotency, exec bit).
- [ ] ⬜ **Task 4.3**: Decide agent-guidance surface (handler `get_claude_md()` text, docs) — without bloat.
- [ ] ⬜ **Task 4.4**: Record decisions in this PLAN under "Technical Decisions"; identify follow-up plans.

## Technical Decisions

<!-- Populated as the audit reaches conclusions. -->

## Success Criteria

- [ ] Candidate script captured as baseline and audited adversarially across all five lenses.
- [ ] All High/Medium audit findings either fixed in the script or explicitly accepted with rationale.
- [ ] A clear, evidence-backed recommendation on distribution + daemon-counter ownership.
- [ ] Every audit iteration committed (`AUDIT-vN.md` + script revision) for traceability.
- [ ] Script remains dual-audience (human-legible, agent-deterministic) after refinement.

## Risks & Mitigations

| Risk                                                        | Impact | Probability | Mitigation                                                      |
| ----------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------- |
| Script and daemon both increment the counter → numbers skip | High   | Med         | Phase 2.4 audit nails counter ownership before any distribution |
| Self-locating design breaks if deployed to the wrong dir    | Med    | Med         | Audit the `BASH_SOURCE` path + document the deployment contract |
| Portability bug (macOS/BSD) silently mis-scaffolds          | Med    | Low         | Phase 2.3 portability lens mirrors Plans 00122/00123 findings   |
| Scope creep into a plan-management CLI                      | Low    | Med         | Non-Goals fence the work to single-command scaffolding          |

## Notes & Updates

### 2026-06-19

- Plan scaffolded. Candidate `mkplan.bash` copied in verbatim as the audit baseline.
- Next: Phase 2 hostile audit → `AUDIT-v1.md`.
