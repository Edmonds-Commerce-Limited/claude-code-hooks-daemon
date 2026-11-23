# Independent review of PR #231 (Plan 00523 F1-F4 and Task 2.4)

Branch `plan-00523-rate-limit-dialog`, commit `1691f70ad`. I read the diff against `origin/main` and the code around it. Line numbers refer to `.claude/ccy/claude-supervise.py` in the worktree unless a file is named. I ran `tests/unit/supervise/test_rate_limit_dialog.py` under `nice -n 19` with `PYTHONPATH=<worktree>/src` and `/workspace/.venv`: 171 passed. I did not run any other tests and did not edit the PR.

## Verdict: safe to merge

I found no path that makes the supervisor type something new:

- Every new path takes state back or holds. None of them adds a send.
- A take-back only runs after a payload that wrote zero bytes. A held payload returns at 10705-10712 before any write. A vetoed one returns at 10932-10936 before `_apply_decision` is called.
- A take-back therefore cannot produce a duplicate Enter or a duplicate `continue`.
- Every host-side file error is caught: load returns `{}` (8889-8891), save is wrapped (10872-10877), and the `/proc` read returns None.
- No field was added to `TickFacts` or `TickOutcome`, so an old host and a new worker (or the reverse) still talk to each other.

The findings below are non-blocking. Findings 1 and 2 should be fixed before this ships in a release, because they make the release note and the readiness signal untrue.

## Findings

1. **Medium (docs and hot-reload): F3 and F4 do not reload with the worker. They need a host relaunch, the same as F2.**

   - Release note 090 says "The worker half reloads by itself; the held-Enter take-back and the banner line need the next ccy relaunch".
   - The builder report says "worker-side changes (F1, F3, F4, the sweep) reload by themselves".
   - Neither is accurate. Only the host writes the two fields that drive these fixes:
     - `enter_takebacks` is incremented only in `_rate_limit_undo_vetoed_enter` (10815-10819).
     - `resume_vetoed_at` is set only in `_rate_limit_undo_vetoed_resume` (10868).
   - Both functions run in the host, from `_rate_limit_host_veto` and `on_held` at 12838-12852.
   - Under a host started before this PR, the worker's F4 cap check (9159) never fires and F3's `own_redraw` (9274-9277) is always False.
   - Both fail safe. Without F4 the old bound applies (occurrence key cap 6, window cap 30). Without F3 the old behaviour applies: the window is abandoned at the re-check deadline, and nothing is typed.
   - Fix: change the note to say that only F1 reloads with the worker, and that F2, F3, F4 and the armed-status lines need the next ccy relaunch. Correct the builder report the same way. The CcySupervisor.md section says nothing about reload, which is acceptable.

2. **Medium (Task 2.4 accuracy): `ARMED` is printed even when the answerer cannot see the screen.**

   - `rate_limit_armed_status` (386-397) looks only at `CCY_RATE_LIMIT_DIALOG` and `dry_run`.
   - The answerer acts only on a `screen_dump`. `_rate_limit_screen_dump` (1722-1734) returns `""` when there is no screen check, and `_build_screen_check` (1711-1719) builds one with `binary=resolve_screen_binary(...)`, which may be None.
   - So a session with no `hooks-screen` binary (a client install without the build, or an unsupported architecture) prints `ARMED (answers the dialog, resumes after the reset)` and then never answers.
   - Task 2.4 exists for Plan 00632's readiness check, and a false `ARMED` is the result that check most needs to avoid.
   - Fix: pass whether the screen binary resolved, and print something like `OFF (no hooks-screen binary)` or `inert (...)` when it did not.

3. **Low (F1 side effect): state files of a dead child that was killed with its dialog open are never swept.**

   - The new keep rule (8941-8948) skips every file whose `occurrence_open` is true and whose phase is not `answered` or `cleared`.
   - The sweep runs over every child's files in the shared status dir, not only the live child's.
   - A common way to reach this state: the human hits the limit and quits Claude while the dialog is on screen. Their keys set `abandoned` (9073-9080), and the child exits before any dialog-free dump clears `occurrence_open`.
   - Before this PR such a file was deleted at anchor+48h. Now it stays for ever, and the sweep re-reads every one of them each time a window opens.
   - No injection results from this. The files are small and keyed to a pid and start tick that cannot come back.
   - Fix: apply the keep rule only while that file's child is alive, by checking `/proc/<pid>/stat` start ticks against the file name. Alternatively, put a long absolute cap on kept files (for example 30 days).

4. **Low (F4 design): the cap of 2 is safe but can leave an unattended session stuck without telling anyone.**

   - Safe:
     - A take-back follows only an Enter that was not typed, so the cap only limits retries and cannot cause a duplicate.
     - The cap is checked on the Enter path after the confirm tick (9159), and dry-run is unaffected.
     - After the cap, phase stays `""`. So `_rate_limit_prefill_blocks` (9207) does not hold other families on that account, and no late `continue` is ever owed.
   - The cost: after two take-backs the dialog is left on screen for the rest of the window.
     - It is held every tick with a deduped NOOP line in `decision.log`, and nothing is shown on the status line.
     - Every take-back so far came from a race between the decision and the apply (output pending, a stdin byte, or the focus latching during the worker round trip). The worker had already required 3 s of quiet output and confirmed focus, so two such races in one window are unlikely but possible on a busy terminal.
   - `enter_takebacks` is never reset per occurrence.
     - In a window with no parsed reset, which lives as one state across occurrences (9127-9129), two take-backs disable the answerer for every later occurrence until that state expires.
     - That expiry is never, while an open non-family state is kept by the load (8906-8909).
   - Recommendation: keep 2. Post a status-line message through the existing `StatusMessagePoster` when the cap trips, so a human knows the dialog is theirs. Consider resetting the count when the occurrence closes, if the owner wants one retry per occurrence rather than per window. The owner should confirm the intent, as the builder asked.

5. **Low (F3 scope): `own_redraw` also hides output that came before the veto.**

   - The test at 9275-9276 is "last output ≤ vetoed_at + 5 s". That also covers output after the reset and before the veto, which the re-check was meant to judge.
   - The only send made while a re-check is open is the clear, and that requires the pre-fill on screen (9298-9301). A vetoed clear left the pre-fill in place, so in practice the next tick clears again rather than sending `continue` into an ambiguous box.
   - I found no live sequence that makes this a duplicate `continue`. The idle, work_idle and busy-footer gates (9260-9266) also apply.
   - Fix (optional): bound it on both sides, `vetoed_at - slack <= last_output <= vetoed_at + slack`. Or skip `own_redraw` when `resume_recheck_until` was already set before the veto.
   - `resume_vetoed_at` is also set for a send held by the focus model, where no redraw happened. Under the same reasoning this is harmless.

6. **Low (tests): the `on_held=` wiring in `supervise()` is not tested.**

   - `TestF2HeldEnter` (test file 1603) calls `_apply_worker_outcome` directly with its own `on_held` lambda.
   - If the `on_held=` argument were deleted at 12847-12852, every test would still pass. That is the same gap D5 closed for `apply_veto` with the spy test at test file 1460-1483.
   - The held `continue` and clear paths (`_rate_limit_host_held` into `_rate_limit_undo_vetoed_resume`) are not tested either. Only the Enter is.

7. **Low (tests): the F4 cap test does not pin that a retry happens.**

   - `test_the_enter_is_pressed_again_only_up_to_the_takeback_cap` breaks out of its loop when no Enter comes back (test file 1716), so it also passes with a cap of 1 or 0.
   - It proves the cap exists, not that one take-back is followed by a fresh Enter.
   - Fix: assert that the Enter returns after the first take-back.

8. **Low (tests): the Task 2.4 banner test is close to a tautology.**

   - `test_the_banner_carries_the_line` (test file 1758) passes a literal string in `extra_lines` and checks the banner prints it.
   - No test checks that `supervise()` passes `rate_limit_armed_status(...)` to the banner, or writes it to the decision log (12611-12612, 12647-12651).

9. **Low (docs):**

   - **Stale docstring.** The `_rate_limit_apply_veto` docstring (10779-10783) still says a held Enter "never reaches this veto and keeps `answered`". F2 made that untrue.
   - **"First decision-log line" is wrong.** PLAN.md (Task 2.4), CcySupervisor.md, the release note and the builder report all say the status is the first decision-log line. It is the second: `supervisor active (...)` is written first (12606-12612).
   - **Stale status line in PLAN.md.** Line 188 still says "Phase 1 (live capture), Phase 2b and Task 2.4 are still open".
   - **Key wording differs from the plan.** Task 2.4 asks for "a config key that turns the answerer on". The key as built turns it off, and the feature is on by default. The "as built" note records the key but not this inversion; one more sentence would cover it.

## The plan's acceptance wording, item by item

- **F1, the sweep keeps an open taken-over or key-capped state:** met. The keep rule mirrors the load (8904-8909 against 8941-8948). Finding 3 is the side effect.
- **F2, a held Enter is taken back like a vetoed one:** met (10927-10931, 10823-10840), but the `supervise()` wiring is untested (finding 6).
- **F3, a vetoed resume is retried, not abandoned:** met for the redraw case (9274-9280), once the host is relaunched (finding 1).
- **F4, a cap of 2:** safe, with no duplicate and no injection. It can leave the dialog stuck and only the decision log says so (finding 4). It is inert until the host is relaunched (finding 1).
- **Task 2.4:** the line is present in the banner and the log, but it can claim `ARMED` falsely (finding 2).
