# Plan 00634 build handoff 2

Branch `plan-00634-human-approval-check` (pushed). Worktree
`.claude/worktrees/agent-a6328547e60968275-2a1ab764`. Stopped at the Unit 1 /
Unit 2 boundary to keep context for the guard.

## Done since handoff 1

- `9c657d585`: `src/claude_code_hooks_daemon/utils/human_approval.py` (Task 2.1,
  GREEN; 85 tests in `tests/unit/utils/test_human_approval.py`, plus the seat
  and role-gate suites, pass). `Timeout.TEAMCHAT_VERIFY = 3`. ruff, black and
  mypy are clean on the touched files.
  - Fail-closed extras, each with a red test first: an empty act set refuses
    (`Refusal.NO_ACTS`). A verifier returning anything but
    `VerifiedLine`/`VerifyFailure` gives ANSWER_UNREADABLE. `TeamchatVerifyCli`
    re-runs `parse_cite`, so a hand-built cite never reaches argv (NO_CITE). A
    record lapses exactly at `stamp + ttl`, and expired records are pruned on
    each write. Only cite-verified acts are recorded; GO-covered acts are not.
  - Q5 switch: `is_armed(..., coordinator_seats_only=True)`.
  - Extra refusals: `NO_TEAM_SEAT` and `SUBAGENT`. Every reason comes from the
    fixed `_REASONS` table and never from answer content.
- `75f661f92`: PLAN.md is In Progress, with Tasks 1.1 and 2.1 ticked and Task
  1.2 (Q4/Q5, owner ruling pending) added. Task 2.3 (live verification after
  issue 369) is split out, and an "Open design points" section records both
  gaps and the unverified items. The decision is journalled at
  `JOURNAL/2026-11-23/145636Z-decision-7d7b89.md`.

## Next: Unit 2, the guard (Task 2.2), test-first

Handler `human_approval_check` (PreToolUse, Bash only). Mode is
`off | advise | block`, default `advise`. Option `coordinator_seats_only`
defaults to true and passes straight to `is_armed`.

Flow:

1. Resolve the seat with `SeatContextResolver.from_config` and the signals with
   `SessionSignals.from_hook_input`.
2. Stay silent when `is_armed` is false, or when no act class is found.
3. Classify the act classes.
4. Parse the Q4 cite.
5. Call `check_approval` with `verifier=DEFAULT_VERIFIER`, one module-level
   `ApprovalRecords` per daemon, and `go=None` until Plan 00632 supplies one.
6. A pass returns ALLOW and never relaxes another handler (invariant 1).
   Advise mode adds context; block mode denies. Neither may say "verified"
   for a failed cite.

Act classification must reuse the existing detectors and add no new
act-detecting regexes:

- PUSH: any `git_invocations(command)` run with `subcommand == "push"`, from
  `utils/git_commit_parsing.py`.
- DELETE:
  - `destructive_git._deleted_branches(command)`;
  - `destructive_git._remote_delete_targets(run)` for each push run;
  - `destructive_git._worktree_removals(command)`.
    These are private names. Either promote them to public with a thin alias and
    a test, or ask whether `branch -d` belongs at all.
- PERMISSION: `DangerousPermissionsHandler().matches(hook_input)`. This covers
  world-writable chmod only. Record the narrower scope as an open point; do
  not widen it with a new regex.
- MERGE_MAIN: `merge_to_main_approval.merge_target(command)` is not None. Read
  how that handler decides that the target is main (current branch) and reuse
  that decision.
- All of these run on what survives `strip_inert_spans` /
  `command_position_*`, which the detectors already do. A `git push` inside a
  `-m` message or a quoted heredoc is prose.

Q4 cite parsing: a trailing shell comment `# human-approval team=<T> id=<$id>`
on the last line. A tight regex is fine here, because it parses the cite and
does not detect an act. Feed the result to `parse_cite`. A malformed cite is
NO_CITE, not silence.

Plumbing, as in commit fb583a8233:

- `constants/handlers.py`: HandlerID.
- `constants/priority.py`: Priority. Place it after the safety blockers, so
  destructive_git still denies first.
- `constants/rule_ids.py`: RuleID, e.g. `R-HUMAN-APPROVAL-MISSING`.
- `.claude/hooks-daemon.yaml` and `.yaml.example`.
- `CLAUDE/UPGRADES/UNRELEASED/config-changes/<next>.yaml`: check the existing
  file name there first.
- `docs/guides/HANDLER_REFERENCE.md` and `docs/guides/CONFIGURATION.md`.
- `tests/integration/test_claude_md_guidance_coverage.py` and
  `tests/integration/test_handler_scope_defaults.py`.
- A pending-release note under `CLAUDE/UPGRADES/UNRELEASED/`, which is needed
  for the success criterion "release-bound items recorded".

Then tick Task 2.2 and the success criteria that the tests prove. Leave Tasks
1.2 and 2.3 open. Open the PR with the open design points listed in its body,
ending with the Claude Code attribution line. Do NOT merge.

## Running

`PYTHONPATH=src nice -n 19 /workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python -m pytest <files> -q -p no:cacheprovider --no-cov`

Run `ruff`, `black` and `mypy` from the same venv `bin/` on the touched files.
Use `&&` chains: the bash-safe-mode guard denies `;` sequences without a
prelude.
