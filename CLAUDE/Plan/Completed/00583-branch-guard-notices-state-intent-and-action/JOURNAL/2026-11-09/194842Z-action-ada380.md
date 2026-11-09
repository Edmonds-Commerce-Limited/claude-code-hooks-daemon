## 19:48 · action · —   — Delivered and closed (GitHub #192)

Delivered. The fix (`d60da0fda`) passed targeted QA 42/42 on the branch (`llm_qa.py changed --range main..HEAD`, 6266 changed-scope tests, recorded green for `7514c6333`). The branch then merged main in (`7d954f213`, plan and doc commits only, no src or tests change), and main fast-forwarded to that merge commit. The daemon restarted cleanly on it, which also settles that the new `branch_stop_gate` → `branch_sweep` import is not circular. The first main CI run after the merge (42676054890) failed on a `provision.sh` shellcheck finding (SC2030/SC2031) introduced by Plan 00581, not by this plan; it was fixed in `43f1a9a98`, and that commit's run 42682133539 (full suite on 3.11/3.12/3.13, covering this fix) is green. GitHub #192 is commented and closed. Why CI's change-to-test mapping missed the lint test for Plan 00581 is filed as Plan 00586 finding G.

All three surfaces now say why they fired and what to do next:

- **Stop-context dormancy line:** carries `BRANCH_LIMIT_PRINCIPLE`, says the session should take the work on before starting anything new, and gives one action line per branch (finish and merge, park with a reason, or delete once the guard proves nothing is lost).
- **`branch-sweep` Dormant section:** states the principle once, then the same per-branch action via the new `dormant_action()`.
- **`wip.cap` deny:** demands finishing, parking or deleting before starting; "continue in one of them" is gone.

RED evidence: 3 tests failed before the fix, one per surface (implementer report in `subagent-reports/`). Release note: `018-branch-guard-notices-state-intent-and-action.md`. The reboot that interrupted the first QA run is why QA ran twice; the earlier run left no result.
