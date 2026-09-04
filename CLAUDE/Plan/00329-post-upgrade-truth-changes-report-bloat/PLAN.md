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

`check-truth-changes` is the measured source, NOT established as the only one
(owner, 2026-09-04). `check-config-migrations` adds 19,400 bytes over the same
range, taking one hop past 91KB before counting the upgrade script's own
stdout, the post-upgrade-tasks, the `/hooks-daemon optimise` step or the
regenerated `CLAUDE.md`. Phase 0 measures the whole envelope through a canary
upgrade rather than assuming this plan's first measurement found all of it.

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

### Phase 0: Measure the whole post-upgrade envelope

- [ ] ⬜ **Task 0.1**: Run a canary upgrade across a wide version span and
  measure EVERY artefact the project agent receives, not just
  `check-truth-changes`: `check-config-migrations`, the upgrade script's
  stdout, `post-upgrade-tasks/`, the `optimise` step and the regenerated
  `CLAUDE.md`. Record a per-source byte table. The client install under
  `untracked/repos/` is a starting point for the canary.
- [ ] ⬜ **Task 0.2**: Establish what Claude Code actually does with an
  oversized tool result — truncation, elision, or delivery-in-full that the
  agent then skims. The remedy differs: truncation silently DROPS
  instructions, whereas skimming merely deprioritises them. Do not design
  against an assumed mechanism.

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

### Phase 3: Chunk the remainder, and parallelise it safely

- [ ] ⬜ **Task 3.1**: Emit the reconciliation work as CHUNKS the upgrade
  agent can delegate one-per-subagent, so no single context has to hold the
  whole report. Each subagent returns what it CHANGED, not the entries it
  read — otherwise the coordinator re-accumulates the bloat the chunking
  removed.
- [ ] ⬜ **Task 3.2**: Chunk by TOPIC, not by size, and only AFTER Phase 1
  collapsing. Ordering is load-bearing: while superseded chains survive, two
  chunks can carry contradictory instructions about the same document. One
  agent reading sequentially lands on the current truth because the later
  entry overwrites the earlier; N agents in parallel race for the same file
  and the winner is arbitrary. Chunking an uncollapsed report converts a
  self-correcting sequence into a non-deterministic one.
- [ ] ⬜ **Task 3.3**: Confirm topic chunks are DISJOINT in the documents
  they touch. Disjointness is what makes parallel dispatch safe; if two
  topics can edit one file, they belong in the same chunk.

### Phase 4: Prove it

- [ ] ⬜ **Task 4.1**: A test pinning that the full-span report stays under
  the chosen bound as the corpus grows — the regression that lets this
  defect return is a new release quietly adding entries.
- [ ] ⬜ **Task 4.2**: A test over the three known superseding chains
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

- Milestone A — the whole post-upgrade envelope is measured, per source, so
  the fix targets what is actually large rather than the first thing found.
- Milestone B — the mechanism is decided and its collapsing yield measured.
- Milestone C — the report is bounded and the skill consumes the bounded
  form.
- Milestone D — the remainder is chunked by topic and safely parallelisable.
