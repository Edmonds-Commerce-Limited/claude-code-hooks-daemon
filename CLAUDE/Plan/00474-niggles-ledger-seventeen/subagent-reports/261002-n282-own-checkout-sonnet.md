# N282: own-checkout signal for in-process teammates

Outcome: Phase A found no reliable per-agent worktree signal. The guard is unchanged;
three characterisation tests pin today's behaviour; NIGGLES.md N282 holds the findings
and design options.

## Phase A facts

Observed:

- PreToolUse contract (`contracts/claude-code-hooks/PreToolUse.json`) and
  `core/handler_scope.py`: a teammate payload carries `session_id`, `transcript_path`,
  `cwd`, `agent_id` (30 chars), `agent_type`. No field names an assigned worktree.
- Plan 00464 (PLAN.md, JOURNAL 26-09-24): the daemon DEBUG log showed a teammate payload
  with `cwd: /workspace` while it worked in a worktree.
- `WorktreeCreate` carries `name`, `cwd`, `session_id`, no `agent_id`. A worktree the
  coordinator assigns by prompt fires no such event.
- This agent's harness note: an agent thread's cwd resets between Bash calls.

Not observed (inferred):

- A live teammate payload. `daemon.payload_capture` is off, I was told not to change
  config or restart, and `bin/hooks-daemon logs` from the worktree said "Daemon not
  running". So "payload cwd follows the coordinator's `cd`" is still inference from
  N282's report plus 00464's `/workspace` sample.

## Decision

No reliable signal, so no Phase B. N264's "never read agent_id for the role test" still
holds; using agent_id as a map key would be a new design (options 1/2 in NIGGLES.md),
not something the payload supports today.

## Tests

`TestOwnCheckoutIsTheCwdAlone` in
`tests/unit/handlers/pre_tool_use/test_subagent_worktree_write_guard.py`: 3 tests,
all pass on unchanged code (characterisation, so there is no RED). File: 36 passed.

## QA

ruff, black --target-version py311, mypy, pyright (0 errors) clean on the test file;
`scripts/qa/audit_error_hiding.py` and `check_input_contract.py` exit 0;
`tests/integration/test_bash_write_blindness_coverage.py` 73 passed. No source file
changed, so no source-file lint was needed.

## Not verified

- Live payload `cwd` for a teammate in either coordinator position.
- Whether `dispatch_declaration` can match an Agent prompt to an agent_id (option 2).
- No release note: behaviour did not change.
