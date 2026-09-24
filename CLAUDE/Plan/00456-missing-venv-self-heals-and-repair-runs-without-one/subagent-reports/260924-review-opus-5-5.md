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

---

## Addendum: re-review of the fixes (`9607ea07..303f75c4`)

Reviewer: Opus 5.5, read-only, with probes in tmp dirs only. Scope: commits
`271040e7`, `b868330e`, `696a6fdf` and `303f75c4`, which touch 24 files
(+1366/-148).

The branch's test files now pass: 154 passed and 1 skipped, in 69s. The
skip is the existing root-only chmod skip. The files run were the 9 from the
first review plus `tests/unit/daemon/test_bootstrap_decision.py`.

The deployed copies still match their templates byte for byte: the wrapper,
and the skill's `install.sh`.

New probes, kept in the worktree's `untracked/scratch/`:

- `review456_stranded_order_probe.py`: N1.
- `review456_term_probe.py`: N2.
- `review456_macos_like_probe.py`: runs with no `timeout`, `setsid` or `flock` on PATH.

**Verdict: APPROVE.** Both blocking findings are fixed and pinned by tests. No
new finding is blocking. The new findings below (N1 to N6) are non-blocking,
and each is to be filed as a plan task.

### Original findings: is each fix real?

| Finding | Verified how | Result |
| ------- | ------------ | ------ |
| B1 | Re-ran `review456_ci_probe.py` at HEAD. Under CI=true, both hooks report `disabled`, and `repair` exits 0 with one uv call. With the opt-out set, the hook reports `disabled`, `repair` exits 0 with one uv call, and no marker is left. Pinned by `TestSwitchedOffMeansSwitchedOff`, which includes a build child that is switched off and writes no marker, and by init.sh's `test_ci_true_is_named_never_reported_as_a_failed_build`. The CI and opt-out logic is now defined once, in `venv_bootstrap_switched_off_by`, and ensure_venv and the driver both use it. | Fixed |
| B2 | Re-ran `review456_uv_home_probe.py` at HEAD: `repair` exits 0 with "Venv repaired successfully". `find_uv()` looks in `~/.local/bin` first and then PATH, the same order `venv.sh` prepends in. The gate, the inputs signature and `cmd_repair` all use it. Pinned by `test_uv_only_in_uv_home_repairs_cleanly`, `TestFindUv` and `TestCmdRepairUsesTheBuildsUv`. | Fixed |
| I1 | Pinned by `test_a_build_past_its_bound_ends_failed_and_is_reported`: with a 2s bound and a 30s uv, the build ends failed, the log says "timed out", and it is not respawned. `test_running_names_the_live_build_pid_and_its_age` checks that the pid is alive with `os.kill(pid, 0)`. On Linux, `timeout` signals its whole process group, so uv dies along with the build. | Fixed with GNU `timeout`. See N2 for a TERM that is not the timeout, and N3 for macOS |
| I2 | The heartbeat touches the lock dir every 60s while its owner lives. Release now removes the lock dir only when its `pid` file matches this process. Pinned by `TestTheMkdirLockSurvivesALongBuild`: a build older than a 3s stale age is still reported running, and release leaves alone a lock owned by another pid. I checked the pid bookkeeping through the handoff: the parent writes `$$`, the child's adopt overwrites it with the child's `$$`, and the child's release compares against that, so they match. Inside `$(ensure_venv ...)`, the write and the compare both use the top-level `$$`, which is also consistent. | Fixed. See N3 for the macOS trade-off, and N6 for a cost |
| I3 | The aside dir now gets a `.gitignore` of `*`, and every run adopts stranded aside dirs and restores them from its EXIT trap. Pinned by `TestVenvsStrandedByAKilledForceAreRecovered`, whose fake installer really sends `kill -KILL $PPID`. | Fixed for the tested case. The fix introduced N1, and N4 and N5 are left open |
| I4 | `_venv_lock_wait_bound` stretches the wait to the recorded build's remaining time (bound plus the 30s KILL grace), and says so. Pinned by `test_repair_outwaits_the_generic_lock_bound`: with a 1s generic lock bound and a 4s build, `repair` succeeds with one uv call. | Fixed |
| I6 | The marker is now read after `try_acquire`, and the lock is released before reporting `failed`. Pinned by `test_a_marker_written_just_before_the_acquire_is_honoured`: a fake `flock` plants the marker at the moment of acquire. | Fixed |

The original fixes to the suggestions also hold up:

- **S1:** the uv identity is now its path, size and mtime.
- **S3:** `_subcommand_of` finds the verb past global options, and `repair --help` builds nothing.
- **S4:** a missing driver is now named.
- **S5:** the mkdir spec must equal this daemon's lock dir. The flock fd is checked against `/proc` where `/proc` exists, and skipped where it does not (macOS). The variable is unset after adoption.

### The declined suggestions

- **S2 (source-shape tests): sound to defer.** The test pins the extension
  point the lead asked for, and behavioural tests sit beside it. Plan 00457
  owns replacing it with per-arm behaviour tests. Carry it as a named task in
  00457.
- **S6 (cost of the gate): sound.** The measured median is about 0.1s per
  hook, and only while the daemon is down anyway. The evidence is
  `untracked/scratch/s6_measure.py`.
- **S7 (three version.py readers): sound.** The skill's `install.sh` runs
  standalone, and init.sh is a per-project copy. Moving the driver's reader
  into a clone library would still leave three regexes, so it would buy
  nothing.

### New findings introduced by the fixes (non-blocking, each to be filed)

#### N1. Recovering a stranded aside dir during a `--force` run keeps the OLD venv and deletes the NEWER one of the same name (confidence 95%)

**Location:** `.claude/skills/hooks-daemon/scripts/install.sh`, in
`_adopt_stranded_venvs` and in `_restore_venvs`'s loop over `KEPT_VENVS_DIRS`
(and the template).

**Problem:** Stranded dirs are appended to `KEPT_VENVS_DIRS` first, and this
run's own aside dir is appended after them. Restore walks the list in that
order. The failure sequence:

1. A `--force` run is KILLed, stranding the other view's venv in dir A.
2. The other view's hooks self-heal, which builds a NEWER venv with the same
   name.
3. The next `--force` run moves that newer venv into dir B.
4. Restore puts A's OLD copy back first. When it reaches B, it finds the
   name taken and deletes the NEWER copy, while printing "rebuilt for this
   environment and already in place". That message is false.

**Evidence** (`review456_stranded_order_probe.py`):

```
  |   restored: venv-home_dev_project_claude_hooks-daemon-py311-0badc0de
  |   venv-home_dev_project_claude_hooks-daemon-py311-0badc0de: rebuilt for this environment and already in place; the kept copy is discarded
surviving generation: OLD
```

**Impact:** A working venv is replaced by its pre-kill copy, which may be
stale. The lost copy is a rebuildable cache, not user data. But this breaks
the fix's own "the new one wins" rule.

**Fix:**
- Restore this run's own aside dir before any adopted stranded dir. Or, on a
  name collision, keep the copy with the newer `.daemon-metadata.json` or
  mtime.
- Make the message say which copy was kept and why.
- Test: a stranded dir plus a newer venv of the same name, then `--force`.
  The newer venv must survive.

#### N2. Any TERM is recorded as "timed out after 900s", and that blocks automatic retries (confidence 90%)

**Location:** `scripts/venv_bootstrap.sh`, in `_vb_build` (`trap _vb_build_timed_out TERM`) and in `_vb_build_timed_out`.

**Problem:** The trap assumes every TERM comes from `timeout`. But a host
shutdown or reboot, or a user running `kill <pid>` on the pid that the new
`running` message shows, also sends TERM. Each writes a failed marker with
unchanged inputs, and logs "the build timed out after 900s". After that,
hooks report "THE LAST AUTOMATIC BUILD FAILED" and never retry until someone
runs `repair`.

Bash also defers the trap until its current foreground command finishes. So
a TERM to the build process alone can let uv finish and the venv resolve,
and a false failure is still logged.

**Evidence** (`review456_term_probe.py`, TERM sent 1s into the build):

```
state after TERM : ['failed']
venv resolves    : True
log says         : ['✗ venv bootstrap FAILED: the build timed out after 900s (HOOKS_DAEMON_VENV_BUILD_TIMEOUT) and was stopped.']
```

**Fix:** In the trap, compare the time elapsed since the record's
`started=` with `bound`:

- If the bound has passed, it really is a timeout: write the marker, as now.
- If not, log "stopped by a signal", write no marker, and exit, so the next
  hook retries.

Also skip the marker if the venv already resolves.

Test: send TERM to the build pid inside its bound, and assert no marker and
a retry on the next hook.

#### N3. On stock macOS a hung build now holds the lock indefinitely, while the messages claim it is bounded (confidence 80%)

**Location:**
- `scripts/venv_bootstrap.sh`, `_vb_hook`: the no-`timeout` branch only warns, on the hook's stderr.
- `scripts/install/venv.sh`, `_venv_lock_start_heartbeat`.
- `init.sh`, the `running` remedy: "A background build is stopped and reported as failed if it outlives its bound".
- `docs/guides/TROUBLESHOOTING.md`, the first row: "stopped and reported failed".

**Problem:** Stock macOS has no `timeout`, no `setsid` and no `flock`, so it
uses the mkdir backend. The macOS-like probe shows that the start and
running paths work there. But the only bound a hung mkdir-lock build ever
had was the 600s staleness age, and the I2 heartbeat now keeps a live holder
fresh indefinitely. So on macOS a hung build wedges the lock until someone
kills it, and the hook message tells the user the opposite.

`SELF_INSTALL.md` does say the build is unbounded without `timeout`. The
message the user actually sees says otherwise. The pid is shown, which does
give the user a recovery path.

**Fix:** Add a bash-native watchdog for when `timeout` is absent. For
example, a background `sleep "$bound"; kill -TERM <child>`, followed by
`kill -KILL` after the grace period, with the watchdog itself detached from
the hook's streams. Or add `unbounded=1` to the record, and word the
`running` message and the TROUBLESHOOTING row conditionally. Test: remove
`timeout` from the tool dir, run a sleeping uv past a short bound, and
assert `failed`.

#### N4. Adopting an aside dir does not check that it is really stranded (confidence 60%)

**Location:** skill `install.sh`, `_adopt_stranded_venvs`.

**Problem:** Any `.hooks-daemon-venvs.*` dir is treated as stranded. If two
skill runs overlap (say, from the host and from the container), the second
run adopts the first run's live aside dir. It restores those venvs when it
exits, which can land them in a daemon dir that the first run's installer
is about to `rm -rf`. The window is short, but the loss is exactly the one
this plan prevents.

**Fix:** Write the owning pid and a hostname into the aside dir, and adopt
it only when that holder is gone. Or take a skill-level lock around the
keep, install and restore sequence.

#### N5. An adopted stranded dir is restored even when this run fails before installing (confidence 70%)

**Location:** skill `install.sh`, `_restore_venvs` runs `mkdir -p "$DAEMON_DIR/untracked"`.

**Problem:** If the killed run had already removed the daemon dir, and the
next plain run then fails early (for example, the network fetch fails), the
restore creates a daemon dir that holds only venvs. From then on:

- the root installer refuses with "already installed";
- the skill reports "not a complete clone";
- only an explicit `--force` recovers.

**Fix:** When `$DAEMON_DIR` has no clone, leave adopted stranded dirs in
place rather than restoring them into a new, empty daemon dir.

#### N6. In the `failed` state under the mkdir backend, every hook starts and kills a heartbeat, which leaves a `sleep 60` behind (confidence 70%)

**Location:** `scripts/install/venv.sh`, `_venv_lock_try_once` starts
`_venv_lock_start_heartbeat`, and `_venv_lock_stop_heartbeat` kills only
the subshell.

**Problem:** The I6 fix takes the lock on every `failed` hook. Under the
mkdir backend, each of those spawns a heartbeat subshell. Killing that
subshell orphans its `sleep`, which lives on for up to the interval. The
hook's own streams are not held, but a busy session accumulates up to one
stray `sleep` per hook per minute.

**Fix:** Start the heartbeat only when the lock is kept past the call:
after a successful adopt, or in `acquire_venv_lock`, not in the
`_vb_hook` try-then-release path. Or kill the heartbeat's whole process
group.

### Things I checked that hold up

- **A lock deleted by the wrong holder:** release now checks the pid. The
  handoff, the adopt and the command-substitution callers all keep `$$`
  consistent, so no holder removes another's lock.
- **The TERM trap:** it releases correctly, through the EXIT trap after
  `exit 124`. What it gets wrong is the reason it records (N2).
- **`/proc` absent:** the check is guarded by `[ -e /proc/$$/fd/$fd ]`.
  The macOS path uses the mkdir backend, which never needs `/proc`.
- **`timeout` absent:** the build still starts, completes and resolves, the
  lock is cleaned up, and the pid is shown (macOS-like probe). The gap that
  remains is N3.
- **`setsid` plus `timeout`:** `setsid` execs `timeout`, which runs the
  build in its own process group. The heartbeat and uv are both in that
  group, so the KILL grace ends every one of them.

---

## Addendum 2: final pass on the N1-N6 fixes (`c9a55fa0`, with the report in `cb95eaea` and `25715f99`)

Reviewer: Opus 5.5, read-only, with probes in tmp dirs only.

**HEAD moved during this pass.** Merge `17024e79` brought `main` in,
including Plan 00458. I checked that the merge changed none of the 00456
files:

- init.sh
- the wrapper and its template
- `scripts/venv_bootstrap.sh` and `scripts/install/venv.sh`
- the skill's `install.sh` and its template
- `cli.py` and `paths.py`

I reviewed `c9a55fa0`, and ran the tests and probes at `17024e79`. The four
changed integration test files pass: 84 passed in 100s.

A side effect of that merge: the I5 path probe (`probe_path_ab.py`) now
returns True both for this worktree and for `/tmp/myvenv`. Plan 00458 fixed
the substring skip, so the 14 acceptance probes should now pass from this
worktree too.

**Verdict: APPROVE.** N1 to N6 are fixed. One new non-blocking finding (N7)
and two residual notes (N8, N9) are below, and each is to be filed.

### The probes re-run at HEAD

| Probe | Result at HEAD |
| ----- | -------------- |
| `review456_stranded_order_probe.py` (N1) | The NEWER self-healed venv survives. The stranded dir, created only seconds earlier, is left alone as possibly live, because it is within 2 heartbeats. A later run adopts it, and its copy gives way to the newer one. Fixed. |
| `review456_term_probe.py` (N2) | A TERM 1s into the build records no failure. The next hook reports `started` (a retry), and the log has no false "timed out". Fixed. |
| `review456_macos_like_probe.py` (N3) | With no `timeout`, `setsid` or `flock`, the build starts, finishes and resolves, and the lock dir is released. The "unbounded" warning is gone. |
| new `review456_macos_bound_probe.py` (N3) | The same tool set, with a 30s uv under a 2s bound: the lock is released after 2.2s, the state is `failed`, the log says "timed out", and there is no job-control noise ("Terminated", "Killed", "Stopped") in the log. The bound now holds without a `timeout` binary. |
| `review456_ci_probe.py`, `review456_uv_home_probe.py` (B1, B2) | Still fixed. |

### N3's process control: what I hunted for, and what I found

- **Does the build get its own process group?** Yes, under both `setsid`
  and `nohup`. `set -m` gives each `&` job its own pgid, whatever group the
  child itself is in. I confirmed empirically that the parent's TERM trap
  and EXIT trap are not active in the job. A group TERM kills the job with
  status 143, and the job never runs the parent's EXIT trap, so the lock is
  never released twice.
- **SIGTTOU, SIGTTIN, and job-control messages.** The child's stdin is
  `/dev/null`, and its stdout and stderr go to the log. So bash's job
  control has no terminal to touch, even when `nohup` leaves the child in a
  session that has a terminal. The bound probe found no job-control notices
  in the log.
- **Does the watchdog outlive a normal build?** No. After a normal build,
  no process carrying the daemon dir in its argv is left (checked through
  `/proc`). The EXIT trap TERMs the watchdog's whole group, which takes its
  `sleep` with it.
- **The build finishing just as the watchdog fires.** Benign.
  - Until the parent's `wait` reaps the job, a signal to its pgid hits a
    zombie and does nothing.
  - The parent's EXIT trap kills the watchdog before anything else.
  - If the job ignores TERM, the watchdog's KILL after the grace period
    releases the parent's `wait`, so a stop is bounded too.
  - In `_vb_judge_stop`, elapsed is always at least the bound when the
    watchdog is what fired, because both are computed from the same
    `started` value, in whole seconds.

### N4's owner file across host and container: holds

A live owner on another host is never read as dead. The only ways it can be
adopted are:

- its owner file is gone, meaning it was released; or
- it has been silent for the lock's full stale age (600s), which its
  60-second heartbeat prevents.

For the same hostname with a different pid namespace, adoption additionally
requires two missed heartbeats (120s), and `kill -0` must fail with ESRCH.
An EPERM result, or a reused pid that is alive, counts as live, so both
fail safe. The residual edge cases are N8 and N9.

### N7. A watchdog outlives a KILLed build child and later signals a pgid that may have been reused (confidence 90%, non-blocking)

**Location:** `scripts/venv_bootstrap.sh`, `_vb_watchdog`.

**Problem:** The watchdog never checks whether its owner, the build child,
is still alive. Suppose the child is sent KILL: a `kill -9` of the pid that
the `running` message names, or the OOM killer. Then no EXIT trap runs,
and three things follow:

- the build job keeps running as an orphan in its own group;
- the watchdog keeps sleeping until the bound;
- the watchdog then sends TERM, and 30s later KILL, to the job's pgid.

With the default bound that is up to 930s after the pgid was freed. Linux
and macOS both reuse pids (macOS caps them near 99,999). So, rarely, this
could TERM and then KILL an unrelated process group belonging to the same
user.

**Evidence** (`review456_watchdog_orphan_probe.py`, bound 6s, uv 2s, the
child sent KILL at 0.7s): the build job finishes, and the venv resolves.
The watchdog, pgid 3013564, is still alive at 4s and at 8s, and at the
bound it signals the finished job's pgid 3013563: the log contains "reached
its ... bound".

**Fix:** Give the watchdog the heartbeat's owner check. Pass it the
child's `$$`, sleep in slices (for example, the heartbeat interval), and
exit as soon as `kill -0 <owner>` fails. Also check `kill -0 -<pgid>`
before each signal.

Test: send KILL to the child, and assert the watchdog is gone within one
slice. That is `build_procs()` in the probe returning `[]`.

### N8. Two runs can race to create and adopt an aside dir (confidence 60%, suggestion)

**Location:** the skill's `install.sh`: `_keep_venvs_aside` runs `mktemp -d`,
then writes `.gitignore`, then calls `_claim_aside`; and
`_aside_is_stranded`'s `[ -f owner ] || return 0`.

**Problem:** For a brief moment after `mktemp -d`, the new dir has no owner
file, and a dir without an owner file reads as "released". A second run
starting in that window adopts it, and the creator then moves its venvs in.
The second run restores those venvs when it exits, which could be while the
creator's installer is about to `rm -rf` the daemon dir. The window is a few
microseconds wide, but the loss would be exactly the one this plan exists
to prevent.

**Fix:** Write the owner file before the dir becomes visible under the
prefix. For example, `mktemp -d` under a non-matching name, claim it, then
`mv` it to the prefix name. Or treat a dir without an owner file that is
younger than one heartbeat as live.

### N9. Adoption and lock staleness both trust mtime across a VM boundary (confidence 50%, residual note)

**Problem:** On Docker Desktop, the host and container clocks can drift
apart, for example after the host sleeps. If the reader's clock runs more
than 600s ahead of the writer's, a live aside dir, or a live mkdir lock,
reads as stale. This is the same design choice the venv build lock already
made, and it is documented there.

**What to do:** Record it where the staleness rule is explained
(`SELF_INSTALL.md`), and consider having the heartbeat write the writer's
epoch into the owner file, so readers can compare clocks rather than trust
mtime.

### New probes (kept in the worktree's `untracked/scratch/`)

- `review456_macos_bound_probe.py`: shows the bound holds without `timeout`, `setsid` or `flock`.
- `review456_watchdog_orphan_probe.py`: N7.
