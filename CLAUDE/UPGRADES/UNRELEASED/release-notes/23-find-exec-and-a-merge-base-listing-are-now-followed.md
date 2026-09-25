# Callout: `find -exec` and a merge-base listing are now followed

**Plan**: 00463
**Audience**: operators

`subagent_full_qa_blocker` now follows `find [paths] [tests] -exec cmd {} ;`
(also `+`, `-execdir`, `-ok`, `-okdir`): `{}` is judged as the files find
selects, which is find's own start paths when nothing narrows them, and
unseen (denied) once a `-name`/`-path`/`-regex` test is present, since the
files actually selected then cannot be read from the command line. A changed
listing narrowed to `git diff --name-only "$(git merge-base main HEAD)" -- tests | xargs -r pytest` is now accepted as targeted: `git merge-base` always
prints a commit, never the empty tree, so it cannot make the listing bare the
way an arbitrary run-time word can.

`python3 -c "$(cat f)"`, `bash <<< "$(cat f)"` and `bash /dev/stdin <<< "$(cat f)"` now read the file `f` the same way `bash -c "$(cat f)"` already did. A
pipe or process-substitution producer's word is expanded against variables
the command sets, so `F=f; cat $F | bash` reads `f` rather than treating the
path as absent. `bash -s` takes no script operand: every word after it is
positional, carried through to the file read from stdin, so `bash -s -- tests < arg1.sh` reads `arg1.sh` with `tests` as `$1`.
