# Code Review: Plan 00456 (branch `worktree-issue-53-venv`, HEAD `f85347a7`) against `main`

Reviewer: Opus 5.5, read-only. Scope: `git diff main...HEAD` (28 files, +3933/-129).
Nothing was edited or committed. Probes were run only against tmp dirs, and all
three are kept for the plan folder:

- `untracked/scratch/review456_ci_probe.py`: CI=true and the opt-out, run through the real driver.
- `untracked/scratch/review456_uv_home_probe.py`: `repair` when uv is only in `~/.local/bin`.
- `untracked/scratch/probe_path_ab.py`: the implementer's own path A/B probe, re-run with more roots.

All three paths are relative to the worktree root.

The branch's own tests pass: 116 passed in 44s, over the 8 new or changed test files, run serially.

## Summary

The healthy hook path is untouched. `_venv_self_heal` is reached only from the
VENV_MISSING diagnosis (`init.sh:1407`), and everything else added to
`emit_hook_error` runs only on the error path. The lock handoff is sound: the
parent takes the lock, the child inherits it, then the parent forgets it, so
the lock is never free in between. The child's stdio is fully detached, and
`test_the_hook_returns_before_a_slow_build_finishes` proves the hook's pipes
close before the build finishes. The deployed copies are byte-identical to
their templates (`bin/hooks-daemon`, and the skill's `install.sh`).

Two defects make the branch's headline remedy, `repair`, fail or lie in
reachable configurations. Both were reproduced with a probe.

Issues found: 2 blocking, 6 important, 7 suggestions.

## Blocking Issues

### B1. The opt-out and CI=true make `repair` unable to build. The `disabled` message and the docs still prescribe it, and CI=true fabricates a "failed" state (confidence 95%)

**Location:**
- `scripts/venv_bootstrap.sh:237`: the hook gate honours only `HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP`.
- `scripts/install/venv.sh:787-790`: `_ensure_venv_fingerprint` also skips on `CI=true`.
- `scripts/install/venv.sh:748-764`: `ensure_venv_locked` returns 0 on that skip.
- `scripts/venv_bootstrap.sh:207-232`: `_vb_build_under_lock` then records a failure.
- `init.sh:236-240`: the `disabled` remedy.
- `docs/guides/TROUBLESHOOTING.md:134` and `CLAUDE/SELF_INSTALL.md:67,74`.

**Problem:** `ensure_venv_locked` silently does nothing whenever
`HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1` or `CI=true`. `_vb_build_under_lock`
then asks the resolver, finds nothing, writes a failed-build marker, and
prints `venv bootstrap FAILED ... (ensure_venv exit 0)`. That has two
consequences:

1. **The opt-out.** The `disabled` hook message says "To build it now:
   `repair`", and the TROUBLESHOOTING table says "Run `repair`". But with
   the variable still set (it is what produced `disabled`), `repair` can
   never build. It exits 1, leaves a `.failed` marker, and gives no reason.
2. **CI=true.** The hook gate does not check `CI`, so a hook starts a
   detached "build" that runs no uv. Every later hook then reports "THE
   LAST AUTOMATIC BUILD OF THIS VENV FAILED. Its log says why", and the log
   says only `ensure_venv exit 0`. `repair` fails the same way.
   `SELF_INSTALL.md:67` says CI=true bypasses bootstrap; for the hook path,
   that is false.

**Evidence** (`review456_ci_probe.py`, real driver, stub uv, tmp dirs):
```
--- CI=true
  first hook : ['started']
  second hook: ['failed']
  uv calls   : 0
  repair rc  : 1
  log verdict: ['✗ venv bootstrap FAILED: no venv resolves for .../clone after the build (ensure_venv exit 0).']
--- HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1
  hook state : ['disabled']
  repair rc  : 1
  uv calls   : 0
  repair says: ['✗ venv bootstrap FAILED: no venv resolves for .../clone after the build (ensure_venv exit 0).']
  marker left: ['.venv-bootstrap-...-py311-81c29529.failed']
```

**Why it matters:** the plan pins one invariant: a venv-missing message
names a remedy that works, and never names install. Here the named remedy
provably cannot work, and nothing says why. CI=true is set by GitHub Actions
(including Claude Code's own action) and by many other runners. No test covers
either variable, because the sandbox `_env()` builds a clean environment.

**Suggested fix:**
1. Make the hook gate treat `CI=true` exactly as ensure_venv does: report
   `state=disabled` and name the variable that caused it.
2. An explicit `repair` is a deliberate request, so it should build
   regardless. Unset both variables for the `ensure_venv_locked` call in
   `_vb_repair`. If you would rather keep honouring them, have `_vb_repair`
   refuse up front and name the variable.
3. When `ensure_venv_locked` reports the skip, `_vb_build_under_lock` must
   not write a failed marker.
4. Add driver and init.sh tests with `CI=true`, and with the opt-out plus
   `repair`.
5. Correct `SELF_INSTALL.md:67`, and point the `disabled` row in
   TROUBLESHOOTING at whatever the fix settles on.

---

### B2. `bin/hooks-daemon repair` builds the venv, then exits 1 with "'uv' not found. Install with: curl ..." when uv lives only in `~/.local/bin`. The skill then reports a failed in-place repair and lists `--force` (confidence 95%)

**Location:**
- `bin/hooks-daemon:108-126`, and the byte-identical template.
- `src/claude_code_hooks_daemon/daemon/cli.py:1858-1869` (`_repair_venv_locked` spawns a bare `["uv", "sync"]`).
- `scripts/install/venv.sh:25-27`: the `~/.local/bin` PATH prepend, which exists only inside the bootstrap subprocess.
- `.claude/skills/hooks-daemon/scripts/install.sh:254-266`.

**Problem:** The gate counts uv in `~/.local/bin` as present. The refusal fix
text even says so: "~/.local/bin, uv's default home, is searched as well".
The bash build finds uv there and succeeds. But that PATH change dies with
the `venv_bootstrap.sh` subprocess. The wrapper then execs the Python
`repair`, whose `uv sync` sees the caller's PATH and fails with the "install
uv" message. That message contradicts the gate. The exit code is 1, although
the venv resolves and the next hook starts the daemon.

The skill's in-place path is `repair && _installation_is_healthy`, so it
prints "The in-place repair did not leave a working venv", followed by the
3-step list that ends in `install --force`. That steers users toward exactly
the escalation this plan exists to remove.

**Evidence** (`review456_uv_home_probe.py`, the sandbox with the stub uv moved to `$HOME/.local/bin`):
```
wrapper repair rc: 1
venv resolves now: True
uv calls         : 1
  | ERROR: 'uv' not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh
  | ✓ venv bootstrap SUCCEEDED: .../venv-...-py311-81c29529/bin/python resolves for this path. The next hook starts the daemon.
```

**Why it matters:** uv's own installer puts uv in `~/.local/bin` and only
edits the shell rc files. So a non-login or tool shell in a container, which
is the #53 environment, is precisely where uv is off PATH. The gate code was
written to accept that case. The Python half of `repair` was not.

**Suggested fix:** Give the Python repair the same uv search the gate uses:
`shutil.which("uv", path=<PATH plus ~/.local/bin>)`, spawning the resolved
absolute path. Alternatively, prepend `$HOME/.local/bin` in the wrapper's
`repair` arm before it continues. Add a wrapper test with uv only under
`$HOME/.local/bin`, asserting rc 0 and no "install uv" text.

## Important Issues (non-blocking; each is to be filed as a plan task)

### I1. A hung detached build wedges the client with no bound and no pid (confidence 85%)

**Location:** `scripts/venv_bootstrap.sh:295-307` (spawn), `init.sh:205-219`
(the started/running text), `scripts/install/venv.sh:600-615` (repair waits
120s).

**Problem:** The build child has no `timeout`. Under the flock backend, a uv
that hangs (on a uv cache lock, or a stalled mount) holds the lock
indefinitely. Every hook says "nothing to do but wait", and `repair` gives up
after 120s with a generic message. Under flock, the child's pid is recorded
nowhere, and the log's first line has no pid either, so the user cannot even
find the process to kill.

**Fix:**
- Run the child under `timeout "${HOOKS_DAEMON_VENV_BUILD_TIMEOUT:-900}"`, and write a marker on expiry.
- Put the child pid in `.venv-bootstrap.current` and the log header.
- Have the `running` message show how long the build has been running, and its pid.
- Test: a stub uv that sleeps past a short timeout ends in `failed`, and a later hook reports it.

### I2. mkdir backend (no flock, e.g. stock macOS): a build longer than 600s gets a second, concurrent build, and the first one's exit deletes the second one's lock (confidence 75%)

**Location:**
- `scripts/install/venv.sh:423-427` (stale reclaim `rm -rf "$lock_dir"`).
- `scripts/install/venv.sh:495-501` (`venv_lock_is_held` treats stale as free).
- `scripts/install/venv.sh:643-650` (`release_venv_lock` does `rm -rf` without checking the pid).
- `scripts/venv_bootstrap.sh:320-325`.

**Problem:** The staleness rule is mtime-only, and it predates this branch.
Before, only daemon starts, repair and install reached it. Now every hook
does, so the first hook after 600s reclaims the lock from a live build. That
second build's `_ensure_venv_build` then runs `rm -rf` on the venv the first
build is still writing. When the first child exits, it removes the second
build's lock dir, which admits a third builder.

**Fix:**
- In mkdir mode, refresh the lock dir's mtime from the child (for example, `touch` it every 60s).
- Or treat the lock as stale only when the recorded pid is dead (`kill -0`).
- Make `release_venv_lock` remove the dir only if its `pid` file is still this process's.
- Test: run under `HOOKS_DAEMON_VENV_LOCK_BACKEND=mkdir` with a short `HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS`.

### I3. A `--force` interrupted by SIGKILL strands every venv in an unignored `.claude/.hooks-daemon-venvs.XXXXXX`, and nothing ever restores it (confidence 80%)

**Location:** `.claude/skills/hooks-daemon/scripts/install.sh:78-121,299-303` (and the template).

**Problem:** The restore runs from the EXIT trap. I measured when that trap
runs: it does run on TERM and HUP, but not on KILL. Claude Code's Bash tool
kills commands on timeout, and a forced re-clone plus `uv sync` can exceed
the default 120s. The venvs are then left in a directory that `.gitignore`
does not cover (only `.claude/hooks-daemon/` is ignored), so a `git add -A`
would commit them. A later run neither looks for them nor restores them, and
the environment that owned them simply rebuilds.

**Fix:**
- At the start of `install.sh`, detect `.claude/.hooks-daemon-venvs.*`, restore it (or name it), and refuse `--force` until it is resolved.
- Or keep the aside-dir under a gitignored name, and add it to `scripts/install/gitignore.sh`.
- Test: create a leftover aside-dir, run the skill, and assert it is restored.

### I4. Hooks now take the build lock on their own, so `repair`, the skill's in-place repair and upgrade can hit the 120s lock wait behind a hook-started build (confidence 70%)

**Location:** `scripts/venv_bootstrap.sh:358`, `scripts/install/venv.sh:589-615`,
`scripts/upgrade_version.sh:347,920`, skill `install.sh:254`.

**Problem:** In the #53 state, the PreToolUse hook for the very Bash call
that runs `/hooks-daemon install` or `upgrade` starts a detached build. That
build holds the lock while the skill's `repair` (or the upgrade's
`ensure_venv`) queues behind it for at most 120s. If a copy-mode sync on a
bind mount takes longer, the waiter fails with "gave up waiting for the venv
lock". The skill then reports a failed repair. It does not say that a build
it could have waited for is still running.

**Fix:**
- When the lock is held by a bootstrap child (`.venv-bootstrap.current` is present), have `_vb_repair` wait on it without the 120s cap, or with the I1 bound.
- Or print the log path and the "build in progress, retry when it finishes" state instead of a failure.

### I5. The report's diagnosis of the 14 acceptance-probe failures is wrong. The conclusion "not caused by this branch" holds, but the stated cause and the proposed ledger niggle are false (confidence 95%)

**Evidence** (`probe_path_ab.py`, re-run with more roots):
```
/workspace/untracked/worktrees/worktree-issue-53-venv -> False
/workspace/untracked/worktrees/worktree-issue-55-signal -> True
/workspace -> True
/tmp/untracked/worktrees/x -> True
/tmp/foo-venv -> False      /tmp/myvenv -> False      /tmp/a-venv-b -> True
```

Another checkout under `untracked/worktrees/` passes. What trips the probes is
this worktree's NAME: `worktree-issue-53-venv/` contains the substring
`venv/`. The handlers skip files by raw substring, with `skip_dir in
file_path`:

- `handlers/pre_tool_use/qa_suppression.py:162`
- `comment_changelog.py:316`
- `comment_size.py:280`

The patterns they test against come from `strategies/qa_suppression/python_strategy.py:23-24`
and `strategies/comments/common.py:10-19`: `venv/`, `build/`, `dist/`,
`vendor/`, `migrations/`.

So the evidence does hold for "predates the branch and is location-dependent":
the merge base fails identically, and `main` at `/workspace` passes. But the
report's claim that the suite "cannot be fully green from any
`untracked/worktrees/` checkout" is false. It must not go into the niggles
ledger as written.

The real, pre-existing defect is a guard false-negative. Any file whose
absolute path contains one of those substrings is silently exempt from
QaSuppression, CommentChangelog and CommentSize. Examples: a project under
`~/myvenv/`, `/srv/rebuild/`, or `/opt/predist/`.

**Fix (separate plan):** match whole path components relative to the
project root (for example, `Path(rel).parts`), not substrings of the absolute
path. Add tests for `/tmp/myvenv/proj/x.py`, which must still be linted, and
`proj/venv/x.py`, which must be skipped. Also correct the report and the
journal entry at 11:04.

### I6. The marker check runs before the lock is taken, so a failure can be retried once by a hook that raced it (confidence 70%)

**Location:** `scripts/venv_bootstrap.sh:270-290`.

**Problem:** Hook A reads the marker, and at that moment the marker is
absent. Build C1 then fails, writes the marker and releases the lock. A's
`try_acquire` then succeeds, A deletes the fresh marker ("a marker still
here recorded different inputs", but it did not), and A starts a retry. This
is bounded to one extra build per race, but it breaks the stated "no retry
until inputs change" contract.

**Fix:** re-read the marker after `try_acquire_venv_lock` succeeds, and
delete it only if its `inputs` differ.

## Suggestions (non-blocking; each is still filed)

- **S1.** `scripts/venv_bootstrap.sh:229`, `init.sh:220-228`, and
  `SELF_INSTALL.md:72` say that a failed build is retried once "uv changes".
  The signature, however, hashes only uv's PATH location
  (`paths.py:823-824`), so a `uv self update` in place does not count. Either
  say "the uv on PATH moves", or hash `uv --version`.
- **S2.** `TestVenvFreeVerbsAreOneDispatch`
  (`tests/integration/test_bin_hooks_daemon_repair_without_venv.py:136-160`)
  and `test_guard_never_escalates_to_force_on_a_broken_install` are regex
  checks on the shape of the source. They pin how the code is laid out, not
  what it does, so a harmless refactor breaks them while a behavioural
  regression that keeps the text would pass. When `signal` lands, replace
  them with a behavioural test: an unknown verb with no venv exits 5, and
  each dispatched verb runs.
- **S3.** `bin/hooks-daemon:129`: the intercept looks only at `$1`, so
  `hooks-daemon --project-root X repair` is refused with exit 5, and that
  message tells the user to run `repair`. Also, `repair --help` with no venv
  builds a venv before it prints any help. Either scan for the first
  non-option word, or document that `repair` must come first.
- **S4.** `bin/hooks-daemon:111,131`: when `scripts/venv_bootstrap.sh` is
  absent (a damaged clone), `repair` falls through to the exit-5 message,
  whose advice is to run `repair`, which is circular. Name the missing
  driver instead.
- **S5.** `scripts/install/venv.sh:550-578`: `adopt_venv_lock` accepts any
  existing directory from `HOOKS_DAEMON_VENV_LOCK_INHERITED=mkdir:<dir>`,
  and `release_venv_lock` later runs `rm -rf` on it. The variable is also
  exported to every descendant of the build child. Check that `<dir>` equals
  `<daemon_dir>/untracked/.venv-bootstrap.lock.d` before adopting it.
- **S6.** In the `failed` and `refused` states, every hook pays for a full
  interpreter discovery and a Python start (`_vb_gate`) before it reaches
  the marker check. Measure this. If it matters, cache the last gate result
  keyed on the mtimes of pyproject.toml, uv.lock and untracked/.
- **S7.** The version.py parse is duplicated three times:
  `venv_bootstrap.sh:174-183`, the skill `install.sh:191-200`, and
  `init.sh`'s `_clone_version`. Partly this is forced, because the skill
  runs standalone. The duplicate that could be removed is the driver's copy
  (it could source a shared helper from the clone), so the three regexes
  cannot drift apart.

## Answers to the lead's questions

1. **Healthy-path cost.** None. `_venv_self_heal` runs only in the
   VENV_MISSING branch, when a version reads (`init.sh:1403-1408`).
   `TestTheHealthyPathIsUntouched` pins this.
2. **Detached build.**
   - One builder at a time: yes. The hook does try-acquire, handoff, then
     forget, and the concurrent test runs 6 hooks and gets 1 build.
   - Truly detached: yes. `setsid`, or `nohup` where setsid is missing;
     stdin, stdout and stderr are all redirected; the only inherited
     descriptor is the lock fd. On macOS (nohup) the child stays in the
     hook's process group, which is harmless because the hook returns in
     about 0.3s.
   - A hang: I1, and I2 for the mkdir backend.
   - The marker: it is cleared on success, on `repair`, and when the inputs
     change. It wedges permanently only under B1. It is respawned once only
     under the I6 race.
3. **Deletion safety.** Every `rm`, `rm -rf` and `mv` I found uses an
   absolute, non-empty path. The driver canonicalises its daemon_dir with
   `cd && pwd`, and `venv_path` always has a fingerprint suffix. `rmdir`
   (never `rm -rf`) guards the aside-dir. The risks that remain are I2, I3
   and S5. The `rm -rf "$DAEMON_DIR"` when only the runtime shell remains
   (skill `install.sh:244-248`) is gated on a check that the directory holds
   only `untracked/` and no `venv*`. That is correct.
4. **Intercept.** The wrapper and its template are byte-identical. The
   quoting is sound. The healthy path is unchanged, because the intercept is
   reached only after resolution fails. The dispatch is a clean extension
   point for an `exec`-shaped `signal` arm. For argument handling, see S3
   and S4.
5. **The gate.**
   - It runs `paths.py` by file path under the discovered interpreter,
     stdlib only. `daemon/` holds no module that shadows a stdlib name.
   - Every failed condition is named, each with its own fix.
   - No venv-missing message suggests install or `--force`.
   - B1 is the exception to "every remedy works": the remedy text names
     `repair` in a state where `repair` cannot build.
6. **Error hiding.** None was added. The only new `/dev/null` redirects
   discard stdout (the venv path, `command -v`) or detach stdio.
7. **Tests.** Most tests pin behaviour: the build driver runs for real
   against a stub uv, and filesystem snapshots are byte-compared. The gaps
   are:
   - no CI or opt-out coverage (B1);
   - no test with uv only in `~/.local/bin` (B2);
   - no hang or mkdir-staleness test (I1, I2);
   - source-shape tests (S2).

   Every ticked success criterion does have a test behind it.
8. **Docs.**
   - `SELF_INSTALL.md:67` and the TROUBLESHOOTING `disabled` row: see B1.
   - The "uv changes" wording: see S1.
   - install.md's "put back afterwards, even if the install fails" does not
     hold under SIGKILL: see I3.

**Probe-failure claim:** the conclusion that the failures predate the branch
is supported. The stated mechanism is refuted. See I5.

## Positive Observations

- Success is judged by the resolver, not by an exit code
  (`_vb_build_under_lock`). A stamp-only venv is counted as failed, and a
  test covers exactly that.
- The lock is handed off with no window: it is held through both fds until
  the parent forgets its copy. `try_acquire`/`adopt`/`forget` is a clean
  split of the old `acquire_venv_lock` loop.
- The refusals change nothing, and the tests prove it with filesystem
  snapshot equality.
- `cmd_repair` is now keyed on the daemon dir. This fixes a real
  client-mode bug in which it locked the wrong file, named a venv the
  resolver refused, and ran `uv sync` against the client's own project.
- The skill's "never auto-force" is enforced both statically and end to end.

## Verdict

[ ] APPROVE
[x] REQUEST CHANGES: fix B1 and B2, each with a regression test. File I1 to I6 and S1 to S7 as plan tasks.
[ ] REJECT
