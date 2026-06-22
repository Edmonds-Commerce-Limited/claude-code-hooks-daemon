# Plan 00135 — De-Risking Spikes (run BEFORE any build)

**Why this file exists:** two hostile reviews + two brainstorms converged on the
fact that the whole architecture decision (ARCH-A launcher+dedicated-daemon vs
ARCH-B PTY supervisor) hinges on **one unverified tmux capability**. tmux is not
installed in the dev container, so these MUST run on a real host with tmux and a
live Claude Code session. Run them in order; **S-KEYTABLE decides everything
else.** Paste results back into this file under each spike's "Result".

> Decision rule: if **S-KEYTABLE** yields no observe-only per-key signal **and**
> **S-SIG** can't produce a fail-closed idle template, **abandon ARCH-A for
> ARCH-B** (PTY supervisor) — which needs no dedicated daemon, no socket-aware
> enforcement, no sidecar (SB-1/SB-9 evaporate). Do not build any ARCH-A-specific
> surface until S-KEYTABLE resolves.

---

## S-KEYTABLE — does tmux give an OBSERVE-ONLY per-keystroke signal? (run FIRST)

**Question:** can a hook/binding record "the user pressed a key just now" WITHOUT
swallowing the key from the application (Claude)?

**Prior (to disprove):** tmux key-tables are in the delivery path — a binding
consumes the key unless it re-sends it; tmux event hooks have no per-key observer.
If so, there is no clean observe-only signal.

```bash
# 1. Is there ANY per-key hook? (look for a keypress/after-send-keys style hook)
tmux show-hooks -g 2>/dev/null
man tmux | grep -nA2 -i 'hook' | grep -i 'key\|press' || echo "no per-key hook in hooks list"

# 2. Try an intercept-and-forward in the root table on a PRIVATE server.
#    The ONLY safe form is: every key both (a) stamps a file AND (b) reaches Claude.
tmux -L spike kill-server 2>/dev/null
tmux -L spike new-session -d -s s -x 200 -y 50
# bind a representative key in the root table to stamp+forward:
tmux -L spike bind-key -T root a 'run-shell "date +%s%N >> /tmp/spike_keys"' \; send-keys -l a
tmux -L spike send-keys -t s -l ""   # focus
# Now ATTACH in another terminal: tmux -L spike attach -t s
#   type "aaa banana" into the pane, watch /tmp/spike_keys grow, and check the
#   pane actually received the letters (cat the captured pane).
tmux -L spike capture-pane -t s -p
# 3. CRITICAL CHECKS:
#    - Did /tmp/spike_keys get a stamp per 'a'?  (signal works)
#    - Did the pane still receive every 'a' and the un-bound keys?  (no key eaten)
#    - Does binding EVERY key (root table catch-all) require N bindings, and does
#      any get dropped/reordered under fast typing?  (reliability)
tmux -L spike kill-server
```

**Verdict criteria:**

- GREEN (ARCH-A viable): a root-table form stamps per-key AND forwards every key
  losslessly under fast typing, with no perceptible latency.
- RED (-> ARCH-B): keys are eaten/dropped/reordered, or only a subset of keys can
  be bound, or it needs the catch-all that interferes with Claude's own keybindings.

**Result:** _(paste host findings here)_

---

## S-PTY — ARCH-B fidelity: does a thin PTY proxy mangle Claude Code's TUI? (run if S-KEYTABLE is RED, or to compare)

**Question:** can a ~100-line PTY supervisor sit between the terminal and Claude,
see every input byte (→ perfect "is the user typing"), inject on the master, and
NOT corrupt Claude's TUI (raw mode, bracketed paste, SIGWINCH, cursor DSR, colour)?

```bash
# Minimal supervisor: pty.spawn copies both directions; we just observe input.
cat > /tmp/spike_pty.py <<'PY'
import os, pty, sys, time
log = open("/tmp/spike_pty_input.log", "ab", buffering=0)
def read_from_master(fd):      # output: Claude -> screen (passthrough)
    return os.read(fd, 65536)
def read_from_stdin(fd):       # input: human -> Claude (observe + passthrough)
    data = os.read(fd, 65536)
    log.write(b"%f %r\n" % (time.time(), data))   # we SEE every keystroke
    return data
pty.spawn(["claude"], read_from_master, read_from_stdin)
PY
python3 /tmp/spike_pty.py
# Drive a full Claude session THROUGH this: type a prompt, accept a permission
# dialog, paste a multi-line block (bracketed paste), resize the terminal
# (SIGWINCH), run something that queries cursor position, use a colour-heavy TUI.
```

**Verdict criteria:**

- GREEN (ARCH-B viable & PREFERRED): the session is visually indistinguishable
  from running `claude` directly (paste, resize, colour, dialogs all correct), and
  `/tmp/spike_pty_input.log` shows every keystroke with timestamps.
- AMBER: works but resize/paste/cursor needs explicit handling (pty.spawn doesn't
  forward SIGWINCH; may need a custom select() loop + TIOCSWINSZ) — still viable,
  slightly more than 100 lines.
- RED: TUI corrupts → ARCH-B is out; fall back to ARCH-A heuristic-only or shelve.

**Result:** _(paste host findings here)_

---

## S-SIG — can capture-pane yield a POSITIVE, fail-closed idle template? (ARCH-A corroboration / fallback)

**Question:** does Claude Code's bottom region render distinctly enough per state
to positively match "idle-ready" and fail closed on everything else?

```bash
# Capture the bottom ~12 lines (with colour) in each state; label and save.
cap(){ tmux capture-pane -t "$1" -p -e -S -12; }
# Run a real Claude session in pane $P and capture during each state:
#   idle (empty box), after typing 3 words (box has text), mid-response
#   (esc-to-interrupt/spinner), permission dialog open, vim insert (if used),
#   /compact in progress, an error/notice.
# Save each: cap $P > /tmp/sig_idle.txt ; cap $P > /tmp/sig_typed.txt ; ...
# Then diff them for a STABLE anchor that ONLY the idle state has.
```

**Verdict criteria:**

- GREEN: a regex/anchor positively identifies idle-ready and is absent from ALL
  other states → fail-closed template viable (store as config).
- RED: idle vs streaming vs dialog share the anchor (can't positively distinguish)
  → screen-template can't be the safety gate; rely on S-KEYTABLE or ARCH-B.

**Result:** _(paste host findings here)_

---

## S-ENF — (ARCH-A only) does the dedicated daemon SURVIVE a shared-daemon restart?

Only relevant if S-KEYTABLE is GREEN and we commit to ARCH-A's dedicated daemon.
This one is partly analysable from the daemon code now (enforcement.py /
process_verification.py) but needs a real container run to confirm:

```bash
# In a container, with enforce_single_daemon auto-enabled:
# 1. Start a dedicated daemon (distinct CLAUDE_HOOKS_SOCKET_PATH) for the project.
# 2. Start/restart the NORMAL shared daemon for the SAME project root.
# 3. Assert the dedicated daemon is STILL RUNNING (not reaped). Then restart the
#    dedicated one and assert the shared one survives.
```

**Verdict criteria:** GREEN only if both survive the other's restart. Current code
(root-only matching) is expected RED → confirms the socket-aware enforcement change
is required before ARCH-A coexistence works.

**Result:** _(paste host findings here)_

---

## After the spikes

- **S-KEYTABLE GREEN + S-SIG GREEN** → ARCH-A is viable; proceed to a buildable
  plan (socket-aware enforcement, injector spec, launcher).
- **S-KEYTABLE RED + S-PTY GREEN** → ARCH-B; far simpler (no dedicated daemon, no
  enforcement change); proceed to a much smaller buildable plan.
- **Both paths RED** → the never-type-into-human-input guarantee can't be met
  safely; recommend shelving the typist and keeping only the observe-only context
  sidecar (or accept native auto-compact).
