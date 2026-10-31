# Fact-check: PLAN.md Task 2.5 annotation (diff 00555 ...diff)

REFUTED: none.

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | The decision-neutral half is on main at `27fd1725f` | VERIFIED | `git merge-base --is-ancestor 27fd1725f main` true; `git branch --contains` lists main; commit adds bin/hooks-daemon, template, test, report |
| 2 | `hooks-daemon diagnose` is read-only | VERIFIED | `_diagnose_venv_free` (bin/hooks-daemon:330-369) only runs diagnose-venv, reads the build record and pid file, `kill -0`, `-S` test; no writes. `diagnose_venv_start` (paths.py:3526) has no write calls |
| 3 | Runs with no venv and no daemon | VERIFIED | Answered before venv resolution (bin/hooks-daemon:418-423); with no venv prints "no venv found" and the fix (356-368); daemon state read from pid file only. Test file `test_bin_hooks_daemon_diagnose_without_venv.py` covers it; bin and template are byte-identical (`cmp`) |
| 4 | Names drift | VERIFIED | paths.py:3554-3567 emits "drift: pyvenv.cfg records ..."; test asserts it |
| 5 | Names the last build record | VERIFIED | `_print_last_build` (402-416), called at 361; test asserts "Last venv build: failed at ..." and "Build log:" |
| 6 | Names the daemon state | VERIFIED | `_print_daemon_state` (374-395); tests assert "daemon: not running" / "running (pid N)" |
| 7 | Names the fix | VERIFIED | line 367 prints `$BIN_DIR/hooks-daemon repair`; test asserts it |
| 8 | Still waiting on the owner: whether the daemon-down guard lets it through | VERIFIED (state of work) | diagnose-verb report line 21: "Not touched: any allow-list or hook-side guard"; no allow-list change in the merge's 4 files |
| 9 | Success criterion ticked: the drift-at-current-key lockout the demo found is fixed | VERIFIED | Demo and fix reports exist in subagent-reports/ (`261031-drift-self-heal-demo.md`, `261031-fresh-check-drift-fix.md`); `venv_python_usable` now gates freshness in scripts/install/venv.sh (lines 118-163, 1211, 1740, 1840) |
| 10 | The demo "reproduced the incident shape" | VERIFIED | Demo report line 9: "PASS for the incident's real shape (Variant B)" |

Note: the diff's DBF-REPORT.md hunk was outside the brief and not checked beyond the fix claim above (`_venv_is_fresh` now requires `venv_python_usable`, venv.sh:163).
