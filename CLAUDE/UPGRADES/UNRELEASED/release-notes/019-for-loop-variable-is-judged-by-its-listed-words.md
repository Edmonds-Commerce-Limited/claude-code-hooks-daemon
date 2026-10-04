# Callout: a `for` loop variable is judged by the words the loop lists, not as a lone `*`

**Plan**: 00474
**Audience**: everyone

`secret_file_guard` read every `$VAR` it could not resolve as a lone `*`, and expanded that `*` against the working directory. `cd untracked; for d in repos/* worktrees/*; do git -C "$d" ls-files; done` was therefore denied as `R-SECRET-BASH-MENTION` whenever the directory the command ran in held a protected file, although no listed word reaches one.

Inside its own loop body, a `for` variable now stands for the words the loop lists, so each `dir/*` word is judged as written. A word that reaches a protected file is still denied, both as a listed word and through the variable. The variable keeps its `*` (and the denial) whenever the command could change it another way: it is assigned, read into, declared, unset or `eval`ed anywhere, two loops use the same name, the command holds a heredoc or `$'...'`, or the list holds a command substitution. A use before the loop, a use outside the body, a `${d%/}` style operator and a use inside a nested `$(...)` also keep the `*`.
