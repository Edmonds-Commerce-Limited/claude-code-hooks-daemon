# The CI failures, the skip count, and how the blocking set is declared

## Phase 1 measurements

### The skip count: 16 across four files, not 11 across three

Reproduced without stopping the live daemon, by running the suite in a
`git worktree` whose own `untracked/` holds no socket — the same condition a
runner is in, at no cost to the session:

| File                                | Daemon skips |
| ----------------------------------- | ------------ |
| `test_absolute_path_socket_deny.py` | 6            |
| `test_playbook_harness.py`          | **5**        |
| `test_stop_hook_hard_block.py`      | 3            |
| `test_tool_use_error_recovery.py`   | 2            |

`test_playbook_harness.py` post-dates this plan (Plan 00243), is IN Step 12.0's
blocking set, and RELEASING.md says of it: *"A skip here means no daemon was
running, which under H-1 is itself an abort condition."* It had been skipping in
CI, uncounted, ever since — the plan's own thesis reproducing itself while the
plan sat unstarted.

Also found, and NOT daemon-related: **11 further skips in
`test_transport_toggle_cycle.py`**, all "relay binary not built:
`untracked/bin/hooks-relay`". A second provisioning gap of the same shape, out
of scope here but recorded so the next count is not surprised by it.

### The blocking set is one command line

Declared as a single hardcoded `pytest` invocation inside a fenced bash block at
`RELEASING.md` Step 12.0, naming six files:

```
test_diagnostic_scripts.py  test_install_sh_end_to_end.py
test_tool_use_error_recovery.py  test_stop_hook_hard_block.py
test_skill_install_python_discovery.py  test_playbook_harness.py
```

It **can** be read mechanically — a stable single-line command whose
`tests/acceptance/*.py` arguments a parser can lift — so Phase 3's guard needs
no second copy, and must not make one.

### `test_absolute_path_socket_deny.py` is not in that set

Though it is 6 of the 16 skips. **Recommendation: add it**, on stronger grounds
than the count. Its docstring records that the playbook *structurally cannot*
reach this handler — Claude Code resolves `file_path` before dispatching
PreToolUse, so the two entries in `absolute_path.get_acceptance_tests()` are
marked `harness_cannot_produce`, and this file is "the live-socket gate" that
replaces them.

`test_playbook_harness.py` IS in the declared set. So the set contains the
harness *and* omits the one file covering what the harness admits it cannot
reach — a hole by construction, not oversight. Left as a recommendation rather
than applied: the set defines what a human release gates on.

### The expected counts were a stale second copy

`combined: 27 passed, 1 skipped` is really **31 passed, 0 skipped** measured
against a live daemon, and `test_diagnostic_scripts.py — 12 passed` has 15.
Removed from RELEASING.md, replaced with the properties that do not drift — *0
failed, 0 skipped*.

The `1 skipped` was the worst of them: it documented as normal exactly the
condition the gate exists to catch, twenty lines above RELEASING.md's own
statement that such a skip is an abort condition. It had been recorded from a
run that had no daemon.

## The three CI failures, and why only one was this plan's subject

This plan was written from "the first fully green CI run". That premise expired:
`Tests + coverage` has been RED on `main` for a long stretch — 9 failures per
interpreter across three files when found (while regression-testing Plan 00347),
down to 4 after Task 2.4a.

| File                                               | Why it failed on a runner                                                                                                | Resolution   |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------ |
| `tests/integration/test_deployed_skill_trees.py`   | Asked git about a **directory-only** ignore pattern (`/hooks-daemon/`) for a path absent on a runner                     | Fixed (2.4a) |
| `tests/integration/test_forwarder_socket_stdin.py` | Hardcoded `/workspace`, so the forwarders were never found                                                               | Fixed (2.4a) |
| `tests/integration/test_relay_guard_fail_open.py`  | Re-derived the hostname socket suffix without the `socket.gethostname()` rung, so it dialled a path nothing was bound to | Fixed (2.4b) |

## Only one of the three was really about the daemon

Two were plain defects that would fail on any machine without a deployed
install, and only *looked* like daemon fallout:

- **The directory-only ignore pattern.** A trailing slash in `.gitignore` makes
  a pattern match directories only, and `git check-ignore` will not match it
  against a path it cannot tell is a directory. So any checkout without a
  deployed install answers "not ignored" — the guard was testing the container,
  not the pattern. It now asks about a path *inside* the directory, which is
  existence-independent.
- **The hardcoded `/workspace`.** The forwarders are tracked and not ignored, so
  they exist in any checkout — just not at that path. Wrong independently of any
  daemon, and would still be wrong if CI provisioned one.

Only `test_forwarder_socket_stdin.py`'s *remaining* failure genuinely needs a
daemon, which Task 2.1 now provisions.

## Why the distinction is worth keeping

A failure is louder than a skip — but a run that is *always* red teaches readers
to skim it, which is how the `Format (black)` breakage in Plan 00346 stayed
hidden for hours inside the noise. Misfiling a defect as a provisioning gap
means waiting on provisioning to fix something provisioning will not fix.

Task 4.2 ("a green CI run") needs all three fixed, whatever happens to the
skips — **16** of them, per Task 1.1's measurement; the "11" this plan was
written with was already stale.

## Method worth keeping: reproduce the runner condition, don't read the log

Both separable defects were found by naming the single property of a runner that
differs from this container, and reproducing just that:

| Defect                   | Runner property                      | Local reproduction  |
| ------------------------ | ------------------------------------ | ------------------- |
| directory-only ignore    | no deployed `.claude/hooks-daemon/`  | `git worktree add`  |
| hostname suffix mismatch | `$HOSTNAME` set but **not exported** | `env -u HOSTNAME …` |

Seconds each, no CI round trip. Both beat waiting ~11 minutes for a shared
pipeline, and the second one disproved a hypothesis the plan had recorded as
needing a runner to confirm.
