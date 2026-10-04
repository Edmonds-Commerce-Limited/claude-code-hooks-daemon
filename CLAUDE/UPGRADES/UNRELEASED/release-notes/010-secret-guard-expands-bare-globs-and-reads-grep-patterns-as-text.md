# Callout: the secret guard expands a bare `*` and no longer denies a grep pattern for its spelling

**Plan**: 00483
**Audience**: everyone

`cat dir/*`, `grep x dir/*` and `cat */*` are now checked against the files the glob really expands to, so a directory holding a protected file is denied. The expansion follows bash's defaults: a `*` does not match dot-entries, so they are neither judged nor counted. The expansion is capped; a glob that reaches more than 5000 paths is denied rather than left unchecked. A quoted `'dir/*'` is a literal and is unaffected. The first (pattern) operand of `grep` and `rg` is now text, not a path, even when it holds a regex escape or an alternation: `grep -n 'foo\.secret' f` and `rg 'a|\.vault-pass' f` are allowed, while a file operand that names a protected file is still denied. An option `rg` does not share with `grep` (for example `--hidden`) turns that relaxation off.
