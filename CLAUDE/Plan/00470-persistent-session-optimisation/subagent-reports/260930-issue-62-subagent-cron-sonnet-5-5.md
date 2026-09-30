# Issue #62 part 1: SubagentStop cron enforcer demanded CronCreate from subagents

## What the twin was for

`cron_subagent_stop_enforcer` was added by Plan 00416 Task 1.1 (commit 330e911d1) as the SubagentStop twin of `cron_stop_enforcer`. Its docstring gives one reason: "a subagent-only session can end without the main-thread Stop event ever firing". That premise does not support enforcing on a subagent. A SubagentStop always carries `agent_id`, and `session_crons` describes the coordinator's session, so the only party told to `CronCreate` was a finished subagent that cannot legitimately do so. The Stop twin was already scoped `MAIN` for this reason in Plan 00423 (issue #40), and `R-SUBAGENT-CRON-DELETE` applies the same ownership rule. The twin was simply missed then.

## Design choice

Candidate (a), by the existing mechanism: `scope=HandlerScope.MAIN` on the twin, matching the Stop twin. The chain applies it via `scope_admits`, so no `agent_id` logic in the handler and no duplicate discriminator. Candidate (b) has nothing to preserve: the twin's only job is to deny a subagent for a missing cron. Consequence, stated plainly: for real traffic the handler is now effectively dormant (real SubagentStops always have `agent_id`). I kept it rather than deleting it because it is a config-overridable handler (`scope: ALL` restores old behaviour), removing it would change handler IDs, docs and registration, and deletion is a separate owner call. The coordinator's own `Stop` remains the enforcement point for declared jobs.

## TDD

Red, before the fix (pytest on the twin's test file, 2 failed, 18 passed):

- `test_a_real_subagent_stop_is_not_admitted`: `AssertionError: assert True is False`, from `scope_admits(handler.scope, <SubagentStop payload with agent_id, session_crons=[]>)`
- `test_the_scope_is_main_like_the_stop_twin`: `assert <HandlerScope.ALL: 'ALL'> is <HandlerScope.MAIN: 'MAIN'>`

The handler-level test cannot call `handle()` to show the deny, because scope is applied by the chain before dispatch; the test asks the chain's own question (`scope_admits`). Green after the fix. Also added `test_the_main_thread_stop_twin_still_enforces`: a main-thread Stop with empty `session_crons` is admitted and DENIED.

The twin's DENY acceptance test used a payload with `agent_id`, which is exactly the case now out of scope, so it became an ALLOW acceptance test (`requires_main_thread=False`).

## Files

- `src/claude_code_hooks_daemon/handlers/subagent_stop/cron_subagent_stop_enforcer.py` (scope, docstring, acceptance test, `get_claude_md`)
- `src/claude_code_hooks_daemon/handlers/subagent_stop/__init__.py`, `src/claude_code_hooks_daemon/constants/handlers.py` (stale "subagent-only session" comments)
- `tests/unit/handlers/subagent_stop/test_cron_subagent_stop_enforcer.py`
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/183-a-finished-subagent-is-no-longer-told-to-create-the-coordinators-crons.md`

`docs/guides/HANDLER_REFERENCE.md` has no text on this handler, so no change there.

## Unverified

- No live SubagentStop was sent to a running daemon; verified through unit tests and `scope_admits` only.
- A Workflow-tool agent's payload is unmeasured (per `handler_scope.py`), so whether it carries `agent_id` is unknown.
