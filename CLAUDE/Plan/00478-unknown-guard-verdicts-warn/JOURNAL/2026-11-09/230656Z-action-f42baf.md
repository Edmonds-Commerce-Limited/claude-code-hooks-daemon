## 23:06 · action · —   — Phase 0 delivered, GitHub #170 closed

Phase 0 delivered and GitHub #170 closed.

- Fix `484ab6791` + formatter pass `0726efd70`, merged to main; main QA CI run 42713973768 green; live probe allowed the reported awk command after a daemon restart.
- Shape: `command_position` gained an opt-in `awk_dollar_is_data` (only destructive_git uses it), so a single-quoted awk program holding `$1` is blanked as data unless it carries `system`, `|` or `>`, or a later segment runs a script an earlier one wrote. Every executing twin is tested as still denied.
- Known conservative edge: an awk `>` comparison keeps the old reading (a false deny is preferred to a false allow).
- The plan stays In Progress: Phase 1 (inventory of could-not-decide deny routes) is next, then Phase 2 conversion.
