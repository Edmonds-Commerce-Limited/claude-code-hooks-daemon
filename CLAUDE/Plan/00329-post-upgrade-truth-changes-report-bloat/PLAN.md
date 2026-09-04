# Plan 00329: post upgrade truth changes report bloat

**Status**: Not Started
**Created**: 2026-09-04
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

Step 4 of the upgrade flow tells the agent to reconcile the project's own
docs against `check-truth-changes`. The command's output is unbounded and
grows with every release, so in practice the step is skimmed rather than
performed — the report is too large to read, and an instruction that is not
read is not followed.

Measured on this repo at v3.61.0:

| Range                        | Output bytes | Entries |
| ---------------------------- | ------------ | ------- |
| v3.0.0 → v3.61.0 (full span) | 89,580       | 74      |
| v3.50.0 → v3.61.0 (a hop)    | 72,352       | 50      |

~22k tokens at the top end, delivered as inline command output: there is no
file offload, no size bound and no pagination. `--format {text,json}` is the
only lever and JSON is larger. Fifty entries is the cost of a routine
eleven-minor-version hop, and each one asks for a semantic search across four
doc trees (`CLAUDE/`, `docs/`, `README*`, `AGENTS*`).

Size is only half the defect. `install/truth_changes.py` has no supersession
logic — `load_truth_changes_between` then `format_truth_changes_for_llm`,
with no dedup, collapse, cap or truncation — so a fact whose truth changed
repeatedly is replayed once per change. The plan-creation truth appears three
times: v3.23.0 (`no bundled scaffolding script` → `run mkplan.bash`), v3.25.0
(`installer-deployed` → `deployed from config SSoT`), v3.26.0 (`config SSoT`
→ `opt-in, defaults to false`). Only the last is current. An agent following
the instruction literally asserts a claim into the project's docs, then
contradicts it, then contradicts it again. `## Notes & Updates` →
`## Delivery & Milestones` repeats the shape across v3.40.0 and v3.49.1.

So the output is a replay of history where the agent needs the current delta.
Collapsing superseded chains attacks the wrong work and the volume at once,
which bounding alone does not.

## Goals

- The post-upgrade reconciliation report is bounded in size, and its bound
  does not grow with the number of releases crossed.
- A truth that changed more than once across the range is surfaced ONCE, as
  its current value — never as the intermediate steps that reached it.
- No entry instructs the agent to assert a statement that a later entry in
  the same report contradicts.

## Non-Goals

- **Not** changing what a truth-change IS, or the `was`/`now` schema's
  meaning. The record of history stays complete on disk; this plan changes
  what is SURFACED for reconciliation.
- **Not** dropping entries to hit a size target. A truth the project still
  asserts must survive collapsing — the aim is removing superseded and
  redundant material, not sampling.
- **Not** rewriting the existing `truth-changes/*.yaml` corpus by hand to
  add whatever key Phase 1 chooses, unless Phase 1 concludes a backfill is
  the only way to make collapsing work.

## Tasks

### Phase 1: Decide the collapsing mechanism

- [ ] ⬜ **Task 1.1**: Determine how a superseding chain is identified.
  Semantic matching is not required if the schema can carry the answer — an
  optional `topic:` key with keep-latest-per-topic is deterministic and
  cheap. Record the decision and why the rejected options were rejected.
- [ ] ⬜ **Task 1.2**: Settle what happens to existing entries that carry no
  topic key. An un-keyed entry must not be dropped, and must not silently
  defeat collapsing for its neighbours.
- [ ] ⬜ **Task 1.3**: Measure how much of the current 74-entry corpus
  actually collapses. If the answer is small, bounding (Phase 2) is the
  primary fix and this phase is secondary — record that rather than assuming
  the reverse.

### Phase 2: Bound what remains

- [ ] ⬜ **Task 2.1**: Give the command a file-offload path: write the full
  report to a file, print a bounded summary plus that path. This is the
  idiom the project already uses elsewhere (`echd-capture`, and the
  `subagent_report_size_blocker` handler that exists to enforce exactly this
  for subagent reports).
- [ ] ⬜ **Task 2.2**: Make the upgrade skill's step 4 consume the bounded
  form, so the instruction the agent receives matches the report it gets.

### Phase 3: Prove it

- [ ] ⬜ **Task 3.1**: A test pinning that the full-span report stays under
  the chosen bound as the corpus grows — the regression that lets this
  defect return is a new release quietly adding entries.
- [ ] ⬜ **Task 3.2**: A test over the three known superseding chains
  (plan-creation across v3.23.0/v3.25.0/v3.26.0; Notes & Updates across
  v3.40.0/v3.49.1) asserting only the current truth is surfaced.

## Success Criteria

- [ ] The full-span report is bounded, and the bound holds when a new
  truth-change file is added.
- [ ] The plan-creation truth is surfaced once, as the v3.26.0 value.
- [ ] No reconciliation report contains an entry whose `now` is contradicted
  by another entry in the same report.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00329-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Milestone A — the mechanism is decided and its collapsing yield measured.
- Milestone B — the report is bounded and the skill consumes the bounded
  form.
