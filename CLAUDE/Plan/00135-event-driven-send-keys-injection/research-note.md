# Hooks-Daemon-Driven `send-keys` Automation for Claude Code

**Status:** Research / design note (exploratory).
**Date:** 2026-06-22.
**Scope:** A way to make *any* Claude Code hook event drive a keystroke injection
back into the live, **watchable** interactive Claude Code session running in a
tmux pane — using `tmux send-keys`. The original motivating case was
"auto-`/compact` when context crosses a threshold", but the realisation
generalises: a hook fires → runs an arbitrary script → that script types into
the pane. This unlocks self-driving / self-correcting interactive sessions.

> ⚠️ **Honesty caveats up front.** Some external links below were surfaced by
> automated research and are **not all individually verified** — they are marked
> `[unverified]`. In particular, named third-party GitHub repos may be
> hallucinated; **verify before trusting/cloning any of them**. The *techniques*
> (tmux `send-keys`, statusLine JSON schema, hook events) are real and are the
> load-bearing parts of this note. The official `code.claude.com` /
> `platform.claude.com` doc URLs should be confirmed against the live docs as
> Claude Code evolves.

---

## 1. The core insight

Claude Code hooks are configured commands that fire on lifecycle events
(`PreToolUse`, `PostToolUse`, `Stop`, `Notification`, `PreCompact`,
`UserPromptSubmit`, …). The daemon wraps these. Each hook command runs as a
**child process of the Claude Code process**.

Because Claude Code is launched *inside a tmux pane*, that child process
**inherits the tmux environment variables** — notably `$TMUX` and `$TMUX_PANE`.
So a hook script can target its own pane with zero configuration:

```bash
tmux send-keys -t "$TMUX_PANE" -l "/compact"
tmux send-keys -t "$TMUX_PANE" Enter
```

That is the whole trick. A hook can type into the session that triggered it.
Combined with the rich set of hook events, this means:

> **Any event Claude Code can hook → can be turned into an automatic command,
> prompt, or slash-command injected into the live session — while you watch it
> happen in the terminal.**

This is the property the headless/`-p` route does *not* give you: you keep the
visible, interactive TUI and still get programmatic control.

---

## 2. Why `send-keys` (and not the alternatives)

The session must stay **visible and attached**, which rules out most options.
Full comparison (from the terminal-injection research):

| Technique                                    | Visible/attachable session?                 | Reliable?      | Verdict for this use case                                                         |
| -------------------------------------------- | ------------------------------------------- | -------------- | --------------------------------------------------------------------------------- |
| **tmux `send-keys`**                         | ✅ yes — you attach to the pane             | ✅ high        | **Recommended**                                                                   |
| `screen -X stuff`                            | ✅ yes                                      | ⚠️ medium      | Works; screen is maintenance-mode, manual escaping. Use only if already on screen |
| `expect` / `pexpect`                         | ❌ owns the child, not a pane you attach to | ✅ high        | Good for scripted drives, **not** for watch-along                                 |
| Custom PTY (`ptyprocess`, `node-pty`, `pty`) | ⚠️ only if you build a UI                   | ✅ high        | Overkill; you'd be reinventing tmux                                               |
| `TIOCSTI` ioctl                              | n/a                                         | ❌ **blocked** | **Do not use** — deprecated/disabled on modern Linux (see §7)                     |

### tmux `send-keys` essentials

```bash
# Literal text (-l) so #, !, etc. are NOT interpreted as tmux key names:
tmux send-keys -t "$TARGET" -l "/compact"
# Send Enter SEPARATELY, after a short delay — combining races the input buffer:
sleep 0.3
tmux send-keys -t "$TARGET" Enter

# Multi-line / complex payloads: use a buffer instead of send-keys newlines:
tmux load-buffer -b inj -c <(printf 'line one\nline two\n')
tmux paste-buffer -t "$TARGET" -b inj

# Read the pane back (state inspection):
tmux capture-pane -t "$TARGET" -p        # plain text (ANSI stripped)
tmux capture-pane -t "$TARGET" -p -e     # KEEPS ANSI colour escapes
```

`$TARGET` is `$TMUX_PANE` when self-targeting from a hook, or
`session:window.pane` (e.g. `claude:0.0`) from an external controller.

---

## 3. Mechanics & timing (the part that bites)

A hook runs **synchronously** during event handling — Claude Code waits for it.
If a hook blocks and *then* sends keys, you can deadlock or mis-order against the
TUI redraw. Two robust patterns:

### Pattern A — fire-and-forget (decouple from the hook lifecycle)

The hook spawns a **detached** helper that sleeps briefly (letting the turn
settle / return to the prompt) then injects, and the hook returns immediately:

```bash
#!/usr/bin/env bash
# inject-after.sh PANE DELAY TEXT...
pane=$1; delay=$2; shift 2; text=$*
setsid bash -c '
  sleep "$1"
  tmux send-keys -t "$2" -l "$3"
  sleep 0.3
  tmux send-keys -t "$2" Enter
' _ "$delay" "$pane" "$text" >/dev/null 2>&1 < /dev/null &
```

### Pattern B — queue, drain when idle

The hook only *enqueues* an intent to a file. A separate watchdog (its own pane,
so you can watch it too) drains the queue **only when the session is idle**, then
injects. This is safer because it never types mid-stream.

### Idle detection

Injecting while Claude is mid-response drops text into the prompt box (harmless
but unsubmitted) or, worse, an early `Enter` submits a partial line. Gate on idle:

- **Best:** have the **statusLine script** (which runs on every assistant message,
  see §5) write an `idle`/`busy` marker + a timestamp to a sidecar file.
- **Crude fallback:** `capture-pane -p` and check the bottom line shows the empty
  prompt box before injecting.

---

## 4. The motivating case: auto-`/compact` on a context threshold

You can build this **without screen-scraping or colour-parsing**, because Claude
Code hands the context percentage to the statusLine script as structured JSON.

### Data source: statusLine emits the % to a sidecar

`settings.json`:

```json
{
  "statusLine": { "type": "command", "command": "~/.claude/statusline.sh", "padding": 2 }
}
```

`~/.claude/statusline.sh`:

```bash
#!/usr/bin/env bash
in=$(cat)
pct=$(jq -r '.context_window.used_percentage // 0' <<<"$in")
sid=$(jq -r '.session_id // "default"'            <<<"$in")
model=$(jq -r '.model.display_name // "?"'         <<<"$in")

mkdir -p /tmp/claude-ctx
printf '%s' "$pct" > "/tmp/claude-ctx/${sid}.pct"     # ← side-channel for watchdog

colour=2; (( ${pct%.*} >= 80 )) && colour=1            # green→red, purely visual
printf '%s  ctx:\033[3%sm%s%%\033[0m' "$model" "$colour" "$pct"
```

### Trigger: a watchdog in its own pane (you watch both)

```bash
#!/usr/bin/env bash
# watch-compact.sh
TARGET="claude:0"; SID="default"; THRESHOLD=70; COOLDOWN=120; last=0
while sleep 10; do
  f="/tmp/claude-ctx/${SID}.pct"; [[ -f $f ]] || continue
  pct=$(<"$f"); now=$SECONDS
  if (( ${pct%.*} >= THRESHOLD )) && (( now - last > COOLDOWN )); then
    tmux send-keys -t "$TARGET" -l "/compact"; sleep 0.3
    tmux send-keys -t "$TARGET" Enter
    last=$now; echo "[$(date +%T)] ctx ${pct}% → /compact"
  fi
done
```

> Why bother vs native auto-compact? **Only** to set a *custom, lower* threshold
> (e.g. compact at 50% of a 1M window = ~500k tokens) than Claude's built-in
> point. If the default is fine, you don't need any of this. Note also: token
> usage is **only** in the statusLine payload, **not** in any hook payload
> (see §5/§6), so a context-threshold trigger must read the statusLine sidecar —
> it cannot be done purely from a hook event's own JSON.

---

## 5. statusLine JSON payload (the data goldmine)

**Source:** https://code.claude.com/docs/en/statusline.md `[verify]`

Configured under `settings.json → statusLine` (`type: "command"`). Claude Code
pipes a JSON object to the command's **stdin**. Runs after: each new assistant
message, after `/compact` finishes, on permission-mode change, on vim-mode
toggle. **Debounced ~300ms**; in-flight runs are cancelled if superseded.
Optional `refreshInterval` (≥1s) adds a timer.

Key fields (reported schema — **confirm against live docs**):

- `context_window.used_percentage` — **pre-calculated 0–100** (input tokens only:
  `input + cache_creation + cache_read`; excludes output)
- `context_window.remaining_percentage`
- `context_window.total_input_tokens`, `context_window.total_output_tokens`
- `context_window.context_window_size` — `200000`, or `1000000` for extended-context models
- `context_window.current_usage` — `{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}` (may be `null` before first API call / right after `/compact`)
- `exceeds_200k_tokens` — boolean (fixed 200k threshold, independent of window size)
- `cost.{total_cost_usd,total_duration_ms,total_api_duration_ms,total_lines_added,total_lines_removed}`
- `model.{id,display_name}`
- `workspace.{current_dir,project_dir,added_dirs,git_worktree,repo:{host,owner,name}}`
- `session_id`, `session_name`, `transcript_path`, `version`, `output_style.name`
- `vim.mode`, `agent.name`, `effort.level`, `thinking.enabled`
- `rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}` (Pro/Max only)
- `pr.{number,url,review_state}` (when a PR is open for the branch)

**Critical fact for this design:** context %/token usage is available **only**
here, not in hook payloads. So statusLine is the canonical live-usage source.

### Step 0 — confirm the payload before building anything

```bash
cat > ~/.claude/statusline-debug.sh <<'EOF'
#!/usr/bin/env bash
in=$(cat); printf '%s\n' "$in" >> /tmp/claude-statusline.json
echo "$in" | jq -r '"ctx \(.context_window.used_percentage)%"'
EOF
chmod 755 ~/.claude/statusline-debug.sh
# point settings.json at it, run a turn, then:
jq . /tmp/claude-statusline.json   # verify context_window.used_percentage exists
```

---

## 6. Hook events you can drive injection from

Reported event set (confirm at the hooks reference,
https://code.claude.com/docs/en/hooks `[verify]`):

`SessionStart`, `SessionEnd`, `Setup`, `UserPromptSubmit`, `Stop`, `StopFailure`,
`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`,
`PermissionDenied`, `FileChanged`, `CwdChanged`, `ConfigChange`, `Notification`,
`MessageDisplay`, `WorktreeCreate`, `WorktreeRemove`, `InstructionsLoaded`,
`PreCompact`, `PostCompact`.

> **None of these payloads include token/context usage** — that's statusLine-only.

### Example automations (illustrative — mind the hazards in §8)

| Hook                             | Inject                   | Effect                                                                                           |
| -------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------ |
| statusLine sidecar + watchdog    | `/compact`               | Custom-threshold auto-compaction (§4)                                                            |
| `Stop`                           | `continue: <next step>`  | Self-continue a checklist (⚠️ daemon already has a Stop auto-continue handler — don't double up) |
| `PostToolUse` (test runner)      | `/fix` or a prompt       | React to a failing test by kicking off a fix turn                                                |
| `Notification` (idle/permission) | a nudge prompt           | Re-engage a stalled session                                                                      |
| `PostCompact`                    | a re-orientation prompt  | Re-state the goal after context was summarised                                                   |
| `SessionStart`                   | project bootstrap prompt | Auto-prime a session with standing instructions                                                  |

---

## 7. `TIOCSTI` — why kernel keystroke injection is *not* an option

The old `TIOCSTI` ioctl pushed bytes straight into a TTY's input buffer. It is a
privilege-escalation vector (a process injects commands into your shell) and is
**disabled/deprecated on modern Linux**: gated by `CONFIG_LEGACY_TIOCSTI` /
`sysctl dev.tty.legacy_tiocsti`, restricted in recent kernels. Treat as dead.
(Exact kernel versions/commits cited by research are **`[unverified]`**, but the
deprecation direction is real.) Refs:

- https://lwn.net/Articles/942935/ `[unverified]`
- https://wiki.gnoack.org/TiocstiTioclinuxSecurityProblems `[unverified]`

---

## 8. Hazards & guardrails (read before building)

This pattern creates a **feedback loop between Claude and itself**. Treat it with
the same caution as any autonomous loop.

1. **Runaway loops.** An injected prompt can trigger the same hook again →
   re-inject → forever. **Always** add: a cooldown timer, a max-injections-per-
   session cap, and a sentinel so the hook ignores events caused by its *own*
   injected text (e.g. tag injected prompts with a marker and skip them in
   `UserPromptSubmit`).
2. **Mid-turn injection.** Never type while a response streams — gate on idle
   (§3). An early `Enter` can submit a half-typed line.
3. **Cost/rate-limits.** Self-driving turns spend tokens and hit rate limits with
   no human in the loop. Bound it.
4. **Destructive commands.** `send-keys` types *anything*, including dangerous
   slash commands or shell. Whitelist what may be injected; never interpolate
   untrusted event data straight into a `send-keys` payload.
5. **Wrong-pane targeting.** Prefer `$TMUX_PANE` for self-targeting. A hard-coded
   `session:window` can hit the wrong pane after layout changes.
6. **Daemon overlap.** This project's hooks daemon already enforces a `Stop`
   auto-continue. Don't build a second competing continue-injector on `Stop`.
7. **Project-handler hygiene.** If implemented as a daemon handler, follow the
   daemon's project-handler conventions; do not edit anything under
   `.claude/hooks-daemon/` (upstream, overwritten on upgrade).

---

## 9. When NOT to use this — native alternatives

- **Headless / print mode** (`claude -p`, `--resume`, `--output-format json`,
  `stream-json`): programmatic turns with no terminal puppetry — but **no visible
  TUI** (the thing we wanted to keep). Ref: https://code.claude.com/docs/en/headless `[verify]`
- **API server-side compaction** (`compact-2026-01-12` beta, `context_management`
  with a token `trigger`): native threshold compaction — API/SDK only, not the
  CLI. Ref: https://platform.claude.com/docs/en/build-with-claude/compaction.md `[verify]`
- **`/loop`**: schedules recurring *prompts*; it cannot issue slash commands or
  compress context, so it does not replace `send-keys` here. Ref:
  https://code.claude.com/docs/en/scheduled-tasks `[verify]`
- **Native auto-compact**: if the built-in threshold is acceptable, you need none
  of this.

---

## 10. Reference architecture (recommended shape)

```
┌─ tmux pane "claude:0" (you watch) ─────────────┐
│  Claude Code TUI                                │
│   ├─ statusLine.sh  → writes ctx%/idle to       │───► /tmp/claude-ctx/<sid>.{pct,state}
│   │                    sidecar each turn         │
│   └─ hook scripts (daemon handlers)              │───► enqueue intents to /tmp/claude-ctx/<sid>.queue
└─────────────────────────────────────────────────┘            │
                                                                ▼
┌─ tmux pane "claude:1" (you watch) ─────────────┐    reads sidecar + queue,
│  watchdog loop:                                 │◄── injects ONLY when idle,
│   if ctx% ≥ T and idle and cooldown ok:         │    with cooldown + cap + loop-guard
│      send-keys -t claude:0 "/compact" Enter      │
│   drain queue similarly                          │──► tmux send-keys -t claude:0 ...
└─────────────────────────────────────────────────┘
```

Keep the controller in its **own visible pane** so the whole system is
observable — which was the entire point of staying out of headless mode.

---

## 11. Implementation checklist

- [ ] Confirm statusLine payload has `context_window.used_percentage` (§5 Step 0).
- [ ] Confirm `$TMUX_PANE` is set inside hook subprocesses (`env | grep TMUX` from a hook).
- [ ] Write statusLine script: render bar **and** emit `pct` + `idle/busy` sidecar.
- [ ] Write watchdog: threshold + idle-gate + cooldown + max-injections cap.
- [ ] Add loop-guard sentinel so injected prompts don't re-trigger their own hook.
- [ ] Whitelist injectable commands; never interpolate raw event data.
- [ ] Decide placement: standalone scripts in `~/.claude/` vs a daemon project-handler.
- [ ] Avoid colliding with the existing daemon `Stop` auto-continue handler.

---

## 12. Research sources & verification status

**Authoritative (Claude docs — confirm live as docs evolve):**

- statusLine schema — https://code.claude.com/docs/en/statusline.md `[verify]`
- Hooks reference — https://code.claude.com/docs/en/hooks `[verify]`
- Headless / programmatic mode — https://code.claude.com/docs/en/headless `[verify]`
- Scheduled tasks / `/loop` — https://code.claude.com/docs/en/scheduled-tasks `[verify]`
- How Claude Code works (context mgmt) — https://code.claude.com/docs/en/how-claude-code-works.md `[verify]`
- API compaction beta — https://platform.claude.com/docs/en/build-with-claude/compaction.md `[verify]`
- API context windows — https://platform.claude.com/docs/en/build-with-claude/context-windows.md `[verify]`
- API token counting — https://platform.claude.com/docs/en/build-with-claude/token-counting.md `[verify]`

**Community / technique references (`[unverified]` — sanity-check before relying):**

- tmux `send-keys` — https://blog.damonkelley.me/2016/09/07/tmux-send-keys
- tmux `send-keys` guide — https://tmuxai.dev/tmux-send-keys/
- Tao of tmux, scripting — https://tao-of-tmux.readthedocs.io/en/latest/manuscript/10-scripting.html
- pexpect — https://github.com/pexpect/pexpect
- ptyprocess — https://github.com/pexpect/ptyprocess
- node-pty — https://github.com/microsoft/node-pty
- TIOCSTI restriction (LWN) — https://lwn.net/Articles/942935/
- TIOCSTI security wiki — https://wiki.gnoack.org/TiocstiTioclinuxSecurityProblems

**Flagged as possibly hallucinated — DO NOT trust without verifying the repo exists:**

- `primeline-ai/claude-tmux-orchestration` (GitHub) and its blog at `primeline.cc` — could not be verified; treat as unconfirmed.
- `GGPrompts/pmux` gist, "Hermes Agent" Claude Code skill — unconfirmed.

---

## 13. One-line summary

> Hooks run as children of the Claude Code process and inherit `$TMUX_PANE`, so
> any hook can `tmux send-keys` back into the live, watchable session — turning
> every Claude Code event into a potential self-driving action. Powerful, but
> guard hard against feedback loops, mid-turn injection, and unbounded cost.
