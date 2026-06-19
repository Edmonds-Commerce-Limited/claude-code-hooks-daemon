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

### Phase 4: Distribution & Integration Design (proposal audit) — `PROPOSAL-AUDIT.md`

- [x] ✅ **Task 4.1**: Counter-ownership contract documented — script mirrors the Python SSOT
  (`plan_numbering.py`); writes via bash so the daemon never double-increments; stricter drift guard.
- [x] ✅ **Task 4.2**: Distribution decided — deploy in `install/plan_workflow.py::bootstrap_plan_workflow`,
  overwrite-on-upgrade + exec bit; surfaced pre-existing hardcoded-`CLAUDE/Plan` SSOT bug to fix.
- [x] ✅ **Task 4.3**: Guidance decided — update `plan_number_helper.get_claude_md()` to name the script
  as canonical, counter-read as number-only fallback; no new handler; README left to the agent.
- [x] ✅ **Task 4.4**: Decisions recorded below + in `PROPOSAL-AUDIT.md`; follow-up implementation plan identified.

### Phase 5: Implementation (TDD)

- [x] ✅ **Task 5.1**: Bundle canonical `mkplan.bash` (audited v2, byte-identical) as package data at
  `src/claude_code_hooks_daemon/install/templates/mkplan.bash` (single source of truth); add
  `[tool.setuptools.package-data]` so wheel builds include it. shellcheck clean.
- [x] ✅ **Task 5.2**: RED — failing tests for installer deploy (`TestMkplanDeployment`: bundled-template
  exists, deploys, byte-identical, `0o755` exec bit, overwrite-on-upgrade, result flag, custom plan dir,
  idempotent) + handler guidance regression (`test_get_claude_md_names_mkplan_as_canonical`).
- [x] ✅ **Task 5.3**: GREEN — `bootstrap_plan_workflow(project_root, plan_dir_name="CLAUDE/Plan")` deploys
  `mkplan.bash` (overwrite + exec bit) and honours the configured plan dir (fixes the hardcoded-`CLAUDE/Plan`
  SSOT bug); `mkplan_template_path()` + `MKPLAN_SCRIPT_NAME` exported; `deployed_mkplan` result flag.
- [x] ✅ **Task 5.4**: GREEN — `plan_number_helper.get_claude_md()` names `mkplan.bash` canonical, counter-read
  demoted to number-only fallback; `<hooksdaemon>` block + `.claude/HOOKS-DAEMON.md` regenerated.
- [x] ✅ **Task 5.5**: Wire `install_version.sh` step 14 to pass `config.plan_workflow.directory`.
- [x] ✅ **Task 5.6**: Dogfood — `mkplan.bash` deployed to this repo's `CLAUDE/Plan/` via the real bootstrap.
- [x] ✅ **Task 5.7**: Live smoke test — deployed script scaffolds 00001/00002 in a throwaway repo, counter
  advances, spaces normalised, `PLAN.md` rendered. Daemon restart RUNNING. QA + release.

## Technical Decisions

### Decision 1: Counter ownership (script vs daemon)

**Context**: both the script and the daemon can advance `hooksdaemon.latestPlanNumber`; a double-increment
would skip numbers. **Decision**: the script writes the folder + `PLAN.md` with bash (`mkdir`/`cat`), NOT
the Write tool, so the daemon's plan-numbering path never fires — no double-increment (verified live: a
Write-tool `PLAN.md` bumped 129→130; the script's bash writes do not). The script mirrors the Python SSOT
in `handlers/utils/plan_numbering.py` exactly, with one safer divergence: it **refuses** on counter-behind-disk
drift where the daemon would blindly hand out `counter+1`.

### Decision 2: Distribution mechanism

**Decision**: deploy `mkplan.bash` from `install/plan_workflow.py::bootstrap_plan_workflow()` (the existing,
idempotent client-plan-dir bootstrap). Policy: **overwrite on every upgrade** + exec bit (daemon-owned tooling,
unlike skip-if-exists README/CLAUDE.md), so audit fixes reach existing installs. **Blocking sub-fix**: that
bootstrap hardcodes `CLAUDE/Plan` and must be threaded to honour `track_plans_in_project` (pre-existing SSOT bug).

### Decision 3: Agent guidance surface

**Decision**: one coherent message — update `plan_number_helper.get_claude_md()` so running the deployed
`mkplan.bash` is the canonical create-a-plan action and "read the counter + 1" is the number-only fallback;
no `ls`/scan, no second method, no new handler. README index updates stay with the agent (Edit tool), not the script.

## Success Criteria

- [x] ✅ Candidate script captured as baseline and audited adversarially across all five lenses.
- [x] ✅ All High/Medium audit findings either fixed in the script (C1, H1, M2, M3) or accepted with rationale (H2, H3, M1, M4, L1–L4).
- [x] ✅ A clear, evidence-backed recommendation on distribution + daemon-counter ownership (`PROPOSAL-AUDIT.md`).
- [x] ✅ Every audit iteration committed (`AUDIT-vN.md` + script revision) for traceability.
- [x] ✅ Script remains dual-audience (human-legible reminders/usage, agent-deterministic exit codes + stdout path).

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
- **Phase 2 (`AUDIT-v1.md`)**: hostile audit found 1 CRITICAL (concurrent runs → duplicate
  numbers, proven), 3 HIGH (reverse-symlink mis-location; no README update; unspecified
  distribution), 4 MEDIUM, 4 LOW. Name validation / drift / bootstrap / portability all robust.
- **Phase 3 (`AUDIT-v2.md`)**: refined to v2 — portable atomic-`mkdir` lock (C1), `MKPLAN_PLAN_DIR`
  override + contract docs (H1), high-water-mark counter (M2), friendly `mkdir` die (M3). Re-ran
  the suite: 12 concurrent runs → `00001`–`00012`, all distinct (was five `00001-*`); shellcheck clean.
- **Phase 4 (`PROPOSAL-AUDIT.md`)**: distribution/guidance decisions grounded in the real code —
  deploy via `bootstrap_plan_workflow` (overwrite-on-upgrade), fix its hardcoded-`CLAUDE/Plan` SSOT
  bug, name the script canonical in `plan_number_helper` guidance, leave README to the agent.
- **Audit remit COMPLETE.** The script is sound to distribute. Implementation (installer deploy +
  exec-bit + idempotency tests, guidance-text change, `track_plans_in_project` SSOT fix) is a
  separate TDD plan — see "Next steps" below.

### Next steps (follow-up implementation plan)

- Wire deploy into `install/plan_workflow.py` (overwrite + `0o755`) honouring `track_plans_in_project`.
- Update `plan_number_helper.get_claude_md()` + regenerate the `<hooksdaemon>` block.
- TDD: installer deploy/idempotency test; handler guidance-text regression test; H-1/QA pass; release.
