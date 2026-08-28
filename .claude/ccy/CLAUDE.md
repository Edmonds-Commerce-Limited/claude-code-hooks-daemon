# .claude/ccy/ — Supervisor Hot-Reload Contract

Canonical home for the ccy supervisor's edit-to-live contract (promoted from
`.claude/rules/ccy-supervisor-dogfooding.md`, which now points here).

**An edit to `.claude/ccy/claude-supervise.py` does not take effect in the live
session the moment you save it**, and treating it as if it does is how a change
gets "verified" against the *old* code and a real bug slips through.

## Why

Every injection decision (`/compact`, `continue`, `/goal`, `/effort`, `/model`)
runs in a **`--worker` subprocess**, not in the long-lived PTY host that owns
the `claude` process (the two-tier design from Plan 00164 Phase 4). The host
hot-reloads that subprocess — swapping in your new code **without a full Claude
Code session restart** — but only when it notices the file changed.

The noticing is **content-hash based, with an mtime pre-check**
(`reload_if_stale` → `compute_source_hash`, re-checked every
`_WORKER_RELOAD_CHECK_SECONDS` ≈ 5s on each tick). Two consequences bite in
practice:

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

A **new pid / start-time** (later than your edit) means the new code is live.
If it has not changed, force a clean restart of just the worker — the PTY/child
is untouched:

```bash
kill <worker-pid>   # host's `if not worker.alive(): worker.restart()` respawns
                    # a fresh worker from current on-disk code on the next tick
```

Then re-run the `ps` check and confirm the pid changed. **Never restart the
whole ccy session** (which would drop the live `claude` process) merely to
reload the worker — that is exactly what the two-tier split exists to avoid.

## Client installs: edit source, then redeploy

In a client project the supervisor is a **deployed artefact**; editing your
local working copy of the daemon source is not enough — the deployed
`.claude/ccy/claude-supervise.py` must be refreshed (daemon upgrade / redeploy)
before the host can reload the worker from it. In this self-install repo the
tracked `.claude/ccy/claude-supervise.py` *is* the source, so an edit here is
directly reload-eligible — but the verify-the-pid discipline above still
applies.
