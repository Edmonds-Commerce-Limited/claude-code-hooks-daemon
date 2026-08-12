# Upstream report — ruff findings in the deployed `claude-supervise.py`

**For:** `claude-code-hooks-daemon` upstream
**Component:** `claude-supervise.py` (standalone PTY supervisor, Plan 00135)
**Daemon version:** 3.51.0
**Reporter context:** `fedora-desktop` (client repo consuming the daemon)

---

## TL;DR

**No bugs found.** All three ruff findings in `claude-supervise.py` are deliberate,
well-documented design choices, and we are not asking for the code to change.

The actual problem is **lintability at the deploy location**. The daemon installs
its own source *inside a client-owned directory* (`.claude/ccy/`), which sits
outside the conventional `.claude/hooks-daemon/` vendor path that client QA
excludes. Every client repo therefore lints daemon-owned code it cannot modify,
and must independently rediscover that fact and encode a local exclusion.

We would like upstream to close that gap once, rather than have every client
close it separately.

---

## Environment

| Item           | Value                                                           |
| -------------- | --------------------------------------------------------------- |
| ruff           | 0.16.2                                                          |
| Python         | 3.x (container system python, per the file's own docstring)     |
| Deployed path  | `.claude/ccy/claude-supervise.py`                               |
| Size           | 140,534 bytes / 3,100 lines                                     |
| Deploy setting | `ccy.deploy_supervisor: true` (refreshed on install + upgrade)  |
| Armed?         | Yes — `ccy.env` points `CCY_CLAUDE_WRAPPER` at it (`--dry-run`) |

---

## Findings

Run with ruff's **default** rule set (`ruff check --isolated`):

| #   | Rule   | Line | Message                                         | Our verdict       |
| --- | ------ | ---- | ----------------------------------------------- | ----------------- |
| 1   | BLE001 | 2407 | Do not catch blind exception: `Exception`       | Deliberate — keep |
| 2   | DTZ005 | 1907 | `datetime.now()` called without a `tz` argument | Deliberate — keep |
| 3   | DTZ006 | 1907 | `datetime.fromtimestamp()` called without `tz`  | Deliberate — keep |

Widening to `E4,E7,E9,F,BLE,PLW1510,B,SIM,RUF` adds **nothing** — only BLE001
appears. For a 3,100-line stdlib-only file driving a PTY, that is a genuinely
clean result, and worth saying out loud: this report is not a quality complaint.

### 1. BLE001 — `except Exception` in the worker tick loop (line 2407)

```python
try:
    outcome = decide_once(...)
except Exception:
    # SAFETY NET: a single tick's exception must not kill the worker
    # (the host would respawn it and the crash would repeat every tick,
    # flooding the PTY with tracebacks). Log the full traceback to the
    # error FILE, emit a safe NOOP so the host still gets a reply, and
    # carry on with the next tick. This is a deliberate broad catch --
    # the whole purpose is to contain ANY unexpected decision failure.
    append_worker_error("decide_once failed:\n" + traceback.format_exc())
    outcome = _worker_error_noop()
```

This is textbook-correct. The catch is at a supervisory boundary, the traceback
is preserved to a file (not swallowed), and a well-defined safe value is
substituted so the protocol continues. Narrowing it would defeat its stated
purpose. **Do not change the code.**

### 2/3. DTZ005 + DTZ006 — naive `datetime` in `_format_bot_prefix` (line 1907)

```python
moment = datetime.now() if now_wall is None else datetime.fromtimestamp(now_wall)
```

The docstring already answers the linter:

> Local time (not UTC) is used deliberately: the marker is read by a human
> scrolling their own terminal history, for whom local time is the natural
> "when did this happen" reference.

Correct call for a human-facing terminal marker. `DTZ` is a false positive
against that intent. **Do not change the code.**

---

## Why the client cannot fix this locally

Three independent blockers, any one of which is sufficient:

1. **The file is overwritten on upgrade.** With `ccy.deploy_supervisor: true`
   (the recommended setting — `false` causes the running supervisor to go stale,
   which `ccy_supervisor_integrity` itself warns about), the installer refreshes
   `claude-supervise.py` on every upgrade. Any local `# noqa` is lost.

2. **The daemon blocks writing the suppression.** The daemon's own
   `qa_suppression` handler denies Write/Edit calls that introduce `# noqa` into
   source files. So an agent cannot add the annotation even as a stopgap; a human
   must do it manually, and then lose it to (1).

3. **The conventional vendor exclusion does not cover it.** Client QA excludes
   `.claude/hooks-daemon/*` because that is understood to be upstream territory.
   `claude-supervise.py` is deployed to `.claude/ccy/` instead — a directory the
   client owns and legitimately lints (it holds the client's `Dockerfile`,
   `ccy.env`, and project handlers). The exclusion pattern that would work is not
   the one anybody writes by default.

The net effect is a linter finding that is simultaneously **not a real defect**,
**not fixable by the client**, and **not silenceable by the client** — the exact
shape that erodes trust in a QA gate.

---

## What we would like upstream to do

Any one of these closes it. Listed best-first in our view:

1. **Carry the suppressions upstream.** Add `# noqa: BLE001` at line 2407 and
   `# noqa: DTZ005, DTZ006` at line 1907 in the shipped source. The intent is
   already documented in comments right there, so the annotation is honest rather
   than a shortcut, and it makes the file clean under ruff's defaults for every
   client at once. Lowest total cost.

2. **Deploy daemon-owned code to a daemon-owned path.** Keep the real file under
   `.claude/hooks-daemon/` and place a symlink (or a thin launcher shim) at
   `.claude/ccy/claude-supervise.py`. Then the vendor exclusion clients already
   have covers it, and the ownership boundary matches the directory layout. This
   is the structural fix and also removes the "is this file mine?" ambiguity for
   agents.

3. **Document the recommended exclusion.** If neither of the above is wanted,
   state the exact per-file ignore in `CLAUDE/LLM-INSTALL.md` so clients can copy
   it rather than derive it:

   ```toml
   # ruff.toml — daemon-owned, refreshed on upgrade; do not lint
   [lint.per-file-ignores]
   ".claude/ccy/claude-supervise.py" = ["BLE001", "DTZ005", "DTZ006"]
   ```

   Weakest option: it still has to be repeated in every client repo, and it goes
   stale the moment a new rule fires on a future supervisor build.

4. **Consider whether `qa_suppression` should exempt vendored paths.** It already
   supports `exclude_paths`; shipping `.claude/ccy/claude-supervise*` in that
   default would at least let a client apply option 3's suppressions inline.

---

## Reproduction

```bash
# From a client repo with the daemon installed and deploy_supervisor: true
ruff check --isolated --output-format concise .claude/ccy/claude-supervise.py
# -> 3 findings (BLE001 x1, DTZ005 x1, DTZ006 x1)

# Confirm nothing else lurks under a wider set:
ruff check --isolated --select E4,E7,E9,F,BLE,PLW1510,B,SIM,RUF \
    --output-format concise .claude/ccy/claude-supervise.py
# -> 1 finding (BLE001)
```

## Filing route

`/workspace/.claude/hooks-daemon/bin/hooks-daemon bug-report` — run from the
project root (never `cd` into the daemon directory).
