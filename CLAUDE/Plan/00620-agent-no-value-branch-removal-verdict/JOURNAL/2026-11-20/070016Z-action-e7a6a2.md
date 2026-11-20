## 07:00 · action · —

Task 2.2 item 1 (the delete-branch CLI route) landed in b9353a8c3, tests first.

- `_delete_reject_route` in `daemon/cli.py` builds the `RejectRoute`: store under `main_checkout(repo) / branches.reject.state_dir`, ledger at `repo / branches.reject.ledger_path`, `default_ref` the resolved default (never the `--protected-ref` line), `now=time.time()`.
- Decision: a `RejectError` from `main_checkout` (bare repository, no main checkout) means NO route, not an error exit. The delete then runs exactly as before the route existed, so an unproven branch is refused and a proven one still deletes. The reason is printed ("The no-value route is unavailable here: ...") and carried in JSON as `reject_route_unavailable`. Failing closed this way costs nothing: no route can only refuse more.
- Output: JSON classifications carry `recovery_bundle`; the text prints a `recovery bundle:` line beside a `rejected-bundled` branch. The unproven refusal text now names `hooks-daemon branch-reject request <name>`; two tests in `test_cli_delete_branch.py` that pinned the old "never deleted by this command" sentence were updated to the new wording and also assert the route's refusal is shown.
- Targeted QA: ruff, black and mypy clean on the changed files; `test_cli_delete_branch*.py` pass. `llm_qa.py changed` not yet run on this branch.

Remaining in Task 2.2: the reviewer agent definition, `branch-reject request`, the dispatch gate, the SubagentStop recorder.
