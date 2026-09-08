# Callout: two plumbing synonyms for already-blocked destructive git commands are now closed

**Plan**: 00205
**Audience**: operators

`destructive_git` blocked `git push --force` and `git branch -D`, but not
their exact plumbing equivalents: a `+`-prefixed refspec (`git push origin +main:main`) and `git update-ref -d refs/heads/<name>`. Both are ordinary
spellings — the `+refspec` form appears in everyday CI/deploy scripts, and
`update-ref` was seen used to route around a blocked `git branch -D` under
pressure. Both are now denied under the same rule IDs as their porcelain
counterparts (`R-GIT-PUSH-FORCE`, `R-GIT-BRANCH-FORCE-DELETE`); nothing else
about `update-ref`'s ordinary create/move usage changed.
