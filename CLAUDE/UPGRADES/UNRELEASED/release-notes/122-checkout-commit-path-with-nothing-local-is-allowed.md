# Callout: `git checkout <commit> -- <path>` is allowed when nothing local can be lost

**Plan**: 00474
**Audience**: everyone

R-GIT-CHECKOUT-DISCARD denied every `git checkout <commit> -- <path>`, including one bringing back a file absent from the working tree and the index, where nothing local could be discarded; with `git restore --source` denied too, no git route was left to restore one file from another commit. ONE plain `git checkout <commit> -- <paths>` is now allowed when every path is a literal relative path inside the repository that is either absent from the working tree and the index or a tracked regular file, and `git diff` and `git diff --cached` are both clean for those paths. Everything else is still denied: a chained or wrapped command, a redirect, an option (`-f`, `-p`, `--ours`), a missing commit (restore from the index), a glob or pathspec magic, a variable or substitution, a directory or symlink that exists, an untracked file, any staged or unstaged change (a deletion included), and any git error or time-out.
