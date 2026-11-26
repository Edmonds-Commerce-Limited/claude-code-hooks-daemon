# Callout: `git restore` of a tracked file left at zero bytes is no longer refused

**Plan**: 00586
**Audience**: everyone

The destructive-git guard denied every `git restore <file>`, including the one that repairs a tracked file a crash or reboot left empty, where only a human could run it. A restore is now allowed when every file it names is a tracked, regular, zero-byte file, because replacing an empty working copy discards no content. A restore of a file that holds content, of an untracked or missing file, of a symlink, of a directory or glob, or one using `--source`, `-p` or a substitution is denied as before.
