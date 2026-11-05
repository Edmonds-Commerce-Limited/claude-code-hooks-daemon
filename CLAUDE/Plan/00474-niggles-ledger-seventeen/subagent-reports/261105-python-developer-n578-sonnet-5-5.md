# N578 report: chained remote delete of a merged branch

## Root cause (verified, not one of the three hypotheses)

`DestructiveGitHandler._judge` (destructive_git.py) only ran `_remote_delete_note` when
`rule_ids == [GIT_PUSH_DELETE_REMOTE]`. `git worktree remove <wt>` also matches
`GIT_WORKTREE_REMOVE_FORCE`, so a chain gave `rule_ids` of two entries. `others` (rules not
in `_LOSSLESS_WHEN_PROVEN`) held the push rule, the `not others` branch was skipped, the
sole-rule `elif` was false, and `note` stayed `None`. Result: a deny with only the generic
text, and the merged proof was never run. The merged-proof step, the segment splitter and
the local-delete anticipation were all fine.

## Fix

`_judge` now judges the remote delete (when its rule matched) on its own, wherever it sits
in a chain, and judges the lossless rules (forced branch delete, worktree removal)
independently. It allows only when both are clear, and a deny joins every note, so the
branch and the "not merged into `main`" reason are always named. A command that also
matches a rule with no safe case (for example `reset --hard`) still denies under that rule,
and now also shows the remote delete's reason. Unmerged, tag, `--mirror` and `--prune`
denials are unchanged.

## TDD

Red commit `0164f07da`, tests in
`tests/unit/handlers/pre_tool_use/test_destructive_git_remote_delete_chained.py` (real temp
repos with worktrees). Red output: `10 failed, 2 passed`; the merged chains were denied by
R-GIT-PUSH-DELETE-REMOTE with the generic text, and the unmerged chains lacked
"`unmerged` is not merged into `main`".
Green: all 760 destructive_git tests pass.

## QA

`llm_qa.py changed --range main..HEAD`: 41/42. The one failure is
`src/.../destructive_git.py [too-broad]` reported as unmapped. That is the tool's design for
this file (its own 860 tests ran and passed); a changed_tests_map.yaml rule does not clear it
(tried, reverted in `2aad6fde5`). The coordinator's full gate covers it. Format and the
release-note shape test were fixed during the run.

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/003-destructive-git-chained-remote-delete.md`.
