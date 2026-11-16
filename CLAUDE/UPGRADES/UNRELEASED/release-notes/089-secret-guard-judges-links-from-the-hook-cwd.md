# Fix: the secret guard judges a link from the command's own directory

**Plan**: 00614
**Audience**: client projects

A symlink with an innocuous name that points at a protected file was denied when spelled as an absolute path, but three spellings reached the file's content past `secret_file_guard`:

- A relative Bash word naming the link (`cat link`, `cat < link`, an interpreter one-liner's `open('link')`). The daemon runs from `/`, so the link was looked up there instead of in the command's working directory. It is now resolved from the hook's `cwd` (and every literal `cd` target), and a link anywhere on the path counts, not only the last component. A relative `Read` or `Grep` path is judged the same way.
- A recursive search (the Grep tool, `grep -r`, `rg`) rooted at a directory link that leads out of the project, typically into another checkout from a worktree. The protected-file index lists only the project, so such a search is no longer vouched for and is denied.
- A glob under a directory link (`cat dlink/*`). The glob is now matched with the link resolved, and denied when the link leads out of the project.

Behaviour change: a recursive search or a glob through a link from inside the project to a directory outside it is denied even when that directory holds no protected file. A path that is outside the project as spelled is judged as before, and an ordinary relative word that is not a link behaves as before.

Upgrade: nothing to do.
