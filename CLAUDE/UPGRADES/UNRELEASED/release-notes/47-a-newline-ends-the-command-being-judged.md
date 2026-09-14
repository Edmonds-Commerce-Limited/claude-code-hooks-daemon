# Callout: a newline ends the command being judged

**Plan**: 00406
**Audience**: everyone

**False-positive fix.** Four blocking handlers judged a multi-line Bash command
as though it were one command, because their "stays inside this sub-command"
character class listed `;`, `&` and `|` but not the newline. A pattern could
therefore run past the end of its own command and convict the next line.

What that denied, all of it legitimate:

- `git push origin main` ⏎ `grep -f patterns.txt notes.txt` — blocked as a
  force push, on grep's `-f`. The most reachable of the four: a push on one
  line and any later line carrying a `-f` was enough.
- `git update-ref refs/heads/backup HEAD` ⏎ `git branch -d refs/heads/old` —
  blocked as a force branch delete, on the SAFE `-d` delete the rules table
  tells you to use instead of `-D`.
- `git merge origin/main` ⏎ `echo --squash is what we avoid` — blocked as a
  squash merge, on the word in the echo.
- a bare `cd` ⏎ `.claude/hooks-daemon/bin/hooks-daemon status` — blocked as a
  `cd` into the daemon directory, which is precisely what that rule's own deny
  message tells you to run instead.

The tell in every case was the same: join the two lines with `&&` and the
verdict reversed. `;`, `&&` and a newline are three spellings of "run this,
then that", so two of them disagreeing was a fact about the implementation, not
a policy.

The one newline that is NOT a boundary still is not: a `\<newline>` line
continuation joins two lines into a single command, and the guards continue to
see through it — `git pu\<newline>sh --force` remains a force push. One handler
had to be routed through the shared command reader before its gap could be
tightened, because it read the raw payload and had never seen that
normalisation at all; tightening it first would have turned a false positive
into a permanent hole.

One deliberate behaviour change comes with this. An unquoted heredoc body is
still scanned rather than blanked, but it is scanned line by line like any
other text, so a flag sitting in the body no longer attaches to a command on
the line that opened it. `git commit -F - <<EOF && git push origin main` with
`--force` in the body was reported as a force push; bash feeds that `--force`
to `git commit` as the message, so the push never carried it.
