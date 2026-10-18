# Callout: fewer false denies from guards that matched text a command only mentions

**Plan**: 00483
**Audience**: everyone

The threat-model conformance audit checked every blocking guard against the careless-not-hostile threat model and narrowed the ones that denied ordinary commands. `destructive_git` and `git_stash` now judge each command segment by its own tokens, so a quoted search pattern, a `gh` body heredoc or a printing `while read` loop that names a destructive git command is read as data. `curl_pipe_shell` and `worktree_file_copy` judge what actually runs, reading shell wrappers word by word, and `root_recursion_guard` judges a command's scan root rather than every word in it. A git global option (`-C`, `-c`) with a quoted or escaped value no longer hides the subcommand after it.

The false positives the audit found but did not fix here are open entries in the niggles ledger (Plan 00474). Nothing to do on upgrade.
