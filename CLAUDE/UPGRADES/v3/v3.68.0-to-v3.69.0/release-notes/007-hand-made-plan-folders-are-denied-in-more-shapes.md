# Callout: hand-making a plan folder is denied in more command shapes

**Plan**: 00483
**Audience**: everyone

`plan_number_helper` denies `mkdir <plan-dir>/NNNNN-name` and points at `mkplan.bash`, but several ordinary spellings of the same creation were allowed. A `| wc`, a mention of `Completed/` or a trailing comment in the same command made the guard stand down, so `mkdir -p CLAUDE/Plan/00999-x CLAUDE/Plan/Completed` created the folder. `cd CLAUDE/Plan && mkdir 00999-x` and `cd CLAUDE && mkdir Plan/00999-x` hid the directory in the `cd`. `mkdir 2>&1 CLAUDE/Plan/00999-x` put a redirection before the operand, and `mkdir CLAUDE/Plan/0{0999,1000}-x` hid the number in a brace list. All of these are now denied, and every operand of a `mkdir` is judged rather than only the first plan-shaped one. A `mkdir` of `Completed`, of a `JOURNAL/` inside an existing plan, a `-p` re-create of an existing folder and any path outside the workspace stay allowed. Spellings that only exist to defeat the parser (a quoted space, a symlink made first, `$'…'` or `$"…"` folder names, a variable holding the command) are still not judged.
