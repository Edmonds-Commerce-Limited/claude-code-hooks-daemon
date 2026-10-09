# Callout: agent dispatch branches now count as work branches

**Plan**: 00474
**Audience**: operators

`branch_count_advisor` and `merge_qa_advisor` used to recognise a work branch only by the `worktree-` prefix. A sub-agent dispatched with `isolation: worktree` works on an `agent-<hex>-<hex>` branch, so those branches were left out of the open-branch count, and merging one drew no advice about recorded QA. Both handlers now treat `agent-*` branches as work branches too. A session that keeps many old agent branches will see the branch-count advisory name them until they are merged or deleted.
