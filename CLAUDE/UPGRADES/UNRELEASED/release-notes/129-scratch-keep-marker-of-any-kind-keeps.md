# Callout: a `.scratch-keep` of any kind now keeps a scratch entry

**Plan**: 00474
**Audience**: operators

The scratch sweep used to keep an entry only when its top-level `.scratch-keep` was a regular file, so `scratch-sweep --apply` archived an entry pinned by a symlinked, dangling, looping or directory marker, though the same marker on a session directory kept it. One rule now decides both: any node named `.scratch-keep` keeps, links are never followed, and a marker that cannot be read counts as kept. A symlinked marker's target is not read for the reason, so the report says "(no reason given)"; put the reason in a regular file if you want it shown.
