# Callout: the secret guard judges the path a Bash command reaches, not only its spelling

**Plan**: 00483
**Audience**: everyone

A project that protects a directory or an absolute path (for example `vault/**`) now has that pattern matched against the path a Bash command actually reaches. A `..` segment is collapsed first, so `cat /abs/x/../vault/r.md` is denied. A relative word is also judged from the hook's working directory and from each literal `cd <dir>` or `pushd <dir>` earlier in the same command, so `cd vault && cat r.md`, `cat r.md` run from inside `vault/`, and an interpreter one-liner after a `cd` are denied. The collapse is lexical and follows no symlink. A `cd` to a variable or substitution is not tracked. Name-based default patterns are unaffected.
