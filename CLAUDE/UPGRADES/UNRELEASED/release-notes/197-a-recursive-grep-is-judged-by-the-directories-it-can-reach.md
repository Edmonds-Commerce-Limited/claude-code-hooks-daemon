# Callout: a recursive grep or rg is judged by the directories it can reach

**Plan**: 00474
**Audience**: operators

`flaggable_content_channel_guard` now works out where a recursive `grep -r`, `rg` or `git grep` can descend, instead of only looking for the flaggable path in the command text. A recursive search rooted at the project, at a directory that contains a flaggable directory, or whose roots cannot be determined (a shell expansion, unparseable quoting, a relative path with no working directory) is denied. A search whose named paths lie off every flaggable directory is allowed. A search with no path operand reads the working directory, or the pipe feeding `rg`.
