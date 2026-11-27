# Callout: secret_file_guard no longer denies a quoted message that only names a protected glob

**Plan**: 00474
**Audience**: everyone

A Bash command (never authored Write/Edit script content, which is judged exactly as before) that is ONE statement, either `echo` with no option, `git commit` with a single `-m` message, or `gh issue|pr create` with a `--body` and/or `--title`, only prints or posts its quoted text. A glob inside that literal-quoted text is therefore no longer treated as a mention of a protected path. A literal protected name inside it still denies. Before this change, a commit message or echo that quoted a permission rule, named the secret-file glob, or held `*` or `**` was denied with R-SECRET-BASH-MENTION.

The exemption is deliberately narrow, and anything outside it is judged exactly as before:

- a pipe, chain or redirect
- a substitution or a backslash
- any other word or option, including a doubled flag such as `-m -m`
- a non-ASCII character outside the quotes
- `printf`, which can assign a variable with `-v`
- `teamchat`, whose message verbs read the text from stdin, so a teamchat heredoc or pipe is NOT covered

Related tightening: an `echo`/`printf` argument piped to a shell, or written to a script, is now judged again (`echo 'cat dir/*' | bash` was allowed).

The deny now names the CLASS of path that matched (for example "a secret-named file", entry N of M in the effective list) and the token's line and column, never the glob itself. A deny caused by a link out of the project, or by the directory cap, no longer also claims that the word matched a protected glob.
