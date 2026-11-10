# Callout: six more guards warn instead of deny when they cannot decide

**Plan**: 00478
**Audience**: client projects

The owner's ruling is "warn dont block": a safety guard that cannot tell whether something is dangerous allows it, with an advisory. A positively recognised finding still denies, and it still denies when the same command also holds a part the guard could not judge. Six more routes that used to deny because the guard had no verdict now allow, with an advisory naming the guard, the cause and how to rephrase:

- `flaggable_content_channel_guard`, a recursive search whose roots or exclusions cannot be placed (a shell expansion such as `$DIR`, unparseable quoting, `git -C`, unknown pathspec magic, a relative root with no working directory). A root that positively contains the flagged directory still denies.
- `plan_journal_guard`, a Bash write whose destination is built at run time, or text the write analysis could not read, that could name a journal day-file or `JOURNAL/` directory. A literal day-file or `JOURNAL/` target still denies.
- `release_merge_freeze` (a project handler), a release state file that cannot be read, is not a JSON object, or has no positive `ci.pr_number`. A positively open release still denies.
- `reference_repo_freshness`, a governed clone with no in-date freshness reading (`R-REFERENCE-REPO-NOT-VERIFIED`, now an advisory only in every `mode`). A clone known to be stale (`R-REFERENCE-REPO-STALE`) still follows `mode`, also when another path in the same call is unverified.
- `curl_pipe_shell`, a download piped into python, perl, ruby or node with an argument that cannot be resolved. A pipe into a shell, or into an interpreter that reads stdin, still denies.
- `root_recursion_guard`, a recursive scan of a path under `/proc` or `/sys` that cannot be stat'ed. A catastrophic root still denies.

Every one of these writes one log line starting `UNKNOWN-VERDICT <handler> <cause>` (WARNING), so a field report can count how often the guards fell back to warning. A command written to defeat the reader can force an unknown verdict and so run with only a warning; the ruling accepts that cost.
