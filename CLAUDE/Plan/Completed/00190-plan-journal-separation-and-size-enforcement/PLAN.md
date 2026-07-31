# Plan 00190: PLAN-vs-JOURNAL Separation & Tiered Plan Size Enforcement

**Status**: Complete
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

- [x] ✅ **Task 0.1**: `plan_time_estimates` fired on journal day-files — fixed;
  live probe confirms journal allowed / PLAN.md denied (`0e1048d5`)
- [x] ✅ **Task 0.2**: `recovery_cron_advisor` instructed recording the cron ID in
  `## Notes & Updates` — 4 sites fixed; `CLAUDE.md`'s generated block verified
  clean after restart (`544f67ea`)
- [x] ✅ **Task 0.6**: `journal-append-only` remediation now states the journal is
  unbounded by design and must not be tidied — a prerequisite for the size
  tiers, not a follow-up (`a114d270`)
- [x] ✅ **Task 0.3**: `journal.mode: block` documented as a ceiling subordinate
  to the surface mode — behaviour was correct, docs were wrong; two regression
  tests now pin the real semantics (`f6e5ccaa`)
- [x] ✅ **Task 0.4**: `mkplan.bash` fallback now emits the `Delivery & Milestones` stub instead of pre-seeding the retired section; both copies
  resynced and verified identical (`0c1a78d8`)
- [x] ✅ **Task 0.5**: `core/chain.py` attributed the "To disable" footer to the
  FIRST denying handler while displaying a LATER handler's reason. Exact
  trigger, once traced: a non-terminal deny followed by a **terminal** deny —
  the terminal branch replaces `final_result` but left `decided_by` behind, so
  the footer named the wrong config key. Fixed by making attribution follow the
  result actually displayed; the Plan 00144 semantics (a laxer terminal result
  never washes out an earlier deny) are preserved and now pinned by a test
- [x] ✅ **Task 0.7**: `background_process_tracker` false-positived on literal
  `&` and on backgrounding keywords appearing in prose — same defect class as
  0.1 (matching without structural context). Fixed by masking literal spans,
  asymmetrically and following bash semantics: a **heredoc body** is stdin data
  the outer shell never executes, so it is masked for both the keyword and the
  `&` test; a **quoted span** may be a command for a nested interpreter
  (`bash -c "nohup worker"`), so it is masked only for the `&` test. Verified
  12/12 against the live daemon. Residual, accepted: a keyword inside a short
  `-m` quoted message still matches

### Phase 1: Research & Design

- [x] ✅ **Task 1.1**: Empirical churn evidence established
- [x] ✅ **Task 1.2**: Five-agent research fan-out
- [x] ✅ **Task 1.3**: Design fixed (Decisions 1-5)

### Phase 2: Scope Demarcation

- [x] ✅ **Task 2.1**: `plan_qa/paths.py` — `PlanFileKind` + `classify()` SSoT,
  testing `JOURNAL/` containment BEFORE the `PLAN.md` filename test so
  dual classification is structurally impossible. `PLAN_INDEX` is a distinct
  kind (the index is 132,938 B and grows one row per plan by design)
- [x] ✅ **Task 2.2**: `edit_target()`/`journal_edit_target()` reimplemented as
  thin adapters; `JOURNAL/PLAN.md` no longer classifies as both
- [x] ✅ **Task 2.3**: Reconciled the disagreeing definitions behind
  `is_journal_file()` — journal territory is decided by LOCATION as well as
  day-file grammar, closing a real bleed where a mis-named file inside
  `JOURNAL/` still received plan rules (`plan_time_estimates`) or was
  silently rewritten (`markdown_table_formatter`)
- [x] ✅ **Task 2.4**: Regression tests — no path resolves to both targets;
  `classify()` and `is_journal_file()` asserted to agree on every sample

### Phase 3: Tiered Size Enforcement

- [x] ✅ **Task 3.1**: `plan-doc-size` check, plan documents only; tiers
  advisory/warning/block as ADVISE/ADVISE/BLOCK per Decision 1
- [x] ✅ **Task 3.2**: `plan_workflow.qa.plan_doc_size` config with named
  constants and a FAIL-FAST monotonicity validator (non-monotonic tiers
  silently disable a tier, which is worse than a startup error)
- [x] ✅ **Task 3.3**: Two-remedy messaging that explicitly rules out deletion;
  in-content escape hatch `MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason>` (a Write
  carries no shell command to prefix, and the reason then survives review);
  shrinking edits never penalised. Messages cite only the axis actually
  breached — naming both when one is under misstates the facts. **Only an edit
  that GROWS the file can block**: measuring the corpus showed 6 plans over the
  block tier, 2 of them active, and a same-size edit (ticking a checkbox) would
  have denied them — closing the risk register's top item without allowlists
- [x] ✅ **Task 3.4**: Scope ruled — the size rule applies to `PLAN.md` ONLY.
  `PLAN_INDEX` (measured at 132,938 B / 1,101 lines, and unbounded by design
  since it grows a row per plan) and supporting docs are exempt by
  construction via the Phase 2 classifier, not by a maintained list
- [x] ✅ **Task 3.5**: `plan-shrink-without-journal` commit-stage guard —
  a PLAN.md losing ≥2,000 bytes with no staged journal entry is the signature
  of delete-instead-of-relocate. Advisory, since a genuine curation pass is
  legitimate; the point is to make the agent notice which it just did

### Phase 4: Documentation Consistency

- [x] ✅ **Task 4.1**: SSoT two-axis contract table in
  `CLAUDE/PlanJournalling.md` (+ the deployed install template, kept in sync),
  including the read contract, the causal justification, and the size tiers
- [x] ✅ **Task 4.2**: `docs/PLAN_SYSTEM.md` — template and all four worked
  examples rewritten. They taught THREE daemon-blocked patterns: dated
  `## Notes & Updates` logs, `**Estimated Effort**`, and `## Timeline` target
  dates. Added a `PLAN.md vs JOURNAL/` core-concept section
- [x] ✅ **Task 4.3**: `CLAUDE/PlanWorkflow.md` — removed the `## Timeline`
  template section and three `Estimated Effort` header lines (all blocked by
  `plan_time_estimates`); requalified the progress-log lines to say edit
  PLAN.md in place and append narrative to `JOURNAL/`
- [x] ✅ **Task 4.4**: `plan_workflow.get_claude_md()` implemented — it
  returned None, so the contract was stated nowhere an agent reads by default
- [x] ✅ **Task 4.5**: `pipe_blocker.get_claude_md()` — states that only PIPES
  are restricted and `tail -n N <file>` / `grep pattern <file>` take the path
  as an argument, so the read contract is actionable
- [x] ✅ **Task 4.6** *(added)*: `plan_qa_edit` and `plan_qa_commit_gate`
  `get_claude_md()` document the two new checks — a blocking rule that is not
  in resident guidance is the exact failure this plan exists to prevent

### Phase 5: Verification & Release

- [x] ✅ **Task 5.1**: Full QA 13/13 (10,718 tests, 95.2% coverage); daemon
  restart verified RUNNING after every change; all enforcement verified against
  the LIVE daemon through the production hook wrappers, not just unit tests
- [x] ✅ **Task 5.2**: Dogfood — this plan is 15,058 B / 279 lines, under the
  18,000 / 350 advisory tier, with an unbounded journal beside it. Corpus
  measured: 6/187 plans over the block tier, and the growth-gating rule was
  live-tested against the real 57 KB plan 00100 (tick-a-box allowed, shrink
  silent, growth denied)
- [x] ✅ **Task 5.3**: `UNRELEASED/` manifests staged — config-changes
  (the new `plan_doc_size` block and the on-by-default enforcement),
  truth-changes (4 `was → now` pairs), and a `recommended`-severity
  post-upgrade task that audits a client's plan tree against the tiers before
  the block bites

## Dependencies

- Related: Plan 00144 (Plan QA System) — owns the check catalogue and surfaces
- Related: Plan 00163 (Plan Journalling) — owns `JOURNAL/` and its checks

## Success Criteria

- [x] Both contracts stated symmetrically in one authoritative location
  (`CLAUDE/PlanJournalling.md`, two-axis table; everything else points at it)
- [x] One classifier; no check applies to both plan documents and journal files
  (pinned by a test asserting no path resolves to both targets)
- [x] Journals provably exempt from every size and curation rule
  (live-verified: a 500 KB journal day-file is silent)
- [x] Plan documents advise, then warn, then block, with an escape hatch
- [x] Every message names relocate-or-split; none recommends a blocked command
  (asserted by test: no message contains "delete" or "trim")
- [x] Full QA passes; daemon restarts RUNNING

## Risks & Mitigations

| Risk                                         | Impact | Mitigation                                             |
| -------------------------------------------- | ------ | ------------------------------------------------------ |
| Existing oversized plans become uneditable   | High   | CLOSED: only a GROWING edit can block (see Task 3.3)   |
| Agent deletes narrative instead of moving it | High   | Two-remedy messages + commit-stage shrink guard        |
| Scope-predicate drift re-opens the bleed     | High   | Single classifier + test asserting all consumers agree |
| Worktree edits resolve the wrong repo        | High   | Resolve git repo from the file's own path              |
| Advisory nags on every edit                  | Medium | Rate-limit in the handler, keyed on `transcript_path`  |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00190-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan scaffolded; research fan-out — `62c75f65`
- Phase 0 rule-bleed fixes (0.1, 0.2, 0.6, 0.4, 0.3) — `0e1048d5`, `544f67ea`,
  `a114d270`, `0c1a78d8`, `f6e5ccaa`
- **Released v3.49.1 "The PLAN-vs-JOURNAL Contract"** — `f5f01974`, tag
  `0df2fcc5` (contract + Phase 0 fixes; no thresholds yet)
- Task 0.7: quote/heredoc-aware backgrounding detection — `92341a47`,
  `f4d708f9`
- Phase 2: one `PlanFileKind` classifier, then journal exemption by LOCATION —
  `295a8476`, `26742b8d`
- Phase 3: tiered `plan-doc-size` + shrink guard — `95c28cc6`, `3e03516e`
- Phase 4: docs stopped teaching the anti-pattern — `b1b089d9`
- Task 0.5 + Phase 5 completion and release manifests — this commit

Open follow-up (not blocking): RELEASING.md Step 13's `git add` list omits
handler sources, so a Step 11 guidance fix can be left uncommitted while its
regenerated CLAUDE.md is auto-committed. Documented in Step 13 during v3.49.1.
