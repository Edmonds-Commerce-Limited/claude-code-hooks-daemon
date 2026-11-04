# Plan 00558: critique of v1

[PLAN-v1.md](PLAN-v1.md) was a report-only branch sweep. Its Non-Goals ruled out enforcement ("Merging, rebasing or deleting branches automatically") and its Goals kept deletion with the existing routes.

That design was overtaken on 3 November 2026 by two pieces of evidence:

- **This repository.** It held 52 linked worktrees, 56 local branches and 44 remote branches. 49 of the worktrees and 39 of the remote branches held nothing that was not already on `main`. The existing advisor (`branch_count_advisor`) printed its SessionStart line throughout and changed nothing. The manual triage is journalled in this plan.
- **GitHub #152** and its follow-up comment, from two other installations on 3.71.0: about 1,100 local branches, 290 remote branches and 380 worktrees in one project; about 250 unmerged remote branches across 40 repositories in another. The owner filed #152 asking for a WIP limit that holds.

A report that a busy session reads past does not hold a limit. That is v1's flaw, and the owner and the second installation report the same failure. v2 ([PLAN.md](PLAN.md)) keeps v1's inventory and report as its foundation and adds the enforcement #152 asks for.

The code facts v2 rests on were verified against the source in [subagent-reports/261103-issue-152-code-facts.md](subagent-reports/261103-issue-152-code-facts.md).
