# Plan 00216: plan duplicate detection

**Status**: In Progress
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Nothing in the plan system warns an author that an existing plan already
covers the same ground. `plan_qa` enforces number collisions, index/folder
bijection, statistics recount and status coherence — all *structural* — and is
blind to two plans being about the same thing.

The cost is not hypothetical. Plan 00213 was filed for a `planlib` proposal
that Plan 00199 had already covered five days earlier. A human noticed; no
tooling did. By then an evaluation agent had spent a large amount of context
re-deriving an assessment that 00199 already held.

This is the DBF case (Core Standard 15): the duplicate plan is the symptom,
and the bug is the guard that could not see it. Filing more carefully is not a
fix — the next author has the same blind spot, and at 215 folders, reading the
tree before filing is not a realistic precaution.

**Phase 1 measured the originally-proposed remedy and killed it.** See
[PHASE-1-MEASUREMENT.md](PHASE-1-MEASUREMENT.md). A deterministic
citation-matching rule cannot see what made 00199 and 00213 duplicates,
because that was semantic, not literal. The remedy for a semantic duplicate is
a semantic reader.

## Goals

- Ship a **specialist dedupe sub-agent** that reads the titles and overviews of
  still-live plans and reports candidates that already cover the proposed work
- **Suggest** its use at plan-creation time — from `mkplan.bash` output and the
  plan-workflow handler guidance — without mandating or blocking
- Deploy it to client projects through the existing plan-workflow asset path,
  so it arrives with the rest of the plan tooling rather than needing setup

## Non-Goals

- No deterministic citation-matching check. Phase 1 measured it: the reliable
  GitHub-issue spelling finds zero pairs here and would have missed the
  motivating case; the loose spelling is 34/35 false positives; the
  supporting-document signal is dominated by project-wide filenames.
- No blocking. Two plans legitimately covering adjacent ground is normal, and a
  non-deterministic reader must never be able to stop work.
- No retrospective de-duplication of the existing tree.

## Technical Decisions

### Decision 1: semantic reader, not a citation rule

**Context**: the plan was filed assuming a shared literal citation would
identify duplicates.

**Options considered**:

1. Match GitHub issue citations — precise, but **zero** pairs in this tree and
   it does not fire on the motivating case, which cites no issue.
2. Match supporting-document filenames — fires, but every live hit is noise
   (`HOOKS-DAEMON.md`, `RELEASING.md`, the `YY-MM-DD.md` template placeholder)
   or a *correct* prior-art citation.
3. A specialist sub-agent reading titles and overviews.

**Decision**: option 3. Measured evidence in
[PHASE-1-MEASUREMENT.md](PHASE-1-MEASUREMENT.md). The duplication was
semantic — both plans were about "planlib tooling in the daemon" — and no
literal signal separates that from two unrelated plans that each happen to
carry a `PROPOSAL.md`.

**Consequence accepted**: the check is non-deterministic and therefore cannot
be QA-gated the way `plan_qa` rules are. It is advisory by construction.

### Decision 2: a deployed agent definition, daemon-owned

**Context**: the daemon deploys skills to `.claude/skills/` and plan tooling to
the plan directory, but has never deployed an agent definition.

**Decision**: deploy `.claude/agents/` as a new asset surface, daemon-owned
(refreshed on every deploy) like `mkplan.bash` and the skills — the file
encodes a procedure, not user content, so fixes must reach the field. Gated on
`plan_workflow.enabled`, so a project without the plan workflow gets nothing.

## Tasks

### Phase 1: Establish the signal against real data

- [x] ✅ **Task 1.1**: Enumerate what plans actually cite
- [x] ✅ **Task 1.2**: Run the candidate rules over the whole tree and inspect
  every hit by hand
- [x] ✅ **Task 1.3**: Confirm against the 00199/00213 pair and record the
  measured false-positive rate — recorded in `PHASE-1-MEASUREMENT.md`

### Phase 2: The specialist agent

- [x] ✅ **Task 2.1**: Write the agent definition — Haiku, read-only tools,
  focused on reporting candidates with reasons rather than a verdict
- [x] ✅ **Task 2.2**: TDD the deployment into `.claude/agents/`, gated on
  `plan_workflow.enabled`
- [x] ✅ **Task 2.3**: Namespace the agent `hooks-daemon-` and carry an
  ownership banner — `.claude/agents/` is a FLAT client-owned namespace where a
  collision silently drops one definition rather than erroring
- [x] ✅ **Task 2.4**: Register it in `CLIENT_OWNED_ASSETS` so the Plan 00217
  default-clean guard covers it — this is the first MARKDOWN asset, so the
  guard gained a markdown check in the same change (a language the guard
  cannot lint passes by omission)

### Phase 3: Suggest it where plans are created

- [x] ✅ **Task 3.1**: `mkplan.bash` suggests the check in its next-steps output
- [x] ✅ **Task 3.2**: Plan-workflow handler guidance names it
- [x] ✅ **Task 3.3**: Asset checker notices when it is missing

### Phase 4: Verify

- [x] ✅ **Task 4.1**: Full QA suite passes
- [x] ✅ **Task 4.2**: Client-mode verification — this changes deployed assets,
  which self-install mode does not represent. Proven in a real client install:
  correct path and mode, byte-identical, frontmatter intact, a client agent
  literally named `plan-dedupe-scout` left untouched beside it, and a tampered
  daemon-owned copy refreshed
- [x] ✅ **Task 4.3**: Dogfood it against this tree — one true negative and one
  true positive on un-built work, both correct
- [x] ✅ **Task 4.4**: Re-dogfooded under REAL dispatch. The pathological case
  is FIXED — it now names Plan 00216 by number instead of answering "already
  shipped, no additional work required". The true-positive control still names
  Plan 00205. The inline harness was indeed the confound
- [x] ✅ **Task 4.5**: Verify the OUTPUT FORMAT contract under real dispatch.
  Task 4.4 exposed what the harness had masked: the finding is correct and the
  plan number is named, but the report is flattened into one sentence and the
  `Overlap:`/`Relationship:` lines are dropped. `Relationship` is the field
  that matters most — "merge" and "supersede" are opposite actions and it is
  the only thing that says which applies. The definition now states the format
  Fixed by hoisting the contract to the TOP of the definition and cutting it
  to the three fields a caller cannot recover for themselves. Restating it as
  "mandatory" further down did nothing — three dispatches dropped the
  checked-count, which predated that wording, so position beat emphasis
- [ ] ⬜ **Task 4.6**: Investigate COVERAGE variance. With the count now
  reported it is visible, and it moves: 34, then 32, then 17 live plans across
  runs against an unchanged tree of 34. A half-read "no duplicates" is
  indistinguishable from a thorough one without the count, which is the
  argument for having required it — but 50% coverage is worse than
  "non-deterministic" was meant to license. Likely remedy: have the procedure
  enumerate the plan folders FIRST and check the total it reports against that
  list, rather than reading until it feels done

## Success Criteria

- [x] The agent names an existing live plan from a description that shares
  almost no vocabulary with it — verified against Plan 00205 (the original
  criterion named 00199/00213, which have since both been archived; the scout
  reads only live plans by design, so that pair is no longer a valid probe)
- [x] It reports nothing, and says how many plans it checked, when the proposal
  is genuinely novel
- [x] It is suggested at creation time and blocks nothing
- [x] It deploys to a real client install, verified in client mode
- [x] Full QA passes
- [x] It does not answer "is this already implemented?" when the proposed work
  happens to exist in the source tree — verified under real dispatch
- [x] Its report states how many plans it checked, so a clean result is
  verifiable rather than merely reassuring
- [ ] The number it reports matches the number of live plans on disk
  (Task 4.6) — currently varies 17–34 against a tree of 34

## Dependencies

- Related: Plan 00213 / Plan 00199 — the duplication that motivated this.
- Related: Plan 00214, whose measure-before-blocking method Phase 1 followed.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00216-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Gap identified while reconciling the 00199/00213 duplication
- Phase 1 measurement killed the originally-proposed deterministic remedy
