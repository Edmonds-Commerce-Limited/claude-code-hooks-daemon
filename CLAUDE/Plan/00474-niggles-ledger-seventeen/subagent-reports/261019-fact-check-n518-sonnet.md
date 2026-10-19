# Fact check: N518-N520, N516/N517 merged, PLAN.md counts (Plan 00474)

9 claims: 8 verified, 1 refuted, 0 unverifiable.

## REFUTED (most consequential first)

**C6 (N519, second sentence)**: "`project_containment` judges an rsync destination but not a cp one."
Evidence against: `core/utils.py:60` defines `_COPY_VERBS = {cp, mv, install}`; `core/utils.py:973-982` makes
`scan_bash_write_targets` (default `authored_only=False`) collect their trailing operands as destinations
(non-authored). `project_containment.py:536-537` takes `scan.paths` from that scan, and its own deny text
(`project_containment.py:1024`) lists "`cp` / `mv` / `install` / `dd` destinations". The comment at
`project_containment.py:540-547` says the shared accessor deliberately does not author-lint cp/mv, but containment
resolves their destinations. So cp IS judged. The 00533 implementer report (lines 190-193) says nothing about cp,
so this sentence is the coordinator's addition and is unsupported. Change to the plan: delete the sentence, or
restate as what was actually observed (for example, whether a cp probe was run in the worktree and what it did).

## Table

| #   | Claim                                                                                                                                                        | Verdict  | Evidence                                                                                                                                                                                                                                                   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | PLAN.md: STATUS-INDEX table has 225 rows                                                                                                                     | VERIFIED | 227 lines start with `\| ` in STATUS-INDEX.md, less header and separator = 225                                                                                                                                                                             |
| 2   | 37 rows open (⬜)                                                                                                                                            | VERIFIED | `grep -c ⬜` over table rows = 37                                                                                                                                                                                                                          |
| 3   | 170 rows carry ✅; 166 of 221 N rows plus 4 carried summary rows                                                                                             | VERIFIED | 170 ✅ rows; 4 are the "N entries carried" rows? Non-N-prefixed rows with ✅ = 18 (14 range rows + 4 carried rows), which are counted within the 221 (225 minus the 4 carried rows); 170-4 = 166 and 225-4 = 221 are consistent                            |
| 4   | N518: `test_safety_handlers_hostile_input_performance[deep_eval_nesting]` failed on py3.12 only, "160x for 8x input", 5/5 isolated pass on head and main     | VERIFIED | Implementer report 00533 lines 187-189; test exists at `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py`, message format at line 267; `block-ancestry-severing-merge` display name at `constants/handlers.py:315`                    |
| 5   | N519: probe #119 denied by `project_containment` (priority 14) before `worktree_file_copy` (15) when the project root is a worktree; passes in main checkout | VERIFIED | `constants/priority.py:89` (14), `:219` (15); report lines 190-193                                                                                                                                                                                         |
| 6   | N519: containment judges rsync destination but not cp                                                                                                        | REFUTED  | see above                                                                                                                                                                                                                                                  |
| 7   | N520: py3.11 acceptance leg errored 10 times "Daemon not running", py3.12/3.13 reached a daemon                                                              | VERIFIED | Report lines 194-195 ("10 'Daemon not running' errors"). The exact string "no live socket" and "the gate printed that it had started one" are not in that report; not checked against gate logs                                                            |
| 8   | N516/N517 merged in 3dbbcfaeb                                                                                                                                | VERIFIED | `git log`: 3dbbcfaeb "Merge issue #124 full-gate fix"; ancestor of HEAD. Note the merge subject is the #124 fix merge; N516/N517 were on main before b4e83885c per report line 177-178, so "merged 3dbbcfaeb" is loose but the commit is on main with both |
| 9   | Evidence link: 00533 implementer report, section "Full-gate fixes"; report `subagent-reports/261019-n516-n517-spend-segment-opus.md` exists                  | VERIFIED | Section at report line 175; n516-n517 report present in this plan's subagent-reports                                                                                                                                                                       |

Caveats: the N517 verdict figures (48 markers, 60-100 ms, 256 KiB, 350-430 KB, 230 of 520 transcripts) were not in
the diff's scope to re-measure and were not checked here; they would come from the n516-n517 report.
Claim 7's quoted text beyond "Daemon not running" is unconfirmed.
