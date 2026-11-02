# Fact-check: PLAN.md diff, Task 3.1 (#146)

Diff: /workspace/untracked/plan-fact-check/00556-secret-guard-bare-dotted-token-mentions.diff
Scope: claims added or changed by the diff only (Task 3.1 status and text).

## Claims

| #   | Quoted claim                                                                                    | Verdict                    | Evidence                                                                                                                                                                                                                                                                                                                                                                                     |
| --- | ----------------------------------------------------------------------------------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "Merged in 209c8d334"                                                                           | VERIFIED                   | `git cat-file -t 209c8d334` = commit; `git show --stat 209c8d334` shows "Merge #146" (parents d2300297a, 6396f5ce4).                                                                                                                                                                                                                                                                         |
| 2   | "the issue is closed"                                                                           | VERIFIED                   | `gh issue view 146 --json state,title,comments` returns `"state": "CLOSED"`.                                                                                                                                                                                                                                                                                                                 |
| 3   | Report link `subagent-reports/261102-task-3.1-issue-146.md`                                     | VERIFIED                   | File listed in `CLAUDE/Plan/00556-secret-guard-bare-dotted-token-mentions/subagent-reports/`; also added by commits 6396f5ce4 and 209c8d334.                                                                                                                                                                                                                                                 |
| 4   | "a trusted consumer command that redirects with `2>&1` is denied, while a plain `>` is allowed" | REFUTED (as current state) | Commit 6396f5ce4 (`src/claude_code_hooks_daemon/utils/secret_file_matching.py`, `is_exempt_invocation`) rewrites redirection `&` operators before the compound-marker check. Tests `tests/unit/utils/test_secret_file_matching.py::TestRedirectionAmpersandDoesNotMakeACommandCompound` assert `2>&1` and plain `>` are both exempt. The line describes the pre-fix defect in present tense. |

Totals: 4 claims, 3 verified, 1 refuted, 0 unverifiable.

## REFUTED claims

1. **Claim 4 (Task 3.1 text).** The `2>&1` denial is fixed, not current. Change the sentence to past tense or state the fix, for example: "was denied before 6396f5ce4; now stays exempt, and a plain `>` was always allowed." The checkbox and "Merged" line can stay as they are.

Note: the issue's "Fixed" comment and the commit both say that real compounds (`&`, `&&`, `;`, `|`) and redirects into a protected target stay denied. The plan does not claim otherwise, so no change is needed there.
