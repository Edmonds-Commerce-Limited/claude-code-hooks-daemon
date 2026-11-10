# Fact check: Plan 00478 stand-in ruling diff

Scope: claims the diff at untracked/plan-fact-check/00478-unknown-guard-verdicts-warn.diff adds or changes.

## REFUTED

None.

## Table

| #   | Claim                                                                                                                                          | Verdict           | Evidence                                                                                                                                                                                                                          |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | The stand-in's ruling is journalled in `JOURNAL/2026-11-10/100942Z-decision-97aacd.md`                                                         | VERIFIED          | File exists in that folder; titled "STAND-IN ruling on Q1-Q4 (not the owner's)"                                                                                                                                                   |
| 2   | Ruling: Q1 deny, Q2 deny, Q3 deny where literally named and warn where not, Q4 rows 21 and 25 out of scope, row 26 in scope (warn)             | VERIFIED          | Journal headings "Q1: DENY", "Q2: DENY", "Q3: DENY where the path is literally named; WARN where it is not", "Q4 row 21/25 OUT OF SCOPE, row 26 IN SCOPE, converts to WARN"                                                       |
| 3   | The owner did not answer by the stand-in deadline                                                                                              | UNVERIFIABLE-HERE | The journal says only that it is the stand-in's ruling and not the owner's. It does not record the deadline or a missing answer. Settle it from the stand-in cron record or the owner's messages                                  |
| 4   | Task 2.2b: Q1 keeps the deny (recognised forced delete, unproven target) and the task only pins the local-delete substitution deny with a test | VERIFIED          | Journal Q1 consequence: "Row 2 stays deny; add the missing pinning test"                                                                                                                                                          |
| 5   | INVENTORY.md row 2 names no test by name for the local-delete substitution                                                                     | VERIFIED          | INVENTORY.md row 2: "No test found by name for the local-delete branch". Grep of the `test_destructive_git*` files found no forced-local-delete substitution test (hits were only prose/quoted-operand tests and the remote twin) |
| 6   | Row 16 has sub-branches that deny with no literal mention of a listed path (the `**`-only glob)                                                | VERIFIED          | INVENTORY.md row 16: "a glob with no literal part (`**`), which is 'named by any text'". `test_write_protected_paths.py:339` is `test_a_glob_with_no_literal_directory_stays_fail_closed`                                         |
| 7   | Row 26 is an unknown producer piped to `tail`/`head`, and blacklisted producers still deny                                                     | VERIFIED          | INVENTORY.md row 26 (producer on neither whitelist nor blacklist). `src/claude_code_hooks_daemon/handlers/pre_tool_use/pipe_blocker.py:5` "Matches blacklist? DENY". Journal Q4 says "blacklisted producers still deny"           |
| 8   | Rows 1, 3, 5, 16-literal and 23 stay deny; rows 21 and 25 are out of scope                                                                     | VERIFIED          | Journal "Scope of Task 2.2b and 2.2e" list                                                                                                                                                                                        |
| 9   | Contested rows are 1, 3, 5, 16, 23 and scope rows 21, 25, 26                                                                                   | VERIFIED          | INVENTORY.md has rows 1, 3, 5, 16, 23 as contested and rows 21, 25, 26 as scope                                                                                                                                                   |
| 10  | Task 2.3: 2.2b and 2.2e still owe rule texts, guidance and release note                                                                        | VERIFIED          | Unchanged text; consistent with the journal's "Task 2.3 follows"                                                                                                                                                                  |

Note: the diff's `Q3` in the Owner-questions header text matches PLAN.md lines 117-118, 121, 128 and 131.

Counts: 10 claims: 9 verified, 0 refuted, 1 unverifiable.
