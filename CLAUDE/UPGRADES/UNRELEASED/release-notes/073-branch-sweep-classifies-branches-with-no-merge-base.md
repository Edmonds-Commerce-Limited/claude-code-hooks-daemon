# Callout: branch-sweep classifies branches that share no history with the default branch

**Plan**: 00605
**Audience**: operators

A branch with no merge base against the default branch (an orphan branch, or any branch left behind when the default branch's history was rewritten) used to come back `UNCLASSIFIED` with a reason blaming the sweep budget, and so counted toward `branches.wip.cap` with no way to clear it. It is now measured and classified as unmerged work, with its whole tip counted as its lines. An unclassified branch's reason now names its real cause (the budget ran out, or git failed), and `branch-sweep --budget-ms N` overrides `branches.sweep.budget_ms` for that run only.
