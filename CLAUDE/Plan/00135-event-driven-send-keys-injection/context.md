# Context — Plan 00135: Event-Driven `send-keys` Injection

## The user's framing (verbatim)

> "we need to think about compaction and also other things that might need to be
> injected — slash commands are the primary usecase i think"

> "then we need to plan this properly"

> "once plan is done, we need hostile multilense review. This feature could be
> the serious game changer that really makes this library super useful, but done
> badly it could have the opposite effect"

These three statements set the scope and the temperament of this plan:

1. **Slash-command injection is the PRIMARY use case.** Not Stop auto-continue
   (already owned), not generic prompt spam. The flagship is *injecting a
   whitelisted slash command* — above all `/compact` at a custom context
   threshold — into the live, watchable Claude Code session.
2. **Plan it properly** — full TDD-phased plan, safety-first, incremental.
3. **Hostile multi-lens review comes next.** The plan is explicitly written to
   be attacked. It is a potential game-changer that, done badly, damages the
   library's reputation. The default posture is therefore *paranoid*: opt-in,
   allowlisted, loop-guarded, idle-gated, capped, and observable.

## The core insight (from `research-note.md`)

Claude Code hooks run as **child processes of the Claude Code process**. When
Claude Code is launched inside a tmux pane, those children **inherit `$TMUX` and
`$TMUX_PANE`**. So a hook script can type back into its own pane with zero
configuration:

```bash
tmux send-keys -t "$TMUX_PANE" -l "/compact"
sleep 0.3
tmux send-keys -t "$TMUX_PANE" Enter
```

Combined with Claude Code's rich hook-event set, this means **any event Claude
Code can hook can be turned into an automatic slash command / prompt injected
into the live session — while the human watches it happen in the terminal.**
This is the property headless/`-p` mode does not give you: you keep the visible,
interactive TUI *and* get programmatic control.

The flagship special case — **auto-`/compact` at a custom (lower) context
threshold** — has one wrinkle: the context percentage is **not** present in any
hook event payload. It is delivered *only* to the statusLine command. The
research note proposed a separate `~/.claude/statusline.sh` to emit a sidecar.

## The key architectural fact that reshapes the design

**The daemon already renders the status line, so it already receives the
statusLine JSON payload.** Verified directly in this repo:

- `src/.../handlers/status_line/model_context.py` lines 144–146 read
  `hook_input.get("context_window", {})` and `ctx_data.get("used_percentage")`
  straight off the Status event input. The same payload carries
  `context_window_size`, `session_id`, `model`, etc.

Consequence: we do **not** need the research note's bolt-on
`~/.claude/statusline.sh`. A new daemon **status-line handler** can write the
`pct` + `idle/busy` + `timestamp` sidecar from inside the existing pipeline — one
source of truth, no extra user-managed script, no risk of the user's statusLine
config drifting from the daemon's expectations. This is a strict improvement
over §4/§5 of the note and is the spine of the recommended architecture.

## Why it matters

If this works and is safe, it turns the daemon from a *guardrail* library into a
*self-driving-session* platform: custom-threshold compaction, automatic
re-orientation after compaction, `/fix` on a failing test run, session
bootstrap prompts — all observable in a tmux pane, all opt-in. That is a
genuinely differentiating capability for the library.

## Why it is dangerous (the make-or-break)

This pattern wires **Claude to itself**. The failure modes are severe and several
are silent:

- **Feedback loops.** An injected prompt fires a hook that re-injects, forever —
  burning tokens and money with no human in the loop.
- **Mid-turn injection.** Typing while a response streams can submit a half-typed
  line via a stray `Enter`.
- **Command injection.** `send-keys` types *anything*. Interpolating untrusted
  event data (a file path, a commit message, tool output) into a send-keys
  payload is a code-execution vector against the user's own shell/session.
- **Wrong-pane targeting.** A hard-coded `session:window` can hit the wrong pane
  after a layout change and type a slash command into something unrelated.
- **Runaway cost / rate-limits.** Self-driving turns spend tokens unattended.
- **Collision with the existing Stop auto-continue** (`auto_continue_stop.py`),
  which already owns the Stop-continuation contract with five branches.
- **TIOCSTI temptation.** Kernel keystroke injection is a privilege-escalation
  vector, deprecated/disabled on modern Linux. It is banned outright (note §7).

Because the downside is reputational as well as technical, the plan treats every
guardrail as a **first-class, blocking requirement** — not an afterthought — and
ships the smallest safe slice first.
