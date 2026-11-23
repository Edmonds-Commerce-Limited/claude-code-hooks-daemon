# Callout: a link loop in the project no longer makes the secret guard deny every word

**Plan**: 00474
**Audience**: everyone

When a project held more than 16 link-holding directories, a Bash command or a written shell script with a computed `cd` (such as the standard plan-script bootstrap, which runs `cd "$(dirname ...)"`) was denied under `R-SECRET-BASH-MENTION` or `R-SECRET-SCRIPT-AUTHOR`, if any one of those directories held two links pointing at each other. The deny named the first configured protected glob and an ordinary word such as `bash`, `cat` or `cd`, together with the "moves into more than 16 existing directories" sentence. That loop no longer stops the guard reading the rest of its directory. A word that names a link in that directory is still denied, and so is every word when a directory really cannot be listed. If your deny carried that sentence and a link loop sits under the project, you can stop byte-copying the plan-script bootstrap from a committed script. A directory that really cannot be listed still causes the same deny.
