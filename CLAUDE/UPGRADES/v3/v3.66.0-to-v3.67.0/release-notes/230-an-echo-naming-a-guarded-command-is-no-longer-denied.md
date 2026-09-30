# Callout: an `echo` naming a guarded command is no longer denied

**Plan**: 00408
**Audience**: everyone

`echo 'git merge x'`, `echo 'cd .claude/hooks-daemon'` and `echo 'mkdir <plan-dir>/NNNNN-x'` are no longer read as the command they print by `merge_to_main_approval`, `daemon_location_guard` and `plan_number_helper`'s folder rule. The exemption applies only when the WHOLE command is one bare `echo`, `printf`, `:` or `true`. There must be no `;`, `&&`, pipe, `&`, line break, grouping, redirection or heredoc, and no wrapper, assignment prefix or quoted name. No argument may contain an expansion, which means no `$`, no backtick, and no unquoted `~`, `{`, `*`, `?`, `[` or `!`. A `printf` may take no option. Any other command, including a compound that merely contains an `echo`, is judged exactly as before. This is deliberate: an exemption for one segment of a compound command can be walked past from another segment (through `$_`, a `trap`, or an alias table), so it is not offered.
