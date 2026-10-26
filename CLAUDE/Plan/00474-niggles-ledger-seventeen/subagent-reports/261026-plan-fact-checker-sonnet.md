# Fact check: NIGGLES.md N541, N542, N543 (Plan 00474 diff)

## REFUTED

1. N543 Status: "The gate should either model the in-command `git add` (as `-a` already is)..." and the Evidence
   "The gate read the index as it stood before the command's own `git add`".
   The gate already models it. `plan_qa_commit_gate.py:132` wraps the check in
   `simulated_staging(reading, ...)`, and `utils/staging_simulation.py:1-30` states that it runs each `git add`
   before the commit against a copy of the index (ledger N246 / 00466 N61). An unreadable add is applied as
   `add -A --ignore-errors`, and an incomplete simulation raises `SimulationIncompleteError`. So the first proposed
   fix is already implemented. The real observation, a denial on `git add -A <plan paths> && git commit`, is a
   runtime event I cannot check. The entry should be reframed as a defect in the simulation (for example its
   handling of `-A` with paths, or a simulation that silently fell back), not as a missing feature.
2. N541 title "eight `test_relay_repair` cases". `untracked/qa/00552-full-gate-report.md:5-8` lists four distinct
   tests, each failing on py3.12 and py3.13, which makes eight failures. The first-error-lines jsonl files hold 4
   entries per leg. The Evidence bullet is accurate ("failed on both legs"), but the title and Status overcount the
   cases. Say "four tests, eight failures across two legs".

## Table

| #   | Claim                                                                                                                 | Verdict                  | Evidence                                                                                                                                                            |
| --- | --------------------------------------------------------------------------------------------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | N543: `git add -A <paths> && git commit` denied by R-PLAN-QA-COMMIT                                                   | UNVERIFIABLE-HERE        | Runtime denial. The rule exists (`plan_qa_commit_gate.py`).                                                                                                         |
| 2   | N543: gate read the index before the command's own `git add`; archived PLAN.md reported "In Progress"                 | REFUTED (as a mechanism) | The gate simulates the add (`plan_qa_commit_gate.py:132`, `staging_simulation.py:1-30`). The observed report is UNVERIFIABLE-HERE.                                  |
| 3   | N543: separate `git add` then `git commit` committed cleanly                                                          | UNVERIFIABLE-HERE        | Runtime event.                                                                                                                                                      |
| 4   | N543: `-a` is already modelled                                                                                        | VERIFIED                 | `plan_qa_commit_gate.py:143` `commits_all`, and `include_tracked_changes=True` at line 132.                                                                         |
| 5   | N543: the deny message does not say a same-command add has not run                                                    | Partly contradicted      | `staging_simulation.py:29-30` says the incomplete-simulation message tells the user to run `git add` as its own call. The generic findings message was not checked. |
| 6   | N542: `qa-full-runner` protocol requires a report path                                                                | VERIFIED                 | `.claude/agents/qa-full-runner.md:23-25, 30`.                                                                                                                       |
| 7   | N542: `qa-full-runner` has no `Write` tool                                                                            | VERIFIED                 | `qa-full-runner.md:4` `tools: Bash, Read, Glob`.                                                                                                                    |
| 8   | N542: dispatch advisory (Plan 00460) warns of no `Write` tool                                                         | VERIFIED                 | `handlers/pre_tool_use/dispatch_declaration.py:301-309, 425, 562-568` ("READ-ONLY AGENT DISPATCH", "no `Write` tool").                                              |
| 9   | N542: dispatched without a path, the agent refused to run                                                             | UNVERIFIABLE-HERE        | Runtime. The definition supports it: "stop and say so if either is missing".                                                                                        |
| 10  | N542: reply auto-saved under `untracked/agent-reports/`                                                               | UNVERIFIABLE-HERE        | The directory exists and holds auto-saved replies. No 2026-10-26 file was checked or matched. `subagent_report_persistence` handler exists.                         |
| 11  | N541: failure is `posix_spawn: setsid unavailable on this platform` in `TestStartRelayRepair` and `TestSpawnDetached` | VERIFIED                 | `00552-full-gate-report.md:5-8`. `relay_repair.py:172` uses `os.posix_spawn(..., setsid=True)`.                                                                     |
| 12  | N541: both py3.12 and py3.13 unit legs                                                                                | VERIFIED                 | Same report lines. Also `untracked/qa/tests-py3.12-unit-unit-features.log` and the py3.13 log each contain 8 matches.                                               |
| 13  | N541: "eight cases"                                                                                                   | REFUTED                  | Four tests, eight failures (see above).                                                                                                                             |
| 14  | N541: fails in both gates (ee25ea681 and 65e8baf03), predating 00552                                                  | UNVERIFIABLE-HERE        | Both commits exist (`git cat-file`). Only the latest gate's artefacts remain. The report marks the failures [KNOWN].                                                |
| 15  | N541: run alone on main, all pass                                                                                     | UNVERIFIABLE-HERE        | Needs pytest, which I was told not to run.                                                                                                                          |
| 16  | N541: cause (test interference) unconfirmed                                                                           | n/a                      | Hedged by the entry itself.                                                                                                                                         |
| 17  | N541: file `tests/unit/install/test_relay_repair.py` exists                                                           | VERIFIED                 | `ls tests/unit/install`.                                                                                                                                            |

Totals: 17 rows. VERIFIED 7, REFUTED 3 (rows 2, 13, and the framing of row 5 partially), UNVERIFIABLE-HERE 6, other 1.
