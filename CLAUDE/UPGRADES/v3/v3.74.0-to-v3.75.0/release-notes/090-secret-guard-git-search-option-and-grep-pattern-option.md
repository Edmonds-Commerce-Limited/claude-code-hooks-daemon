# Callout: the secret guard no longer treats every git -S/-G as a search value, or skips a grep path after -e

**Plan**: 00618
**Audience**: client projects

`secret_file_guard` stopped judging the word after a git search option as a path, so that `git log -S <string>` with a protected-looking string is allowed. That exemption assumed `-S` and `-G` take a search value on every git subcommand. They do not: on `git grep`, `-G` takes no value and the next word is a file git reads, and on `git blame`, `-S` names a file git reads and echoes back line by line. Both shapes are denied again for a protected path.

The exemption now applies only where the option really takes a value: `-S`/`-G` on `log`, `show`, `whatchanged`, `diff`, `diff-tree`, `diff-index` and `format-patch`, and `--grep`/`--author`/`--committer`/`--grep-reflog` on `log`, `show`, `whatchanged`, `rev-list` and `format-patch`. It also no longer applies after `--` or `--end-of-options`, when a git global option the guard does not recognise comes before the subcommand, or when the word before a separate `-S` could take `-S` as its own value (`git log --until -S <path>` makes the path a pathspec).

The grep/rg check that lets a `--include=*` or `-g '*'` filter through over clean directories assumed the first operand is always the pattern. When the pattern is attached to its option (`-e<pattern>`, `--regexp=<pattern>`, a cluster such as `-ve<pattern>`, `-f<file>`, `--file=<file>`), after `--`, or with `rg --files`, that first operand is a searched directory. Such a command is no longer judged clean, matching what the separate `-e <pattern>` spelling already got.

Every change makes the guard deny more, never less. A command that is now denied and should not be can be rewritten with the search value in a form the guard reads (`git log -S <string>` rather than after another option), or the filter can be given a pattern operand instead of `-e`. Protected patterns and config defaults are unchanged.
