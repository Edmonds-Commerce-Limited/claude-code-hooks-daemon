# Callout: tdd_enforcement no longer gates a Write over an existing file

**Plan**: 00521
**Audience**: client projects

`tdd_enforcement` is about creating a production source file, but it denied a `Write` that overwrote an existing source file with no test, even though an `Edit` to the same file was allowed and can rewrite it wholesale. A `Write` whose target is an existing regular file is now treated like an `Edit` and passes. A `Write` that creates a new path is judged exactly as before. A symlink, a directory or a dangling path at the target counts as not existing, so the gate still applies. Read-before-overwrite (`R-WRITE-CLOBBER`) is a separate guard and is unchanged.
