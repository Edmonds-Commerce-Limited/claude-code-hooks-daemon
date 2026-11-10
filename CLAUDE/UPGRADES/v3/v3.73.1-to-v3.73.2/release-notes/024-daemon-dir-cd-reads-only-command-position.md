# Callout: R-DAEMON-DIR-CD no longer denies a quoted search pattern that names `cd`

**Plan**: 00590
**Audience**: client projects

(GitHub #194.) `daemon_location_guard` denied commands that change no directory, such as `grep -c "cd " .claude/hooks-daemon/CLAUDE.md`, because the quoted pattern's `cd ` was joined to grep's file argument once quotes were removed. The text of a `grep`/`egrep`/`fgrep`/`rg` command is now ignored when nothing could run it (no expansion in it, and its output is not piped to a shell). Every executing form still denies: `bash -c`/`sh -c` bodies, `eval`, `$( )`, backticks, `( )`, an executing heredoc, `echo "cd ..." | sh`, and a real `cd` after the grep. `echo`/`printf` are still judged as before.
