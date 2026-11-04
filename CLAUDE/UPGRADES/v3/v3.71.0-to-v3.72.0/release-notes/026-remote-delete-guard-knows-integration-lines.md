# Callout: the remote-branch delete guard accepts branches merged into an integration line, and never deletes a line

**Plan**: 00558
**Audience**: operators

`destructive_git` allows `git push <remote> --delete <name>` only for a branch it can prove merged. It now also counts a branch whose remote-tracking tip is an ancestor of any `refs/remotes/<remote>/<line>` for a `branches.integration_lines` glob (for example `release/*`), not only of the default branch; the proof is one `git for-each-ref --merged` per target over all the named branches, so a 40-branch delete costs a fixed handful of local calls plus the single `git ls-remote` (#153).

It also refuses outright, whatever the proof and with a reason naming which, the default branch, an integration line itself, a `branches.exempt` name and a `branches.protected_names` name. The handler reads the top-level `branches:` block; with none, the model defaults apply (no lines, no exemptions, protected `main`, `master`, `develop`, `trunk`), so a remote `develop` that was deletable when merged is now refused.

Nothing to do on upgrade.
