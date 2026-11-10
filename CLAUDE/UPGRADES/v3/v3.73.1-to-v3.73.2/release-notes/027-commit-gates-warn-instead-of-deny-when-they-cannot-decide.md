# Callout: commit gates warn instead of deny when they cannot decide

**Plan**: 00478
**Audience**: client projects

The owner's ruling is "warn dont block": a safety guard that cannot tell whether a commit is dangerous allows it, with an advisory. A positively recognised finding (a conflict marker, a secret term, a public pattern, a lint failure, a missing provenance block, a docs or plan QA finding) still denies. Eight routes that used to deny because the gate had no verdict now allow, with an advisory naming the guard, the cause and how to rephrase:

- `conflict_marker_commit_gate`, git ran out of time reading the commit (`R-CONFLICT-MARKER-SCAN-TIMED-OUT`, now an advisory only; the rule ID stays so the explanation and the advisory still cite it).
- `conflict_marker_commit_gate`, a commit it cannot place or read (`cd` through a variable, `--git-dir`, `GIT_INDEX_FILE`, `--pathspec-from-file`, `git am <patch>`, a directory outside a repository, a git failure). A marker found in another commit of the same command still denies.
- `sensitive_content`, a secret word list that exists but cannot be read. The advisory names the configured path and never a term. A public-pattern match still denies.
- `sensitive_content`, a staging simulation that fails. The command text (a commit message, a `gh` body) is still scanned, so a term written in it still denies.
- `staged_lint_gate`, a staging simulation that fails (in block mode as well as warn).
- `remote_docs_commit_gate`, a staging simulation that fails.
- `docs_qa_commit_gate` in block mode, a staging simulation that fails.
- `plan_qa_commit_gate` in block mode, a staging simulation that fails.

Every one of these writes one log line starting `UNKNOWN-VERDICT <handler> <cause>` (WARNING), so a field report can count how often the guards fell back to warning. A command written to defeat the reader can force an unknown verdict and so run with only a warning; the ruling accepts that cost.
