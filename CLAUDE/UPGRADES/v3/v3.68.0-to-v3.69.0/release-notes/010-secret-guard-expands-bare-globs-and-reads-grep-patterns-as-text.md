# Callout: the secret guard judges a bare `*` by the protected files that exist and no longer denies a grep pattern for its spelling

**Plan**: 00483
**Audience**: everyone

`cat dir/*`, `grep x dir/*` and `cat dir/k*` are now checked against the protected files that exist (the index described under "The secret, quarantine and containment guards deny only on a finding" below), so a directory holding a protected file is denied. A glob follows bash's defaults: a `*` does not match dot-entries. A glob made only of wildcards (`ls */*`, `ls */*/*`) names no place and is not judged, so everyday listings are allowed. A quoted `'dir/*'` is a literal and is unaffected. The first (pattern) operand of `grep` and `rg` is now text, not a path, even when it holds a regex escape or an alternation: `grep -n 'foo\.secret' f` and `rg 'a|\.vault-pass' f` are allowed, while a file operand that names a protected file is still denied. An option `rg` does not share with `grep` (for example `--hidden`) turns that relaxation off.
