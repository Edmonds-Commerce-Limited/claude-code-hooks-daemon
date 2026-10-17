# rfix-stopgate-isolation

## Assumptions

None needed. No release note: the change is tests-only (nothing under `src/` changed), and no existing
callout describes contract-harness behaviour.

## Cause

`tests/integration/test_acceptance_contract.py` initialises `ProjectContext` against the real repo and drives
every declared input in-process. `IdleWorkableIssueStopGateHandler` reads `ProjectContext.daemon_untracked_dir() / workable-issues.json`, so on a checkout holding a fresh cache the "no cache" case denied.

## Red test

`TestDeclaredInputsAreIsolatedFromHostState::test_a_fresh_workable_issues_cache_on_the_host_does_not_change_a_verdict`
points `ProjectContext` at a temporary "host" state dir holding a fresh cache (never /workspace's file), then drives
every declared input. Before the fix:

```
AssertionError: library:Stop/IdleWorkableIssueStopGateHandler::idle workable issue stop gate - an ordinary stop with no cache: expected decision 'allow', got 'deny'
1 failed, 2 passed
```

## Fix (harness layer)

The contract test body moved into `_contract_failures()`, which runs under `_isolated_state_dir()`: a context
manager that swaps `ProjectContext._instance` for a `dataclasses.replace` copy whose `daemon_untracked_dir` is an
empty temporary directory, restored afterwards. Project root, config and git facts stay real (the handlers are built
from them). A second test pins the restore. After the fix: 7 passed in the file.

The handler's declared playbook text is unchanged and stays accurate: its "no cache" case still describes the
state the handler needs, and the harness now supplies that state.

## Exposure audit (Stop / SubagentStop / SessionStart handlers reading untracked state)

Every handler with a BLOCKING acceptance case that reads state does so through `ProjectContext.daemon_untracked_dir()`,
so the one harness fix covers them: `idle_workable_issue_stop_gate`, `auto_continue_stop` (ledger, awaiting-human
marker, `stop-events.jsonl` which the contract run previously appended to in the real state dir),
`subagent_handoff_gate`, `background_task_recorder`. `unproven_venv_advisor` resolves via `get_untracked_dir(root)`
but is advisory (no BLOCKING case, never driven by this test). The `Path.cwd() / "untracked"` fallbacks in
`contract_staleness`, `gitignore_safety_checker`, `version_check` are likewise advisory SessionStart handlers.
Nothing else needed fixing.
