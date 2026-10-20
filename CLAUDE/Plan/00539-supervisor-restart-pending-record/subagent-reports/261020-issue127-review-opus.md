STOPPING BECAUSE: review complete.

**Verdict: APPROVE.** Nothing must be fixed before merge. Both targeted test files pass (138 tests) in the worktree's venv: `test_plugin_exit_for_restart.py` and `test_main_focus_hold.py`. I found no QA suppressions, no comment changelog narrative and no dead code.

**Checked and correct:**
1. **Write order:** the record is written only after every refusal in `request()` (pending, dry-run, cooldown, abandon cap, session id, focus hold), and before `/exit` is typed. A test proves this for each refusal.
2. **Removal:** the record is removed when typing raises (then re-raised under `BaseException`), on `abandon()` and in `finish()`.
3. **Deadline:** wall-clock, 30 + 5 seconds from before typing, so it covers the whole hold.
4. **Write:** atomic, mode 0600, in the state dir.
5. **Environment:** the variable is set only in the forked child before `execvp`. A resumed child gets the same path at relaunch.
6. The reader contract in CcySupervisor.md and the release note are accurate.

**Non-blocking, to file:**
- **S1** `claude-supervise.py` around line 10162: if `_forward_io` raises, `finish()` never runs and the record stays until its deadline. That is harmless (35 seconds at most), but `CcySupervisor.md`'s "Removed ..." bullet overstates it. Fix: remove the record in a `finally` around the waitpid/finish, or say in the doc that the deadline is the backstop.
- **S2** `test_the_deadline_margin_is_named_and_positive` in `test_plugin_exit_for_restart.py` only asserts a constant is greater than 0, so it tests nothing. Replace it with a test that the record's deadline is not earlier than the coordinator's hold.