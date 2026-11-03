# Callout: deleting many merged remote branches in one push is now judged within the dispatch budget

**Plan**: 00558
**Audience**: operators

`destructive_git` confirms each branch of `git push <remote> --delete a b c ...` against the remote's live tip with `git ls-remote`. It made one call per branch, so a 37-branch delete at about a second a call exceeded the handler's 20 s dispatch budget and was not judged at all (#153).

It now makes one `git ls-remote` per remote (split into calls of 500 branches only to keep the argument list bounded) and compares each branch with its own entry, matched by exact ref name. The verdict is unchanged: a delete is allowed only when every named branch is merged into the default branch and its live tip equals the tracking tip. A different tip, a branch absent from the listing, or a failed or timed-out call still denies, naming the branch.

Nothing to do on upgrade.
