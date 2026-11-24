# Callout: the secret-file guard denies more bracket, case and extglob reads of a protected file

**Plan**: 00474
**Audience**: everyone

The secret-file guard now denies five more ways a command could reach a protected file. Each one was allowed before and is listed in the niggles ledger as N720, with N719.

- **A finite bracket under `nocaseglob`.** For example, `shopt -s nocaseglob; cat dir/[X]YZ`. The guard now matches that bracketed word case-blind whenever bash's defaults are not certain. This includes the protected-file index's own matcher.
- **A POSIX class that is not first in its bracket.** For example, `[x[:lower:]]`. These are now read as bash reads them on the Write-script route and the no-index route, as well as the Bash route.
- **`-O` inside a flag cluster.** For example, `bash -xO dotglob` or `bash -Ox dotglob`. This now switches the guard to its conservative glob reading, the same as plain `-O` already did.
- **An extglob word beside a size limit.** An extglob word next to a large brace expansion or deep nesting now counts as a glob. It is also judged before the brace expansion can hit the limit, so the command is denied instead of allowed with an advisory.
- **A reversed bracket range.** A range such as `[z-a]` is now read as "any name" with no error, so it no longer writes a full traceback to the log.

Certain mode now has one more requirement. It needs every shell snapshot to record `shopt -s globasciiranges` as well as `dotglob`, `globstar` and `nocaseglob` off. A snapshot without it leaves the guard on the conservative reading. Real Claude Code snapshots already record it.

Nothing the guard denied before is now allowed. No config change is needed.
