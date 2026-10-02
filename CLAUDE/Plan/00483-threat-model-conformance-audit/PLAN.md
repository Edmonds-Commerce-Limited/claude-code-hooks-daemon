# Plan 00483: threat model conformance audit

**Status**: Not Started
**Created**: 2026-10-02
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner ruled that the daemon is guardrails, not armour. It helps a careless agent, and it
does not defend against a hostile one, which can simply stop the daemon. The ruling is written
down in
[ARCHITECTURE.md § Threat model](../../ARCHITECTURE.md#threat-model-the-agent-is-careless-not-hostile).
It was reviewed in
[261002-threat-model-review-fable.md](../00474-niggles-ledger-seventeen/subagent-reports/261002-threat-model-review-fable.md).
The README carries a short "Guardrails, not armour" section.

The ruling came after many rounds of work went into chasing obfuscated shapes. One example
is the dropped N53 branch, which spent 9+ review rounds on a shell walker for commits assembled
from text. Much of the open backlog may be the same kind of work. This plan checks everything
the project does against the ruling, then acts on the result:

- the guards;
- the open ledger entries;
- the corpus of uncovered commands;
- the review routines.

The test it applies is the section's two-part criterion. A shape is out of scope when its
operative text is not visible to the daemon at call time, or when it has no working purpose
other than defeating a parser. Everything else, every ordinary respelling included, is in scope.

## Goals

- Every open ledger entry and corpus row is classified as an in-scope defect or as
  `Dismissed (threat model)`, with the shape named.
- Every dismissal that is a command has a `UNCOVERED-accepted` row in
  `scripts/qa/dangerous-invocation-corpus.yaml`, so it is not raised again.
- Every blocking guard has a recorded verdict:
  - conforms;
  - has an in-scope gap (filed as a defect);
  - causes an in-scope false positive while catching an out-of-scope shape (filed to narrow);
  - holds code serving only out-of-scope shapes (listed for the owner).
- The in-scope defects found are fixed through the ledger, in small batches.

## Non-Goals

- Weakening anything the section lists under "What this ruling does not change":
  - fail-closed verdicts on what a guard cannot read;
  - no escape hatch an agent can type;
  - human-gated release and upgrade approval;
  - protection of a protected file against ordinary reads.
- Removing existing guard code on a reviewer's say-so. Removal is an owner decision, taken
  from the Phase 1 list.
- Defending against prompt injection beyond what the shape test already covers, unless the
  owner rules otherwise (open question 1).

## Tasks

### Phase 1: Inventory the guards

- [ ] ⬜ **Task 1.1**: List every blocking PreToolUse handler. For each, record what it matches
  and the shapes its parsing handles, from the code rather than its docs. Start with the
  guards that parse shell:
  - `secret_file_guard`, `quarantine_artefact_read_guard`, `flaggable_content_channel_guard`;
  - `sensitive_content` and the commit gates;
  - `destructive_git`, `git_stash`, `sed_blocker`, `pipe_blocker`;
  - the plan-folder `mkdir` guard, `project_containment`, `upgrade_approval_guard`.
- [ ] ⬜ **Task 1.2**: For each guard, classify each parsing branch as in-scope or out-of-scope
  under the two-part test. Mark every out-of-scope branch that causes an in-scope false
  positive, with a reproducing command. Use the evaluation-error and false-positive evidence
  from Plan 00481 where it exists.
- [ ] ⬜ **Task 1.3**: Write the inventory to `INVENTORY.md` in this folder, one table per
  guard. Add the list of out-of-scope-only code for the owner (open question 2).

### Phase 2: Triage the backlog

- [ ] ⬜ **Task 2.1**: Classify every open entry in ledger 00474: its index, its carried lists
  ([CARRIED-REFIX-BRANCHES.md](../00474-niggles-ledger-seventeen/CARRIED-REFIX-BRANCHES.md),
  [CARRIED-N53-BRANCH.md](../00474-niggles-ledger-seventeen/CARRIED-N53-BRANCH.md)), and
  the 65 entries still open in archived ledger 00466. Each entry is either an in-scope defect,
  dismissed under the threat model with the shape named, or already fixed on main (verified
  by reproduction, not assumed).
- [ ] ⬜ **Task 2.2**: Classify the 14 `UNCOVERED-open` rows in
  `scripts/qa/dangerous-invocation-corpus.yaml` the same way. Move dismissals to
  `UNCOVERED-accepted` with the reason.
- [ ] ⬜ **Task 2.3**: Record every dismissal: in the ledger, mark it
  `Dismissed (threat model)`; for a command, add a corpus row. The coordinator checks each
  batch's classifications against the two-part test before they land.

### Phase 3: Act

- [ ] ⬜ **Task 3.1**: Fix the in-scope defects through the ledger, at most 3 branches open at
  once (Plan 00475).
- [ ] ⬜ **Task 3.2**: Narrow each guard that causes an in-scope false positive while catching
  an out-of-scope shape (TDD: the false positive is the red test).
- [ ] ⬜ **Task 3.3**: Bring the owner's removal decisions on out-of-scope-only code into
  effect, if any were taken.

### Phase 4: Keep it applied

- [ ] ⬜ **Task 4.1**: Check that the review routines apply the test: Routine 00001's check
  inventory, the delta routine, the `security-reviewer` and `code-reviewer` agents, and the
  evasion test table. Fix any that still ask for adversarial coverage.
- [ ] ⬜ **Task 4.2**: Check that the user-facing docs say "guardrails, not armour" where a
  client would look before filing an obfuscated bypass upstream (the README, troubleshooting,
  bug reporting).

## Open questions for the owner

1. **Prompt injection.** An agent following instructions injected through an issue body, a
   fetched page or a cloned file is well-meaning, but its instructions may come from an
   adversary. Two options from the Fable review:
   - **(A) Judge the command, never the motive** (recommended). An injected agent is covered
     exactly as far as its instructions produce in-scope shapes. Past that, it is the hostile
     case, and the defence is upstream: the permission mode, the human, OS permissions.
   - **(B) Name injection as a third actor.** Chase obfuscated shapes, but only where the sink
     is exfiltration: protected reads, `gh` bodies, network egress.
2. **Code serving only out-of-scope shapes**: keep it while it costs nothing, which is the
   current text; or remove it to cut maintenance. Decide per item from the Phase 1 list.

## Success Criteria

- [ ] No open ledger entry or `UNCOVERED-open` corpus row is left unclassified.
- [ ] Each dismissal is recorded both in the ledger and, for a command, in the corpus.
- [ ] Every blocking guard has a verdict in `INVENTORY.md`.
- [ ] Every in-scope false positive found has a narrowing fix merged or a ledger entry.

## Delivery & Milestones

- Threat model written and reviewed: f38117f59, 67acd0cda.
