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

Every injection decision (`/compact`, `continue`, `/goal`, `/effort`) runs in a
**`--worker` subprocess**, not in the long-lived PTY host that owns the `claude`
process (the two-tier design from Plan 00164 Phase 4). The host hot-reloads that
subprocess — swapping in new code **without a full Claude Code session restart**
— but only when it notices the file changed.

**Since Plan 00317 this includes typed-command RECOGNITION, not just the
decision.** Parsing what the human typed (`/compact`, `/effort <x>`) runs in the
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

## Client installs: edit source, then redeploy

In a client project the supervisor is a **deployed artefact**; editing your
local working copy of the daemon source is not enough — the deployed
`.claude/ccy/claude-supervise.py` must be refreshed by a daemon upgrade or
redeploy before the host can reload the worker from it. In this self-install
repository the tracked `.claude/ccy/claude-supervise.py` *is* the source, so an
edit here is directly reload-eligible — but the verify-the-pid discipline above
still applies.
