# Code Review: Plan 00537 / issue #125, branch worktree-plan-00537

Reviewed `15533743f..25f9d3a45`: 4 commits, 9 files, about 1,280 lines added.
The main parts are `.claude/ccy/claude-supervise.py` and
`tests/unit/supervise/test_main_focus_hold.py`. The probe is at
`/workspace/untracked/agent-reports/261020-issue125-review-probe.py`. Run it from
the worktree root with `/workspace/.venv/bin/python -I <probe> <worktree>`.

Verdict: **CHANGES REQUIRED**. 1 critical, 2 important, 3 suggestions.

## Critical

### C1. After a lone Esc, the next letter can blind the focus model for good (Confidence: 95%)

**Location:** `.claude/ccy/claude-supervise.py`, `MainFocusModel.feed` / `_consume_esc` /
`_consume` (`_ST_STR` branch). These are the lines added at the hunk at about line 926.

**Problem:** `feed()` can end a read with `_state == _ST_ESC`, and that state carries
over into the next read. The next byte is then parsed as the second byte of an
escape sequence, even if it was a separate keystroke typed seconds later.

The human's next key is a printable letter. If it is `P`, `X`, `]`, `^` or `_`
(the `_STRING_INTRODUCERS`), the model enters `_ST_STR`. It stays there until a
BEL or `ESC \` arrives, and a human never types either. While in `_ST_STR`,
every later Up/Down is swallowed (`ESC` goes to `_ST_STR_ESC`, then `[` goes back
to `_ST_STR`). So nothing latches. Esc presses are swallowed the same way.

**Evidence (probe output):**

```
A: Esc alone, type 'Please fix', Enter, then Up (expect HELD)   confirmed=True
B: Esc alone, type ']', then Up (expect HELD)                   confirmed=True
```

Pressing Esc to interrupt Claude and then typing "Please ..." is an ordinary
sequence. After it, the supervisor types into a sub-agent again, which is the
exact defect #125 exists to stop. This is a false negative, in the unsafe
direction, and it lasts for the rest of the session.

The same carry-over also causes false holds after the human has released one
(probe cases C, D and E). After Up, Esc, then typing "OK", "[x" or "Please",
the old hold is restored. It keeps its old `since`, so it can come back straight
at the loud escalation level. The human pressed Esc as the banner told them,
and the hold silently returned.

**Fix:**

1. Do not let an ESC that ends a read put the next read into string state.
   The simplest fix: at the end of `feed()`, commit a trailing ESC as a bare Esc
   and reset to `_ST_GROUND`.
   - If the split focus-event case must be kept, only re-enter a sequence when
     the next read is a complete CSI/SS3 sequence (`[` params final, or `O` final).
   - Never enter `_ST_STR` from a carried-over ESC.
2. Bound `_ST_STR`. Human keystrokes do not produce DCS/OSC/PM/APC, so a string
   state left open past the end of a read should drop back to ground.
3. Add tests for probe cases A to E.

## Important

### I1. When the `_apply_decision` belt holds a payload, the host still adopts the worker's post-send state (Confidence: 85%)

**Location:** `supervise()._on_poll`, at about lines 9867 to 9893, together with
`_apply_decision` at about line 8140.

**Problem:** When the belt holds a payload (`main_focus_confirmed=False` at apply
time), `_apply_decision` returns False. `_on_poll` then still runs
`machine.import_state(outcome.machine_state)`. It also calls
`activity.line.clear()` whenever `outcome.abandoned_box_flushed` is set, and it
does so whether or not anything was typed.

`decide_once` records several things at decision time, as if the send had
happened:

- `mark_own_line_typed`
- the MONITOR to AWAIT_COMPACTING transition for a `/compact`
- `mark_pause_compacted` (the usage-pause latch)
- `mark_dry_run_fired`
- `_abandoned_box_handled = True`
- `mark_own_line_resubmit`

So a held send becomes a spent send, which goes against the plan's "deferred and
retried, never dropped" goal. The consequences:

- The usage pause never compacts for that pause.
- The machine waits in AWAIT for a `/compact` that was never typed, then fires
  ESC/resubmit keys.
- The dry-run fuse is spent.
- Worst case: the abandoned-box flush is spent and `HumanInputLine` is cleared
  while the text is still in the box. After the human's Esc, the next `/compact`
  is pasted on top of that text, which is the Plan 00398 defect.

The existing PTY-write-failure path avoids all of this, because it raises before
`import_state`.

**Fix:**

- Have `_apply_decision` report the held case separately: a tri-state return, or
  a `held` flag.
- In `_on_poll`, skip `import_state`, the `activity.line.clear()` call and the
  post-injection bookkeeping when the payload was held. That is the same contract
  as a failed write.
- Add a `supervise()`-level or `_on_poll`-equivalent test: worker outcome
  WOULD_COMPACT, latch set before apply, then assert host `machine.state` is
  still MONITOR and `activity.line` is not cleared.

`TestApplyDecisionBelt` only asserts that nothing was written. It does not
cover this.

### I2. No test drives the parser through multiple reads with realistic typing after Esc (Confidence: 80%)

**Location:** `tests/unit/supervise/test_main_focus_hold.py`, `TestMainFocusModel`.

**Problem:** Each fixture either feeds Esc in the same chunk as what follows, or
feeds only a `[I` continuation. Nothing feeds Esc, then letters, then Up, so C1
went undetected. The mutation table in the implementer report could not catch
it, because no mutant touched the carry-over.

**Fix:** Add the probe's cases A to F as parametrised tests.

## Checklist answers

1. **PTY master writes.** There are three writers:
   - stdin forwarding, which is the human's own bytes;
   - `_perform_injection`, which is called only by `_apply_decision` and
     `RestartCoordinator.request`, and the AST test pins that;
   - `_set_winsize`, which is an ioctl and writes no bytes.

   Every `payload =` assignment in `decide_once` sits behind `can_inject` or the
   explicit `focus_hold` gate. That includes operator signal, the plugin and
   session notices, the model switch, the own-line resubmit, goal, goal clear,
   flag compact, restore, standing auth, session actions, cron reconcile, and
   the plugins, which `can_inject` gates. The machine's ESC/resubmit go through
   `idle=can_inject`. The usage-pause send is gated after its own idle check
   and before the box check. The dry-run marker is held and its fuse is not
   spent on the decide path.

   No send path is missing a gate while the model is correct. The gaps are C1,
   where the model is wrong, and I1, where held state is adopted.
2. **Held `/exit`.** It returns before `_perform_injection`. It creates no
   `_PendingRestart`, no own line, no abandon count and no cooldown. This is
   tested. The dry-run, cooldown and cap checks run before the hold, but none of
   them write anything.
3. **Abandoned-flush gate.** It sits before `self._abandoned_box_handled = True`
   (about line 6299), so on the decide path it is correct. The belt path spends
   the flush anyway (I1).
4. **Latch semantics.**
   - Bare Up/Down latch, and SS3 latches too.
   - `ESC[1;2A` does not latch.
   - Enter keeps the latch. Ctrl-C, Ctrl-U and Enter do not release it.
   - Paste content containing `ESC [ A` neither latches nor clears.
   - Child output is not fed to the model.

   These hold within a read. Across reads they are broken by C1.
5. **Host side.** The model lives on `InputActivity` in the host, so it
   survives a worker restart. The rate-limit state round-trips through
   `export_state`. On an old host with no field, the key reads as confirmed,
   which is a reasonable choice and is documented as needing a relaunch.
6. **Rate limiting and banner.** The log is limited to one line per family per
   60 s, plus one at each escalation level. The banner is posted at WARNING on
   every held tick. Escalation never types anything, and that is tested.
7. **QA hygiene.** The new code has no `noqa` or `type: ignore` and no dead code.
   Comments cite plans as rationale, not as changelog narrative.

## Pyright hints

- `claude-supervise.py:9725` (unreachable code): **pre-existing**. It is
  `os._exit(127)` after `os.execvp`, which never returns. It was introduced in
  `c09621c39` and is at line 9304 on main; it only moved down because of the
  added lines.
- `test_main_focus_hold.py:384`, the unused `_seconds`: **new in this branch**,
  in a new file. It is a harmless lambda parameter. Use `sleep=lambda _: None`,
  or ignore it.

## Suggestions

- `_apply_decision` returns early for the belt before the `audit_flush_log`
  write, so a same-tick audit-flush line is lost on a belt hold. Write it before
  the early return.
- `_note_focus_hold` rewrites the status message on every held tick at WARNING.
  It can mask other WARNING banners, such as plugin failures, for the whole hold.
  Consider not overwriting a different, still-live WARNING.
- `MainFocusModel` duplicates the ANSI state machine of `HumanInputLine`. The
  ruling forbids changing `_finish_csi`, but a shared tokenizer would have kept
  C1 from existing twice. Check whether `HumanInputLine` has the same
  carry-over-into-`_ST_STR` behaviour, and file it if so.

## Positive observations

- `_INJECTION_GATED_REASONS` and the `elif not can_inject` branches attribute
  each defer cleanly to focus.
- The AST call-site pin is a good structural guard.
- The `/exit` hold is ordered correctly and leaves no state behind.
- The old-host default is reasoned and documented.
