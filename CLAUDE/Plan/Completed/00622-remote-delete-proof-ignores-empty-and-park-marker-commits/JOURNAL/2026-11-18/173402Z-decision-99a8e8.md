## 17:34 · decision · —

Fix round 2 for the loosening review (D1, D2).

D1: `patch_equivalent` drops only the park writer's markers again, as it did before this plan. It no longer drops every empty commit. A patch-id ignores whitespace, and with no merge base `git cherry` compares against the whole history. Excusing every empty commit there extended that weakness to any branch that carried one. Empty commits are now excused only by the lossless tiers:

- `empty-commits-only`: the tip's tree is in the default's history.
- the net-change proof.

So a cherry-picked branch with an empty commit on top is refused on the hook path, which has only patch-ids. The full local proof and the remote proofs pass it as `content-preserved`.

D2: `run_git` pins `GIT_NO_REPLACE_OBJECTS=1` and `GIT_GRAFT_FILE=/dev/null/no-grafts` for every daemon git call. Both are applied after the caller's env, so a caller cannot override them. Measured on git 2.47.3: `GIT_NO_REPLACE_OBJECTS` and `--no-replace-objects` do not disable `info/grafts`, so the graft file needs its own override. A path under `/dev/null` cannot exist, so git silently reads no grafts. `/dev/null` itself would also work, but it prints the graft deprecation hint. The pins are global rather than scoped to the proofs, because that one place covers every proof call site, `holder_of` and the delete itself.

Corpus: 57 shapes (9 new, all N). The before side was re-recorded against main's source. DENY to ALLOW: 18, all on Y or E shapes. 0 of them are on N. The `s-pick-empty` local-hook flip is gone. ALLOW to DENY: 12, all on the replace and graft shapes.
