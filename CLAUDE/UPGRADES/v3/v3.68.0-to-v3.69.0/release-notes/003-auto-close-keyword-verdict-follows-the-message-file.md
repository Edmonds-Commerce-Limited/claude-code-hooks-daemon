# Callout: the closing-keyword check no longer answers a repeated `git commit -F` from the previous request

**Plan**: 00483
**Audience**: everyone

`github_auto_close_keywords` remembered its verdict by command text alone, so after a denied `git commit -F msg.txt` you could fix `msg.txt` and retry the identical command and still be denied, and (the dangerous direction) a clean verdict for one `msg.txt` was reused for an edited file or a same-named file in another directory, letting a closing keyword through. The verdict is now shared only between the two calls of one dispatch and is recomputed for every new command, so it always reflects the message file's current content and the working directory.
