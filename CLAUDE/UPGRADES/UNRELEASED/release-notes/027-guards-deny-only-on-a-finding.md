# Callout: the secret, quarantine and containment guards deny only on a finding

**Plan**: 00483
**Audience**: everyone

`secret_file_guard`, `quarantine_artefact_read_guard` and `project_containment` used to deny a call whenever they could not finish judging it: a command they could not read, a cap or the scan deadline, an unresolved variable, an internal error. They now deny only on a positive finding, which is a literal protected path or name in the command, or a protected file a recursive read provably reaches. A call they cannot judge is allowed, and the advisory says what was not checked.

- A recursive search (`grep -r`, `rg`, `git grep`, the Grep tool on a directory) and a glob are judged against a cached index of protected files. The index is built from `git ls-files` at session start, refreshed in the background every ten minutes, and never walks the tree during a call, so the size of a checkout costs the call nothing. A project that is not a git repository, or a daemon that has just started, has no index yet: the search is allowed with an advisory. `--exclude-dir`, `--exclude` and `rg -g '!dir'` that remove the protected path allow the search, and `rg` and `ag` are judged on the files git does not ignore.
- A variable no longer becomes a wildcard: `ls "$d"_rsa`, `for d in repos/*; do ls "$d"; done` from a directory holding a protected file, and `echo {1..300}` are allowed. A `cd` earlier in the command moves the directory a search or glob is judged from. The structural false positives of the secret guard are gone with the code that caused them: the heredoc message of `git commit -F -` is no longer judged because an earlier statement was a `cd`, `source` or `export`.
- `R-SECRET-COMMAND-UNREADABLE`, `R-SECRET-EVALUATION-ERROR`, `R-SECRET-SCAN-INCOMPLETE`, `R-QUARANTINE-ARTEFACT-READ-EVALUATION-ERROR`, `R-QUARANTINE-SCAN-INCOMPLETE` and `R-PROJECT-CONTAINMENT-EVALUATION-ERROR` are removed. A write to a path the guard cannot place (`> "$OUT"` with no literal assignment) is allowed with an advisory; a write to a named out-of-root path is still denied.

The commit gate still scans what reaches git, so a call that could not be judged cannot put a secret into history. `tests/integration/test_ordinary_command_regression_gate.py` runs about 350 ordinary commands through every blocking handler and fails if any is denied.
