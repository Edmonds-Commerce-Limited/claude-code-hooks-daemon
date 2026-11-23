# Plan 00634 build handoff 4

Branch `plan-00634-human-approval-check` (pushed). Worktree
`.claude/worktrees/agent-a6328547e60968275-2a1ab764`. Handoff 3 steps 1-3 are
done; read handoff 3 for the settled design, then this file. Do not re-read
the plan or design docs.

## Done

1. Detector seams (commit "public detector seams"):
   `dangerous_permissions.sets_world_writable`,
   `merge_to_main_approval.merge_lands_on_main` (None = unreadable) and
   `is_pr_merge`, `destructive_git.names_a_deletion` (unverifiable -> True).
   Tests: `tests/unit/handlers/pre_tool_use/test_human_approval_detector_seams.py`.
   Note: `names_a_deletion` also returns True for a push with a flag the
   remote-delete reader does not know (`-f`, `--mirror`): fail closed.
2. `team_seat` injection cli -> controller -> registry as `_team_seat`
   (declared-attribute selection). Test:
   `tests/unit/handlers/test_registry_team_seat_injection.py`.
3. RED handler tests:
   `tests/unit/handlers/pre_tool_use/test_human_approval_check.py`. Its
   docstring lists the seams the handler must expose: `_mode`
   (`off|advise|block`), `_coordinator_seats_only`, `_resolver` (lazy from
   `_team_seat`), `_verifier` (default `DEFAULT_VERIFIER`), `_records`, and
   module functions `classify_acts(command, cwd) -> frozenset[ActClass]` and
   `cite_from_command(command) -> ApprovalCite | None`. The module must import
   `merge_lands_on_main` by name (tests monkeypatch `module.merge_lands_on_main`).

## Left (handoff 3 steps 4-6)

4. GREEN `handlers/pre_tool_use/human_approval_check.py` against that test
   file. Points the tests pin: `PUSH` = any `git push` invocation; a merge
   with an unreadable branch is MERGE_MAIN, `gh pr merge` always is; a cite
   is only a trailing `# human-approval team=<T> id=<$id>` comment on the
   LAST line, with exactly one team and one id key (any extra key -> None);
   the pass result is a bare ALLOW (no reason, no context); refusal text is
   `verdict.reason` plus act names only; exceptions in `matches` -> False,
   in `handle` -> DENY (block) / ALLOW + context (advise), never echoing the
   exception text. Add `HandlerID.HUMAN_APPROVAL_CHECK`,
   `Priority.HUMAN_APPROVAL_CHECK = 21`,
   `RuleID.HUMAN_APPROVAL_MISSING = "R-HUMAN-APPROVAL-MISSING"`.
5. Config, docs, release note, tagging/coverage tests (handoff 3 step 5).
6. PLAN.md ticks, open points, PR (handoff 3 step 6). Do NOT merge.

## Gotcha

Running `pytest tests/unit/handlers/pre_tool_use/ -k destructive_git` in the
worktree is slow and something in it holds this worktree's `index.lock`
(repeated `git status`), so `git add` fails while it runs. Run single test
files, and never commit while a pytest run is in the background.
