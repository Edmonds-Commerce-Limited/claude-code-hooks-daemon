# Callout: read-only git facts moved into `utils`, and two declared edges are gone

**Plan**: 00444
**Audience**: handler authors

Callout 16 introduced `tests/integration/test_qa_package_dependency_direction.py`
and listed four edges it declares rather than forbids. Two of them were
`docs_qa` importing `plan_qa.gitfacts` — documentation QA depending on plan QA
for read-only git plumbing that has nothing to do with plans. Those two are now
struck off; the allowlist holds two.

The declared reason said the class was "shared machinery that happens to live in
one subsystem", which was not quite right. `GitFacts` has eight members and
seven are generic, but `plan_counter()` reads `hooksdaemon.latestPlanNumber` and
is the whole reason the class sat in `plan_qa`. Relocating it wholesale would
have carried the plan counter into `utils` and moved the layering problem rather
than removing it.

So this is a split. `claude_code_hooks_daemon.utils.git_facts` now holds
`GitFactsBase` and `StagedChange`: staged changes with rename detection,
staged/HEAD file contents, and last-commit dates, all routed through `run_git`
and strictly read-only. `plan_qa.gitfacts.GitFacts` subclasses that base and
adds `plan_counter()` alone.

**No plan-QA caller changes.** `GitFacts` keeps its exact public surface and
`StagedChange` is re-exported from `plan_qa.gitfacts`, so
`from claude_code_hooks_daemon.plan_qa.gitfacts import GitFacts, StagedChange`
still resolves. If you want the generic half without pulling in plan QA — which
is the point of the move — import `GitFactsBase` from `utils.git_facts`.

**If you monkeypatch `run_git` for a test, patch it on `utils.git_facts`.** That
is where the name the code calls now lives; patching `plan_qa.gitfacts` reaches
only the plan-counter subclass. This repository's own `tests/unit/plan_qa`
fixture moved for exactly that reason.

Behaviour is unchanged, and the git-facts core has direct unit tests at its own
address for the first time rather than being exercised only through plan QA's
suite.
