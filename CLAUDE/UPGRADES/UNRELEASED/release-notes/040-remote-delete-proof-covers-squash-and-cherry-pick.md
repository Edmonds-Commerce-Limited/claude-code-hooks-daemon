# Callout: a squash-merged or cherry-picked remote branch now counts as merged

**Plan**: 00594
**Audience**: client projects

The proof that a remote branch is merged used to be ancestry only, so a branch merged by squash (several commits into one), by a renamed pull request, or by cherry-pick stayed "open" and its remote delete was refused. The proof now tries ancestry, then patch-id (`git cherry`), then tree containment (every file version on the branch is byte-identical to one in the default branch), all offline. The `git push --delete` guard, `branch-sweep --clean --remote` and the branch-creation cap all read the same proof, so an agent may delete such a branch, the sweep deletes it behind its recovery bundle, and it no longer counts against the open-branch cap once the proof has run. A branch with even one commit the default branch never took stays unproven. Results are cached by tip in `untracked/branch-inventory/cache.json` (new `proofs` key; older caches load unchanged).
