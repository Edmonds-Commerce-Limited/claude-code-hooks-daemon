# Fact check: Plan 00570 PLAN.md (whole document, new plan)

## REFUTED (most consequential first)

1. "`delete-branch` uses the same lookup, so it refuses these branches as 'content found nowhere'".
   `containment_of` is referenced only in `core/branch_inventory.py` and `core/branch_sweep.py` (grep of src for `containment_of`/`Containment.`).
   `cmd_delete_branch` (`daemon/cli.py:6590`) calls `delete_branches` -> `classify_branch` (`daemon/branch_safety.py:567`).
   That function compares tree/history paths against the default branch and integration-line bases. The "content found nowhere" text is at `branch_safety.py:733`.
   It never reads `refs/remotes/<remote>` containment.
   Plan impact: Overview para 3 and Task 1.2 need rewording. The delete-branch fix is a separate change in `classify_branch`, not a reuse of `containment_of`. The "Where the lookup lives" claim must be corrected.

## Table

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | `containment_of` is in `core/branch_inventory.py` | VERIFIED | `branch_inventory.py:527` |
| 2 | It runs `for-each-ref --contains` over `refs/remotes/<remote>` only | VERIFIED | `branch_inventory.py:548-555` (plus a merge-base check against the default's remote ref at 543) |
| 3 | Reports NOWHERE with text "no remote ref holds its commits" | PARTLY | Text is "CONTAINED NOWHERE (no remote ref holds these commits):" at `core/branch_sweep.py:324`; wording differs slightly ("these", not "its") |
| 4 | Sweep advises `git push -u origin <name>` | VERIFIED | `branch_sweep.py:243` |
| 5 | `delete-branch` uses the same lookup | REFUTED | see above |
| 6 | Plan 00558 (branch WIP limit and hygiene v2) makes an ls-remote check for integration-line tips (#153) | PARTLY | Plan exists as `Completed/00558-git-branch-hygiene-sweep`; its #153 item is one `ls-remote` for named branches in R-GIT-PUSH-DELETE-REMOTE (PLAN.md lines 26, 41). The title "branch WIP limit and hygiene v2" does not match the folder name; the implementation is `destructive_git.py:962-1003` |
| 7 | Plan 00206 is the deterministic delete proof | VERIFIED | `Completed/00206-safe-branch-delete-deterministic-proof` |
| 8 | Plan 00249 is the `delete-branch` crash fix | PARTLY | `Completed/00249-delete-branch-merged-but-unpushed`; the folder name does not say "crash fix", content not checked |
| 9 | Hook paths exist (session start, branch creation guard) | VERIFIED | `handlers/session_start/branch_sweep.py`, `handlers/pre_tool_use/branch_creation_guard.py` |
| 10 | `CLAUDE/UPGRADES/UNRELEASED/release-notes/` is the holding area | VERIFIED | directory exists, holds 001-003 plus README |
| 11 | WIP cap exists, #165 pool plan is separate | UNVERIFIABLE-HERE | WIP cap exists (`core/branch_creation.py` mentions wip); issue #165 needs GitHub |
| 12 | "Branch-hygiene docs state the containment rule" | UNVERIFIABLE-HERE | No non-plan doc under CLAUDE/ or docs/ contains "CONTAINED NOWHERE"/"no remote ref holds" except the old release note `CLAUDE/UPGRADES/v3/v3.71.0-to-v3.72.0/release-notes/024-branch-sweep-report-and-summary.md`; Task 1.3 should name the real doc |
