# Callout: an `echo` naming a guarded command is no longer denied

**Plan**: 00408
**Audience**: everyone

`echo 'git merge x'`, `echo 'cd .claude/hooks-daemon'` and `echo 'mkdir <plan-dir>/NNNNN-x'` are no longer read as the command they print by `merge_to_main_approval`, `daemon_location_guard` and `plan_number_helper`'s folder rule. A bare `echo`, `printf`, `:` or `true` now has its arguments treated as text, but only when nothing can run them. Its output must not be piped or redirected, it must carry no `$` expansion or substitution, `printf` must not use `-v`, no wrapper such as `command` or `sudo` may precede it, and nothing in the same command may redefine it or reroute the shell's output. `bash -c '...'` and every one of those shapes are still judged as before.
