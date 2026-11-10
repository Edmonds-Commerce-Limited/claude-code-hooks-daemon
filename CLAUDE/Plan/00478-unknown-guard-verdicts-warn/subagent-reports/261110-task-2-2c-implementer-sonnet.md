# Task 2.2c implementer report (Sonnet)

Branch `worktree-478-2c-misc-guards`. Rows 14, 15, 19, 20, 22, 24 converted: the UNKNOWN sub-case allows with `unknown_verdict_allow`; the positive sub-case still denies.

## Per row

| Row | Guard                             | UNKNOWN now ALLOW + advisory + `UNKNOWN-VERDICT` log                                                                 | Positive, still denies                                     | Mixed shape guarded                                                                                                                                                                                                                                                                                                                                |
| --- | --------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 14  | `flaggable_content_channel_guard` | roots/exclusions not placeable (expansion, bad quoting, `git -C`, unknown pathspec magic, relative root without cwd) | a root containing the flagged dir                          | one unplaced root plus one reaching root; unplaced segment before a reaching or `git diff` segment. `_recursive_search_reaches` used to `return unplaceable` at the first unplaceable root and so lost a later positive root; it now records `unplaced` and keeps scanning. `_matched_reason` returns the first positive over any unplaced segment |
| 15  | `plan_journal_guard`              | run-time destination, or unreadable text, that could name a day-file or `JOURNAL/`                                   | a literal day-file / `JOURNAL/` target                     | unplaced destination before or after a literal one, and unreadable text beside a literal one. `_bash_target` used to return at the first unplaced destination                                                                                                                                                                                      |
| 19  | `release_merge_freeze`            | state file unreadable / not JSON / not an object / no positive `ci.pr_number`                                        | a positively open release                                  | none exists: with a problem there is no release PR, so there is no positive finding to lose                                                                                                                                                                                                                                                        |
| 20  | `reference_repo_freshness`        | no in-date reading, in every mode                                                                                    | stale clone (`R-REFERENCE-REPO-STALE`, per `mode`)         | stale and unverified paths in one call, in both orders. `handle` used to return at the first finding; it now walks all paths, a DENY returns, unverified paths are collected into one advisory                                                                                                                                                     |
| 22  | `curl_pipe_shell`                 | non-shell interpreter with an unresolved argument                                                                    | pipe into a shell; `-`/stdin operand; `sh -c "$(curl ..)"` | unknown stage plus a shell stage in one command, either order                                                                                                                                                                                                                                                                                      |
| 24  | `root_recursion_guard`            | `/proc` or `/sys` path that cannot be stat'ed                                                                        | catastrophic root                                          | unstatable root with `/` root, same command or later segment. `_Verdict` (SAFE/UNKNOWN/DANGEROUS) is combined with `max`                                                                                                                                                                                                                           |

## Disagreements and notes

- Row 19: `_on_main` (an unplaceable git directory counts as on main) is left alone. It applies only while a release is positively open, so it is part of the positive finding. The brief's row 19 scope is "cannot tell whether a release is open" only.
- Row 20: `_not_verified` was deleted as dead code. `_NOT_VERIFIED_RULE` stays for `explain-rule` and now says "(advisory only)". Block-once no longer applies to NOT VERIFIED: the advisory repeats on every read, which is what the log wants.
- Row 22: an unresolved word before a decisive `-c` / script operand is UNKNOWN (previously DENY); a later `-` operand is CODE.
- Row 14: `git grep foo -- ':(top)x'` no longer defaults to the root `.` when its only pathspec is unplaceable magic.

## RED output (tests run with the six implementations reverted)

```
51 failed, 559 passed
 15 .claude/project-handlers/pre_tool_use/test_release_merge_freeze.py::TestUnreadableState
  5 tests/unit/handlers/pre_tool_use/test_curl_pipe_shell_unknown_verdict.py::test_unresolved_interpreter_argument_allows_with_an_advisory
  7 tests/unit/handlers/pre_tool_use/test_flaggable_content_channel_guard.py (TestRecursiveSearchDenyMessage, TestUnplaceableRootsWarnInsteadOfBlocking)
 10 tests/unit/handlers/pre_tool_use/test_plan_journal_guard.py::TestUnplaceableDestinationsWarn
 12 tests/unit/handlers/pre_tool_use/test_reference_repo_freshness.py (TestNotVerified, TestHandlerContract, TestOnlyRealCheckoutsAreGoverned, TestPathDisplay)
  2 tests/unit/handlers/pre_tool_use/test_root_recursion_guard.py::TestUnstatablePathWarnsInsteadOfBlocking
```

The implementation was written before the tests were run, so the RED run was produced by reverting the implementation patch and re-applying it. The mixed-shape deny tests passed in the RED run where the old code already denied them.

## Text updated

Rule/`get_claude_md` text of the five src handlers, the module docstring of `release_merge_freeze`, the `rule_ids.py` comment, `docs/guides/HANDLER_REFERENCE.md` (curl, root recursion, flaggable, journal, reference repo table), release note 028.
