# Callout: a deny from a guard that ran out of time or entries now says so

**Plan**: 00474
**Audience**: everyone

Two guards fail closed when they cannot finish: `conflict_marker_commit_gate` when `git` times out reading a commit, and `secret_file_guard` when a glob passes its entry cap or the scan deadline passes. Both used to report the same reason as a real finding, so an agent could not tell "could not check" from "found something". Each now has its own rule ID and reason, which says what ran out, that nothing was found, and what to do:

- `R-CONFLICT-MARKER-SCAN-TIMED-OUT`: git did not answer within its 5 s limit. No conflict marker was found and the content needs no edit; retry the same commit.
- `R-SECRET-SCAN-INCOMPLETE`: a glob expanded past its cap of examined paths, or the scan deadline passed. No protected path was found; narrow the glob or the search root, name the files, or retry after a deadline.

Both still deny, and no cap or timeout changed. A real finding keeps `R-CONFLICT-MARKER-COMMIT`, `R-SECRET-BASH-MENTION` or `R-SECRET-READ`. `bin/hooks-daemon explain-rule` describes each new rule.
