# Callout: a grep pattern inside a command substitution is no longer read as a glob

**Plan**: 00474
**Audience**: operators

`secret_file_guard` already allowed a quoted `grep`/`rg`/`awk` pattern or `echo`
text, because bash never globs quoted text and those commands only search or
print it. That relaxation was not applied to a command inside a command
substitution, a backtick pair or a process substitution, so
`x=$(grep '^tests/.*test_.*\.py$' list.txt)` was denied as mentioning a
protected path (ledger 00474 N291).

The text inside each substitution is now treated as a command of its own. Only a
`grep` pattern is relaxed there: a substitution's output becomes words of the
outer command and is glob-expanded, so the quoted text of `echo`, `printf`,
`rg -r` or an `awk` program stays judged inside one (`cat $(echo 'prefix*')` is
still denied). Nothing else relaxes: a file the
inner command reads (`cat`, a `grep` file operand, `grep -f`, `rg --pre`,
`awk -f`), an unquoted glob, and quoted text given to a program that globs it
(`find -name`, `python -c`, `grep --include`) stay denied inside a substitution
just as outside it. A substitution the guard cannot close with certainty is not
relaxed at all.
