# Stop-guard handoff 3: fixing the PR 226 review (context budget)

Brief: fix F1-F9 of `261123-opus-independent-review-pr226.md` TEST-FIRST, one finding per red
test then fix, commit and push each; apply the coordinator's `on_unreadable_bus` decision; comment
on PR 226. Worktree `.claude/worktrees/agent-a6d1fc9ca72dfceff-148fd440`, branch
`plan-00636-stop-guard`. Python: `untracked/venv-workspace_claude_worktrees_agent-a6d-7f9b-py313-0d6d49c6/bin/python`
with `PYTHONPATH=src`, under `nice -n 19`, targeted tests only.

## Done

- Review filed (commit f954e7c8f).
- F1 red test: `tests/unit/handlers/stop/test_owner_wait_stand_in_cooperation.py` (real
  `HandlerChain`, real guard + real `auto_continue_stop`, readable fake bus). 2 of 5 fail as
  expected (stand-in headline missing from the merged deny).

## Decided design (with the advisor)

- **F1: merge, do not move.** Placing the guard after `auto_continue_stop` is forbidden by
  `tests/integration/test_stop_chain_terminal_shadowing.py::test_nothing_is_registered_after_the_handler_that_breaks_the_chain`.
  Extract from `AutoContinueStopHandler._stand_in_block` into `utils/stand_in_cron.py`:
  `stand_in_requirement(hook_input, *, config, delay_hours) -> BlockingResult | None` (autonomy
  `environment_allowed`, focus, `persistent_crons.enabled`, then `stand_in_verdict`) and
  `configured_delay_hours(config)` (reads `handler_options(config.handlers.stop.get("auto_continue_stop"))`
  `stand_in_delay_hours`, default on a `delay_hours_problem`). auto_continue calls it (keeps its
  `under_rule`). The guard gains a `_config_loader: Callable[[], Config]` seam (the test sets it;
  also feed `_team_seat_config` from it) and, when it denies and `_declares_human_blocked(text)`,
  appends the stand-in reason. The test's `_Bus` already has `flags_readable()`.
- **F3:** in `stop_hook_helpers` add `latest_stop_hook_block_text(path, lookback)` (text of the
  most recent "Stop hook feedback:" content or `hook_blocking_error` `blockingError`). Guard
  `matches()`: `stop_hook_active` + unreadable transcript = stand down (N411); a latest block
  carrying `R-STOP-OWNER-WAIT-UNBUMPED` = stand down (one refusal); otherwise (spurious, or another
  handler's block) evaluate. Verify the headline really lands in the marker text (the deny is
  `under_rule`, reason begins `BLOCKED [R-STOP-OWNER-WAIT-UNBUMPED]`).
- **F2:** widen only the guard's own regexes (never `_HUMAN_BLOCKED_PATTERNS`, frozen). Search
  all declaring text after the first `STOPPING BECAUSE:`, quoted spans excluded; red test = the
  review's 8 probe rows verbatim plus `not waiting on any user input` (negation: a not/no/never/n't
  in the same clause before the match). Unreadable transcript (not re-entry) with a runtime =
  matched, handled as unconfirmed under the bus policy.
- **F4:** arm via `TeamRoleAnswer.guards_armed` (`teamchat_seat.py:228`); unresolved probe or
  unknown role = `_Unconfirmed` under the policy; declared worker and no runtime stay untouched.
- **F5:** any exception in `handle()` for an armed coordinator DENIES regardless of policy (one
  refusal, not a loop); cover `matches()` raising; update the reason in
  `tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`.
- **Coordinator decision:** `on_unreadable_bus: auto | refuse | allow`, default `auto` = `refuse`
  where the adapter's `flags_readable()` is True (v2), else `allow` (v1) with an ADVISORY naming the
  team and thread classes it could not check (v1 cannot list thread ids). Add `flags_readable()` to
  the `OwnerWaitBus` protocol (`TeamchatOwnerWaitBus` returns False). Do NOT write a literal
  `refuse` into `init_config`, `.claude/hooks-daemon.yaml` or the example. Rewrite
  `test_default_is_refuse` and the invalid-value test deliberately. Check how a Stop ALLOW with
  context reaches the model (response-validation tests).
- **LOW:** F6 `bump_command` adds `--team`; F7 strip thread-id shapes and stopwords, `bump Q61`
  and `still waiting on @owner` must not count; F8 make `started_at` required and document seconds
  (Matrix ms must be converted); F9 check `ModeLabel.AWAITING_HUMAN` only, not `is_blocked`.

## Left

All fixes above, then docs (HANDLER_REFERENCE, CONFIGURATION, release note under
`RELEASES/UNRELEASED/`, config-changes yaml, PLAN.md / DESIGN.md 20.1 and the OPEN point, noting the
coordinator asked for `auto`, which is fail-open by design on v1 with the advisory as its only
effect), regenerate HOOKS-DAEMON.md and the CLAUDE.md block, journal via `mkplan.bash --journal`,
light QA (targeted tests, stop-chain shadowing, response-validation, tests/unit/config, ruff,
black, mypy), push, comment on PR 226.
