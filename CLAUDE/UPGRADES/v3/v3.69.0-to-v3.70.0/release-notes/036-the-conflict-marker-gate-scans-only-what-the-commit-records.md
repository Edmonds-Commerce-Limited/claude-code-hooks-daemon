# Callout: the conflict-marker gate scans only what the commit records

**Plan**: 00474
**Audience**: everyone

On a large repository under load, the conflict-marker commit gate could deny a clean commit as `R-CONFLICT-MARKER-SCAN-TIMED-OUT`. It ran `git grep` over the whole tree (the index, or the working tree for `commit -a`) and only afterwards dropped every file the commit did not record, so on a repository of about 5,800 files each grep took 4 to 7 seconds against a 5 second limit. Both `git grep` passes now name the paths the commit records, as literal pathspecs in chunks of 256, so the scan costs what the commit changes rather than what the repository holds. A recorded file whose name holds `*`, `?` or `[` is read as that file and nothing wider. The verdicts are unchanged: the same markers are found, a marker in a file the commit does not record never denies, and the timeout limit and its fail-closed rule are as before (reported as issue #83).
