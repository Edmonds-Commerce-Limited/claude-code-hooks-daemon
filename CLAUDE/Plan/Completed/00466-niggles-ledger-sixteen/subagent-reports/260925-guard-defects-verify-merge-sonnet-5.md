# Plan 00466: guard-defects verify + merge round (Sonnet 5)

Worktree: `worktree-n466-guard-defects`. Started at `27ad6df0f`.

## 1. Verify review 8's MAJOR-A/B/C against fix round 8

Re-ran review 8's own "Reproduce" probes (`probe_rv8_grep.pyprobe`,
`probe_rv8_oneliner.pyprobe`, `nested_extra_shapes.pyprobe bt N` for
N=1..8) against `worktree-n466-guard-defects` at `27ad6df0f` (after fix8's
6 commits). All three majors are CLOSED:

- **MAJOR-A** (grep `-f`/`--file`/`--exclude-from` reading a protected
  file): `probe_rv8_grep`, 0 mismatches on the rows review 8 called
  blocking. 4 rows still fail-open (`grep -r ''`, `--include=`, `egrep -e ... -e ''`), but review 8's own severity note already classes these as
  "no worse than the documented residual" (L2/N74), not blocking.
- **MAJOR-B** (escaped nested backticks): `bt` depths 1-8 all deny (depths
  4+ via the `TooManyToEnumerateError` fail-closed path, correctly).
- **MAJOR-C** (interpreter one-liner value-taking options): `probe_rv8_oneliner`,
  0/17 mismatches.

**Two extra variants per major**, not named by fix8's own tests
(`/workspace/untracked/scratch/rv8/probe_verify_variants.pyprobe`):
dollar-escape and doubled-backslash backtick forms (B), `--file=`/`--include=`
attached-value forms (A), `-X`/`--require=` value-taking one-liner flags
(C). 4/6 denied correctly; the 2 mismatches are not new regressions — one
(`--include=<key>`) duplicates the already-known non-blocking L2-class
residual, the other (doubled-backslash backtick) is an invalid probe: real
bash closes that span early too (verified against real bash), so it never
reaches a nested `bash -c` in the first place. No new MAJOR found; no code
changes needed.

## 2. Merge main

`git merge main --no-ff` (main was ~180 commits ahead, includes the B3
integration). 5 conflicts, all resolved keeping both sides' intent:

- `JOURNAL/00466-Journal-26-09-24.md`: append-only day-file, both branches'
  entries kept (marker removal only, no hand-authored content — the
  `plan_journal_guard` blocked a reordering edit, so entries stay in their
  landed positions rather than strict HH:MM order).
- `NIGGLES.md`: N20's remedy (main) and N16's full write-up (HEAD, this
  branch's own review-8 finding) both kept, ordered so N16 sits where its
  placeholder note said it would land.
- `PLAN.md`: both branches' niggle tables reconciled into one, every row
  from both sides kept, most-advanced status taken per row (e.g. N10/N11/
  N39 keep this branch's Remedied status; N3/N7/N12-N15/N17-N21/N26/N27/
  N29-N31/N44/N63 take main's newer Remedied status; N74-N79 are main's
  already-filed review-8 ledger candidates, all still Open).
- `path_exclusion.py` / `secret_file_matching.py`: both sides independently
  fixed the same empty-`file_path`/empty-home-prefix crash (N44); kept
  main's fuller docstring + implementation, dropped the duplicate.

Merge commit: `89f680a66019182530d359b15dc01db65885df37`.

## 3. QA

Targeted pytest on this branch's own touched files + both merge-conflicted
src files' tests (`test_rule_ids`, `test_shell_expansion`,
`test_path_exclusion`, `test_secret_file_matching`,
`test_quarantine_artefact_read_guard`, `test_secret_file_guard`,
`test_project_containment`, `test_enforce_llm_qa`): **1035 passed**.
ruff/mypy/pyright/black --check on the 7 touched source files: all clean.
Daemon restarted, `bin/hooks-daemon status` confirms **RUNNING**
(PID 1238560).

## 4. Gate

Queued in the background: `bash /workspace/untracked/scratch/gate.sh worktree-n466-guard-defects` (not awaited, per instructions).

## Left for the coordinator

- N16 (splat exemption both-edges false positive) is still Open.
- N74-N79 (review 8's L2/L3/L4/L5/L6/L8 ledger candidates) are still Open,
  out of this round's scope.
- Watch the gate output at `/workspace/untracked/scratch/gate-worktree-n466-guard-defects.out`
  for `exit=N head=89f680a66019182530d359b15dc01db65885df37`.
