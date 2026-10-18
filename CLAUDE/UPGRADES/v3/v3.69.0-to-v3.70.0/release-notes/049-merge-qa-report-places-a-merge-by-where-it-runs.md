# Callout: the merge QA report places a merge by the directory it runs in

**Plan**: 00474
**Audience**: client projects

`merge_qa_report` decided whether a `git merge`, `git pull` or `git rebase` belonged to the project by the session's working directory alone. A merge run as `cd <nested repo> && git merge ...` or `git -C <nested repo> merge ...` was therefore read against the project, and the report described an operation that never happened there. The handler now places the merge the way `daemon_sync_after_merge` already did: by the `cd`, `pushd` or `git -C` in effect at the merge, falling back to the session directory when the target cannot be worked out statically (`cd $DIR`). A merge inside a nested or vendored checkout is left alone, and a plain merge at the project root is reported as before. Both handlers now share one function, `merge_directory` in `utils/merge_scope.py`.
