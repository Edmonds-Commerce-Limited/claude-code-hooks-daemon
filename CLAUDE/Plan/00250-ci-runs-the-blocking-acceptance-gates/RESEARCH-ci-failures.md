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

## Task 2.4c: the forwarders bake the generating machine's path

`test_dogfooding_hook_scripts::test_hook_scripts_match_installer` fails on a
runner because 27 of the 31 tracked hook files carry a literal absolute path
(the four without it — `status-line`, `stop`, `subagent-stop`,
`worktree-create` — carry no relay guard at all):

```bash
_rl_dir="/workspace/untracked"
_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/workspace/untracked/bin/hooks-relay}"
```

A fresh generation anywhere else produces `/home/runner/work/...`, so every
script differs. It passes locally for exactly the reason it cannot pass
elsewhere.

**"Just derive it at runtime" is not available**, which is worth stating before
anyone proposes it. `render_relay_guard`'s docstring makes the baking
deliberate:

> Pure bash builtins only — zero subshells, zero external spawns — so the guard
> costs microseconds when the relay binary/socket are absent
>
> …baked in as a literal absolute path, never computed at hook-run time.

This runs on **every hook invocation**. Any fix must preserve zero-spawn.

| Option                                     | Zero-spawn?                    | Cost                                                                                                              |
| ------------------------------------------ | ------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `${BASH_SOURCE[0]%/*}/../../untracked`     | yes — pure parameter expansion | adds `..` segments to a socket path the same docstring already flags as at risk of the **AF_UNIX 108-byte limit** |
| `${CLAUDE_PROJECT_DIR}/untracked`          | yes                            | that variable is set by Claude Code and absent in CI and in tests — precisely the contexts this must work in      |
| normalise inside the dogfooding comparison | n/a                            | fixes CI, leaves the tracked artefact machine-specific — treats the symptom                                       |

**The prior question** is whether `.claude/hooks/*` should be tracked at all,
given they embed a path valid only on the machine that generated them. That is
the real decision and it is larger than this plan; the options above are only
worth weighing once it is answered.

## Task 2.4d: what the gate found once it could run

These are not fallout from provisioning the daemon. They are what the gate was
always going to report, and could not while it skipped. All three were found in
CI run 34189706909 — the first run in which `test_playbook_harness.py` executed.

### Absent tooling had been standing in for correct commands

`lint_on_edit` splits a command with `shlex` and runs it through
`subprocess.run` in **list form with no shell**. Two declared commands were
wrong in ways only a machine with the real tool installed can notice:

| Language | Declared command              | What a real tool does with it                                                                |
| -------- | ----------------------------- | -------------------------------------------------------------------------------------------- |
| Rust     | `clippy-driver {file}`        | `clippy-driver` is a rustc wrapper, so it defaults to a **binary** crate and rejects any     |
|          |                               | library-shaped file with `E0601: main function not found` — including the strategy's own     |
|          |                               | "valid code passes" probe, `pub fn hello() {}`                                               |
| Kotlin   | `kotlinc -script {file} 2>&1` | `-script` accepts a `.kts` script and this strategy is registered for `.kt` **only**, so the |
|          |                               | command rejects every file it is ever given; the `2>&1` was never a redirect, and reached    |
|          |                               | kotlinc as a literal argument                                                                |

Both were invisible here because this box has the rustup `clippy-driver` **shim**
(which reports "not installed", a case the strategy already special-cases into an
ALLOW) and no `kotlinc` at all. A GitHub runner has both tools for real.

**Reproduced locally without installing anything**, since `clippy-driver` is a
rustc wrapper and shares its CLI:

```
$ rustc untracked/scratch/rustprobe/valid.rs -o /tmp/out
error[E0601]: `main` function not found in crate `valid`
```

Fixed by giving the extended command the same crate framing the default already
carried, and by replacing the Kotlin command with one that compiles a `.kt` file
to a scratch output directory.

There is no `kotlinc` and no JVM on this machine — which is the whole reason the
defect survived — so the Kotlin command is verified against Kotlin's own
[compiler reference](https://kotlinlang.org/docs/compiler-reference.html) rather
than by execution:

| Token     | Documented as                                                                              |
| --------- | ------------------------------------------------------------------------------------------ |
| `-script` | *"executes the first Kotlin script (`*.kts`) file among the given arguments"* — the defect |
| `-d path` | *"Place the generated class files into the specified location."*                           |
| `-nowarn` | *"Suppress all warnings during compilation."*                                              |

So the bug and the fix are both documented facts. What execution would still add
is whether kotlinc's JVM startup fits the handler's 15s `LINT_CHECK` budget on a
cold runner; if it does not, `lint_on_edit` fail-opens (an ALLOW) and probe #142
— "Kotlin lint - invalid code blocked" — will report as the one failure. The
remedy for that is already built: `options.timeouts.Kotlin` (Plan 00309).

Guarded as a class rather than per-language, in
`tests/unit/strategies/lint/test_lint_commands_are_runnable_as_declared.py`: no
declared lint command may contain a shell metacharacter, since none is run
through a shell. Kotlin was the only offender of 18 commands.

### The harness could not observe the handler's fail-open

The probe dispatch used `Timeout.DAEMON_RESTART_VERIFY_TIMEOUT_SEC` — 15s, a
constant named for restart verification — while `lint_on_edit` allows a single
lint `LINT_CHECK` = 15s and `validate_eslint_on_write` allows `ESLINT_CHECK` =
30s. The two budgets were **equal by accident**, with these consequences:

- `lint_on_edit` catches `TimeoutExpired` and ALLOWs, but only *after* its 15s
  elapse — by which point the harness has already killed the hook. The fail-open
  was unreachable from the harness.
- `TimeoutExpired` propagates out of `_run_probe`, so one slow lint ends the
  whole gate: 201 probes report as a crash rather than one failure. That is why
  Python 3.12 and 3.13 reported only a timeout while 3.11 got far enough to name
  the two Rust/Kotlin mismatches.

`PROBE_DISPATCH_TIMEOUT_SECONDS` now lives beside the harness logic and is
**derived** (`2 * max(LINT_CHECK, ESLINT_CHECK)`), so raising a lint budget
cannot silently restore the collision — the failure the pinned constant allowed.

### A guard that asked what was installed rather than what was written

`test_acceptance_tool_payload_agrees_with_prose.py` classified a Bash payload as
prose when `shutil.which(head)` found nothing. `rg` and `agent-browser` are real
commands this project's probes use and a runner does not carry, so the guard
failed there for a reason having nothing to do with the playbook.

The classifier now also accepts a lowercase command-name **shape**, which is
machine-independent. Every prose opener it was written to catch (`With`,
`Simulate`, `Run any`, `Stage`, `WebFetch` — Plan 00345's eight real ones) is
capitalised, so all of them stay rejected; each is pinned in a test that stubs
`shutil.which` to return nothing, so the guard is now exercised in the runner's
condition rather than only in this container's.

## Task 2.4c, measured: the machine-specific surface is two lines

The three options above were recorded before anyone counted. Counted, the
picture changes enough to add a fourth that is better than all of them.

Across the 31 tracked hook files — 1342 lines in total — **54 lines contain the
generating machine's root, and they are only 2 distinct lines** (27 files × 2;
the other 4 files carry no relay guard):

```bash
_rl_dir="/workspace/untracked"
_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/workspace/untracked/bin/hooks-relay}"
```

Everything else is byte-identical template. So the comparison in
`test_hook_scripts_match_installer` is failing on 4% of its lines, and on a
property nobody wants asserted.

### What the test actually wants to prove

Its own docstring names three purposes — the installer creates correct scripts,
no manual edit has drifted from the installer, and script updates reach the
installer code. **The absolute project root is an INPUT to the generator, not
part of the template any of those three is about.** Comparing it byte-for-byte
additionally asserts "this checkout sits at the same absolute path as the
machine that generated the committed file", which is not a property worth
having and is false on every machine but one.

### The fourth option, and why it is not "treating the symptom"

Normalise the project root on BOTH sides, then compare **exactly**. That was
dismissed earlier as symptom-treatment; the count is what changes the verdict:

- The normalisation is a **closed, two-line surface**, not a fuzzy match. Every
  other byte is still compared exactly, so a drifted template still fails.
- It needs no change to `render_relay_guard`, so the zero-spawn hot path and the
  AF_UNIX 108-byte headroom are both untouched — the constraint that ruled out
  the two runtime-derivation options.
- It leaves the prior question (should `.claude/hooks/*` be tracked at all?) open
  rather than pre-empting it, because it does not change what is tracked.

**Pair it with a second guard**, or the normalisation becomes a blind spot: after
substituting the project root, assert that NO other absolute path from the
generating machine survives. That turns the measurement above into a standing
invariant instead of a one-off observation — if a third machine-specific line
ever appears, it fails loudly rather than being silently normalised away.

### A smaller defect, worth fixing in the same pass

The mismatch report names the file and then says only *"Installed version
differs from installer output"*. No diff, no line number. A dogfooding failure
that cannot be diagnosed from its own message is one more reason to regenerate
blindly rather than investigate — which is precisely the drift the test exists
to prevent.
