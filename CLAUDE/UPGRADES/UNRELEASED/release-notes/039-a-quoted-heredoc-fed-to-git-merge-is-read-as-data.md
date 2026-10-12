# Callout: a quoted heredoc fed to git merge is read as data

**Plan**: 00474
**Audience**: everyone

`git merge` was missing from the set of git subcommands whose heredoc body is read as data, although `git commit` and `git tag` were in it. A quoted heredoc fed to `git merge` (`git merge topic -F - <<'EOF'`) was therefore tokenised as shell, and an apostrophe in the body ended the read: `project_containment` then allowed the call but printed "could NOT fully judge this call ... report it". `merge` is a git built-in that no alias can shadow and it never runs its stdin, so it now joins the data subcommands. An unknown or aliasable subcommand with the same body is still scanned.
