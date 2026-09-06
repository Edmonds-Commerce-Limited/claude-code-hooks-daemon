# I5 investigation — `deploy_core_docs_if_enabled` directory targeting

## Verdict: not a defect to fix; the coupling is deliberate and already tested

The mechanism reported is accurate — I confirmed empirically (`untracked/scratch`
repro script) that with `workflow_docs: docs/agent/PlanWorkflow.md` and
`documentation.enabled: true`, all three documents (`PlanWorkflow`, `Worktree`,
`DocumentationStrategy`) land under `docs/agent/`, none under `CLAUDE/`.

But this is Plan 00334's **deliberate** design (Decision 7 in its
`DECISIONS.md`), not an oversight, and it is already guarded by a passing test:
`tests/unit/install/test_core_doc_deployment.py::TestTheDeployFollowsTheConfiguredPath::test_nothing_is_written_to_the_default_tree`
asserts nothing lands in `CLAUDE/` (including `CLAUDE/core`) once `workflow_docs`
moves. Decision 7's own text: *"The other core documents have no config key of
their own and keep canonical names in that same directory"* — i.e. the same
directory as `workflow_docs`, precisely so a project that moved its docs tree
doesn't also acquire a stray `CLAUDE/` it never asked for.

Applying the proposed fix (pin `Worktree`/`DocumentationStrategy` to a
hardcoded `CLAUDE/`) would **regress that tested behaviour** — it reintroduces
the exact scattering the existing test guards against, for any project that
moved its docs tree.

Plan 00334's own `DECISIONS.md` "Known residuals" section already names the
*actual* remaining defect and scopes it out of this module: `worktree_file_copy.py`
and `docs_qa/checks/rules_file_shape.py` hardcode the literal strings
`CLAUDE/Worktree.md` / `CLAUDE/DocumentationStrategy.md` in their guidance TEXT,
independent of *any* config (not `workflow_docs`, not even
`documentation.trees.agent`). The author explicitly deferred fixing those
strings ("making rule text configuration-aware in general... its own change")
rather than fixing the deploy target — because the deploy target was correct
for the reason above. Re-pointing the deploy to a hardcoded `CLAUDE/` doesn't
even fully solve the general problem either (a project that renamed
`documentation.trees.agent` away from `CLAUDE` while leaving `workflow_docs`
default would still get a stale guidance string).

## The `parent == "."` concern

Not a bug — already correctly handled and tested. `PurePosixPath("PlanWorkflow.md").parent`
is `"."`, and `Path / "."` collapses to the same path in pathlib (verified:
`Path('/tmp/project') / '.' == PosixPath('/tmp/project')`), so `project_root / "."`
never scatters into a literal `./` directory. This is pinned by the existing
`test_a_top_level_document_lands_at_the_project_root`, which asserts
`core/PlanWorkflow.core.md` correctly lands at the project root — no change needed.

## What I changed

Added one characterization test,
`TestTheDeployFollowsTheConfiguredPath::test_worktree_and_documentation_strategy_travel_with_it`,
in `tests/unit/install/test_core_doc_deployment.py`, extending existing coverage
(which only exercised `PlanWorkflow`) to pin that `Worktree` and
`DocumentationStrategy` travel with `workflow_docs` too, and documenting why in
its docstring — to stop a future pass from "fixing" this the way I5 proposed.
No changes to `src/claude_code_hooks_daemon/install/core_docs.py`.

Test run: `tests/unit/install/test_core_doc_deployment.py`,
`test_core_docs.py`, `test_shipped_asset_citations.py` — 105 passed.
