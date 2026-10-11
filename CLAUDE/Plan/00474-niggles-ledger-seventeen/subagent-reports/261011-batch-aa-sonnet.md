# Batch AA: PLAN.md and NIGGLES.md status reconciliation

Documentation only. No entry's substance changed.

## PLAN.md

- Stale rows set from the ledger bodies: N311 (22429c3a5), N309 (Plan 00492), N307 and N306 (530ffc83d), N305 and N304 (branch n304-n305-gate-dirs, no merge commit named), N302 (1078e4291), N298 (branch quoted-text-fps), N246 (530ffc83d). N256 is part 1 fixed, part 2 moved to Plan 00478.
- N338-N342 split: N338-N341 fixed, N342 open as an owner decision.
- N222 row: the guard and test halves are fixed (batch D). The saved `UNFINISHED-N252-SCALING.md` diff is obsolete. It adds `MIN_MEASURED_SECONDS` and a repeat-until-the-clock-moves loop to `cpu_seconds`. Current `tests/scaling.py` solved the same clock-lag problem differently (4115b5f9e: sampling budget with `MAX_REPEATS`; d97464d6e: `scaling_ratio` floors its denominator at the clock tick), and has none of the diff's names. Applying the diff would conflict. The file is kept.
- Carried-entry rows: all four carried-branch rows now read 0 open. Every one of the 55 "On main" lines in CARRIED-REFIX-BRANCHES.md reads fixed, dismissed, folded or no change. The old 12/6/8 figures were the triage-date counts.
- 00466 row: 42 open (see NIGGLES.md note below).
- Added rows for N312-N412. Fixed runs are grouped into range rows because one row per entry (about 100) would pass the 35,000-byte PLAN.md limit; the aligned table costs about 200 bytes a row. Every open, owner-decision, partly fixed and deliberate-limit entry has its own row. Owner decision: N333, N342, N389, N402 (b), N411, N376 serial phase, N373 setters, N361 severity, N397 copy half, and N396, N334, N336, N337 (live ccy supervisor). Deliberate limit (🚫): N378, N330, plus residual limits marked beside N403, N385, N374, N354. N369 is plain Open (agent-workable, not an owner call).

## NIGGLES.md

- Header at lines 7-15: "65 open" is now "42". The archived 00466 index has 56 rows marked open or in progress, not 65. Of those, 14 are resolved in this ledger (N222, N95, N42, N79 fixed; N45, N57, N68, N71, N72, N77, N78, N89 dismissed; N62, N74 no change).
- "Status: Open (all 55)" is now "0 open of 55", with the basis stated.
- N374 and N376 headers carry a status in the standard style.

## Not done

- The original 65 figure could not be reconstructed; the 56 comes from counting the index status column.
- N310 stays 🔄 (body says fixed for all four instances, open as a class).
