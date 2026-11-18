# Callout: the search guards fail closed on a shell-state tilde and follow a cd before git -C

**Plan**: 00618
**Audience**: client projects

`secret_file_guard` and `flaggable_content_channel_guard` crashed on a search root or `git -C` value starting `~+`, `~-` or `~N` (bash's `$PWD`, `$OLDPWD` and directory-stack forms). The secret guard turned the crash into an advisory allow, so `git -C ~+/<dir> grep --no-index -e .` still read a protected file under `<dir>`. Both guards now deny any search through such a tilde, and through an unknown `~user`. That includes a `cd ~-` earlier in the command and a `git grep` pathspec under the tilde. `~` and `~user` for a real user are placed at the home directory as before.

`flaggable_content_channel_guard` also placed a literal `git -C` only from the payload working directory. It now places the `-C` from where the shell is after an earlier `cd`/`pushd` as well, including one inside `( ... )`, and denies when either placement reaches the flagged directory. It denies a `-C` value that an `xargs -I`/`--replace` token or `parallel` substitutes. A `git -C` that resolves above the project, such as `git -C .. grep --no-index`, is judged as reading the whole project.

Every change makes the guards deny more, never less. A command that is now denied and should not be can name the directory literally instead of through a tilde or an `xargs` token. Protected patterns, flaggable globs and config defaults are unchanged.
