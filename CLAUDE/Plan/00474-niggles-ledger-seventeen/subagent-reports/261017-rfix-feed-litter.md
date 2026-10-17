# rfix-feed-litter: feed double-offer and scratch-scan deadline defects

Source: second-pass reviewer E, D1 and D2. No owner decisions were needed, so there are no assumptions to list.

## D1: deliver_pending double offer

Cause: `deliver_pending` built both folder lists (`pending_folders()` and `offered_due()`) before either batch ran. A plan with a new pending record and an older offer past the re-offer interval was handed over by the pending batch, then again by the stale-offer batch (the offer it had just written was read as stale only because the list was already computed). Result: two identical instructions, and the offer count reached the cap one offer early.

Fix (`utils/plan_fact_check.py`): the batches now hold callables, so `offered_due(moment)` is evaluated after the pending batch has run.

Test: `TestDelivery.test_a_stale_offer_and_a_new_pending_record_give_one_instruction`. Red before the fix, green after: one message, `offered.offers == 1`.

## D2: scratch walk spends the shared deadline

Cause: `collect_scratch_report` set `shared.exhausted = True` for any incomplete walk (entry cap, unreadable directory, failed stat). `idle_housekeeping_advisor` passes that same deadline to the gone-branch scan, which then printed "SCAN INCOMPLETE: the time budget ran out" above a complete ref list, or a bare block when no ref was gone.

Fix (`utils/stale_litter.py`): the line that spent the deadline is removed. `ScanDeadline.expired()` already marks `exhausted` on a real timeout, so only a real timeout spends it. `_ScratchTally` now records `incomplete_reasons` (entry limit, time budget, unreadable path) and the scratch report names them: "SCAN INCOMPLETE: <reasons>, so the figures below are a lower bound."

Tests (`tests/unit/utils/test_stale_litter.py`):

- entry cap leaves the shared deadline unspent and names "entry limit"
- unreadable directory (monkeypatched `os.scandir`, so it also holds when running as root) gives its own reason
- failed stat gives its own reason
- an incomplete scratch walk leaves the ref report without "SCAN INCOMPLETE", both with a gone ref and with none (quiet)
- the existing time-budget test now also asserts the "time budget" reason

Red run (fixes reverted): 6 failed, 83 passed in the two test files. The six are the new rows above. The red output was quoted from `untracked/scratch/red.txt`; for example the stat case failed with `assert 'could not be read' in 'OLD SCRATCH FILES ... SCAN INCOMPLETE: it stopped at its entry limit or time budget ...'`. After restoring the fixes: 139 passed (plan_fact_check, stale_litter, idle_housekeeping_advisor tests).

## Release note

No new callout. Release note 014 said the scan reports SCAN INCOMPLETE "when it stopped early"; it is edited to say it also reports the reason and covers a part of the tree it could not read.

## Sibling check

- Other writers of `exhausted`: only `ScanDeadline` itself (`utils/stale_checkouts.py`); no other scan sets it from outside.
- `stale_checkouts` uses the same deadline only through `run`/`expired`, so it is unaffected.
- `idle_housekeeping_advisor` still passes the shared deadline, which is now correct.
- `plan_fact_check_feed` tests still pass (one test file run).
- No other call site computes two dependent folder lists up front in `plan_fact_check.py`.
