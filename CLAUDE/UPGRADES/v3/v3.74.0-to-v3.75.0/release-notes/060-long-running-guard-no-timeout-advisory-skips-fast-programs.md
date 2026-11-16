# Callout: the no-timeout advisory of the long-running guard no longer names plan and bus helpers

**Plan**: 00474
**Audience**: client projects

R-LONG-RUNNING-NO-TIMEOUT, the advisory `long_running_command_guard` gives for a foreground command of unknown length, fired on ordinary quick helpers such as `mkplan.bash` and `pingbus`, which trained readers to skip it. Both are now on the built-in known-fast list, next to `git`, `gh`, `ls`, `cat`, `grep`, `rg`, `jq`, `awk` and `hooks-daemon`.

Network and object-store git verbs (`clone`, `fetch`, `pull`, `push`, `gc` and the like) and programs on no list still draw the advisory. The deny rules are unchanged: a `timeout` above the threshold, a long `sleep`, a wait loop and a known-slow command are denied whatever else is listed. To silence the advisory for a quick project command, add its name to `handlers.pre_tool_use.long_running_command_guard.options.extra_fast_programs`. The handler ships off, so nothing changes unless you enabled it.
