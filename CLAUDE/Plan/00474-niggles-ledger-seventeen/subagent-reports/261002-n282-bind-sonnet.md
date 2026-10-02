# N282 bind agent to first worktree (sonnet)

Branch `worktree-n282-bind-agent-checkout`. Implements option 1 of ledger 00474 N282.

## Change

- `subagent_worktree_write_guard.py`: in-memory `OrderedDict` of `agent_id` to linked `Checkout`, behind a `threading.Lock`, capped by `MAX_BINDINGS` (256, least recently used evicted). `_crossing` is now an instance method returning `(own, target, bound)`.
- Unbound or no `agent_id`: the cwd rule, unchanged. A first write the cwd rule allows, into a linked worktree of the cwd's repository, binds. A first write the cwd rule denies, or one into the main tree, binds nothing (design choice: a denied crossing must not become the agent's home).
- Bound to W: write into W allowed whatever the cwd (cwd is not even resolved, so an undecidable cwd cannot stop it); any other checkout of the same repository denied, including from a main-tree cwd; outside the repository or another repository untouched. Undecidable target stays fail-open, as before.
- Deny message adds the bound-from-first-write line and the target path.
- Docstring and `get_claude_md` state that `agent_id` is only a map key, never the role test, and that a daemon restart forgets bindings.
- Tests: `TestOwnCheckoutIsTheCwdAlone` replaced by `TestUnboundAgentsFallBackToTheCwd`, `TestFirstWriteBindsTheAgentToItsWorktree`, `TestBindingsAreBounded`, `TestConcurrentCalls`; `test_a_subagent_in_the_main_tree_is_not_judged` now uses two agent ids (the same id binding to A then writing the main tree is correctly denied).
- Release note 208; NIGGLES.md N282 decision, outcome, status.

## Interpretation note

The brief says "bind, then judge as today". I bind only when the cwd rule allows the write, so a first write denied by the cwd rule (cwd in sibling A, target W) still denies and binds nothing; the agent stays unbound there until a write the cwd rule allows. That keeps the N264 crossing from laundering itself by retry, at the cost that the false deny persists for an agent whose very first write happens while the shared cwd is a sibling.

## Verification

RED before the implementation: 11 failed, 40 passed on the handler's test file. GREEN after: handler tests plus `tests/integration/test_bash_write_blindness_coverage.py` 124 passed (worktree copy imports, `-o pythonpath="src ."`). ruff, black `--target-version py311`, mypy clean; pyright 0 errors (needs `--pythonpath` of the venv interpreter to resolve pytest); `scripts/qa/audit_error_hiding.py` and `scripts/qa/check_input_contract.py` pass.
