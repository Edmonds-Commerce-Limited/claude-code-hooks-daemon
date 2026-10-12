# Fact check: N427 entry, PLAN.md Niggles count, STATUS-INDEX.md

Verdicts: 10 claims, 8 verified, 0 refuted, 2 unverifiable-here.

| # | Claim | Verdict | Evidence |
| - | ----- | ------- | -------- |
| 1 | The stub "daemon" lives in `tests/venv_bootstrap_sandbox.py` | VERIFIED | `stub_uv` writes a venv `python` script, lines 160-197 |
| 2 | The stub runs `<python> -c 'import time; time.sleep(60)' "$@"`, with the daemon's own args (`-m ...cli --project-root ... start`) | VERIFIED | `tests/venv_bootstrap_sandbox.py:178` (`"$@"` carries the CLI args) |
| 3 | The Plan 00477 Task 5.2a merge (57295f89c) taught the stub to treat `restart` like `start` | VERIFIED | Line 171 matches `start` or `restart`. `git show 57295f89c^1:tests/venv_bootstrap_sandbox.py` has no `restart`. 57295f89c is an ancestor of HEAD |
| 4 | The `test_provision_sh.py` sync cases use that sandbox | VERIFIED | `tests/integration/test_provision_sh.py:26,85` (imports and builds `Sandbox`). Sync tests at 434-665, e.g. `starts() == 2` at 448 |
| 5 | The command line contains `/tmp/pytest-of-root/.../project` | VERIFIED | `Sandbox.project = tmp_path / "project"` (line 123). init.sh passes `--project-root <root>` (init.sh:1795). A pytest tmp_path sits under `pytest-of-<user>` (standard pytest behaviour) |
| 6 | The processes outlive their test and its tmp_path | VERIFIED (mechanism) | `cleanup()` (lines 294-312) terminates only the single pid in the PID file. A restart overwrites that file (line 181), so the stand-in from the first start is orphaned. This fits the "accumulate" claim |
| 7 | They expire on their own after 60 s | VERIFIED | `time.sleep(60)`, line 178 |
| 8 | PLAN.md: the table has 132 rows | VERIFIED | STATUS-INDEX.md has 128 `N<digits>` rows (N427 included) plus 4 aggregate "N entries" rows, which makes 132 |
| 9 | PLAN.md: 2 rows are open (⬜): N424 and N427 | VERIFIED | `grep ⬜` on STATUS-INDEX.md gives exactly two rows, lines 7 (N427) and 10 (N424). The open-row count matches |
| 10 | "Eight processes" were alive at the coordinator's check, and `pgrep -f pytest` matched them | UNVERIFIABLE-HERE | A point-in-time observation. None are alive now (`time.sleep(60)` count is 0). A loop of the sync tests followed by `pgrep -af '[p]ytest'` would settle it |

The 1 row difference between 131 and 132 is the N427 row added by the diff, so the arithmetic is consistent.
