# Plan 00475: targeted qa and small batches

**Status**: In Progress
**Created**: 2026-09-30
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Two process failures, one plan. Both waste the owner's CPU and token budget.

**Full QA runs far too often.** The coordinator ran the whole
`./scripts/qa/llm_qa.py all` gate, which holds a host lock for the entire suite,
before merging even a four-file fix such as GitHub issue #59. **Owner
direction:** during feature and bug work, QA is TARGETED at what the change
affects. The full gate stays a main-thread gate (Plan 00463 stands), but it runs
only when preparing a release on `main`, after a substantial body of work has
been merged. A specialist QA sub-agent looks at a set of changes, decides what to
run, runs it and reports pass or fail. Only one QA process runs at a time, and
several changes may be tested together.

**Work is started in bulk and left to rot.** Ledger 00466 ended with 21 unmerged
branches, most 139 to 650 commits behind `main`. Many had been through 9 to 20
review rounds (the cap is 3). Nine were superseded copies of newer branches.
**Owner direction:** keep work granular. Start a small batch, finish it, merge
it, then start the next. Do not start many things and let them flounder, and do
not accumulate branches or archive tags.

Most of the QA tooling already exists (survey:
`untracked/agent-reports/auto/260930-073506-Explore-aa4f69c7609441674.md`).
`llm_qa.py changed` maps changed files to tests through
`scripts/qa/run_changed_tests.py` and `scripts/qa/changed_tests_map.yaml`, and
runs the static checks plus those tests. `llm_qa.py main-moved` already judges a
moved range. `subagent_full_qa_blocker` already keeps sub-agents off the full
suite. What is missing is the rule text (about 15 docs still tell the main thread
to run `all` at every step), a sub-agent that chooses the scope, a host-wide
one-at-a-time lock for every QA run, and any limit on work in progress.

## Design

### QA tiers

| Tier       | When                                | Who                                | What runs                                                                                      |
| ---------- | ----------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| Targeted   | Every change, before merge          | QA sub-agent                       | `llm_qa.py changed --base main`, plus any extra named checks the agent judges the diff touches |
| Post-merge | After a batch merges to `main`      | QA sub-agent over the merged range | `llm_qa.py changed --range <old-main>..<new-main>`; CI runs the whole pytest suite off-host    |
| Full       | Release preparation only, on `main` | Main thread (Plan 00463)           | `llm_qa.py all`                                                                                |

**The main design risk.** Plan 00463 made the coordinator run the full gate per
batch because some checks break from changes far away (handler guidance
coverage, docs QA, plan QA, the handler reference, generated-doc drift). Under
this plan the first full run happens at release preparation, so such a break
could sit on `main` until then. Mitigation to measure in Phase 1: of the 40
checks, only `tests` is known to be expensive. If every other check is cheap, the
targeted tier runs ALL of them plus the mapped tests. Then the only thing
deferred is the unmapped part of the pytest suite, which CI runs on every push to
`main` anyway.

**Evidence from the ledger 00466 cleanup.** Targeted QA missed both breaks the
first two landings put on `main`: acceptance probe #124 after N101 (the mapper
does not link handler code to `tests/acceptance/test_playbook_harness.py`), and
an `eacces_safe` static-check violation after N211 (a repo-wide check that
`changed` does not run). Neither is expensive. Both belong in the targeted tier:
the cheap repo-wide static checks always, and the playbook harness whenever
handler code changes.

### One QA process at a time

Every `llm_qa.py` run, not only whole-suite pytest, takes the host-wide lock in
the repository's common git dir, with a bounded wait. A second run queues
instead of competing. Today `untracked/qa/.llm_qa.lock` is per checkout, and
`hooksdaemon-full-qa.lock` covers whole-suite pytest only.

### Small batches

- **Work-in-progress limit:** at most 3 open work branches at once. Starting a
  fourth waits until one merges or is dropped.
- **Finish before starting:** a branch merges or is dropped within its batch. A
  branch left unmerged falls behind `main` and its merge cost grows.
- **Review cap stays at 3 rounds.** After that, merge what is sound or drop it.
- **Dropping is a deletion:** record the reason in the ledger entry, then delete
  the branch and its worktree. No archive branches, no archive tags.
- **Ledger entries are recorded on `main`, not on a work branch.** Ledger 00466's
  dropped branches held entries that `main` never had (N135, N176, N177, N189,
  N244-N246 on the N53 branch, N253-N256 on the N253 branch), and they had to be
  recovered by hand before deletion. A branch changes an entry's status only.

## Goals

- Targeted QA is the default for every change. The full gate runs only at
  release preparation.
- A QA sub-agent decides and records the scope of each targeted run.
- No two QA runs execute at once on the host.
- No more than 3 work branches are open at once. Each batch finishes before the
  next starts.

## Non-Goals

- Letting sub-agents run the full suite (Plan 00463 stands).
- Changing CI, which already runs the full pytest suite on every push to `main`.

## Tasks

### Phase 1: Measure

- [ ] 🔄 **Task 1.1**: Measure each of the 40 `llm_qa.py` checks on this host.
  Record which are cheap enough for the targeted tier. First measurement: 27
  checks together (every check except `tests`, `smoke_test`, `semgrep`,
  `dependencies`, `github_urls`, `python_var_guidance`, `skip_list_substring`,
  `dangerous_invocation_corpus`, `security_downgrade_flags`, `capture_corruption`,
  `sensitive_content`, `git_history` and `british_english`) took 394 seconds
  wall-clock. The remaining non-test checks still need timing.

### Phase 2: Targeted QA

- [ ] ⬜ **Task 2.1**: Extend `llm_qa.py changed` with the cheap cross-cutting
  checks Phase 1 identifies (TDD).
- [ ] ⬜ **Task 2.2**: Turn `qa-runner` into the scope-deciding QA agent. It reads
  the diff, picks the checks, runs them and reports verdict, scope and reasoning.
- [x] ✅ **Task 2.3**: Take the host-wide lock for every `llm_qa.py` run, with a
  bounded wait (TDD). Merged in 8f2cd8bc8.

### Phase 3: Rules

- [x] ✅ **Task 3.1**: Rewrite `CLAUDE/QA.md` as the single home for the tiers.
  Point `PlanWorkflow.md`, `CodeLifecycle/*`, `AgentTeam.md`, `Worktree.md` and
  `development/IssueSdlc.md` at it instead of requiring `all`.
- [x] ✅ **Task 3.2**: Write the small-batches rules (WIP limit, finish before
  start, dropping) into `Worktree.md` and `AgentTeam.md`. Delivered in 1a5214069.
- [x] ✅ **Task 3.3**: Keep the release documents (`RELEASING.md`, the release
  skill and agent) as the one place the full gate is required.

### Phase 3b: CI tiers (owner request)

Measured over the last 60 `qa.yml` runs: every push to `main` ran the full suite
on three Pythons, a 39-minute median with a 98-minute worst case once queueing is
included. 34 of 58 were markdown-only commits, yet 9 of those failed, because tests
read the plan index, ledgers and docs. So markdown is narrowed, not skipped.

- [ ] 🔄 **Task 3b.1**: A tested change classifier (markdown only; code; build or
  CI config) drives which jobs run. Markdown only runs the doc and plan checks
  plus the tests that read the changed files, on one Python. Code runs lint,
  types and `llm_qa.py changed` over the pushed range on one Python, falling back
  to the full suite on that Python when the mapper cannot map a file. Build or CI
  config runs the full matrix.
- [ ] ⬜ **Task 3b.2**: The full three-Python matrix runs nightly on `main`, on
  manual dispatch, and on the release pull request (Plan 00476). The release
  slate gate (Plan 00359) accepts a tier's green for everyday work and requires
  a full-matrix green for a release.

### Phase 4: Enforcement

- [ ] ⬜ **Task 4.1**: A SessionStart advisory counts open work branches and names
  any beyond the limit, or any far behind `main`. Decide advisory or blocking
  with the owner.

## Success Criteria

- [ ] A small fix goes from branch to `main` with targeted QA only, and CI green.
- [x] Two concurrent `llm_qa.py` runs in different worktrees serialise. Seen
  live: the cron-hosts branch's `llm_qa.py changed` queued behind the provision
  branch's run.
- [x] No doc outside the release documents requires `llm_qa.py all`. Merged in
  b4576108a. The deployed core docs now name the project's own QA gate.
- [ ] The branch-count advisory fires on a repository with more than 3 open work
  branches.

## Delivery & Milestones

- Ledger 00466 branch cleanup is the first batch run under these rules.
