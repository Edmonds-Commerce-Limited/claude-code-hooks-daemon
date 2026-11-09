# Callout: a shell file test no longer reads as an interpreter running inline code

**Plan**: 00576
**Audience**: operators

`subagent_full_qa_blocker` judges a program it does not recognise as UNSEEN when it is run with `-e`, `-E`, `-c`, `-r`
or `--eval`, the flags that hand code to an interpreter. The shell file tests `[ -r FILE ]`, `[[ -e FILE ]]` and
`test -e FILE` matched that shape, though there `-r` means "readable" and `-e` "exists". A sub-agent running a script
that holds such a test, such as `hooks-daemon status`, got an advisory saying it ran inline code. `[`, `[[` and `test`
are now among the programs whose own flags are never read as inline code. Found during Plan 00576's close-out
configuration review.
