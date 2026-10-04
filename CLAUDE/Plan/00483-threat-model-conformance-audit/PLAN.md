# Plan 00483: threat model conformance audit

**Status**: In Progress
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
- Defending against prompt injection. The owner ruled the daemon makes no such claim.

## Tasks

### Phase 1: Inventory the guards

- [x] ✅ **Task 1.1**: List every blocking PreToolUse handler. For each, record what it matches
  and the shapes its parsing handles, from the code rather than its docs. Start with the
  guards that parse shell:
  - `secret_file_guard`, `quarantine_artefact_read_guard`, `flaggable_content_channel_guard`;
  - `sensitive_content` and the commit gates;
  - `destructive_git`, `git_stash`, `sed_blocker`, `pipe_blocker`;
  - the plan-folder `mkdir` guard, `project_containment`, `upgrade_approval_guard`.
- [x] ✅ **Task 1.2**: For each guard, classify each parsing branch as in-scope or out-of-scope
  under the two-part test. Mark every out-of-scope branch that causes an in-scope false
  positive, with a reproducing command. Use the evaluation-error and false-positive evidence
  from Plan 00481 where it exists.
- [x] ✅ **Task 1.3**: Write the inventory to `INVENTORY.md` in this folder, one table per
  guard. Add the list of out-of-scope-only code for the owner (open question 2). Done:
  [INVENTORY.md](INVENTORY.md). 62 of 74 PreToolUse handler files can deny; 38 shell-parsing
  guards have tables, the other 24 are triaged at file level (part G, UNVERIFIED). 15 guards
  cause an in-scope false positive. About 3,500 lines of out-of-scope-only code are listed for
  the owner. The two headline false positives were reproduced live by the coordinator: a
  `cd "$DIR" &&` before a quoted heredoc makes `git_stash` deny prose, and `${P:-"/usr"}`
  before an `awk '{…}'` is denied as unreadable. Both feed Task 3.2.

### Phase 2: Triage the backlog

- [x] ✅ **Task 2.1**: The 55 carried entries are done: [TRIAGE-carried-a.md](TRIAGE-carried-a.md),
  [TRIAGE-carried-b.md](TRIAGE-carried-b.md), [TRIAGE-carried-c.md](TRIAGE-carried-c.md). The
  results: 23 in-scope defects, 14 dismissed, 13 fixed on main, 2 folded, 3 for the owner (N154,
  N230, N240). The 67 entries open in ledger 00466 are done in
  [TRIAGE-ledger-466.md](TRIAGE-ledger-466.md): 29 in-scope defects, 22 fixed on main, 8
  dismissed, 4 folded and 4 for the owner (N55, N62, N74, N96). The coordinator reproduced
  N85 with `hooks-daemon probe` (allowed). The owner delegated the decisions on N154, N230 and
  N240 to a Fable subagent; see `RULINGS-owner-delegated-fable.md`. Classify every open entry
  in ledger 00474: its index, its carried lists
  ([CARRIED-REFIX-BRANCHES.md](../00474-niggles-ledger-seventeen/CARRIED-REFIX-BRANCHES.md),
  [CARRIED-N53-BRANCH.md](../00474-niggles-ledger-seventeen/CARRIED-N53-BRANCH.md)), and
  the 65 entries still open in archived ledger 00466. Each entry is either an in-scope defect,
  dismissed under the threat model with the shape named, or already fixed on main (verified
  by reproduction, not assumed).
- [x] ✅ **Task 2.2**: Classify the `UNCOVERED-open` rows in
  `scripts/qa/dangerous-invocation-corpus.yaml` the same way. Move dismissals to
  `UNCOVERED-accepted` with the reason. Done by the coordinator. 9 rows are open, not 14: 5 were
  closed as COVERED since this task was written (`checkout -f`, `switch -f`, `reflog expire`,
  `gc --prune=now`, `filter-branch`). None is dismissed. Each is an ordinary command typed in full
  (`git reset --keep`, `rm -rf`, `truncate -s 0`, `git push --delete`, `git tag -d`,
  `pip install --index-url`, `gh auth token`, `crontab -r`, `docker run -v /:/host`), so neither
  limb applies: the text is visible at call time, and each has ordinary uses rather than existing
  only to defeat a parser. All 9 are in scope and stay `UNCOVERED-open`. The corpus header makes
  every new deny owner-gated per row, so they go to the owner as one batch.
- [ ] 🔄 **Task 2.3**: Done for the carried entries (merge 56677e3c6). That added 9
  `UNCOVERED-accepted` corpus rows. N201, N228 and N257 have no row, because main denies the
  representative command anyway. Record every dismissal: in the ledger, mark it
  `Dismissed (threat model)`; for a command, add a corpus row. The coordinator checks each
  batch's classifications against the two-part test before they land.

### Phase 3: Act

- [ ] ⬜ **Task 3.1**: Fix the in-scope defects through the ledger, at most 3 branches open at
  once (Plan 00475). N154 and N230 (Fable FIX rulings) were verified already fixed on main at
  c7271043f, so branch worktree-p483-inscope changes no code for them. Report:
  [subagent-reports/261003-task-3.1-n154-n230-sonnet.md](subagent-reports/261003-task-3.1-n154-n230-sonnet.md).
  Batch A on branch worktree-p483-leak: N61 no longer reproduces (fixed by 530ffc83d, now pinned
  with a public-pattern test); N94 fixed (the auto-close verdict memo is keyed by the hook_input
  object, not the command text). Report:
  [subagent-reports/261003-task-3.1-batch-a-n61-n94-sonnet.md](subagent-reports/261003-task-3.1-batch-a-n61-n94-sonnet.md).
  Segmentation batch on branch worktree-p483-segment: N48 (sed_blocker splits on newline), N87 (`$'...'` bodies decoded), N93 (`eval` body judged like `bash -c`) fixed; N85 no longer reproduces. Report:
  [subagent-reports/261003-task-3.1-batch-b-segmentation-sonnet.md](subagent-reports/261003-task-3.1-batch-b-segmentation-sonnet.md).
  N50, N54 and N43 fixed on branch worktree-p483-config: an option naming a method, read-only
  property or `_` name is refused and reported, one cached default `Config` replaces the
  per-Stop rebuild, and redaction falls back to the default word list when the config fails.
  Report: [subagent-reports/261003-task-3.1-batch-c-config-sonnet.md](subagent-reports/261003-task-3.1-batch-c-config-sonnet.md).
- [ ] 🔄 **Task 3.2**: Narrow each guard that causes an in-scope false positive while catching
  an out-of-scope shape (TDD: the false positive is the red test). X-1 fixed on branch
  worktree-p483-x1-rebind-heredoc: the shared rebinding check no longer withholds the heredoc
  exemption for `cd`/`pushd`/`popd`, `source`/`.` or a non-special `export X=$Y`; alias,
  function and PATH bindings still do. Report:
  [subagent-reports/261002-x1-sonnet.md](subagent-reports/261002-x1-sonnet.md).
  FP batch 2 fixed on branch worktree-p483-fp-batch2: the brace reader reads a quoted
  `${name:-word}` default (and `=`, `+`, `?`) instead of failing closed; `curl -o /dev/null`
  and `wget -O /dev/null` are no longer outside writes; `$PWD`, `${PWD}`, `$(pwd)` and
  `$(git rev-parse --show-toplevel)` resolve to the hook cwd and its repository root, judged
  as any path. Loop variables, `$DEST`, `$TMPDIR` and `$HOME` are untouched. Report:
  [subagent-reports/261002-fp-batch2-sonnet.md](subagent-reports/261002-fp-batch2-sonnet.md).
  Issue #70 class fixed (merged on main): a regex pattern operand of grep/rg given through `-e`
  or `--regexp`, and the pattern of `git grep`, is text and not a glob of a protected name. File
  operands, `--include` values, revisions and pathspecs stay judged as paths. Tests pin the
  reported `'.*WORD'` shapes, which had been allowed on main without any test.
- [ ] ⬜ **Task 3.3**: Bring the owner's removal decisions on out-of-scope-only code into
  effect, if any were taken.

### Phase 4: Keep it applied

- [x] ✅ **Task 4.1**: Check that the review routines apply the test: Routine 00001's check
  inventory, the delta routine, the `security-reviewer` and `code-reviewer` agents, and the
  evasion test table. Fix any that still ask for adversarial coverage. Done: CHECKS.md scope
  note carries both clauses and the dismissal record; F-BYPS, F-GAP, D-SEC bounded; both
  routines and both agents point at the test; evasion docstring bounded. Review:
  [subagent-reports/261002-phase4-review-sonnet.md](subagent-reports/261002-phase4-review-sonnet.md).
- [x] ✅ **Task 4.2**: Check that the user-facing docs say "guardrails, not armour" where a
  client would look before filing an obfuscated bypass upstream (the README, troubleshooting,
  bug reporting). Done: BUG_REPORTING.md first check, 1-defect.yml intro and optional
  checkbox, TROUBLESHOOTING.md section 5 subsection. config.yml skipped by instruction.

## Open questions for the owner

1. **Prompt injection: resolved (owner).** The daemon makes no claim to defend against it.
   The threat model and the README say so. A prompt-injection defence may become a future
   major version, as a separate project.
2. **Code serving only out-of-scope shapes**: keep it while it costs nothing, which is the
   current text; or remove it to cut maintenance. Decide per item from the Phase 1 list.

## Success Criteria

- [ ] No open ledger entry or `UNCOVERED-open` corpus row is left unclassified.
- [ ] Each dismissal is recorded both in the ledger and, for a command, in the corpus.
- [ ] Every blocking guard has a verdict in `INVENTORY.md`.
- [ ] Every in-scope false positive found has a narrowing fix merged or a ledger entry.

## Delivery & Milestones

- Threat model written and reviewed: f38117f59, 67acd0cda.
