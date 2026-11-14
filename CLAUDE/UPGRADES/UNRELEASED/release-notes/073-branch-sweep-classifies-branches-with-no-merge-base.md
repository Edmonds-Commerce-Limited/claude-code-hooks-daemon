# Callout: branch-sweep classifies branches that share no history with the default branch

**Plan**: 00605
**Audience**: operators

A branch with no merge base against the default branch (an orphan branch, or any branch left behind when the default branch's history was rewritten) used to come back `UNCLASSIFIED` with a reason blaming the sweep budget, and so counted toward `branches.wip.cap` with no way to clear it. It is now measured and classified as unmerged work (never merged, contained or patch-equivalent, even when its commits repeat patches the default branch holds), with its whole tip counted as its lines. In a shallow clone whose fork point was not fetched it stays unclassified, with a reason saying the history was not fetched. An unclassified branch's reason now names its real cause (the budget ran out, git failed, or history not fetched), and `branch-sweep --budget-ms N` overrides `branches.sweep.budget_ms` for that run only.
