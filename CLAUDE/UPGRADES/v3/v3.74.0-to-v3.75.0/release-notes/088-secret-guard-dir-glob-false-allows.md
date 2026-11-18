# Callout: the secret guard no longer misses POSIX classes and symlinked directories in a glob

**Plan**: 00612
**Audience**: operators

`secret_file_guard` allowed two recursive reads that reach a protected file. `grep -r x [[:alpha:]]*/` was allowed because POSIX bracket classes (`[[:alpha:]]`, `[[:digit:]]`, `[[:space:]]` and the rest) were passed to `fnmatch` untranslated and matched nothing. `grep -r x l*/` was allowed when `l` is a symlink to a directory holding a protected file, because the index holds real paths.

Glob components are now matched with the POSIX classes translated, for file globs and directory globs alike (`[^x]` and `[!x]` still both negate). A trailing-slash glob also matches a symlink to a directory holding a protected file, found by listing the single directory the glob's literal parent names; a symlink matched only below a wildcard directory (`*/l*/`) is still not judged, which keeps the cost independent of tree size. Protected patterns and config defaults are unchanged.
