# Callout: destructive_git no longer denies printed git text that is captured or reformatted

**Plan**: 00596
**Audience**: client projects

`destructive_git` denied commands that only PRINT the words of a destructive git command when the printed text was captured or reformatted. Two shapes are now data:

- **A print-only capture.** `msg=$(printf '%s\n' 'then git push origin --delete b'); echo "$msg"` and `echo "$(printf ...)"`. A substitution whose body is one `printf`/`echo` of literal words, and whose output lands only as a variable's value or a printing command's argument, is no longer a "substitution that can run a delete".
- **A text formatter.** `printf '...git reset --hard' | fold -w 40`. `fold`, `fmt`, `nl`, `expand`, `unexpand`, `paste`, `rev` and `tac` join `tr`, `cut` and `column` as pipeline stages that only reshape text.

Text that may be executed keeps its verdict: a substitution in command position, `eval "$(...)"`, `bash -c "$(...)"`, `source <(...)`, a pipe into `sh`, `bash`, `xargs` or any program the guard cannot classify, a body that runs git, and a captured variable later run (`$msg`, `eval "$msg"`, `bash -c "$msg"`).
