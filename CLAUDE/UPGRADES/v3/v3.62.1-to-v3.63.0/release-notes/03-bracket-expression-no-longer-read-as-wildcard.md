# Callout: a bracket expression at a token's edge is no longer a wildcard

**Plan**: 00356
**Audience**: everyone

The secret-file guard read a finite bracket expression at the edge of a
token (an ordinary `jq '.[0]'` subscript, for one) as an open wildcard and
denied the command. Finite bracket forms are now expanded and matched
literally; `.vault-p*`-style globs and `[Vv]ault_pass` remain denied.
