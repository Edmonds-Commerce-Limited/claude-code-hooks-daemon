# Callout: a recursive search over a huge tree is denied, never passed unchecked

**Plan**: 00483
**Audience**: everyone

`secret_file_guard` and `quarantine_artefact_read_guard` used to examine only the first 5000 files of a tree a recursive search would read, and allowed the search when the tree was larger. A protected file listed later was never seen, and `git grep` answered on its first 5000 tracked files alone. A search the guard cannot finish examining is now denied, never allowed:

- `secret_file_guard` denies it as `R-SECRET-SCAN-INCOMPLETE` (the Grep tool on a directory, `grep -r`, `ack`, `rg --no-ignore`, `git grep`), and the new `R-QUARANTINE-SCAN-INCOMPLETE` is the quarantine guard's equivalent. The reason says what ran out and that no protected path or artefact was found. A real finding keeps `R-SECRET-READ`, `R-SECRET-BASH-MENTION` or `R-QUARANTINE-ARTEFACT-READ`.
- The cap is now 250000 entries (directories included) with the existing 5 second scan deadline as a backstop, and the deadline now reaches the walk itself.
- `rg` and `ag` are judged on the files git does not ignore, and `git grep` on the index, both read from `git ls-files`, so a project with large gitignored trees (virtualenvs, `node_modules`, sibling worktrees) is not denied for their size. `grep -r` and `ack` read everything, so a very large tree still ends in the denial; search with `rg`, add `--exclude-dir`, or search a narrower root.
- A glob of up to 100000 paths (it was 5000) is judged on what it reaches, so `ls */*/*/*` in a large repository is no longer denied for its size alone.

Neither cap is a setting.
