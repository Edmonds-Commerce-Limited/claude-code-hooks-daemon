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
— but only when it notices the file changed. (There is no `/effort` family:
the supervisor injects no effort of any kind — see below.)

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

## The usage pause: one compact, then silence

Plan 00479 Task 4.5. When a session crosses its usage ceiling the daemon pauses
it rather than ending it: one resume cron replaces every other cron, and the
session wakes at the window reset. The supervisor's part is the rule below; it
is the ONE place that rule lives.

**The record.** The daemon records the pause as `<session>.usage-paused` in the
same `context-sidecar` directory as every other signal (suffix deliberately not
`.json`). Its fields are `session_id`, `paused_at`, `resume_at` (epoch seconds),
`window` (`five_hour` or `seven_day`), `used_percentage`, `ceiling` and a short
`reason`. The writer, reader, clearer and the validity rule are
`src/claude_code_hooks_daemon/utils/usage_pause.py`; the supervisor cannot import
that package, so `load_usage_pause` in `.claude/ccy/claude-supervise.py` keeps
its own copy, and `tests/unit/supervise/test_usage_pause.py` pins the two
together. A record counts only for an own session, never future-dated, and only
until `resume_at` plus an hour of grace, so a gate that died without clearing it
cannot hold a session silent for ever. An unreadable record is no pause.

**The rule**, applied by `_usage_pause_outcome` ahead of the state machine and
every injection family while a live record exists for an own session:

1. Once the session has stopped (`idle` and `work_idle`, with an empty input
   box), type exactly ONE `/compact`. Its instruction names the resume time in
   UTC and tells the session to do nothing further until the resume cron fires.
   It is not the `continue` compact. The decision is latched per pause
   (`pause_compacted_for`, keyed by `paused_at`), so a pause compacts once; a
   later pause compacts again.
2. Inject nothing else. No `continue` (the compaction signal that the compact
   itself produces is left to expire), no `/goal` or `/goal clear`, no model
   restore, flag-cleaning compact, standing-authorisation reminder, session-actions
   directive or operator-signal line. Any of them would wake a session whose
   whole purpose is to stay quiet until the cron.
3. A compaction wait already in flight is dropped (`AWAIT_COMPACTING` to
   `MONITOR`) and the compact waits a tick, so the host's stale-compact guard
   cannot swallow the latch.
4. When the record is cleared or expires, the latch is forgotten and the
   supervisor behaves normally again. The lift is logged once.

Every decision is written to `decision.log` the usual way: the compact as a
`would-compact` line naming the pause and resume time, the waiting, the held
state and the lift as deduped `noop:` lines, and a compact held back by a
non-empty input box as the usual `injection deferred` line.

**Known limits.** The latch lives in the worker's machine. The PTY host adopts
the worker's state through `import_state`, and a host that predates this change
ignores the new key, so a worker that is reloaded or crashes MID-PAUSE forgets
that it has compacted and types one more compact. A compact that was pasted but
not submitted is not followed up with the bare Enter that the ordinary compact
gets, because that follow-up belongs to the machine this rule bypasses. Both
cost one wasted compact at worst, never a nudge.

Ship it like any other supervisor change: the worker hot-reload below, verified
by the `ps` check, never a session restart.

## Supported Python and the launcher

**Supported Python: 3.11 or later** — the canonical statement is
[Supported Python](../LLM-INSTALL.md#supported-python); the floor is
`requires-python` in `pyproject.toml`.

The supervisor runs on the container's system `python3`, which can be older (RHEL
9 ships 3.9). Newer syntax fails when Python PARSES `claude-supervise.py`, so a
version check inside it can never run. A shell launcher therefore sits in front:
`.claude/ccy/claude-supervise` (no extension, POSIX `sh`, deployed with the
supervisor). `ccy.env` points `CCY_CLAUDE_WRAPPER` at it; ccy runs
`<wrapper> claude <args>`, so the launcher receives
`[supervisor flags] -- <claude argv...>`.

The contract:

1. Interpreter, first that reports Python 3.11 or later: `$CCY_PYTHON`, then
   `python3.14`, `python3.13`, `python3.12`, `python3.11`, `python3`.
2. Found: `exec <python> claude-supervise.py "$@"`, every argument unchanged. The
   `--worker` subprocess starts from `sys.executable`, so it uses the same Python.
3. None found, or `claude-supervise.py` missing: a multi-line warning on stderr
   (the version found, the 3.11 requirement, that supervision is OFF, how to fix
   it), held for `CCY_UNSUPPORTED_PYTHON_PAUSE` seconds (default 5) on an
   interactive terminal, then `exec` of everything after the first `--`, i.e.
   `claude` unsupervised. Claude Code always opens.
4. No `--` in the arguments: exit 2, as the supervisor does.

`MIN_MAJOR` / `MIN_MINOR` in the launcher must equal `requires-python`; a test
pins them. An upgrade repoints a `ccy.env` that still execs the bare script at the
launcher (`wrapper_migrated`), and `ccy_supervisor_integrity` warns about one that
does not yet.

## Plugins: extending the supervisor without forking it

Plan 00487. A launcher that needs one more behaviour (a maximum session age, a
deadline message) writes a **plugin** instead of asking for a feature that is
really its own. The contract below is the whole API; nothing in the daemon
knows about any particular plugin.

### Naming a plugin

Plugins are named explicitly on the supervisor's own command line, before
`--`. Nothing is found by scanning a directory.

```text
claude-supervise.py --arm --plugin <name>=<worker.py> [--plugin <name>=<worker.py> ...] -- claude ...
```

- `<name>` matches `[a-z][a-z0-9_-]{0,31}`. `<worker.py>` is an absolute path.
- Plugins are asked in the order the flags appear.
- `--disable-plugin <name>` keeps a named plugin off. The host passes it on
  EVERY worker start (see "The failure path"), and a launcher may pass it too.
- `--plugin-host` (a host half run between `fork` and `exec`) and the in-container
  `Restart` result are **not implemented**. The API reserves room for them
  (Plan 00487 Tasks 1.4 and 1.5); a plugin cannot use them yet.

Each file must be a regular file (a symlink is refused), owned by the
supervisor's uid or root, with neither the file nor its directory group- or
world-writable. The host vets the file and **never imports it**; the `--worker`
subprocess re-vets it immediately before importing. A refusal only skips that
plugin: the session always starts.

### The worker half

The file is stdlib-only and defines:

```python
PLUGIN_API = 1                         # the MAJOR version; a mismatch is a load failure

def create_worker_half(api):           # returns an object with the members below
    ...

class WorkerHalf:
    name: str                          # must equal the --plugin name
    version: str
    def on_start(self) -> None: ...
    def on_idle(self, tick) -> "api.ExitForRestart | api.Notify | None": ...
```

`api` gives the factory:

| Member                         | Meaning                                                                                   |
| ------------------------------ | ----------------------------------------------------------------------------------------- |
| `api.api_version`              | `(major, minor)`. Minor versions only ever ADD optional members.                          |
| `api.state_dir`                | A private `0700` directory for this plugin, under `.claude/ccy/state/plugins/<name>/`.    |
| `api.session_id()`             | The supervisor's own session id when exactly one is known, else `None`.                   |
| `api.status(text, level, ttl)` | A transient status-line message (`"info"` or `"warning"`, `ttl` clamped to 1-60 seconds). |
| `api.audit(message)`           | One `decision.log` line, `plugin <name>: <message>`, sanitised to one printable line.     |
| `api.ExitForRestart(reason)`   | A result `on_idle` may return: end the session for a relaunch (see "Exit for restart").   |
| `api.Notify(kind, minutes)`    | A result `on_idle` may return: ask for a fixed session notice (see "Session notices").    |
| `api.RESTART_SOON`             | `Notify` kind `"restart-soon"`; `minutes` is required, an `int` from 1 to 240.            |
| `api.DEADLINE_REACHED`         | `Notify` kind `"deadline-reached"`; takes no `minutes`.                                   |

`tick` is `IdleTick(now, session_id)`.

**When the hooks run.** `on_start()` runs once each time the worker process
starts, and a worker hot reload starts it again, so it must be idempotent; keep
anything that has to survive in `state_dir`. `on_idle(tick)` runs ONLY at the
very end of the `decide_once` cascade, after every built-in family including the
session-actions directive, and only when all of these hold: nothing else claimed
the tick (no payload, decision `NOOP`), no compaction signal is pending, the
machine is in `MONITOR`, the session is idle with an empty input box
(`can_inject`) and the supervisor has no unconfirmed line of its own in the box.
A plugin therefore never races a compaction, a `continue` or any other injection.

**Plugin code never runs in the PTY host.** When the worker is silent or dead the
host's in-process fallback (`_poll_once`) decides with the built-in families
only: no plugin is imported, started or asked there, whether the silence lasts one
tick or the rest of the process. Plugins resume on their own when a worker answers
again. The host never imports a plugin file either; it only vets it. (A plugin that
holds the GIL, or leaks a thread, in the host would take the session with it, which
is exactly what the worker split exists to prevent.)

**Plugins never type.** The only effects a plugin has on the session are an exit
request and a `Notify` request, and the host validates both. Only fixed supervisor
templates reach the chat.

### The worker's reply channel is private

The worker's stdin and stdout are the tick and reply pipes to the PTY host, and
plugin code runs in that process. Before any plugin is loaded the worker
(`_isolate_worker_channels`) duplicates the real stdin and stdout to private
streams, points fd 0 at `/dev/null`, and points fd 1 and `sys.stdout` at the
worker error log (`untracked/claude-supervise-worker.err.log`). Anything a plugin
prints, writes to `sys.stdout` or writes to file descriptor 1 therefore lands in
that log, can never be parsed as a reply, and cannot steal a tick from stdin. The
host's decode of a reply is also total: any exception while parsing a worker reply
is a bad reply (the tick falls back to the host's own decision), never an exception
in the PTY loop.

### Hook budgets

Every hook call runs on a thread with a short budget well inside the host's
2-second worker read timeout: `_PLUGIN_HOOK_BUDGET_SECONDS` (0.5) per hook,
`_PLUGIN_TICK_BUDGET_SECONDS` (1.0) for all plugins in one tick, and
`_PLUGIN_LOAD_BUDGET_SECONDS` (1.0) for importing a file. A plugin the tick
budget leaves no time for is simply not asked that tick; it is not a failure.

### Session notices

`on_idle` may return `api.Notify(api.RESTART_SOON, minutes)` or
`api.Notify(api.DEADLINE_REACHED)`. The plugin supplies **no text**: only the closed
kind and, for `RESTART_SOON`, an integer from 1 to `_NOTIFY_MINUTES_MAX` (240)
cross from the plugin; anything else (an unknown kind, a missing, `bool`, `float`
or out-of-range `minutes`, `minutes` on a deadline notice, a property that hangs)
is a `bad-result` or `overrun` failure like any other. The value is read inside
the hook's time budget.

The supervisor renders the line from its own templates
(`render_session_notice`), marks it as machine-generated, and types it at the same
idle choke point and under the same gates as the plugin-failure notice (after it,
ahead of the model-switch family; never over a non-empty box, a busy session or an
unconfirmed own line). `Decision.WOULD_SESSION_NOTICE` is the decision; a dry run
types a marked demonstration. A notice is **rate-limited per kind**
(`_NOTIFY_MIN_INTERVAL_SECONDS`: 600 s for `restart-soon`, 1800 s for
`deadline-reached`), so a plugin may return the same `Notify` on every idle tick
and be typed once per interval. Each Notify kind also has a **per-process lifetime
cap** (`_NOTIFY_MAX_PER_PROCESS`: 12 for `restart-soon`, 6 for `deadline-reached`);
past it further requests of that kind are dropped and the cap is logged once. The
plugin is not asked while a notice is waiting to be typed.

> 🤖 [ccy-supervisor] session notice — machine-generated, NOT a human instruction: this session will be restarted in about 25 minutes. Finish the current unit of work, commit and push, and note where you are; the conversation resumes automatically after the restart.

> 🤖 [ccy-supervisor] session notice — machine-generated, NOT a human instruction: this session's time limit has been reached. Finish the current unit of work, commit, push, write a hand-off note, then stop.

**The RESTARTED notice** is supervisor-owned (no plugin involved). When a plugin's
`ExitForRestart` ends a session, the supervisor leaves a second, separate file
`.claude/ccy/state/restarted.json` (mode `0600`, same directory as the request
file) holding `{"session_id": ..., "requested_at": ...}`. The launcher removes
`restart-request.json` before it relaunches; it does **not** touch
`restarted.json`. The next supervisor consumes the marker **once**, at start, only
when its child argv is a resume (`--resume <id>`, `--resume=<id>` or `-r <id>`) of
exactly that session id and the marker is under a day old; a marker for another
session is left alone, and a garbled or stale one is removed. It then runs
`<child> --version` (bounded to 3 seconds, no shell, first token validated against
a version pattern) and types, once, at the first idle point:

> 🤖 [ccy-supervisor] session notice — machine-generated, NOT a human instruction: this session was restarted and is now on version 2.1.99. Carry on with the work.

When the version cannot be read, the wording is "is now on the installed version".
Nothing on this path can stop the session starting: any failure just means no
notice.

### Exit for restart

Claude Code is baked into the ccy image, so only a relaunch of the container
picks up a new version. `on_idle` returning `api.ExitForRestart(reason)` asks for
that. `reason` is short, logged only, and never typed into the chat. The host:

1. **refuses** (a deduplicated `noop:` line in `decision.log`, nothing typed)
   unless `cached_own_session_ids()` holds exactly one id. That set only ever
   grows, so a `/clear` or a resumed conversation that introduced a second id
   makes every later request refuse until the supervisor is relaunched;
2. types `/exit` through the ordinary injection path and tracks it as an
   unconfirmed own line;
3. **holds every other injection** until the child exits, for at most
   `_RESTART_EXIT_WAIT_SECONDS` (30). A child that ignores `/exit` is
   abandoned: the hold is released, a line is logged, and the session carries
   on. The hold is the only thing that delays a compaction, so a compaction is
   never delayed beyond that bound. The still-owned `/exit` line then follows the
   ordinary own-line rule, so it can still be submitted late, in which case the
   session simply ends;
4. once the child has exited, writes `restart-request.json` (and the separate
   `restarted.json` marker, see "Session notices") and exits with
   **`EXIT_STATUS_RESTART_REQUESTED` (75, EX_TEMPFAIL)**.

**An abandoned request is not re-made straight away.** After an abandon the same
ask is ignored for `_RESTART_RETRY_COOLDOWN_SECONDS` (600), and a plugin whose
requests have been abandoned `_RESTART_MAX_ABANDONED` (3) times in one process is
disabled through the uniform failure path (kind `exit-stuck`, the worker restarted
without it, one fixed-template notice).

In dry-run mode nothing is typed and the request is only logged.

**The request file** is `.claude/ccy/state/restart-request.json` (override the
directory with `CCY_SUPERVISOR_STATE_DIR`), mode `0600`, written atomically:

```json
{"session_id": "<id>", "reason": "<short text>", "plugin": "<name>", "requested_at": 1790000000.0}
```

The launcher must act on status 75 **only when this file is present and
fresh** (check `requested_at`), relaunch with `--resume <session_id>`, and
delete the file once it has read it. A genuine child exit status of 75 with no
file is not a request. If the file cannot be written, the supervisor exits with
the child's own status instead, because the launcher could not act on 75.

### The failure path

A plugin must never block the supervisor or the session. Every failure takes the
same four steps:

1. **Detect.** The failure kinds are a closed set: `load` (a refusal, with a
   closed reason such as `api-mismatch`, `import-error` or
   `group-or-world-writable`), `exception`, `overrun` (a hook past its budget),
   `bad-result` (anything `on_idle` returned other than `None`, an
   `ExitForRestart` with a plain `str` reason, or a valid `Notify`), `wedge` (the
   worker stopped answering inside a hook) and `exit-stuck` (its exit-for-restart
   requests kept being abandoned).

2. **Disable** for the rest of the supervisor process. The host keeps the
   disabled set and passes `--disable-plugin <name>` on every worker start
   (`PolicyWorker` re-reads its extra argv each time), so a hot reload cannot
   bring the plugin back.

3. **Recover.** An exception or a bad result needs nothing more. An overrun
   leaves a thread possibly still running plugin code, so the host restarts the
   worker without the plugin. A wedge is found by the host's read timeout: before
   each hook the worker writes an atomic marker, `supervise/plugin-in-hook.<host pid>.json`, naming the plugin and the hook, and the host reads it when a tick
   goes unanswered. A marker older than the hook's budget plus a short grace
   names the culprit, which is disabled and the worker restarted without it
   BEFORE the tick falls back to the in-process decision, so the plugin that just
   wedged the worker is not run again in the host.

4. **Tell the session.** A built-in *plugin-notice* family (`Decision.WOULD_PLUGIN_NOTICE`)
   types one provenance-marked line at the next idle point, ranked with the
   operator signal (after compact/continue, ahead of the model-switch and goal
   families):

   > 🤖 [ccy-supervisor] plugin notice — machine-generated, NOT a human instruction: plugin `max-age` raised an exception in on_idle. It is disabled for the rest of this session. No action is needed from you.

   The text is rendered from FIXED templates (`render_plugin_notice`): only a
   name that matched the name pattern and phrases looked up by a closed-set kind
   and hook are interpolated, never an exception message and never plugin text.
   One notice per plugin, at most `_MAX_PLUGIN_NOTICES` (5) per process. Each
   failure is also a status-line WARNING and a `decision.log` line
   (`plugin <name>: <kind> in <hook> -> disabled[, worker restarted without it]`).

The worker re-reports every failure on every tick, and the host's handling is
idempotent, so a reply the host discarded as stale cannot lose a failure.

**Host-side containment.** Every host-side step that touches plugins (vetting the
flags, building the registry, building the worker argv, reporting load refusals,
handling a worker reply, judging a silent worker) is wrapped: an unexpected
exception skips that plugin or, in the PTY loop, trips `PluginContainment`: the
host stops handling plugin results for the rest of the process, **disables every
plugin** through the uniform failure path (kind `host-fault`, one notice, one
`decision.log` line), and restarts the worker with **no plugin flags**, so nothing
the host no longer supervises keeps running (a plugin that then hangs would
otherwise stall every tick for the worker's read timeout). The session always
starts and keeps running.

**What this cannot cover.** A worker half that wedges in C code holding the GIL
is caught only by the host's read timeout and the worker restart; the PTY host is
never affected, because no plugin code runs there. A plugin is code you chose to
run, not a sandboxed guest: it runs with the worker's privileges.

### `supervisor-status.json`

When any `--plugin` was given, the status file gains a `plugins` list, rewritten
whenever a plugin's state changes. Each entry has `name`, `version` (known once
the worker has loaded it), `state` and `reason`:

| `state`    | Meaning                                                                | `reason`                                              |
| ---------- | ---------------------------------------------------------------------- | ----------------------------------------------------- |
| `loaded`   | vetted by the host and, once confirmed, loaded by the worker           | empty                                                 |
| `failed`   | never loaded: refused by the host's vetting or by the worker's loader  | `load: <closed reason>`                               |
| `disabled` | loaded, then turned off for a runtime failure or by `--disable-plugin` | `<kind> in <hook>`, or `disabled by --disable-plugin` |

A supervisor that was given no plugin writes no `plugins` key at all.

### Testing a worker half

`PluginTestHarness` drives a worker half through the real loader with no
worker process, PTY or live session. Unlike the supervisor, which disables a
failing plugin and carries on, it raises `PluginHarnessError` with the
traceback. The script's filename has a hyphen, so load it by path:

```python
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("claude_supervise", Path(".claude/ccy/claude-supervise.py"))
supervise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervise)

harness = supervise.PluginTestHarness(
    "max-age", Path("plugins/max_age.py"), work_dir=tmp_path, session_ids=("s-1",)
)
harness.start()                        # loads the half and runs on_start
request = harness.idle(now=1_790_000_000.0)
assert request == supervise.PluginExitRequest(plugin="max-age", reason="session is 3 days old")
assert harness.status_messages == [("restart in 10 minutes", "warning", 5)]
```

`harness.half`, `harness.state_dir`, `harness.audit_lines()`,
`harness.notifications` (the `Notify` results of the latest `idle`) and
`harness.status_messages` expose what the plugin did. This repository's
`tests/unit/supervise/conftest.py` shows the three-line pytest fixture a plugin
author copies.

### Editing plugin code and the supervisor

The plugin flags and the registry are HOST code, so a ccy relaunch is needed to
start using plugins at all; the hot reload described above covers the worker's
half of this (the loader, the hooks, the notice families, `ExitForRestart` and
`Notify` handling in `decide_once`, the reply-channel isolation). Editing a plugin file does not change the content hash the reload
watches: restart the worker once (see "The rule" above) to pick the edit up.

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

### What the owner should add to `modelSettings`

In whichever settings file they want it to apply — most commonly their user
settings — naming exact model ids per `settings-reference.md:1197`
("Claude Code writes each entry under the model's canonical name... and
matches that model's alias, date-suffixed, `[1m]`, and recognized
provider-specific IDs to the same entry"). This is the canonical copy of
these entries; post-upgrade task 02 points here:

```json
{
  "modelSettings": {
    "claude-fable-5-1": { "effortLevel": "low" },
    "claude-opus-5": { "effortLevel": "xhigh" },
    "claude-opus-4-8": { "effortLevel": "xhigh" }
  }
}
```

- `claude-fable-5-1` (Fable 5.1, the `fable` alias's target) at `low` is the
  level the old DROP ANCHOR injection typed. This entry does NOT cover Fable 5
  (`claude-fable-5`, what a gateway resolves `fable` to) or the `mythos` ids
  the supervisor treats as the same family (`_MODEL_FAMILY_CANONICAL`); add
  those ids too if the project's gateway can serve them.
- `claude-opus-5` and `claude-opus-4-8` at `xhigh` are the level the old
  downgrade compensation typed, for Fable's two automatic-fallback targets
  (`model-config.md:486` — biology-flagged requests land on Opus 5,
  cybersecurity-flagged requests land on Opus 4.8). This is BROADER than the
  old compensation, which fired only for a drop that started at Fable: these
  two entries set Opus 5 and Opus 4.8 to `xhigh` wherever they serve a
  request in this session (including an Opus 5.5 → Opus 4.8 cyber fallback,
  or a manual pick of either), not just in a fable-origin episode.
- `claude-opus-5-5` gets NO entry: Opus 5.5 stays at its built-in `medium`
  default (`model-config.md:548`), and a top-level `effortLevel` in the user
  file does not apply to it either (`model-config.md:550`). A top-level
  `effortLevel` in the project or local settings file, or
  `CLAUDE_CODE_EFFORT_LEVEL` (the shell variable, or the same variable set
  through the project, local or user file's own `env` object), WOULD apply to
  every model, Opus 5.5 included, and override all three entries above;
  `hooks-daemon check` reports any of those as `[WARN] Effort Source`. A
  managed settings file or `--settings` can pin it too, but `check` does not
  read either: this project vendors no confirmed on-disk path for managed
  settings, and `--settings` cannot be seen from a running session. Rule
  those out by hand if `check` passes and effort still looks pinned.

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
