# Guard-defects gate fix (260925, Sonnet 5)

Brief: `untracked/scratch/briefs/gd-gatefix.md`. Worktree
`worktree-n466-guard-defects`, HEAD before this round `a80785d03`. The full
gate had failed 3 of 39 checks (tests, error_hiding, plan_qa).

## Merge

Merged `main` first (N81-N89 ledger rows, N47 status change). Only
`CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md`'s niggles table conflicted
(`NIGGLES.md` auto-merged cleanly, including N16's placeholder note
resolving correctly to this branch's real N16 write-up). Resolved by union of
every row from both sides, each row's most advanced status: N10/N11/N39 kept
this branch's `✅ Remedied` (they carry the actual fix content; `main`'s
`🔄 In progress` reflected that N16/N39's fix was still only on this
unmerged branch), N80-N89 joined from `main`.

## The 4 test failures: one shared root cause

`test_sed_blocker_prevents_inline_edits_e2e`,
`test_disabled_handler_does_not_block_e2e`,
`test_configured_extra_whitelist_allows_its_command`, and
`test_audit_error_hiding.py::TestRealRepoSelfScan` (the last only once the
error_hiding fix below landed) were not four separate defects.

**Root cause**: `ProjectContainmentHandler.matches()` calls
`_offending_targets_or_error()`, which calls `self._resolved_root()`
(`ProjectContext.project_root()`) UNCONDITIONALLY, before checking whether
the command names any write target at all
(`src/claude_code_hooks_daemon/handlers/pre_tool_use/project_containment.py:392-395`).
Real daemon startup always calls `ProjectContext.initialize()` before
routing (`daemon/controller.py:274`), so in production this eager resolve
never raises. But the three failing tests built an `EventRouter` +
`HandlerRegistry` and called `router.route()` directly, without
initializing `ProjectContext` — which `project_containment` (registered by
default, priority 14, independent of what the test's own config touches)
now treats as an evaluation failure and denies for, per the Plan 00466 N11
fail-closed fix that IS this branch's own prior work
(`d0de526d1`, only on this branch, not on `main`). Confirmed with a
`git branch --contains` check.

Concretely: `sed_blocker` (priority 15) and `pipe_blocker` (priority 15,
via `_register_with_options`) both run AFTER `project_containment` (14) in
priority order, so `project_containment`'s universal-deny pre-empted them
before they ever got to render their own verdict. `destructive_git`
(priority 10) runs BEFORE `project_containment` in the one test that
explicitly overrides its priority, so that test never observed the bug —
but `test_disabled_handler_does_not_block_e2e` disables `destructive_git`
entirely, so `project_containment` (default-registered, priority 14) picks
up `git reset --hard HEAD` on its own and denies it too.

**Is this a product defect?** In production `ProjectContext` is always
initialized first, so the eager-resolve ordering is inert there — only a
harness that constructs the router without a live `ProjectContext` sees it,
and every OTHER passing e2e test in these two files was either lucky on
priority order or already using the established `project_context`/
`_project_context` fixture. Fixed by initializing `ProjectContext` in the
three affected tests via those existing fixtures (matching what real daemon
startup does), not by touching `project_containment` itself — the fail-
closed behaviour it exercises is exactly Plan 00466 N11's intended fix.

**Worth a niggle anyway**: `matches()` resolving the root before checking
`_named_targets()` means ANY caller that routes even ONE event through a
`ProjectContext`-uninitialized process now gets a universal deny from
`project_containment`, not a narrowly-scoped one. That is arguably too
broad a blast radius for a guard whose own docstring frames it as "at least
one out-of-root write target" — a command with plainly zero possible write
targets (e.g. `ls`, `git log`) still pays the eager resolve and, in an
uninitialized process, still gets denied. Recommend a follow-up niggle:
short-circuit `matches()`/`_offending_targets_or_error()` on an empty
`_named_targets()` result before resolving root, so only a command that
actually NAMES a target pays for (and can fail on) the resolve. Not fixed
here — narrower than this round's scope, and the current behaviour is
provably safe (deny, never allow) even though it is broader than strictly
necessary.

## error_hiding (2 violations, same function)

`secret_file_guard.py::_parse_python_fragment` had a bare
`try/except/continue` (silent-continue, line 608) in its two-attempt retry
loop, and a bare `try/except: return None` (return-none-on-error, line 613)
on its third and final attempt. Restructured to the codebase's own
established "surfaced fallback" shape (already used elsewhere in this same
file, e.g. its neighbouring `handle()` methods): each retry logs at debug
before continuing (a 2-statement handler body — the checker's silent-
continue/log-and-continue rules both key on a single-statement body, so
logging alone does not clear them, and adding the explicit `continue` after
it does), and the final attempt logs at WARNING (the checker's
`_SURFACING_LOG_LEVELS`) and returns the parse result through a local
variable rather than a literal `return None` inside the except handler
(the `return-none-on-error` rule scans literally for `Return` nodes inside
a handler body, so no amount of logging clears it — only moving the
`return` outside the `try` does).

Verified the "not provable" `None` fails closed at both existing callers:
`_python_shell_exec_literals_ast` returns `None` up when
`_parse_python_fragment` does, and its own caller falls back to the
(weaker, more conservative-leaning-to-flag) regex heuristic rather than
silently treating unparseable content as "no shell-exec calls" — i.e. the
None path was already fail-closed before this fix; this fix only satisfies
the audit's syntactic shape requirements without changing behaviour.

## plan_qa (1 advise finding)

`journal-entry-ordering`: two `20:21` entries in
`00466-Journal-26-09-24.md` appeared after a `21:07` entry. Per the
checker's own remediation, appended a `correction` journal entry
(`mkplan.bash --journal 466 correction ... --ref 26-09-24/20:21`) rather
than editing the append-only day-file.

## Verification

- Targeted tests: 988 passed (`test_handler_config_blocking.py`,
  `test_registry_option_injection.py`, `test_audit_error_hiding.py`,
  `test_secret_file_guard.py`, `test_secret_file_matching.py`).
- ruff, mypy, pyright, black: clean on every touched file.
- Daemon restarted from the worktree, verified `RUNNING`.
- Gate queued in the background at commit `b0b0a7d71`; not waited on.

## Commit

`b0b0a7d71` — "Ledger 00466: gate fix round - 4 test failures, 2
error_hiding, 1 plan_qa"
