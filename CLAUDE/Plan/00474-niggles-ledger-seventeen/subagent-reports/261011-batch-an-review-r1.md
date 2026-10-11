# Code Review r1: batch AN, N280 doc-write jail

Branch `worktree-batch-an-n280`, diff `main...worktree-batch-an-n280`, code commit `fd85826ff`,
report commit `3c81ba0b0`. Seven files, +845/-2.

## Verdict

**APPROVE.** Nothing blocks the merge. The non-blocking findings below each become plan tasks.

The jail is correct for the threat model, which is careless code pointed at the wrong
project. It refuses write-mode `open`, `os.rename` on either side, and `os.remove` on the two
docs of every checkout. Reads are never refused. A tmp project's `CLAUDE.md` is not affected,
because only the exact resolved paths `<checkout-root>/CLAUDE.md` and
`<checkout-root>/.claude/HOOKS-DAEMON.md` are protected. The conftest guard's own restore is
correctly wrapped in `allowed()`, and the protected names now have a single source, so the
DRY change is good.

Verified here: `tests/unit/test_doc_write_jail.py`, `test_tracked_doc_guard.py` and
`test_conftest_docs_guard_culprit.py` pass in the worktree (34 tests, 1.7 s). The diff
contains no `noqa`, `type: ignore` or pragma suppressions.

## Answers to the dispatch questions

- **False refusals for legitimate tests:** none for the normal case. A tmp project's
  `CLAUDE.md` is outside the protected set, and a symlink that is deleted acts on the link
  itself. The `rmtree` dir_fd case is resolved through `/proc/self/fd`. There is one narrow
  false refusal, shown in finding 1.
- **Performance:** I measured this in a 3.11 venv (probe below), each figure per operation:
  - read-mode open: +0.3 us (noise)
  - write-mode open: +38 us (51 -> 89 us)
  - every other audit event, e.g. `compile`: about +1.8 us, the cost of the Python hook call

  Write-opens are the only expensive path. Assuming a typical suite does a few hundred
  thousand file writes, that comes to tens of seconds of CPU over a run of about 40k tests.
  That is acceptable, and finding 3 can reduce it.
- **Is `git worktree list` cached?** It runs once per pytest process, at conftest import.
  QA shards are sibling processes, so each runs it once, which costs milliseconds. Child
  Pythons never run it, because they read `HOOKS_TEST_DOC_JAIL_PATHS` from the environment.
  No per-session cache is needed.
- **Cleanliness:** the code is clean, standard library only, with good docstrings. The tests
  check behaviour with a real child interpreter, a real `git worktree add`, and a real
  `cmd_regenerate_docs` run in a subprocess.
- **Docs:** no project doc describes the old guard either, so nothing is stale. The jail does
  silently change the environment every test child gets (`PYTHONPATH` and
  `sitecustomize`). See finding 4.

## Findings (all non-blocking)

### 1. A relative `os.open(..., dir_fd=...)` is falsely refused when the cwd is a checkout root (IMPORTANT, confidence 85)

`tests/jail_site/doc_write_jail.py:140-143` (`_audit`, the `open` branch). The `open` audit
event does not carry `dir_fd`, so a relative name is resolved against the cwd. pytest's
default cwd is the repository root. The probe
`untracked/scratch/batch-an-review/dirfd_probe.py` prints
`FALSE REFUSAL of an unrelated file: DocWriteRefused`.

The agent report lists this case under "Does not see", which describes it wrongly: it is a
false positive, not a gap. No current test hits it. It is rare (it needs a write-mode
`os.open` with `dir_fd`), and that rarity is the only reason this is non-blocking.

Remediation: for a relative path in the `open` branch, do not refuse. Instead, record an
"unverifiable" line that does not raise, or check only when the path is absolute or the cwd
is not a checkout root. Then correct the limits list in the module docstring and the report.
Pin the fix with a test that does a dir_fd write of `CLAUDE.md` into another directory while
the cwd holds a protected `CLAUDE.md`.

### 2. The module docstring's limits list is incomplete (SUGGESTION, confidence 80)

`tests/jail_site/doc_write_jail.py:18-20`. The docstring names only `-I`/`-S`, a cleared
environment, and non-Python processes. It leaves out three cases:

- `os.truncate(path)`, which the jail does not refuse. Confirmed by `perf_probe.py`: the
  protected file is emptied.
- The dir_fd case from finding 1.
- Any test that prepends its own `sitecustomize` directory to `PYTHONPATH`. That shadows the
  jail in the child. Five tests do this, not just the one the report names:
  `test_a_retried_hook_never_restarts_a_slow_start`,
  `test_start_waits_on_a_slowly_initialising_daemon`, and three in `tests/unit/daemon`.
  All of them use tmp projects, so this is harmless today.

Remediation: either list all three cases in the docstring, or add `os.truncate` to `_audit`
with a test. Adding `os.truncate` costs one branch.

### 3. Every write-open pays for a full `realpath` (SUGGESTION, confidence 70)

`doc_write_jail.py:74-77` and `_resolve`. Write-opens are about 75% slower when the jail is
armed. Remediation: return early when `os.path.basename(path)` is not `CLAUDE.md` or
`HOOKS-DAEMON.md` and `os.path.islink(path)` is false. This keeps the symlink-alias test
passing and replaces the realpath walk with one `lstat` for most writes. Re-run
`perf_probe.py` to confirm the gain.

### 4. The run-wide `PYTHONPATH` and `sitecustomize` injection is undocumented outside the module (SUGGESTION, confidence 70)

`tests/conftest.py`, `_arm_doc_write_jail`. Every child Python of the run now loads
`tests/jail_site/sitecustomize.py`. That shadows the system
`/usr/lib/python3.11/sitecustomize.py`, an apport hook, which is inert here. It also makes
a test author's own `sitecustomize` silently disable the jail.

Remediation: add a short paragraph to `CLAUDE/QA.md`, or wherever test-isolation rules
live, that names the two environment variables, explains the shadowing, and shows how a
test that needs its own `sitecustomize` can chain to the jail by importing `doc_write_jail`
and calling `install_from_environment()`.

### 5. A late refusal from a background child is blamed on the next test (SUGGESTION, confidence 70)

`tests/conftest.py`, `no_test_writes_a_generated_doc_of_any_checkout`. The log offset is
per test, but a daemon or child that outlives its test appends later, so the failure names
the wrong test. The log line carries the pid. Remediation: put the pid in the assertion
message together with a note that a pid not started by this test belongs to an earlier
test's leftover process.

### 6. `_record` swallows `OSError`, so the "record that cannot be swallowed" can be lost (SUGGESTION, confidence 70)

`doc_write_jail.py:89-91`. If the append fails, the refusal is still raised, but a writer
that catches it leaves a green test. Remediation: on `OSError`, also write the refusal line
to `sys.__stderr__` with `os.write(2, ...)`, so the attempt remains visible.

### 7. A file-existence test (SUGGESTION, confidence 75)

`tests/unit/test_doc_write_jail.py:327-328` (`test_the_site_directory_holds_a_sitecustomize`).
It checks only that a file exists, and both subprocess tests already cover it with real
behaviour. Remediation: delete it.

### 8. Commit hygiene (SUGGESTION, confidence 90)

`fd85826ff`'s message ends with `Addresses #0`, which refers to no issue, and it has no
Co-Authored-By trailer. Amend is blocked, and the report already flags this. Remediation:
mention it in the merge commit message so a reader of the history knows `#0` refers to
nothing.

## Positive observations

- The refusal log lives outside the exception path, so a writer that swallows the error
  still fails the test. The fixture-unwrap test proves this.
- The `rmtree` dir_fd false positive was found by running the jail against the suite, then
  fixed and pinned with two tests.
- Reads and appends go through `os` primitives, so a test that patches `open` cannot break
  the record.
- The report is honest that the root cause is still unknown, and its decoy-cwd experiment
  is a sound way to rule out the cwd candidate.

## Probe scripts (keep as evidence)

- `/workspace/untracked/scratch/batch-an-review/perf_probe.py <worktree>`: overhead numbers,
  the `open` event's argument shape, and `os.truncate` not being refused.
- `/workspace/untracked/scratch/batch-an-review/dirfd_probe.py <worktree>`: the false
  refusal in finding 1.
