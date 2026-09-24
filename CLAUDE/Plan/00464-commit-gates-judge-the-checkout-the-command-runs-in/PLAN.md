# Plan 00464: commit gates judge the checkout the command runs in

**Status**: Not Started
**Created**: 2026-09-24
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

**Found in passing (00422 N23, graduated at once as a class defect).** A
worktree agent's `cd <worktree> && git commit` was denied by
`R-PLAN-QA-COMMIT`, citing `Completed/00456-…/PLAN.md`. That path existed
only in the MAIN checkout's index, where the coordinator was archiving
00456 at the same moment. A retry passed once the coordinator had
committed.

**Cause, confirmed in the daemon's DEBUG payload log.** An in-process
teammate's PreToolUse payload carries `"cwd": "/workspace"`, the main
checkout, even while it works in a worktree. The commit gates choose the
repository to judge from that field. For example,
`plan_qa_commit_gate._is_foreign_repo` resolves `GitRepo.resolve_for(cwd)`
and compares it with `ProjectContext.project_root()`. Neither looks at the
command, so a worktree commit is judged against the main checkout's staged
tree.

**Both directions are wrong, and one fails open.**

- A false deny, from unrelated staged state in the main checkout: observed.
- A worktree commit's OWN staged content is never checked. That includes
  the sensitive-content commit scan, whose contract is that "the commit is
  the gate". A merge into `main` is not a `git commit`, so a term committed
  in a worktree can reach `main` unscanned.

The gates known to key on `cwd`: `plan_qa_commit_gate`,
`docs_qa_commit_gate`, `staged_lint_gate`, and `sensitive_content`'s
commit scan. `remote_docs_commit_gate` and `guard_config_commit_gate` need
checking. `utils/secret_file_matching.py` already has an effective-cwd
notion worth reusing.

## Goals

- Every commit gate judges the repository the `git commit` actually runs
  in. That repository is resolved from the command: a leading
  `cd <dir> &&`/`;`, `git -C <dir>`, `--git-dir`/`--work-tree`, and
  `pushd`. The payload `cwd` is used only as the base for a relative path.
  A worktree of this project is judged against ITS OWN staged tree and
  config.
- One shared resolver serves every gate, so the gates cannot diverge
  again, and a class test enumerates every commit gate and proves it uses
  it.
- Unresolvable cases fail CLOSED to the most conservative choice. When
  the target cannot be determined (for example `cd "$VAR"`), a blocking
  gate must never silently skip. It judges both checkouts, or denies
  with a message naming the ambiguity.
- The `git merge` path is considered. Say whether a merge commit's
  incoming content needs the sensitive-content scan (it bypasses every
  commit gate today) and act on the answer.

## Non-Goals

- Changing what any gate checks. This plan changes only WHERE it looks.

## Tasks

### Phase 1: TDD in a worktree

- [ ] ⬜ **Task 1.1**: Audit every handler that keys on the payload `cwd`
  or on `ProjectContext.project_root()` to judge a git operation's
  repository. List each one, with the direction it fails in.
- [ ] ⬜ **Task 1.2**: RED tests. For each gate: a payload with
  `cwd=<main>` and command `cd <worktree> && git commit …` is judged on the
  WORKTREE's staged tree. A violation staged only in the worktree is
  caught. A violation staged only in main does NOT deny the worktree
  commit. `git -C <worktree> commit` gets the same checks. Include a
  secret-term fixture for the sensitive-content scan.
- [ ] ⬜ **Task 1.3**: The shared effective-repository resolver, reusing
  the existing command parsing, not a new parser. Move every gate onto
  it. Answer the `git merge` question with evidence, and act on it.
- [ ] ⬜ **Task 1.4**: Security class doc entry (CLAUDE/Security/), docs,
  release note. Targeted QA, under the Plan 00463 rule; the coordinator
  runs the full gate.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: The coordinator runs full QA on the branch head,
  merges `--no-ff`, verifies ancestry and CI, and restarts the daemon.
- [ ] ⬜ **Task 2.2**: Live check: from a worktree, commit content that
  violates plan QA and is staged only there, and confirm it is denied.
  Mark 00422 N23 remedied.

## Success Criteria

- [ ] A worktree commit is judged on its own staged tree by every commit
  gate. Proven per gate and by a class test.
- [ ] Unrelated staged state in the main checkout never denies a
  worktree commit.
- [ ] No blocking gate silently skips a commit it cannot place.
- [ ] Full QA passes (run by the coordinator) and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00464-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
