# Callout: the secret guard denies `find -exec` and `xargs` readers over a directory holding a protected file

**Plan**: 00615
**Audience**: operators

Since v3.75.0 (shipped under Plan 00618, noted here because that release carried no note for it) the secret-file guard treats `find <dir> -exec <reader> {} +`, `-execdir`, `-ok`, `-okdir`, and `find <dir> | xargs <reader>` as a read of every file under `<dir>`, and denies it when the directory can hold a protected file, whether directly or through a symlink. `tar`, `zip`, `cp`, `rsync`, `scp`, `diff` and `git diff --no-index` over such a directory are denied the same way. Only an exact list of commands that open no file content stays allowed as the action (`echo`, `printf`, `true`, `false`, `ls`, `stat`, `basename`, `dirname`, `test`, `[`, `rm`, `rmdir`, `chmod`, `chown`, `touch`, `mkdir`); any other command, including `file`, `head` and `wc`, counts as a reader. Any of these shapes over a directory with no protected file stays allowed. An `xargs` reader fed by a producer other than `find` is judged against the working directory.
