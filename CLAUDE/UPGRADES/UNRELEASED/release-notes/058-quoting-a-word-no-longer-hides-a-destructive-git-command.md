# Callout: quoting a word no longer hides a destructive git command

**Plan**: 00408
**Audience**: everyone

`destructive_git` now reads a command after removing the quoting that bash
removes from inside a word. `git checkout "--" f.txt`, `git push origin "--force"`, `git push origin '+main:main'`, `git checkout "."` and
`git "reset" --hard` were all allowed before, although git receives exactly
the same arguments as the unquoted spelling. `git_stash` got the same fix
(`git "stash"` now stashes and `git stash 'pop'` now recovers). Quoting that
bash keeps is left alone, so a commit message such as
`git commit -m 'document --amend'` is still prose and still allowed.
