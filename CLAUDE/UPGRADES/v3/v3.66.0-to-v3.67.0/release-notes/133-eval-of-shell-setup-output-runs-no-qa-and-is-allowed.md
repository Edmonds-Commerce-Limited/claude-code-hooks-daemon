# Callout: eval of shell setup output runs no QA, and is now allowed

**Plan**: 00463
**Audience**: operators

`subagent_full_qa_blocker` denies `eval`/`source` of a producer's output it
does not understand, since the producer might print project code. A short,
named list of shell-setup producers is now an exception, matched on program
AND subcommand: `ssh-agent` with only `-s`/`-c`, `pyenv`/`rbenv`/`nodenv init`,
`direnv export`, `conda shell.<shell> hook`, `brew shellenv`, and
`<program> completion <shell>` with `completion` first and the shell name the
only word after it. These only emit shell state (exports, aliases,
functions), never a QA command, and none of them reads a file — so
`eval "$(ssh-agent -s)"`, `eval "$(pyenv init -)"` and
`source <(kubectl completion bash)` are allowed. This is a named list, not a
structural rule: trusting a specific program's own output is a decision
about that program, which the command line cannot prove on its own. A
producer not on the list — `curl`, an arbitrary script, `pyenv exec cat f`,
`cat f completion`, or a listed name run by its path (`./ssh-agent`) — still
fails closed.
