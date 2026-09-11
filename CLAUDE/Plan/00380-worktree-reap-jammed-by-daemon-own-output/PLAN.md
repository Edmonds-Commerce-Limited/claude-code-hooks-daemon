# Plan 00380: worktree reap jammed by daemon own output

**Status**: In Progress
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Five agent worktrees sat unreapable for days, and every one of them was safe to
remove the whole time: all five had **zero commits unmerged to main**. The
owner asked why they accumulate and whether the project's own hooks were
blocking cleanup.

The hooks are not the problem. `git worktree remove --force` is matched by no
rule — it is the worked example in `destructive_git.py:46` of a command
deliberately NOT matched. The five were removed with no hook objecting.

The problem is the reaper refusing on evidence that is not evidence. Four of
the five were held by ONE untracked path, `.claude/reports/v2.2.0-to-v2.15.2/`
`ADVISORY.md` — the daemon's own generated output. It reached `main` by
accident in `41391a66` ("WIP handoff before shutdown … not QA'd"), and
`.claude/reports/` is not gitignored, so in any worktree pinned to a commit
predating that one the daemon's artefact reads as the agent's unsaved work.
The fifth was held by 15 lines of superseded black-formatting churn that `main`
had already fixed in `cbc44c58`.

Compounding it, the refusal message says "remove it by hand" and the summary
says "N need a human". Both are false — an agent can inspect and remove — and
that wording is what caused a session to hand the cleanup to the owner across
several turns instead of doing it. A message that misroutes the work is a
defect in the message.

## Goals

- A daemon-generated artefact never makes a worktree unreapable.
- The reaper's refusal text routes the reader to the action they can actually
  take, instead of implying a human is required.
- A generated advisory is not tracked in git.

## Non-Goals

- Loosening the safety predicate generally. Uncommitted work is still a refusal
  and must stay one; only paths that provably are NOT work stop counting.
- Auto-reaping on a timer. The reaper stays report-first, `--reap` opt-in.
- Rewriting the history that committed the artefact. It is untracked going
  forward; `41391a66` stays as it is.

## Tasks

### Phase 1: Stop generating the jam

- [x] ✅ **Task 1.1**: Untrack `.claude/reports/` and gitignore it. It is
  generated output that reached the index in a WIP commit; nothing reads it
  from version control. Current code already writes reports to
  `untracked/reports` (`daemon/cli.py:6274`, `:6332`), so the tracked copy is
  pure residue.

### Phase 2: The reaper stops mistaking output for work

- [x] ✅ **Task 2.1**: An uncommitted path that the MAIN checkout would ignore
  does not count as work. Main's `.gitignore` is the authority on what is
  generated; a worktree pinned to an older commit carries a stale copy of it,
  which is exactly how this jam formed. Consulting main rather than a
  hardcoded list also covers generated paths added later.
- [x] ✅ **Task 2.2**: Prove it on the real failure shape — a worktree whose
  only uncommitted path is ignored in main must become reapable, and one with
  a genuinely modified tracked file must still be refused.

### Phase 3: The message routes to the right actor

- [x] ✅ **Task 3.1**: Replace "remove it by hand" and "N need a human" in
  `core/worktree_reaping.py:264` and `daemon/cli.py:6094`. The reader is
  usually an agent, and the action is available to it. Name the command.
- [x] ✅ **Task 3.2**: Say what to inspect FOR. "The work is accounted for"
  gives no test; "no commits unmerged to base, and the uncommitted paths are
  generated output or already landed" does.

## Success Criteria

- [ ] A worktree whose only uncommitted path is generated output is reported
  reapable, and `--reap` removes it.
- [ ] A worktree with genuinely uncommitted work is still refused.
- [ ] `.claude/reports/` is untracked and ignored.
- [ ] The refusal text names an action its reader can take, and a test pins
  that it does not tell the reader a human is required.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Prompted by the owner asking why stale worktrees require human pruning, and
  whether the project's own hooks were blocking cleanup. The hooks were not;
  the reaper and one accidental commit were.
- The five worktrees themselves were removed before this plan was written —
  all had zero commits unmerged to main, and their branches are kept.
