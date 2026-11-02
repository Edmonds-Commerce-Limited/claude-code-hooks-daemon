# Plan 00559 fact check (diff-added claims)

Scope: the diff at `untracked/plan-fact-check/00559-daemon-clone-follows-expected-version-after-pull.diff`
adds two bullets under "Related plans that constrain the design" and one process sentence.
Only those claims are checked. Claims already in PLAN.md (for example the `background_sync.py`
at-most-once behaviour and Plan 00477 Task 5.2) are outside the diff and were not checked.

## Claims

| #   | Quoted claim                                                                                                                                | Verdict                                         | Evidence                                                                                                                                                                                                                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "Plan 00535 (upgrade handover without a live daemon rebuild)"                                                                               | VERIFIED                                        | `CLAUDE/Plan/00535-upgrade-handover-without-live-daemon-rebuild/PLAN.md:1` has the title; `CLAUDE/Plan/README.md:21` lists it as Not Started.                                                                                                                                                                                                |
| 2   | "A re-provision set off by a hook must stop or hand over the running daemon before it rebuilds, or it hits that plan's mixed old/new tree." | VERIFIED                                        | `00535 PLAN.md:13-17` (upgrade rebuilt the venv a running daemon used; sessions "met a mixed old/new tree"); `00535 PLAN.md:21-24` (Goals: never rebuild a venv or check out source a running daemon executes from; no mixed old/new tree). The "must" is the design constraint 00535 itself sets, so it is consistent with the source plan. |
| 3   | "Plan 00473 (post-merge handlers judge the command's repository)"                                                                           | VERIFIED                                        | `CLAUDE/Plan/00473-post-merge-handlers-judge-the-command-repository/PLAN.md:1` (title); `README.md:65` (Not Started). Its Overview (lines 12-16) states the goal: judge the repository the command ran in.                                                                                                                                   |
| 4   | "A git post-merge trigger needs the same repository resolution."                                                                            | VERIFIED (with a stale-premise note, see below) | 00473 Goals (line 24-26) and Non-Goals (line 29) say to reuse 00464's resolver.                                                                                                                                                                                                                                                              |
| 5   | "the dedupe check found no duplicate"                                                                                                       | UNVERIFIABLE-HERE                               | This is a record of a process step. No scout report exists on disk for it. `JOURNAL/2026-11-02/165835Z-action-b012ce.md` records only the scaffold.                                                                                                                                                                                          |

## Note on claim 4 (not a refutation of the diff text)

00473 says `daemon_sync_after_merge` and `merge_qa_report` judge the payload `cwd` (its line 12-16) and that it is blocked on Plan 00464's resolver (lines 18-20). The current tree already resolves the merge directory from the command:

- `src/claude_code_hooks_daemon/utils/merge_scope.py:62` defines `merge_directory(command, cwd)`, which moves `cwd` by the `cd`/`pushd`/`git -C` in effect at the first merge, pull or rebase.
- `src/claude_code_hooks_daemon/handlers/post_tool_use/daemon_sync_after_merge.py:246` calls it: `GitRepo.resolve_for(merge_directory(get_bash_command(hook_input) or "", cwd_raw))`.

00464's Task 1.3 (`PLAN.md:82`) is still a plan for a shared commit-gate resolver, not shipped code. So 00473's premise (`cwd` only, blocked on 00464) is stale for `daemon_sync_after_merge`.

Effect on 00559: a post-merge trigger should reuse `merge_directory` (`utils/merge_scope.py:62`), not wait for 00464. The plan's pointer to 00473 stays correct as the owning plan, but the plan should name the existing resolver. This is a suggested edit, not a refuted claim.

## REFUTED claims

None. No claim the diff adds is contradicted by the tree.

## Summary

5 claims: 4 verified, 0 refuted, 1 unverifiable (the dedupe check, which has no artefact on disk).
