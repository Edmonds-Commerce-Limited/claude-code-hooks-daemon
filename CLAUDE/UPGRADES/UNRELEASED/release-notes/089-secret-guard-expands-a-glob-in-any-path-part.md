# Callout: the secret guard now expands a glob in any part of a path, not only the first

**Plan**: 00474
**Audience**: everyone

A link to a protected file could be read through a glob the secret guard did not expand. The guard denied `cat kit/bin/late` when `late` was a link to a protected file. It allowed `cat kit/*/late`, `cat kit/bin/l*` and, from `kit`, `cat b?n/late`. On the Bash route the guard relied on the index of protected files, so a link made after the index was built, or a missing index, left the gap open. On the script route (`R-SECRET-SCRIPT-AUTHOR`) the gap was always open.

A glob in any part of a word is now expanded from each directory the command may run in, and each match that passes through a link is judged as the literal path would be. That covers `**`, a glob after a computed `cd`, and a glob read above the link's directory. A quoted glob is still a literal. A glob that matches nothing, and a literal path, are judged as before. Each directory is listed once per command, whichever word needs it. Some expansions cannot be finished: more than 4096 distinct directories or paths to read in one command, more than 4096 paths at one step of a word, more than 4096 matches through links, or a directory or entry that cannot be read. Each of those is now denied instead of being treated as no match. If you see a new deny on a very wide glob, narrow the glob.
