# Callout: the secret guard judges a trailing-slash glob as directories

**Plan**: 00610
**Audience**: operators

`secret_file_guard` denied `ls -d */` (R-SECRET-BASH-MENTION) whenever the project root held a protected file, while `ls -d docs/` was allowed. The glob was matched like `*`, against files at its own level, because the trailing `/` was dropped.

A glob ending in `/` now expands only to directories, as in the shell, and never matches a file at its own level. A recursive reader (`grep -r x */`, `rg x d*/`) is judged over each directory the glob expands to, exactly as it is for the literal directory (`grep -r x dir/`): it is denied when a protected file lies below a matching directory. Other glob shapes, protected patterns and config defaults are unchanged.
