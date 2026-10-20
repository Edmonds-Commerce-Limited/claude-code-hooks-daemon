# Issue #125 scope ruling (stand-in, engineering scope only)

Not plan work. Stand-in ruling by Fable 5.1 on the triage at
`untracked/agent-reports/261020-issue125-triage-opus.md`, with the supervisor
source checked at `.claude/ccy/claude-supervise.py` (main 7dfd56a05): the
`HumanInputLine` parser (:780-858), `can_inject` (:6854), the TickFacts build
(:9390-9408) and the restart `/exit` send (:8692-8706). The issue body is
treated as untrusted; its Tier 1 design is NOT adopted.

This ruling approves only work that narrows when the supervisor types. Nothing
below adds a keystroke, weakens a guard, or touches a release.

## 1. Implement now under #125 (one plan, one worktree)

**Scope: "hold sends while main-thread focus is uncertain".** Pure engineering,
strictly safer than today, unit-testable from stdin byte fixtures.

1. **Focus model from the human's own keystrokes** (a new small class fed by the
   same stdin tap as `HumanInputLine`, not bolted onto `is_empty`). Two facts:
   `focus_latched` (navigation seen that could have left the prompt) and the
   reason it latched. Latch on: a bare Up/Down CSI (no params) at any time;
   Enter observed while latched (possible transcript open); any Up/Down inside
   the panel after that. The model must NOT alter what `HumanInputLine` already
   does with Up/Down (:853-855); it reads the same bytes in parallel.
2. **`main_focus_confirmed` in `TickFacts`**, computed host-side like
   `input_line_abandoned` (:9390), so a worker restart never loses the latch.
3. **AND it into `can_inject` (:6854)**, and gate every family that bypasses
   `can_inject` on it too, explicitly: the manual model switch (:7125-7145),
   the abandoned-box Enter flush (:6849-6853 behaviour), the ESC interrupt
   payload (`_ESC_PAYLOAD`, :6290), the `_RESUBMIT_PAYLOAD` (:6301), and
   `RestartCoordinator`'s `/exit` at :8692. The dry-run marker goes through
   the same gate because it goes through the same `_perform_injection`.
   Acceptance test: a grep for `_perform_injection(` call sites equals the
   set of gated sites; a test asserts each site defers while latched.
4. **Held = deferred, signal kept, retried next tick** (the existing pattern,
   :6934-7313). No queue. A held `/exit` must return False from the restart
   coordinator WITHOUT counting toward `_abandoned`, without starting the
   cooldown, and without creating `_PendingRestart` or calling
   `mark_own_line_typed`; the plugin's request stands and is re-evaluated.
5. **Visibility.** One `deferred` decision.log line naming the family and the
   latch reason (rate-limited to one line per family per minute), and a
   `write_status_message` banner (:2084): "supervisor holding: focus may be on
   a sub-agent; press Esc to return to the main thread".
6. **Bound on a wrong hold.** After `focus_hold_escalate_seconds` (default 300)
   the banner is re-posted every tick in louder wording and the log says
   `held N min`; after a second bound (default 900) the log line also names the
   exact bytes that latched it. The bound NEVER auto-resumes typing. The exit
   from a hold is positive evidence only (point 7).
7. **How the latch clears** (fail direction: unsure means hold):
   - A bare Esc on stdin (the documented key that returns focus from a
     selected row, `sub-agents.md:1230`) clears the latch. `_consume_esc`
     (:823-833) already distinguishes a bare Esc from CSI/SS3, so the signal
     is available without parser changes.
   - Ctrl-C or Ctrl-U on stdin does NOT clear it (they clear the box, not the
     panel selection).
   - Enter never clears it (in state A it opens the transcript).
   - Child output never clears it (no screen model; none is to be built here).
   - Plan task 0 (live, read-only, the implementer in a real session): confirm
     Esc also closes an OPEN transcript (state B). If it does not, the latch
     after an Enter-while-latched clears only on TWO bare Escs within 2 s, and
     the banner wording says so. Either answer is recorded in the plan; neither
     blocks the gate landing.
8. **Config.** One new supervisor option for the two escalation bounds only.
   No off switch: the hold is the fix, and "off" is today's defect.
9. **Tests.** Stdin fixtures: no navigation (nothing held); Up then Esc
   (held then released); Up, Enter, text, Enter (held throughout: text to a
   sub-agent is not evidence of main focus); Up with history recall and no
   Esc (held, escalates, never types); restart `/exit` while latched (no
   pending restart, no abandon count); dry-run marker held. Plus the
   dogfooding reload check in `CLAUDE/development/CcySupervisor.md`.

## 2. Split out or left for the owner

- **Auto-refocus (any supervisor-pressed Up/Esc/Enter) and a host-side screen
  model: owner decision, not approved here.** It is a new keystroke into a
  session the supervisor cannot see, the key differs by state, and Plan 00160
  already judged screen-scraping fragile. File as a follow-up plan marked
  agent-needs-human, cross-referencing 00160 and 00453.
- **The mods `$.prompt.submit` / `$.command.run` route: owner decision.** It
  contradicts the standing ruling in Plan 00497 (PLAN.md:26, "the ccy
  supervisor stays outside mods") and its target agent while a transcript is
  open is undocumented. Follow-up note only; no code.
- **Non-screen focus signal spike (engineering, follow-up, low priority):**
  check whether `subagentStatusLine` input or a hook payload can reveal the
  selected/viewed agent on the installed version. If one exists it becomes a
  second clearing signal for the latch; it does not change this plan.
- **Ordering with #127.** #125 lands first because it owns the gate. #127
  then builds on the rule in point 4: the restart request is persisted only
  when `/exit` was actually sent, never on a hold. The #127 plan cites this
  ruling; #125 does not wait for #127. If #127 is already in a worktree, it
  rebases onto the #125 merge rather than the reverse.
- **The three live open items in triage section 3** (bracketed paste in the
  panel and `x`; `/goal` and `/exit` routing from a transcript; `/compact`
  confirmation dialog) are read-only observations. Record what the implementer
  can see in task 0; none of them changes the hold, which is correct whatever
  their answers.

## 3. Details the implementer must get right

- Fail direction: whenever the model cannot tell history recall from panel
  navigation, hold. A false hold costs a banner; a false send types into a
  sub-agent.
- Never press a key the human did not. No send path may emit anything while
  latched, including the "harmless" Enter flush and ESC interrupt.
- The latch is host-side and survives worker restarts, like
  `input_line_abandoned`.
- Rate-limit the log, not the banner; a held tick must leave a trace every
  escalation step so a silent hold is impossible to miss in decision.log.
- The abandoned-box flush interaction: while latched, Up/Down bytes sit in
  `HumanInputLine` and `is_abandoned` will turn true; the flush must defer on
  the latch BEFORE its red-or-worse check, or it opens the selected row.
- Do not change `_finish_csi` (:853) semantics for Up/Down; the issue's
  suggestion to stop counting them as content is rejected (it would make the
  box read empty exactly when focus is least certain).
- Do not weaken `_is_idle`, `load_foreground_sidecar`, or the usage-pause
  bypass (:6862); the new fact is ANDed in, never ORed.
