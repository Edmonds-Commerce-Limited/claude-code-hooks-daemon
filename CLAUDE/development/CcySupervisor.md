# The ccy supervisor — the edit-to-live contract

Canonical home for how an edit to `.claude/ccy/claude-supervise.py` reaches the
running session, and how to verify it did.

**An edit to the supervisor does not take effect in the live session the moment
you save it**, and treating it as if it does is how a change gets "verified"
against the *old* code and a real bug slips through.

## Why this document is here and not in `.claude/ccy/`

The contract used to live at `.claude/ccy/CLAUDE.md`. That file **cannot be
tracked**: ccy's startup security gate refuses to launch when it finds any file
in `.claude/ccy/` tracked by git, and its prescribed remediation is a history
rewrite plus a force push. `.claude/ccy/.gitignore` records the decision in its
own comment, and the full defect report for the ccy maintainers is kept at
`untracked/fedora-desktop-ccy-CLAUDE-bug.md`.

An untracked canonical home is a dead link in every fresh clone and every new
worktree, which is exactly where a reader most needs it. So the contract lives
here, in the tracked agent tree, and the ccy directory keeps whatever local
copy that machine's install mounts.

## Why an edit is not immediately live

Every injection decision (`/compact`, `continue`, `/goal`, `/model`) runs in a
**`--worker` subprocess**, not in the long-lived PTY host that owns the `claude`
process (the two-tier design from Plan 00164 Phase 4). The host hot-reloads that
subprocess — swapping in new code **without a full Claude Code session restart**
— but only when it notices the file changed. (`/effort` was a fifth family here
before Plan 00466 N47 review 2; the supervisor injects no effort of any kind
now — see below.)

**Since Plan 00317 this includes typed-command RECOGNITION, not just the
decision.** Parsing what the human typed (`/compact`) runs in the
`--worker` subprocess, fed by a bounded raw-input tap the host forwards each
tick, rather than in the never-reloading host. If you are editing
`HumanInputLine`, the fix ships live the moment the worker reloads — same rule
as below, no session restart, no host change needed.
`CLAUDE/Plan/Completed/00317-supervisor-host-thin-shim/AUDIT.md` audits what
stays host-side and why: mainly primitives that must act on a byte before it
reaches the child, such as the Ctrl+C double-press swallow, which cannot
round-trip to the worker without adding forwarding latency.

**`/model` is deliberately absent from that list** (Plan 00328). The supervisor
does not recognise a human's model command at all — not the typed form, not the
picker. The auto-restore arms on the daemon's `.model-downgrade` signal, which
carries Claude Code's OWN record of a safety substitution, so a model the human
picks is respected because it produces no such record. Do not re-add keystroke
recognition to reach the restore: the picker types no text, so the inference has
no safe setting.

**`/compact` recognition from keystrokes is exact, and stays exact** (Plan
00399). A `/compact` reached by typing `/comp` and pressing Tab is expanded
inside Claude Code's input box and forwards no bytes that spell it, so the
keystroke match never fires. That compaction is recognised instead from the
daemon's `<session>.compacting` record, which `compaction_signal` writes at
PreCompact with an `origin` (`human`, `supervisor` or `auto`), and the resume
line in `decision.log` names it: `compaction detected (human /compact)`. Do not
widen the keystroke match to prefixes: a false recognition parks the machine in
a human-owned AWAIT for the whole await timeout, during which no band compacts.
The record fires at compaction START, so a Tab-completed `/compact` QUEUED
behind a streaming turn is still unseen until it runs, and the supervisor may
type its own `/compact` in that window.

## How the reload is noticed, and the two ways it silently is not

Noticing is **content-hash based, with an mtime pre-check** (`reload_if_stale` →
`compute_source_hash`, re-checked every `_WORKER_RELOAD_CHECK_SECONDS` ≈ 5s on
each tick). Two consequences bite in practice:

1. **A bare `touch` does nothing.** mtime advances but the content hash is
   unchanged, so no reload fires. You cannot "poke" the worker awake.
2. **A redeploy that preserves mtime** (`cp -p`, `rsync -a`, some installers)
   can change the *content* without advancing mtime, so the mtime pre-check
   skips the hash and the reload silently never happens — leaving a stale
   worker.

There is also a session-history trap: a worker spawned at time *T* is running
the code that was **on disk at *T***, which may predate a later commit. A
`git log` commit time is not a deploy time — do not infer the running worker's
code from git history. Inspect the process, not the log.

## The rule: verify the reload, do not assume it

After editing the supervisor, **confirm the worker actually reloaded before you
test behaviour**:

```bash
ps -eo pid,lstart,args | grep 'claude-supervise.py --worker' | grep -v grep
```

A **new pid / start-time** (later than your edit) means the new code is live. If
it has not changed, force a clean restart of just the worker — the PTY and the
child are untouched:

```bash
kill <worker-pid>   # the host's dead-worker path respawns a fresh worker from
                    # current on-disk code on the next tick, and logs
                    # `worker died ... -> respawned` to decision.log
```

Kill it **once**. Since Plan 00361 the host treats a second death on the same
source fingerprint as a crash loop: it logs `worker crash-looping` once and
holds further respawns to a backoff (`_WORKER_CRASH_BACKOFF_SECONDS`) until the
file's content changes, deciding in-process meanwhile. That is also what happens
while an in-tree edit leaves the file in a state that cannot run: check
`decision.log` for `worker died` / `worker crash-looping` / `worker recovered`,
and the worker error log for the dated, fingerprinted
`worker crashed (source <hash>)` record.

Then re-run the `ps` check and confirm the pid changed. **Never restart the
whole ccy session** — which would drop the live `claude` process — merely to
reload the worker. That is exactly what the two-tier split exists to avoid.

## Effort is not the supervisor's concern at all

Plan 00466 N47 review 2 found the decisive reason the supervisor must never
type `/effort`, at any level, for any purpose: Claude Code SAVES every
interactively-typed `/effort <level>` into `modelSettings` in the settings
file that confirming it with `Enter` targets — almost always the owner's own
`~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json`) — the same
single source of truth the owner asked the supervisor to stop fighting. See
`remote-docs/docs.claude.com/en/docs/claude-code/model-config.md:552-557` and
`remote-docs/docs.claude.com/en/docs/claude-code/settings-reference.md:900`.
An unattended process typing `/effort` therefore does not make a session-only
adjustment — it permanently overwrites what the owner saved for that model.

So the supervisor holds **no effort state and injects no `/effort` command,
ever** — not on downgrade, not on manual `/model`, not on compaction, not in
response to a settings change. The two behaviors the supervisor used to
enforce by injection are now DATA the owner adds to their own `modelSettings`
— **but this only works while the session's own effort has never been set.**

**The pin (review 3 — this is the part review 2 got wrong).** Claude Code's
resolution order (`model-config.md:544-548`) puts an **explicit choice**
above the saved `modelSettings` level: "`CLAUDE_CODE_EFFORT_LEVEL`, launching
with `--effort`, or `/effort` in the session". The docs never say what an
explicit choice does across a LATER model change, but they do rank it first
with no per-model qualifier, and the installed Claude Code 2.1.282 binary
confirms it plainly: the session tracks one `sessionEffort` value —
`{kind:"inherit"}` at start, `{kind:"level", value}` after `/effort <level>`
or an effort pick in the `/model` picker's slider, or `{kind:"default"}`
after `/effort auto`. The resolver looks the model up in `modelSettings`
**only** while `sessionEffort` is still `inherit`; `level` and `default` both
skip the per-model table outright — `level` returns the pinned value no
matter which model serves the request, and `default` returns the model's
BUILT-IN default (not its saved level). An automatic refusal fallback (Plan
00328's downgrade) changes only the model field; it never touches
`sessionEffort`. Nothing found sets `sessionEffort` back to `inherit` — once
pinned (by `/effort <level>`, `/effort auto`, an effort pick in the picker,
`--effort`, or `CLAUDE_CODE_EFFORT_LEVEL`), **no settings.json configuration
can make different models in that SAME session run at different effort
levels again.** That is the direct answer if the owner asks "why isn't my
`modelSettings` entry applying" — check whether anything in the session
already pinned it.

- **`/effort auto` does not restore per-model resolution.** It sets
  `sessionEffort` to `{kind:"default"}`, the model's own BUILT-IN default —
  not a return to `inherit`, and not a re-read of `modelSettings`. It also
  **writes**: `settings-reference.md:1211` — "Run `/effort auto` to clear
  your saved level for the model you're using" — clearing that model's
  `modelSettings` entry in the settings file it applies to. Both facts
  matter: it does not get the owner back to the two-model-different-levels
  behaviour below, and it is itself a settings.json write, just like every
  other confirmed `/effort`.
- The two-different-levels behaviour (Fable at low, its fallback at xhigh)
  therefore only holds for a session that **never types `/effort`, never
  picks an effort level in `/model`, and is never launched with `--effort`
  or `CLAUDE_CODE_EFFORT_LEVEL`.** If the owner wants it, they must leave
  effort alone for that session; if they need a specific level HERE and NOW,
  typing `/effort` is a deliberate, one-time choice that pins the rest of
  that session, exactly as before this design — the difference N47 makes is
  that the SUPERVISOR never does this automatically or fights the choice
  afterward.

**What the owner should add to `modelSettings`** (in whichever settings file
they want it to apply — most commonly their user settings), naming exact
model ids per `settings-reference.md:1197` ("Claude Code writes each entry
under the model's canonical name... and matches that model's alias,
date-suffixed, `[1m]`, and recognized provider-specific IDs to the same
entry"):

```json
{
  "modelSettings": {
    "claude-fable-5-1": { "effortLevel": "low" },
    "claude-opus-5": { "effortLevel": "xhigh" },
    "claude-opus-4-8": { "effortLevel": "xhigh" }
  }
}
```

- `claude-fable-5-1` (Fable 5.1, the `fable` alias's target) at `low` replaces
  the old DROP ANCHOR injection: a low ceiling for the model that does the
  fable-anchor work. This entry does NOT cover Fable 5 (`claude-fable-5`, what
  a gateway resolves `fable` to) or the `mythos` ids the supervisor treats as
  the same family (`_MODEL_FAMILY_CANONICAL`); add those ids too if the
  project's gateway can serve them.
- `claude-opus-5` and `claude-opus-4-8` at `xhigh` replace the old downgrade
  compensation: Fable's two automatic-fallback targets
  (`model-config.md:486` — biology-flagged requests land on Opus 5,
  cybersecurity-flagged requests land on Opus 4.8). This is BROADER than the
  old compensation, which fired only for a drop that started at Fable: these
  two entries now apply an xhigh floor to Opus 5 and Opus 4.8 wherever they
  serve a request in this session (including an Opus 5.5 → Opus 4.8 cyber
  fallback, or a manual pick of either), not just a fable-origin episode.

Since none of this is code, **no worker reload applies to it at all** —
editing `modelSettings` is an ordinary Claude Code settings edit, not a
`claude-supervise.py` change, and takes effect the next time Claude Code
resolves effort for the model in question (typically the next request, or
the next session start for values Claude Code already resolved this
session) — PROVIDED that session's own effort was never pinned per above.
The `ps`/reload discipline in this document is about the supervisor's own
CODE. A code change (such as this fix) still needs a worker reload or a
full ccy relaunch to take effect — see "How the reload is noticed" above,
and relaunch ccy after upgrading past this fix specifically, since the old
host's in-process fallback path still types `/effort` until it does.

## Client installs: edit source, then redeploy

In a client project the supervisor is a **deployed artefact**; editing your
local working copy of the daemon source is not enough — the deployed
`.claude/ccy/claude-supervise.py` must be refreshed by a daemon upgrade or
redeploy before the host can reload the worker from it. In this self-install
repository the tracked `.claude/ccy/claude-supervise.py` *is* the source, so an
edit here is directly reload-eligible — but the verify-the-pid discipline above
still applies.
