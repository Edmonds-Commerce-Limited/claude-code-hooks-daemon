# Callout: branch-park writes a signed commit when the repository requires signing

**Plan**: 00594
**Audience**: client projects

`hooks-daemon branch-park` (and `--clear`, and the park a sub-agent makes before it stops) wrote its trailer commit with `git commit-tree`, which does not read `commit.gpgsign`. In a repository that requires verified signatures the park commit was therefore unsigned and the host refused the push of it; a client report found every sub-agent branch ending in one. The park now asks for a signature (`commit-tree -S`, so `user.signingkey`, `gpg.format` and `gpg.program` apply) whenever `git config --type=bool commit.gpgsign` is true. A repository that does not ask for signing behaves as before.

If signing is required but fails (no key, the signing program missing), the park stops with git's own reason and a hint naming the settings to check. It does not write an unsigned commit and it does not move the branch: the branch, its park record and the remote are left exactly as they were.
