# Fact check r4: Plan 00500 Success Criteria

Summary: 10 claims: 7 verified, 1 refuted, 2 unverifiable.

## REFUTED

- **R1**: "`all --resume` reused the 41 other steps and re-ran only those two (3,659.8 s ...)". `untracked/scratch/full-gate-resume.txt` has exactly one reused step (`smoke_test`, marked `(reused)`; the file has two "reused" lines, both smoke_test). Every other step prints a fresh summary and a timing that differs from the fresh run (security 13.1 s vs 19.7 s, shell_check 20.5 vs 26.0, pyright 100.9 vs 143.0, tests 3,337.8 vs 9,266.9), so they were re-run, not reused. Only the tests step's legs show checkpoint reuse. The saving came from a short rerun, not from 41 reused steps. The 3,659.8 s and 9,654.8 s totals are correct. Correct the wording, or confirm from `provenance` why the other steps re-ran (the commit that changed the tree would invalidate them).

## Table

| #   | Claim                                                          | Verdict           | Evidence                                                                                                                                             |
| --- | -------------------------------------------------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 2026-10-10 full gate: 9,654.8 s total, tests 9,266.9 s         | VERIFIED          | full-gate.txt TIMING: tests 9266.9s, total 9654.8s                                                                                                   |
| 2   | gate prints a per-step timing summary and slowest tests        | VERIFIED          | full-gate.txt "TIMING (slowest first)" and "slowest tests:" (it lists tests, not files)                                                              |
| 3   | a commit during the gate left `pyright` and `tests` unrecorded | VERIFIED          | full-gate.txt "NOT RECORDED FOR THIS TREE" for `pyright` (line 18) and `tests` (line 97)                                                             |
| 4   | resume reused the 41 other steps                               | REFUTED           | see R1                                                                                                                                               |
| 5   | resume total 3,659.8 s                                         | VERIFIED          | full-gate-resume.txt total 3659.8s                                                                                                                   |
| 6   | no single-pass "before" total recorded                         | VERIFIED          | baseline report "Plainly"                                                                                                                            |
| 7   | 2026-10-09 run: 9,779.8 s for 129,518 tests                    | VERIFIED          | baseline report table row 2026-10-09 06:44                                                                                                           |
| 8   | that run was "resumed after a reboot"                          | UNVERIFIABLE-HERE | report says fresh `all` started 10-08 23:20, resumed 03:07 and 04:01; a reboot is stated only for the 10-08 chain. Host boot history would settle it |
| 9   | 135,644 tests today; 1.3% faster total, about 6% per test      | VERIFIED          | full-gate.txt "135644 passed"; (9779.8-9654.8)/9779.8 = 1.28%; per test 0.07551 vs 0.07118 s = 5.7%                                                  |
| 10  | py3.11 leg varied about 700 s between two earlier runs         | VERIFIED          | baseline: 5,842.9 vs 6,535.5 s = 692.6 s. (Quiet-host and noise judgement is opinion.)                                                               |
