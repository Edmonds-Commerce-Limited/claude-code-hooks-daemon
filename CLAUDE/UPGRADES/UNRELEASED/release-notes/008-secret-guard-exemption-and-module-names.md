# Callout: the secret guard's metadata exemption is stricter and module names are not paths

**Plan**: 00483
**Audience**: everyone

`secret_file_guard` exempts `hooks-daemon secret-meta` and `git rm --cached` only when the command is nothing but that invocation. A lone `&`, a `$( )` substitution or a backtick anywhere in the command now voids the exemption, so another command riding along (`secret-meta x & cat <protected file>`) is judged and denied as it would be on its own. Two false positives are removed: `python -m pkg.secret_x` and an `import a.b.secret_x` that is not the first statement of a `python -c` script no longer count as a mention of a `*.secret*` protected path, because a dotted module name is not a file. File operands, including those after a `-m` module, are still judged as paths, and a command the guard cannot read is still denied.
