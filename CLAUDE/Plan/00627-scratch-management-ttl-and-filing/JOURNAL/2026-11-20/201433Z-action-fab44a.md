## 20:14 · action · — — Task 3.8 precondition: restore outcome split

Task 3.8 precondition unit 3 (restore outcome split) closed.

`restore` now returns `RestoredWithLeftovers(Restored)` (frozen, `problems`, `staging`) when the no-replace
rename succeeded but a later step failed: the root-mode `fchmod` (it used to sit in a `finally` and turn a
completed move into a misleading `RestoreRefused`), the destination `fsync`, or `_clean_staging`. A failure
before or at the rename still cleans staging and raises `RestoreRefused`; if that cleanup fails the message
names the staging left so `reclaim_staging` can remove it. Tests cover each after-move failure, a failed
rename, and a failed cleanup during a refusal. No new rename or delete surface; not wired to the CLI.
