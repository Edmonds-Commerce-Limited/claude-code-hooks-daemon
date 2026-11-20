# Callout: destructive_git no longer denies printed git text that is captured or reformatted

**Plan**: 00596
**Audience**: client projects

`destructive_git` denied commands that only PRINT the words of a destructive git command when the printed text was captured or reformatted. Two shapes are now data:

- **A print-only capture.** `msg=$(printf '%s\n' 'then git push origin --delete b'); echo "$msg"` and `echo "$(printf ...)"`. A substitution whose body is one `printf`/`echo` of literal words is no longer a "substitution that can run a delete" when the WHOLE command only prints: every segment is a plain `NAME=$(...)` assignment of it, an `echo`/`printf` (not `printf -v`) of literal words or of that variable with no redirect, or a data-sink pipe stage given options only. Anything else anywhere in the command (another command, a redirect, `declare -n`, `${!r}`, a variable in command position) keeps the original verdict.
- **A text formatter.** `printf '...git reset --hard' | fold -w 40`. `fold`, `fmt`, `nl`, `expand`, `unexpand`, `paste`, `rev` and `tac` join `tr`, `cut` and `column` as pipeline stages that only reshape text.

Text that may be executed keeps its verdict: a substitution in command position, `eval "$(...)"`, `bash -c "$(...)"`, `source <(...)`, a pipe into `sh`, `bash`, `xargs` or any program the guard cannot classify, a body that runs git, and a captured variable later run (`$msg`, `eval "$msg"`, `bash -c "$msg"`).

Newly denied, because they run the written text: a script written earlier in the command and fed to a shell on stdin (`echo '...git reset --hard' > s.sh; sh < s.sh`, `cat s.sh | sh`, including through `exec`/`env`/`command` and a `cp`/`mv` copy), and a `printf -v n '...git reset --hard'` whose `$n` is later expanded outside a plain print.
