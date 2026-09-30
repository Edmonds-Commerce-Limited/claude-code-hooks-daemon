# Callout: the merge-approval and issue-filing gates close three gaps

**Plan**: 00408
**Audience**: client projects

With `worktree.merge_to_main_requires_human_approval` on, `git pull <remote> <branch>` into the default branch is now gated like the equivalent
`git merge`. A pull naming no branch, or naming the default branch itself, is
still an ordinary update. A merge whose branch is not in the command text
(`... | xargs git merge`) is now gated under the approval key
`unnamed-branch` instead of being read as "not a merge". Separately,
`issue_filing_gate` now reads every git remote in the working directory, not
only `origin`. Before, a clone whose only remote was named `upstream` filed
against the public tracker with the gate standing down. `--repo` still wins
over the remotes.
