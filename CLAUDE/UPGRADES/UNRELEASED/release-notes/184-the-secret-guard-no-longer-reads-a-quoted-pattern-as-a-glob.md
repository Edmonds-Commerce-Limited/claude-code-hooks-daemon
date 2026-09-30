# Callout: the secret guard no longer reads a quoted pattern as a glob

**Plan**: 00474
**Audience**: operators

`secret_file_guard` judged every word that looked like a glob as though bash
would expand it, including a regex in `grep -E "^tests/.*py:[0-9]+"`, the text
of an `echo` or a `gh` comment body, and the body of a quoted heredoc fed to
`cat`. Those were denied as mentioning a protected path (issue #66, ledger
00474 N269 and N256). Bash never globs quoted text, and these commands only
print or search it, so they are now allowed.

Only the operands of a text consumer are relaxed: a `grep`/`rg`/`awk` pattern,
`echo`/`printf` arguments, a `gh` body or title, a commit message, and a
sink-fed quoted heredoc body. A quoted word that names a protected path is
still denied, an unquoted glob is still expanded and checked, and so is quoted
text given to a program that globs it (`python -c`, `bash -c`, `find -name`,
`rg -g`, `grep --include`).
