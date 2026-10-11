# Apply owner sheet B to plans 00470, 00484, 00500

All decisions are worded as the coordinator's, under the "clear winner" guidance, not as owner rulings.

## Files changed (no commit made)

- `CLAUDE/Plan/00470-persistent-session-optimisation/PLAN.md`: Task 4.3 declined (decision 1); Task 4.4 done (decision 2); Tasks 3.5 and 4.1 marked 🚫 waiting on the owner or IaC (sheet B items 7 and 8); the orchestrator-model criterion ticked as declined. Status stays `Blocked` because 3.5 and 4.1 remain.
- `CLAUDE/Plan/00470-persistent-session-optimisation/JOURNAL/00470-Journal-26-10-11.md`: decision entry, via `mkplan.bash --journal`.
- `CLAUDE/Plan/00484-dbf-adoption-and-toolchain-conformance/PLAN.md`: success criterion 3 reworded to "every gap is closed or listed in the declaration" (decision 4) and ticked; Task 3.3 ticked.
- `CLAUDE/Plan/00484-dbf-adoption-and-toolchain-conformance/JOURNAL/00484-Journal-26-10-11.md`: decision entry.
- `README.md`: new "Conformance declaration" subsection after "Defence Before Fix" (project and artefact toolchain levels, known gaps, G14 fail-open states, G11 scan mode listed as a known gap).
- `CLAUDE/Plan/00500-full-qa-timing-and-speed/` moved by `git mv` to `CLAUDE/Plan/Completed/00500-full-qa-timing-and-speed/`. PLAN.md now has Status `Complete`, the wall-clock criterion recorded per decision 5 (Addresses #107), and a holding-area success-criteria line citing release note 009. A journal entry was added in the moved folder (`JOURNAL/00500-Journal-26-10-11.md`).
- `CLAUDE/Plan/README.md`: 00500 row removed from Active and added to Completed; the 00441 row (30-row window) moved out; statistics set to Completed 427, Active 52.
- `CLAUDE/Plan/Completed/README.md`: the 00441 row added at the top of the archive (link prefix `Completed/` dropped, as for the existing rows).
- `CLAUDE/Plan/00474-niggles-ledger-seventeen/OWNER-QUESTIONS-261011.md`: one link repointed to the archived 00500 folder.
- Scratch bodies for the journals: `untracked/scratch/261011-j470.md`, `261011-j484.md`, `261011-j500.md`.

## Notes for the coordinator

- Plan 00484 now has every task and criterion ticked but its Status is still `Blocked`. I did not archive it (not asked). Completing it needs the Status flip, a holding-area success-criteria line, the `git mv`, README row and stats, and a repoint of the README link to CONFORMANCE.md (which currently points at the live plan folder).
- The declaration publishes the `toolchain` level only (G16's permitted form); no `detector` declaration is made. CONFORMANCE.md's draft block and G16 row still say "open for Task 3.3" and were not edited. Exact counts in the draft (113 suppressions, 32 checkers, 10 Semgrep IDs) were not republished since not re-verified.
- `plan-qa --sweep` reports no findings except an unrelated advisory (00495 journal freshness). The 00470 PLAN.md size advisory (about 24 KB) predates this work.
