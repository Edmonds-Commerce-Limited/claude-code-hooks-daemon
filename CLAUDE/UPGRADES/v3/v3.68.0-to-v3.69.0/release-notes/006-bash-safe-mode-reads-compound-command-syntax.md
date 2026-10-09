# Callout: `bash_safe_mode` no longer denies a fully gated group or loop

**Plan**: 00474
**Audience**: everyone

`bash_safe_mode` used to read the `;` that is part of compound-command syntax as ungated sequencing. A fully gated command such as `cd X && { ./qa.bash > out.txt 2>&1 && echo ok || echo bad; }` or `cd X && for b in a b c; do git -C x/$b rev-parse HEAD || exit 1; done` was denied for having no `set` prelude. The `;` before `do`, `then`, `done`, `fi`, `esac` and `}` no longer counts, and neither does the break before a `case` clause. A real `a; b` inside a loop or group body still counts and is still denied. A command the check cannot parse with certainty (a `$( )` in a loop header, an unbalanced `done`) is judged exactly as before.
