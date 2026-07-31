# Plan 00190: PLAN-vs-JOURNAL Separation & Tiered Plan Size Enforcement

**Status**: In Progress
**Created**: 2026-07-31
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Agents conflate `PLAN.md` with `JOURNAL/`. They append narrative progress into the
plan instead of the journal, so plans grow monotonically and are never curated
until they are too expensive to read and too tangled to trust.

The root cause is **rule-bleed between two near-opposite rule-sets**, and it runs
in both directions. Journal rules applied to a plan produce an append-only,
ever-growing plan. Plan rules applied to a journal invite an agent to "tidy" an
append-only log and destroy the record. Both are reachable today.

This plan makes both contracts explicit, symmetric and enforced: tiered size
enforcement on plan documents only, a single file classifier so neither rule-set
can leak, and consistent guidance across every touch point. It reuses the existing
`plan_qa` surfaces rather than adding a parallel mechanism.

## Context & Background

### The contract — two axes, both directions

| Axis                 | `JOURNAL/*.md`                            | plan documents (`PLAN.md`, …)  |
| -------------------- | ----------------------------------------- | ------------------------------ |
| **Write**            | append-only, never rewritten              | freely rewritten / curated     |
| **Growth**           | unbounded **by design**                   | bounded — lean, surgical       |
| **Size enforcement** | **never** size-limited                    | tiered advise → warn → block   |
| **History lives in** | the file itself                           | **git**, not the file body     |
| **Read**             | **never whole** — grep / tail / sub-agent | **read in full** for grounding |

The axes are causally linked, which makes both rules self-justifying: `PLAN.md`
must stay lean **because** it is read in full every session — its size limit is
*derived from its read cost*; `JOURNAL/` may grow forever **because** it is never
read whole.

### Evidence

Measured across all 183 PLAN.md with `git log --numstat --follow`: median
`del/add` **0.077**, mean 0.113, and **15.8% have never deleted a single line**.
PLAN.md editing is ~92% additive — these files are appended to, not curated. Raw
size is a *lagging* indicator; `del/add` is the *leading* one.

The existing plan-QA sweep returns only 2 advisory findings over the whole tree
(`staleness-nag`, `journal-freshness`). **No check measures size, growth or
curation**, so the drift is not merely unenforced — it is invisible to the tooling
that exists to catch plan rot.

Journalling **amputates the tail rather than shrinking the median**: mature plans
with a `JOURNAL/` sit at median 16.6 KB vs 17.3 KB without (indistinguishable),
but p90 23.4 vs 36.4 KB, max 25.8 vs 57.2 KB, and zero journal-era plans exceed
35 KB. A plan's irreducible content is ~10-20 KB and journalling neither can nor
should touch it. Size enforcement and journalling are complementary.

### Two hazards the design must guard against

1. **Delete-instead-of-relocate.** "Your plan is too big" invites deletion.
   Messages must name `JOURNAL/` as the destination and state that it grows freely.
2. **Scope-dependent signals.** Dated headings and pasted logs are *correct*
   journal content, and only a defect signal in a plan document.

## Goals

- State both contracts symmetrically in **one** place; thin pointers elsewhere.
- Guarantee **file-scope demarcation** via a single SSoT classifier — neither
  rule-set can leak onto the other file type.
- Enforce **tiered size limits on plan documents only**, at read-cost thresholds.
- Make remediation unambiguous: **relocate** narrative, or **split** an
  over-scoped plan — never delete.
- Establish the **read contract**, recommending only handler-permitted mechanisms.

## Non-Goals

- **No retroactive rewriting of existing plans** — grandfathered, not bulk-edited.
- **No size, staleness or curation pressure on journals** — ever.
- **No new parallel enforcement mechanism**; work through the `plan_qa` catalogue.
- **No read-time journal advisory handler** (see Decision 3).
- No change to plan numbering/archival invariants (owned by Plan 00144).

## Technical Decisions

### Decision 1: Tiers are wording, not new machinery

`Level` stays two-valued. Tier 1 → ADVISE, tier 2 → ADVISE with escalated wording,
tier 3 → BLOCK. A check may already emit different levels per finding
(`stats_recount.py` does). A third `Level` member would break `report.py:46-47`,
whose header count knows only BLOCK and ADVISE.

### Decision 2: Thresholds derived from read cost, not percentiles

Canonical unit is **tokens**; bytes/lines are the runtime proxy (measured density
3.97 B/token). Rule shape `bytes > B OR lines > L` — both axes are needed.

| Tier     | bytes   | lines | ~tokens | corpus hit   |
| -------- | ------- | ----- | ------- | ------------ |
| advisory | >18,000 | >350  | ~4,500  | 31/183 (17%) |
| warning  | >25,000 | >500  | ~6,300  | 20/183 (11%) |
| block    | >35,000 | >900  | ~8,800  | 6/183 (3.3%) |

Percentiles describe *this* repo and would be meaningless in a client project with
100 KB plans; read cost extrapolates. Independent anchor: `src/**/*.py` median is
761 tokens, p95 4,643. A plan is grounding, not the work, so it should cost no
more than the source it describes. Resident context is already ~42,500 tokens
(21%) before any read, so tiers are calibrated against the ~123,500-token real
working budget.

Block requires an escape hatch (`MUST_EXCEED_PLAN_SIZE_BECAUSE="reason"`), and
**shrinking edits are never blocked** — otherwise an oversized plan can never be
refactored down.

### Decision 3: No read-time journal advisory handler

An `ALLOW`-with-context advisory does not prevent a context flood — the journal is
read anyway and the advisory tokens are paid on top. Documentation plus the size
check's own remediation reaches the agent at the moment of relevance for free.
Revisit only with measured data.

### Decision 4: The block message must name TWO remedies

Only one of the six worst offenders is a journalling failure (00101 collapses
45.2 KB → 9.5 KB once dated incident blocks move out). The other five are
**over-scoped, not journal-polluted** — after perfect curation 00100 is still
45.8 KB because its task tree alone is 28.5 KB. So the message must offer
*relocate to `JOURNAL/`* **or** *split the plan*. Naming only the first to a
00100-class plan leaves deleting genuine task content as the only lever.

### Decision 5: Scope predicates are config-independent

Journal exemptions key on the day-file **grammar**, never on journal config.
Using the config-dependent predicate would let `journal.enabled: false` silently
re-enable plan rules on every journal file.

## Tasks

### Phase 0: Live dogfooding fixes

- [x] ✅ **Task 0.1**: `plan_time_estimates` fired on journal day-files — fixed,
  QA 13/13, daemon verified, live probe confirms (commit `0e1048d5`)
- [ ] ⬜ **Task 0.2**: `recovery_cron_advisor` instructs recording the cron ID in
  `## Notes & Updates` (4 sites: `:145`, `:444`, `:445`, `:89-93`/`:213-214`)
- [ ] ⬜ **Task 0.3**: `journal.mode: block` is silently subordinate to
  `edit_mode` — the documented promise is conditionally false; fix docs
- [ ] ⬜ **Task 0.4**: `mkplan.bash:318-322` fallback writes `## Notes & Updates`
- [ ] ⬜ **Task 0.5**: `plan_time_estimates` block reason names the wrong handler
  in its "To disable" hint
- [ ] ⬜ **Task 0.6**: `journal-append-only` remediation never says the journal is
  *supposed* to grow — the precise bleed vector once size nags exist

### Phase 1: Research & Design

- [x] ✅ **Task 1.1**: Empirical churn evidence established
- [x] ✅ **Task 1.2**: Five-agent research fan-out
- [x] ✅ **Task 1.3**: Design fixed (Decisions 1-5)

### Phase 2: Scope Demarcation

- [ ] ⬜ **Task 2.1**: `plan_qa/paths.py` — `PlanFileKind` + `classify()` SSoT,
  testing `JOURNAL/` containment BEFORE the `PLAN.md` filename test so
  dual classification is structurally impossible
- [ ] ⬜ **Task 2.2**: Reimplement `edit_target()`/`journal_edit_target()` as thin
  adapters; fix `JOURNAL/PLAN.md` classifying as both
- [ ] ⬜ **Task 2.3**: Reconcile the two disagreeing "journal file" definitions
- [ ] ⬜ **Task 2.4**: Regression tests asserting no rule crosses the boundary

### Phase 3: Tiered Size Enforcement

- [ ] ⬜ **Task 3.1**: TDD the size check, plan documents only
- [ ] ⬜ **Task 3.2**: `plan_workflow.qa.plan_doc_size` config with named
  constants and monotonicity validation
- [ ] ⬜ **Task 3.3**: Two-remedy messaging; escape hatch; shrink exemption
- [ ] ⬜ **Task 3.4**: Rule the scope of `CLAUDE/Plan/README.md` (34,002 tokens —
  it would block instantly) and of the 107 supporting docs
- [ ] ⬜ **Task 3.5**: `plan-shrink-without-journal` commit-stage guard against
  delete-instead-of-relocate

### Phase 4: Documentation Consistency

- [ ] ⬜ **Task 4.1**: SSoT contract in `CLAUDE/PlanJournalling.md`; one-line
  pointers elsewhere
- [ ] ⬜ **Task 4.2**: `docs/PLAN_SYSTEM.md` — remove the template section and
  three worked examples that teach dated logs inside PLAN.md
- [ ] ⬜ **Task 4.3**: `CLAUDE/PlanWorkflow.md` — qualify 8 progress-log lines
- [ ] ⬜ **Task 4.4**: Implement `plan_workflow.get_claude_md()` (currently None,
  highest-leverage injection point)
- [ ] ⬜ **Task 4.5**: `pipe_blocker.get_claude_md()` — state that unpiped
  `tail -n N <file>` is unrestricted

### Phase 5: Verification & Release

- [ ] ⬜ **Task 5.1**: Full QA; daemon restart RUNNING
- [ ] ⬜ **Task 5.2**: Dogfood — this plan stays under the advisory tier
- [ ] ⬜ **Task 5.3**: config-changes + truth-changes + post-upgrade-task manifests

## Dependencies

- Related: Plan 00144 (Plan QA System) — owns the check catalogue and surfaces
- Related: Plan 00163 (Plan Journalling) — owns `JOURNAL/` and its checks

## Success Criteria

- [ ] Both contracts stated symmetrically in one authoritative location
- [ ] One classifier; no check applies to both plan documents and journal files
- [ ] Journals provably exempt from every size and curation rule
- [ ] Plan documents advise, then warn, then block, with an escape hatch
- [ ] Every message names relocate-or-split; none recommends a blocked command
- [ ] Full QA passes; daemon restarts RUNNING

## Risks & Mitigations

| Risk                                         | Impact | Mitigation                                             |
| -------------------------------------------- | ------ | ------------------------------------------------------ |
| Existing oversized plans become uneditable   | High   | Exempt shrinking edits; grandfather; escape hatch      |
| Agent deletes narrative instead of moving it | High   | Two-remedy messages + commit-stage shrink guard        |
| Scope-predicate drift re-opens the bleed     | High   | Single classifier + test asserting all consumers agree |
| Worktree edits resolve the wrong repo        | High   | Resolve git repo from the file's own path              |
| Advisory nags on every edit                  | Medium | Rate-limit in the handler, keyed on `transcript_path`  |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00190-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan scaffolded, indexed, research fan-out dispatched — `62c75f65`
- Phase 0 Task 0.1: journal rule-bleed fix (found by the bug blocking its own
  documentation) — `0e1048d5`
