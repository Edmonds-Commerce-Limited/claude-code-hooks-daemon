# Callout: the secret guard denies `find -exec` and `xargs` readers over a directory holding a protected file

**Plan**: 00615
**Audience**: operators

Since v3.75.0 (shipped under Plan 00618, noted here because that release carried no note for it) the secret-file guard treats `find <dir> -exec <reader> {} +`, `-execdir`, `-ok`, and `find <dir> | xargs <reader>` as a read of every file under `<dir>`, and denies it when the directory can hold a protected file, whether directly or through a symlink. `tar`, `zip`, `cp -r`, `rsync`, `scp`, `diff` and `git diff --no-index` over such a directory are denied the same way. A command that opens no file content (`ls`, `stat`, `echo`, `rm`, `chmod`, `touch`, `mkdir` and similar) and any of these shapes over a directory with no protected file stay allowed. An `xargs` reader fed by a producer other than `find` is judged against the working directory.
