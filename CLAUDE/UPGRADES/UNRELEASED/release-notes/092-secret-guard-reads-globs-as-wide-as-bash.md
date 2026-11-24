# Callout: the secret guard reads brackets, case, extglob words and dot names at least as widely as bash

**Plan**: 00474
**Audience**: everyone

Some globs reached a link to a protected file while the secret guard read them more narrowly than bash and allowed them. With `kit/bin/late` a link to a protected file, the guard allowed these:

- a bracket with a POSIX class after its first member, as in `cat kit/[a[:lower:]]in/late` or `kit/[![:digit:]]in/late`;
- `shopt -s nocaseglob; cat kit/B?N/late`;
- extglob words the guard captured wrongly, as in `cat "k"it/@(bin|zz)/late`, `kit/@("bin"|zz)/late`, nested `kit/@(b@(i)n)/late` and `env BASHOPTS=extglob bash -c 'cat kit/@(b@(i)n)/late'`;
- dot names matched through `GLOBIGNORE=x; cat kit/*/late2` or `env BASHOPTS=dotglob bash -c ...`.

Every one of these is now denied on the Bash route, with or without the protected-file index, and on the script route (`R-SECRET-SCRIPT-AUTHOR`).

Bash's default globbing is now assumed only when every shell snapshot records `dotglob`, `globstar` and `nocaseglob` as off, and the command does not change options itself. These count as changing options: `shopt`, `-O`, `GLOBIGNORE`, `BASHOPTS`, `BASH_ENV`, `source`, `.` and `eval`. Otherwise a glob also matches dot names, `**` recurses, and a glob component ignores case. As a result, a command that names one of those may see a new deny when a glob in it reaches a link. Quoted text, such as a `bash -c '...'` script, is now also checked for extglob words. So `awk '!(NR%2)' notes.txt` run beside a link to a protected file can now be denied.
