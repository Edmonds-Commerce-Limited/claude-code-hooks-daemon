# Plan 00483 batch (a): records and inventory close-out, 2026-10-09

Documentation only, plus one data file (the corpus). No `src/` change.

## Done

1. PLAN.md Task 3.1: each "fixed on branch worktree-X" now also names the merge commit from the status audit
   (a248be4c2, 3495e36b9, 6f9cd976b, fec3aa703, 9b2e15be1, 76bf848aa, c953b0c62, 2ba5b72a2, f152ea9d9, cd7638c73,
   012915bd9 superseded by dc5c9263b, 3644f831e, 9d182f299). Task 3.1 ticked. Task 3.2 stays open: 43 of 50 probes still deny.
2. CARRIED-REFIX-BRANCHES.md status lines: N170 and N136 fixed (9b2e15be1), N130 fixed (012915bd9, then superseded by
   the protected-file index at dc5c9263b). N124 stays open with its residual stated: `find -regex`/`-iregex` operand.
   Re-confirmed live: a Bash command carrying `find . -regex '.*decision:.*'` was denied R-SECRET-BASH-MENTION (matched
   `.vault-pass*`). The `python3 -c` regex shape was not re-probed. N222 (test half only) and N260 (plugin flag and
   daemon state) stay open with their residuals in the new 00474 section.
3. Task 2.3: new section "Plan 00483 write-back for the 00466 entries" in 00474 NIGGLES.md plus 10 index rows in 00474
   PLAN.md (the convention for carried entries is an index row "Carried from 00466" and a status). Dismissed (threat
   model), source the Task 2.1 triage: N45, N57, N68, N71, N72, N77, N78, N89. No change: N62 and N74, source the
   Fable-delegated rulings (extended to those entries by the coordinator, confirmed by a coordinator call); N74 was also
   settled by owner ruling A2. Nothing is attributed to the owner except A2.
   Corpus rows added (all measured by `check_dangerous_invocation_corpus.py`, now 37 rows, 0 open, 23 accepted):
   `dismissed-n57-variable-body-in-bash-c`, `dismissed-n77-variable-body-in-eval`, `dismissed-n89-redefined-data-sink`,
   and the two N240 `script` rows the Fable ruling promised but the corpus never got. N78 has no row: main denies
   `cat $'\151d_rsa'`. A literal assignment (`V='git reset --hard' && bash -c "$V"`) is also denied, so the N57 and N77
   rows hold the variable with no visible assignment.
4. INVENTORY.md Part H: verdicts for `write_protected_paths` (conforms in design; in-scope gaps on `perl -i`, `rsync`,
   `find -delete`, `/bin/rm`, literal `bash -c` body, brace lists, not yet filed), `host_command_guard` (conforms;
   candidate widenings `podman`, `uv pip`, `PIP_INDEX_URL`) and `github_issue_assignment_guard` (conforms; one low
   raw-text commit-match false-positive candidate). Code read only, no probes: marked UNVERIFIED.
5. Success Criteria: 2 and 3 ticked with evidence. 1 and 4 stay open.

## Left for batches b and c

- Criterion 4: the 43 denied probes in the status audit section 3, none yet fixed or in the ledger.
- Criterion 1: 00474's own entries N353 to N381 are not triaged under the two-part test.
- The in-scope gaps and the false-positive candidate in Part H need ledger entries if the owner wants them filed.
- Not done (outside this batch): a dated freshness note on INVENTORY Parts A to F for the A1/A2 removals.
