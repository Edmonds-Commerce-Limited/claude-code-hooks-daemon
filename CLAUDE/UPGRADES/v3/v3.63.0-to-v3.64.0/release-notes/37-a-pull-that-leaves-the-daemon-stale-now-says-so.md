# Callout: a pull that leaves the daemon stale now says so

**Plan**: 00389
**Audience**: operators

The daemon reads its config once at startup and imports every handler module
once at `initialise()`. It does not hot-reload. So when a `git pull` brings in a
colleague's `hooks-daemon.yaml` — a new blocking handler, a retuned priority, a
changed option — or new project-handler code, none of it is in force. The
project is protected by a config that is committed but not loaded, and until now
nothing said so. A guard that has silently stopped applying is worse than no
guard, because nobody is looking for it.

A new advisory runs after `git merge`, `git pull` and `git rebase` and reports
when that operation changed daemon config or handler code. It names WHICH paths
changed and the exact restart command. It is silent when the operation touched
nothing the daemon cares about, which is nearly every pull.

**It also catches the version half, in both directions.** `.claude/hooks-daemon/`
is gitignored, so a pull never touches the installed clone — but it can move the
version recorded in the tracked `.claude/HOOKS-DAEMON.md`, which is the reviewed
truth. When the two disagree the daemon refuses to start, and the cost of finding
that out the hard way is a whole session with every safety handler inactive. The
advisory names BOTH versions and the upgrade command (so the clone can be brought
up to what the tracked assets declare), and then asks for the regenerated tracked
artefacts to be committed (so the repository stops describing a daemon it no
longer has).

**It advises and never acts, deliberately.** It names a command for a human and
runs nothing itself. The daemon serves this hook in-process, so a daemon that
restarted itself here would be killing the process that still owes a response —
and a lost hook response is a failed hook, which can block your next tool call.
Trading a silent staleness bug for a loud breakage is not an improvement. A test
pins this rather than a sentence in a document.

**Two things worth knowing.** The advisory only sees a pull run in the session it
is attached to; one run in another terminal is not covered by this handler. And
if your project overrides `project_handlers.path`, set
`options.watch_paths` to match — that value is not injected for you, so the
default would watch the wrong directory.
