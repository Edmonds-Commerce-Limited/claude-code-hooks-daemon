# Callout: `find -exec` and a merge-base listing are now followed

**Plan**: 00463
**Audience**: operators

`subagent_full_qa_blocker` now follows `find [paths] [tests] -exec cmd {} ;`
(also `+`, `-execdir`, `-ok`, `-okdir`): `{}` is judged as find's start paths,
wherever it appears in a word (`{}/`, `./{}`). A test such as `-name` only
selects a subset of them, so `find tests/unit/qa -name 'test_*.py' -exec pytest {} +`
is targeted and `find tests -name 'test_*.py' -exec pytest {} +` is full. A
changed listing narrowed to `git diff --name-only "$(git merge-base main HEAD)" -- tests | xargs -r pytest`,
quoted or not, is now accepted as targeted: a substitution that is exactly one
`git merge-base <rev>...` with no flag always prints one commit, never the
empty tree, so it cannot make the listing bare the way an arbitrary run-time
word can.

The launchers `ssh-agent cmd`, `pyenv exec`, `rbenv exec`, `direnv exec DIR`
and `conda`/`mamba`/`micromamba run` are followed to the command they run, and
a shell behind one still reads the code piped to it.

`python3 -c "$(cat f)"`, `bash <<< "$(cat f)"` and `bash /dev/stdin <<< "$(cat f)"` now read the file `f` the same way `bash -c "$(cat f)"` already did. A
pipe or process-substitution producer's word is expanded against variables
the command sets, so `F=f; cat $F | bash` reads `f` rather than treating the
path as absent. `bash -s` takes no script operand: every word after it is
positional, carried through to the file read from stdin, so `bash -s -- tests < arg1.sh` reads `arg1.sh` with `tests` as `$1`.
