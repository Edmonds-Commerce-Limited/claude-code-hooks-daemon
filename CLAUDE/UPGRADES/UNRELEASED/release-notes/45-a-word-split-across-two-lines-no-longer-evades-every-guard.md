# Callout: a word split across two lines no longer evades every guard

**Plan**: 00405
**Audience**: everyone

**Security fix.** A backslash-newline inside a WORD — `git pu\`+newline+`sh --force` — was handed to every blocking handler as `git pu sh --force`, which
matches nothing. The shell REMOVES a line continuation and joins the halves
into one word; the daemon replaced it with a space, which splits the word
instead. Every guard that reads a Bash command through `get_bash_command` was
evadable this way, including `destructive_git`, so `reset --hard`,
`push --force` and their siblings could all be spelled past the block.

The continuation is now removed rather than substituted, matching the shell.
Nothing changes for the ordinary long command written across lines: the
separating space is already there before the backslash, which is exactly why
the two behaviours looked identical for so long and the wrong one was picked.
The converse now holds too — `git`+backslash+newline+`push` is `gitpush` to the
shell, runs nothing, and correctly stops being reported as a force push.
