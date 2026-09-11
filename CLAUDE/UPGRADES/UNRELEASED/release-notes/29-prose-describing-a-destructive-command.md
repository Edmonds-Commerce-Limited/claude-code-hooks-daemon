# Callout: a commit message describing `--force` is no longer a force push

**Plan**: 00377
**Audience**: everyone

`destructive_git` judged the raw command text, so a span bash hands over as
DATA could be read as a command. Writing a commit message that documented a
newly added `--force` flag was denied as `R-GIT-PUSH-FORCE`, with a deny
message asserting the command "PERMANENTLY DESTROYS data" — of a command that
created a commit.

The cause was narrower than it looked, and is worth knowing because it decides
which shapes were affected. The opener line was:

```bash
git commit -F - <<'EOF' && git push origin main
```

so the heredoc body physically follows `git push` in the command string, and
the force-push pattern's character class excludes `;`, `&` and `|` but not
newlines — the scan ran from `git push` straight down into the message. A
second route needed no heredoc at all: the single-line patterns stay on one
line but still match inside a `-m` value, so `git commit -m 'document --amend'`
was denied too.

Both are fixed. Inert spans are blanked before the command is judged, so a
quoted-delimiter heredoc body and an inert `-m`/`-F` message value are no
longer read as shell syntax. This applies to every rule the handler enforces,
not just force-push — prose naming `git reset --hard`, `git clean -f` or
`--amend` was equally affected.

**What still blocks, deliberately.** Nothing bash would actually run has been
exempted:

- a message value carrying a SUBSTITUTION — `git commit -m "$(git push --force)"` — because double quotes do not stop expansion;
- an UNQUOTED `<<EOF` body, because bash expands inside it.

Quote the delimiter (`<<'EOF'`) whenever a heredoc body is prose and neither
boundary affects you.

The same fix moved the message-blanking half of the scanner into
`utils/shell_segmentation`, next to the heredoc half that was already shared.
`pipe_blocker` now calls the shared function rather than keeping its own copy,
so the two handlers can no longer disagree about what counts as a command.
