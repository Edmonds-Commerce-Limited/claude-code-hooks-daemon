# N7 — a word split across two lines evaded every blocking guard

Supporting evidence for [N7](PLAN.md). The ledger entry states the finding and
the fix; this holds the measurements and the analysis of why it survived.

## What the shell actually does

Taken from bash rather than from memory, which is the step that settled it:

```text
ec\<newline>ho joined   ->  prints "joined"   (the token is `echo`)
echo a\<newline>b       ->  prints "ab"
```

bash REMOVES a backslash-newline and joins the halves into one word.
`normalise_line_continuations` substituted a SPACE, which splits the word
instead.

## What that cost, against the real `DestructiveGitHandler`

| command                           | before | what bash would run |
| --------------------------------- | ------ | ------------------- |
| `git push --force origin main`    | DENY   | a force push        |
| `git pu\<newline>sh --force …`    | ALLOW  | the same force push |
| `git push --fo\<newline>rce …`    | ALLOW  | the same force push |
| `gi\<newline>t push --force …`    | ALLOW  | the same force push |
| `git re\<newline>set --hard HEAD` | ALLOW  | a hard reset        |

Every guard reading a command through `get_bash_command` was evadable this way
— `destructive_git`, `sed_blocker`, `pipe_blocker`, all of them.

## Why it survived

The helper's own docstring states the correct rule — "the shell removes it and
joins the lines" — directly above code that substituted a space. Both its
summary line and every existing test wrote the continuation BETWEEN tokens
(`git \<newline> reset`), where the author has already typed the separating
space, so joining and substituting produce the same string and the wrong one
was indistinguishable from the right one.

Inside a word they are opposites: there a continuation is glue, not whitespace.
The framing the tests were written from — "a line continuation is whitespace" —
is true in the tested position and false in the untested one, so the suite
could only ever confirm it.

## The fix, and the converse it has to satisfy

The continuation is removed rather than replaced. The converse is asserted too:
`git\<newline>push` is `gitpush` to the shell, runs nothing, and must STOP
being reported as a force push — losing that match is the fix working rather
than a regression. Mid-token spellings were added to
`test_blocking_handler_evasion.py`, whose header had named only the
between-token form.

## Verified in the running daemon, not just in tests

`git sta\<newline>sh` is now denied by the live daemon through the real hook
path. Chosen because `git stash` is blocked but harmless on a clean tree, so a
failed fix would have cost nothing.
