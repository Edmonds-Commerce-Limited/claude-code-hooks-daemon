# Issue #125 triage: supervisor injections land in a focused sub-agent

Not plan work (triage only). Read-only investigation against `main` at 7dfd56a05.
Everything in the issue was treated as untrusted data. Its proposed design was
checked as a hypothesis, not followed as a spec.

## 0. Where the shipped source lives

The issue cites `src/claude_code_hooks_daemon/install/ccy_supervisor.py:41`. That
file is only the deployer (`SUPERVISOR_SCRIPT_NAME = "claude-supervise.py"` at
:41). The supervisor itself has a single source: `.claude/ccy/claude-supervise.py`
(9,903 lines, last touched 2f56e3026). It is dogfooded in place and copied out by
`_copy_asset` (ccy_supervisor.py:148, :221). It is not under `src/`, and no other
copy exists in the tree. All citations below refer to that file unless noted.

## 1. Code claims checked against main

Every line number the issue gives matches main exactly.

| Claim                                                                                                                                 | Verdict  | Evidence                                                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `_perform_injection` writes a bracketed paste plus Enter straight to the PTY master and has no idea of focus                          | VERIFIED | :6558-6599. It writes paste-framed text (:6594), sleeps, sends `\r` (:6596) and optionally sends confirm-Enters (:6597-6599). `submit=False` writes raw bytes (:6588-6590). It has no focus or target parameter. |
| Called from `_apply_decision` (:7738, call at :7780) and from the restart path (:8692)                                                | VERIFIED | :7780-7785. :8692 types `_RESTART_EXIT_COMMAND = "/exit"` (:8558).                                                                                                                                               |
| Child output is never parsed: `_forward_io` only times it and copies it to stdout                                                     | VERIFIED | :9146-9157. `OutputActivity.record` (:1005-1008) stores only a byte count and a timestamp. A search for pyte, screen, capture-pane or tmux finds no screen model. The only tmux mention (:6489) is a comment.    |
| Typing guard: `_is_idle` (:6617), `HumanInputLine` (:684), `is_empty` (:894), `is_abandoned` (:898), fed into TickFacts at :9396-9408 | VERIFIED | `can_inject = facts.idle and facts.input_line_empty` (:6854). Some families gate on `input_line_empty` alone. The manual model switch does (:7125-7128, :7145).                                                  |
| `HumanInputLine._finish_csi` (:853) counts a bare Up/Down as box content                                                              | VERIFIED | :853-855 appends the CSI final byte to the buffer. A bare ESC (:832-833) does not clear it. Only Enter, Ctrl-U or Ctrl-C clears it (:792-803).                                                                   |
| `load_foreground_sidecar` (:2298) is about separate sessions, not threads inside one session                                          | VERIFIED | :2298-2335 compares per-`session_id` sidecars written by `context_sidecar.py` (fields: session_id, pct, red, model_id, ts and so on, but no agent id).                                                           |
| `write_status_message` (:2084) can act as a warning channel                                                                           | VERIFIED | :2084. This is the Plan 00173 transient banner.                                                                                                                                                                  |

### What the issue gets wrong or leaves out

These points come from the vendored upstream docs and change the impact the issue
claims. Behaviour depends on the Claude Code version. The installed version here
is 2.1.304.

- **Two different focus states exist, and the issue treats them as one.**

  - (A) A panel row is *selected*. The prompt has lost focus, the arrow keys move
    between rows, Enter opens the row, `x` stops the selected agent, and Esc
    returns focus to the prompt (`remote-docs/code.claude.com/docs/en/sub-agents.md:1223-1230`).
    In this state, Esc "deselects it instead of interrupting"
    (`interactive-mode.md:46`).
  - (B) A sub-agent's *transcript is open* (after Enter). The placeholder then
    reads "Message @name…" (`changelog.md:3546`).

- **In state (B), slash commands do NOT go to the sub-agent.** "Follow-up
  messages and skills go to that agent, and built-in commands go to your main
  conversation" (`sub-agents.md:1232`).

  - `/compact`, `/clear` and `/rewind` act on main after a confirmation dialog
    (`sub-agents.md:1234`, added in 2.1.286 per `changelog.md:1458`).
  - `/model` and `/fast` are refused with a notice (`sub-agents.md:1235`, since
    2.1.199 per `changelog.md:5246`).

  So the issue's claim that "a /compact typed into a sub-agent compacts the wrong
  context" is refuted for current versions. The real failure modes are:

  - `/compact` stalls on a confirmation dialog the supervisor does not expect.
    The trailing Enter, or a later Enter or ESC, then interacts with that dialog.
  - `/model` restore silently does nothing.
  - Plain-text payloads really do reach the sub-agent: `continue` (:6285),
    standing-auth, operator, session-actions, cron-reconcile, plugin and
    session notices, and every dry-run marker (dry-run text is plain text even
    for compact).
  - `/goal` is a built-in (`hooks.md:2758`), so it presumably goes to main. This
    is not confirmed for the transcript view.

- **State (A) is arguably the more dangerous one, and the issue does not mention
  it.** Supervisor bytes are interpreted as panel keys:

  - The `\r` submit or the abandoned-box Enter (`_RESUBMIT_PAYLOAD = "\r"`,
    :6301) would OPEN the selected sub-agent's transcript.
  - `_ESC_PAYLOAD` (:6290) deselects instead of interrupting.
  - How the panel treats a bracketed paste, including any `x` it contains, is
    not documented here.

  Derived from the code (not reproduced live): moving into the panel with
  Up/Down puts bytes in `HumanInputLine`'s buffer (:855). The box therefore reads
  non-empty, so most families defer. But `is_abandoned` later turns true and the
  abandoned-box flush presses Enter for a red-or-worse reading (:6849-6853), which
  would open the selected row. Conversely, after Enter opens a transcript the
  buffer is cleared (:803), so every gate passes and plain text flows into the
  sub-agent. That matches the reporter's observation.

## 2. Triage checks

**(a) Built and reverted?** No. `git log --grep` and `-S` for refocus, thread
list, panel and focus-related terms find nothing reverted. The nearest precedent
is 1e111cbff (Plan 00160 Phase 2). It guards `/compact` against the wrong
*Agent-View session* during a session switch, which is the other kind of
"thread". Plan 00158 Truth #5 (55850bd75) recorded that "Task-tool subagents
(shared session → agent-panel row only, no bar)".

**(b) Still true on main?** Yes. Nothing in `_perform_injection`, `_apply_decision`
or the TickFacts gates (:6854) knows about focus.

**(c) Cluster with #126 and #127.**

- #126 (wrapper migration keeps `python3`) is an installer/launcher defect in
  `install/ccy_supervisor.py` (:253-326). It does not interact with this issue.
- #127 (restart exit indistinguishable at SessionEnd) shares the actuator. Its
  restart path types `/exit` through the same `_perform_injection` (:8692).
  - Any hold gate added for #125 must also cover `RestartCoordinator`, not only
    `_apply_decision`. Otherwise `/exit` bypasses it. Whether `/exit` is a
    built-in that goes to main from a transcript view is undocumented here.
  - If #127 persists the restart request before typing `/exit`, a held `/exit`
    would leave a recorded request with no exit behind it. The two fixes need a
    defined ordering: record only when actually sent, or clear on hold.
  - Recommendation: separate plans, with a cross-reference.

**(d) Partially delivered?** Only the pieces next to it:

- the session-level foreground guard (Plan 00160 Phase 2, `load_foreground_sidecar`)
- the defer-and-retry pattern via `deferred_log` and `can_inject` (:6854,
  :6934-6941, :7042, :7093, :7145, :7250, :7313)
- the banner channel (:2084)

Nothing covers focus inside a session.

**(e) Plans already filed?** `find-plan focus` found none. `find-plan supervisor`
lists 31 plans. The relevant ones:

- 00160 (Dormant): foreground identity across sessions. Its own analysis calls
  PTY screen-scraping fragile (PLAN.md:163).
- 00453 (Not Started): modal overlay, which reads stdin rather than the screen.
- 00399 (Blocked): tab-completed slash commands. It has the same blind spot
  (the supervisor cannot see the screen).

None of them covers this issue. Also relevant: Plan 00497 (hooks-daemon mod, Not
Started) states "Not the supervisor. The ccy supervisor stays outside mods"
(00497 PLAN.md:26).

**(f) Is focus exposed anywhere other than the screen?** Not in any documented
channel the supervisor can read today.

- **Status line JSON input:** no focus, selected or viewed field
  (`statusline.md:191-230`). `agent.name` means only `--agent` (:222). The main
  bar is per *session*. Sub-agents get no bar (Plan 00158 Truth #5), so the
  context sidecar cannot carry sub-agent focus.
- **`subagentStatusLine`** (`statusline.md:1135-1173`) receives every visible
  row, but its task fields have no selected or viewed flag. The daemon does not
  configure it (no hits in src or settings).
- **Hook payloads:** `agent_id` and `agent_type` say which agent a hook fired IN
  (`hooks.md:770-775`), not which one the human is viewing. They could at best
  detect a misdelivery after the fact (for example, a prompt event carrying an
  `agent_id`). That routing is unverified.
- **State files:** none documented. The supervisor reads only the
  context-sidecar, signal and goal files in `untracked/`. No sidecar carries
  focus.
- **Possible upstream route (out of scope today):** the mods API offers
  `$.prompt.submit` and `$.command.run`, which inject without keystrokes
  (`claude-code.d.ts.md:2517-2529`, :2645-2656). It also offers `$.prompt.read()`
  (:2540), which reads the prompt box. That is a non-PTY actuator, but nothing
  documents which agent it targets while a transcript is open. It also conflicts
  with the owner's ruling in 00497:26.
- **Which key returns focus to main:** for state (A) the docs say Esc
  (`sub-agents.md:1230`), not Up. For state (B), "Enter on main row" is implied
  by `changelog.md:2107`, but the default key path is not documented in the
  vendored tree (`keybindings.md` is not vendored). This supports the reporter's
  worry that Up recalls history.

## 3. Recommendation

**Classification: actionable defect, but the fix scope needs a human decision.**

- The actionable part is the conservative HOLD, which is pure engineering.
- Auto-refocus (Tier 1) needs an owner decision, because it means the supervisor
  presses navigation keys in a session it cannot see. It also has no upstream
  signal and would rest on screen-scraping that is version-fragile.

**Smallest safe fix:**

1. **Stop poisoning the model.** Teach `HumanInputLine` and the stdin tap to
   track panel and transcript navigation from the human's own keystrokes:
   Up/Down into the panel, Enter on a row, Esc back. The result is a
   `focus_uncertain` fact, latched whenever stdin shows navigation that could
   have left the prompt, and cleared only by evidence of a return to the main
   prompt. This is pure engineering, unit-testable, and adds no sends.
   - Caveat: it cannot tell a history-recall Up from a move into the panel
     without screen state. When uncertain it must fail toward HOLD.
2. **Add a HOLD gate.** Add `main_focus_confirmed` to TickFacts and AND it into
   `can_inject` (:6854). Every family that bypasses `can_inject` must gate on it
   too: model switch (:7145), abandoned-box flush, ESC, and the restart `/exit`
   (:8692). A held injection is already "deferred, signal kept, retried next
   tick" under the existing pattern, so no new queue is needed (contrary to
   Tier 2's "queue and flush" framing). The fix adds a deferred log line and a
   `write_status_message` banner ("supervisor holding: return to the main
   thread").
   - Safety: this narrows when the supervisor types and never adds keystrokes,
     so it is strictly safer than today.
   - Residual risk: a false HOLD starves compaction. This needs a bounded
     escalation, such as a louder banner, but never typing.
3. **Do not build auto-refocus** (pressing Up, Esc or other keys) without an
   explicit owner ruling. It is the only part that touches safety in the "types
   into sessions" sense:
   - It requires a host-side screen model of child output with SGR parsing.
     None exists, and Plan 00160 already judged this fragile.
   - The key differs by state (Esc for a selected row, unknown for an open
     transcript).
   - A wrong key can stop an agent (`x`), open a transcript (Enter) or recall
     history (Up).

**Safety-touching versus pure engineering:**

- Safety-touching: any new keystroke (refocus), changes to the abandoned-box
  Enter or ESC families, and the restart `/exit` ordering with #127.
- Pure engineering: the stdin focus model, the TickFacts field, the HOLD gate,
  the banner, the decision.log line, and the test fixtures for stdin sequences.

**Open items to verify live before planning:**

- Does a bracketed paste reach the panel in state (A), and can it trigger `x`?
- Is `/goal` or `/exit` routed to main from a transcript view?
- Does `/compact` from a transcript view leave a dialog that the supervisor's
  later Enter or ESC would answer?

## Side effects of this triage

Two reference copies were written to `untracked/scratch/` (untracked) so the
#126 and #127 bodies could be read: `issue-126-triage-ref.json` and
`issue-127-triage-ref.json`. No tracked file was changed, and no process was
touched.
