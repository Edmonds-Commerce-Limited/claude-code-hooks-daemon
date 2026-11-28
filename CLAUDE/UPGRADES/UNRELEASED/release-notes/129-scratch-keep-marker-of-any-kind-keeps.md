# Callout: a `.scratch-keep` of any kind now keeps a scratch entry

**Plan**: 00474
**Audience**: operators

The scratch sweep used to keep an entry only when its top-level `.scratch-keep` was a regular file, so `scratch-sweep --apply` archived an entry pinned by a symlinked, dangling, looping or directory marker, though the same marker on a session directory kept it. One rule now decides both: any node named `.scratch-keep` keeps, links are never followed, and a marker that cannot be read counts as kept. So a marker of ANY kind, a stray empty directory included, keeps its entry until a human removes it, and only a regular file's first line is shown as the reason: any other kind is reported KEPT "(no reason given)". The agent guard (R-SCRATCH-KEEP-MARKER) now also denies `mkdir`, `mkfifo` and `mknod` of the marker, and any write to a path below it.
