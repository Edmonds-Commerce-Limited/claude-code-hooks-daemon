# Plan 00581 fact check (diff-added claims only)

9 claims: 8 verified, 1 refuted, 0 unverifiable.

## REFUTED

- Claim 4, "The new tests failed before the fix and pass after it, in all three cases". The implementer report
  (`subagent-reports/261109-issue-168-implementer-sonnet.md:21`) says that before the fix the matching-venv test
  "already passed". Only the stale-venv test(s) were RED, so not every case failed before the fix. The criterion
  should say the stale-venv tests failed before the fix and the matching-venv test passed both before and after
  (a regression guard).

## Table

| #   | Claim                                                                                               | Verdict  | Evidence                                                                                                                                                         |
| --- | --------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `cfa601263` holds the fix, tests and release note `017-provision-repairs-a-stale-venv.md`           | VERIFIED | `git show --stat cfa601263`: provision.sh, tests/integration/test_provision_sh.py, 017 release note                                                              |
| 2   | `provision.sh` and `.claude/provision.sh` identical (deployed copy is a symlink to the root script) | VERIFIED | `ls -l`: `.claude/provision.sh -> ../provision.sh`                                                                                                               |
| 3   | Callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`                                              | VERIFIED | `017-provision-repairs-a-stale-venv.md` present                                                                                                                  |
| 4   | New tests failed before the fix and pass after, in all three cases                                  | REFUTED  | implementer report line 21 (see above)                                                                                                                           |
| 5   | Targeted QA 42/42                                                                                   | VERIFIED | JOURNAL/2026-11-09/162556Z-action-5d86e6.md records the coordinator's 42/42. The implementer's own run was 39 of 42 (format failed mid-run, then re-run passed). |
| 6   | CI QA run 42650039659 success                                                                       | VERIFIED | `gh run list`: QA, headSha cfa601263, success                                                                                                                    |
| 7   | CodeQL 42650039133 success                                                                          | VERIFIED | `gh run view`: workflowName CodeQL, event name "Push on main", conclusion success on cfa601263                                                                   |
| 8   | #168 closed                                                                                         | VERIFIED | `gh issue view 168`: CLOSED 2026-11-09T16:24:53Z                                                                                                                 |
| 9   | Merged to main with green CI                                                                        | VERIFIED | cfa601263 is in main history (HEAD~1); the runs in rows 6 and 7 succeeded                                                                                        |
