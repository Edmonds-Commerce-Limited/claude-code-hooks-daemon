STOPPING BECAUSE: the review is finished. **APPROVE.** I found 0 Critical, 0 Important and 2 Suggestions (both non-blocking, to be filed as plan tasks).

I reviewed 4 files (+112/-4). The 268 tests across the four plan_number_helper test files pass on this worktree's own venv. I compared the 34 shapes from your list and 39 inner-command shapes on origin/main (5f9f99444) against HEAD (5297f75b8). The #198 reproduction (`echo "found: $(grep -rl takeover CLAUDE/Plan/00001*/…)"`) was denied on main and is allowed at HEAD.

**Still denied at HEAD:**
- Every scan in your list: `echo "$(ls -d CLAUDE/Plan/* | tail -1)"`, `echo $(ls CLAUDE/Plan/0*)`, the `printf "$(find … -name '0*' | sort | tail -1)"` form, `echo CLAUDE/Plan/00*`, `0059*` (4 digits still counts as discovery), `000[0-9]*`, and `[0-9][0-9][0-9][0-9][0-9]*`.
- `echo $(echo CLAUDE/Plan/*)` and two levels of nesting.
- `echo '$(' CLAUDE/Plan/*`: the single-quoted literal is handled correctly.
- `echo "$(date)" CLAUDE/Plan/*`, `echo x >(cat) CLAUDE/Plan/*`, and `echo "$(ls -1 CLAUDE/Plan | sort | tail -1)"` (plus the find, grep, stat, basename and printf versions).

**Changed from deny to allow, and acceptable:**
- Unterminated `$(`, `"$("` and a lone backtick. Bash rejects these as syntax errors, so they never run.
- `00596*` and `12345*`. Five digits name one plan, which is consistent with the `ls` rule.
- `cat`, `wc`, `head` and `du` over `CLAUDE/Plan/0*/…` inside `$(…)`. These read files rather than discover a number, so main's deny was a false positive.

**Suggestion 1 (confidence 75): an inner discovery scan is now allowed when wrapped in echo.**
- `echo "next: $(realpath CLAUDE/Plan/0* | tail -1)"` and `echo "$(for d in CLAUDE/Plan/0*; do :; done; echo $d)"` (and their backtick forms) were denied on main and are allowed at HEAD.
- This is not a new hole: the bare commands are allowed on main too. Main only caught them by accident, through the echo rule.
- Fix: in `matches()` (`plan_number_helper.py`), add rules for `realpath`/`readlink -f` over a plan-dir glob, and for a `for … in <plan_dir>/<glob>` loop. Use the same 5-digit allowance, and add deny tests for the bare and the echo-wrapped forms.

**Suggestion 2 (confidence 70): arithmetic or nested parentheses end the echo gap early.**
- `echo $((1+2)) CLAUDE/Plan/*`, `echo "$(( 1 + 1 ))" CLAUDE/Plan/0*` and `echo $(foo (bar)) CLAUDE/Plan/*` were denied on main and are allowed at HEAD.
- Cause: in `_ECHO_ARGUMENT_GAP` (`plan_number_helper.py:91-93`), the substitution pattern `\$\([^()]*\)` cannot match any inner `(`, and the `(?!\$\(…)` lookahead stops the gap from treating `$(` as plain text. So the gap halts before the real glob.
- This shape is unlikely from a careless agent, so it is non-blocking.
- Fix: add an alternative for `\$\(\([^()]*\)\)` and one for a single level of nested parentheses, plus deny tests for both.

The tests are behavioural rather than theatre: the implementer's report shows 6 new tests failed before the fix, and the deny cases call `handle()` and check for DENY. The probe scripts and their outputs are kept in `/workspace/untracked/worktrees/worktree-597-echo-glob-substitution/untracked/scratch/probe597/` (`probe.py`, `probe2.py`, `main.txt`/`head.txt`, `m2.txt`/`h2.txt`). The scratch origin/main worktree was removed with plain `git worktree remove`.