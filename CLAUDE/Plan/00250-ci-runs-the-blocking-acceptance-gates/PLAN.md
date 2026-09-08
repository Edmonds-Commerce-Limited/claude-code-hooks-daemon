# Plan 00250: CI must actually run the acceptance gates it calls blocking

**Status**: In Progress
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The first fully green CI run (`4d1a553b1`, run 32033242091) was also the first
run whose skips were named, because Plan 00245 had just added `-rs` to the CI
pytest step. It named 11 skipped tests nobody knew were skipping:

| File                                                 | Skips | Reason given                                                 |
| ---------------------------------------------------- | ----- | ------------------------------------------------------------ |
| `tests/acceptance/test_absolute_path_socket_deny.py` | 6     | "Daemon not running — no live socket found under untracked/" |
| `tests/acceptance/test_stop_hook_hard_block.py`      | 3     | "Daemon not running"                                         |
| `tests/acceptance/test_tool_use_error_recovery.py`   | 2     | "Daemon not running — no live socket found under untracked/" |

All three files need a live daemon socket and skip cleanly without one. CI never
starts a daemon in the QA job, so all 11 have skipped on every run since they
were written.

**That count is now 16 across FOUR files** — Task 1.1 measured it directly, and
`test_playbook_harness.py` (5 skips, added later by Plan 00243) joined the set
without anyone noticing. The table above is left as the plan found it, because
the growth is the point: a class of invisible skip does not stay the size you
first counted.

`CLAUDE/development/RELEASING.md` Step 12.0 names ~~all three~~ **two** of the
three as BLOCKING acceptance gates — `test_stop_hook_hard_block.py` and
`test_tool_use_error_recovery.py`. **`test_absolute_path_socket_deny.py`, which
accounts for 6 of the 11 skips, is not mentioned in that file at all.** It is
therefore not covered by Phase 3's "a skip of a declared-blocking gate fails the
run" guard, and Phase 1 has to settle whether it belongs in the blocking set or
is genuinely optional — a guard keyed on a declaration cannot protect a file the
declaration omits.

About one of the two it does name, Step 12.0 says explicitly:

> The test skips cleanly when no daemon is running locally; under H-1 the daemon
> is always started before this step, **so a skip there is itself an abort
> condition.**

CI does not know that. It reports the run green.

## This is a blind guard, not a missing feature

The tests exist, they are correct, and they are wired into the workflow. What is
missing is any mechanism by which their absence is noticed — the exact shape of
`CLAUDE.md` Core Standard 15 (DBF), and the second instance of it inside Plan
00245 alone. That plan's Decision 3 already settled the general question for the
`uv` case: **prefer providing the dependency in CI to skipping**. This applies
the same decision to the daemon.

~~The `Daemon load` job in the same workflow starts a daemon successfully on the
runner, so this is a provisioning gap rather than a platform limitation.~~

**That sentence is false, and Task 2.1 was written on it.** The `daemon-load`
job checks out, installs from the lockfile, and imports every handler module.
It starts no daemon, and says why in its own comment: *"A real `hooks-daemon restart` needs an installed daemon, so asserting every handler module imports
is the CI-safe equivalent."* Nothing in this workflow has ever installed or
started one.

The conclusion survives — it IS a provisioning gap — but the cheap route to it
does not. There is nothing to reuse, so Phase 2 has to decide what a CI install
looks like rather than copy a step.

**The answer turned out to be that there is no install** — see
[RESEARCH-ci-install.md](RESEARCH-ci-install.md). A checkout already has the
config, the forwarders and the package; the only missing piece is the gitignored
`.claude/hooks-daemon.env`, which the repo guard accepts on mere existence. CI
writes that and starts the daemon, touching no tracked file.

Running the installer was tried first and the runner rejected it. Both
`create_settings_json` and `create_daemon_config` **rename** an existing file to
`.bak` and write a default template over it — `force` only decides whether the
backup happens — so every invocation replaces this project's 1188-line handler
config. The daemon then refused to start at all, because that template is
invalid against the current schema, and the run went from 4 failures per
interpreter to 31 failures plus 7 errors.

## The same gap has a louder sibling, and CI is no longer green

**This plan was written from "the first fully green CI run". That premise has
expired.** `Tests + coverage` is RED on `main` and has been for a long stretch.
It was 9 failures per interpreter across three files when found (while
regression-testing Plan 00347), and is **4** after Task 2.4a:

All three are now fixed — see
[RESEARCH-ci-failures.md](RESEARCH-ci-failures.md) for what each one was.

Two of the three turned out NOT to be this plan's subject at all: they were
plain defects that would fail on any machine without a deployed install, and
only *looked* like daemon fallout. Both were found by reproducing the runner
condition locally rather than reading a CI log — a `git worktree` for the
missing install, `env -u HOSTNAME` for the unexported shell variable — seconds
each, no round trip. Only `test_forwarder_socket_stdin.py`'s remaining failure
genuinely needs a daemon, which Task 2.1 provisions.

**Consequence for this plan**: Task 4.2 ("a green CI run") needs all three
fixed, whatever happens to the skips — **16** of them, per Task 1.1's
measurement; the "11" this plan was written with was already stale.

## Goals

- The three socket-dependent acceptance files EXECUTE in CI rather than skip.
- A skip of a gate that `RELEASING.md` declares blocking fails the run, so this
  class cannot go unnoticed again — for these three files or the next one.
- The declaration lives in ONE place, so a file added to the blocking set in
  `RELEASING.md` does not silently stay unguarded.

## Non-Goals

- Making every acceptance test run in CI. Some are genuinely
  `harness_cannot_produce` (Plan 00196 documented `test_absolute_path_socket_deny`
  that way for the *playbook*; that is about rendering, not about whether the
  pytest file can run against a socket).
- Reworking the acceptance playbook harness — that is Plan 00243's scope, and it
  refines skip RENDERING rather than skip VISIBILITY.
- Changing what the tests assert.

## Context & Background

Confirmed by the dedupe scout across all 36 live plans: no live plan covers
this. Plan 00245 (skip visibility via `-rs`, and `if: !cancelled()` so one
failing step stops hiding later ones) and Plan 00243 (playbook skip-rendering)
are both strict subsets — neither starts a daemon in CI, and neither makes a
silent skip of a declared-blocking gate fail anything.

Plan 00245 is what FOUND this, and deliberately did not absorb it: that plan's
goal was a green CI, and it is met. Widening it to also provision a daemon would
have reopened a plan whose success criteria were satisfied.

## Tasks

### Phase 1: Establish the gap as a test, not a claim

- [x] ✅ **Task 1.1**: Observed, and **the count in this plan's overview is
  wrong**. Reproduced without stopping the live daemon by running the suite in
  a `git worktree`, whose own `untracked/` holds no socket — the same condition
  a runner is in, at no cost to the session:

  | File                                | Daemon skips |
  | ----------------------------------- | ------------ |
  | `test_absolute_path_socket_deny.py` | 6            |
  | `test_playbook_harness.py`          | **5**        |
  | `test_stop_hook_hard_block.py`      | 3            |
  | `test_tool_use_error_recovery.py`   | 2            |

  **16 across four files, not 11 across three.** `test_playbook_harness.py`
  post-dates this plan (Plan 00243), is IN Step 12.0's blocking set, and
  RELEASING.md says of it: *"A skip here means no daemon was running, which
  under H-1 is itself an abort condition."* It has been skipping in CI,
  uncounted, ever since — this plan's own thesis reproducing itself while the
  plan sat unstarted.

  Also found, and NOT daemon-related: **11 further skips in
  `test_transport_toggle_cycle.py`**, all "relay binary not built:
  `untracked/bin/hooks-relay`". A second provisioning gap of the same shape,
  out of scope here but recorded so the next count is not surprised by it.

- [x] ✅ **Task 1.2**: The blocking set is declared as **one hardcoded `pytest`
  invocation inside a fenced bash block** at `RELEASING.md` Step 12.0, naming
  six files:

  ```
  test_diagnostic_scripts.py  test_install_sh_end_to_end.py
  test_tool_use_error_recovery.py  test_stop_hook_hard_block.py
  test_skill_install_python_discovery.py  test_playbook_harness.py
  ```

  **It CAN be read mechanically** — a stable single-line command whose
  `tests/acceptance/*.py` arguments a parser can lift — so Phase 3's guard does
  not need a second copy, and must not make one.

  Two things found while establishing that, both of which change later phases:

  - **`test_absolute_path_socket_deny.py` is not in the set**, though it is 6
    of the 11 skips. A declaration-keyed guard cannot cover it; decide whether
    it belongs in the set.
  - **The expected COUNTS beside that command are already a second copy** —
    `combined: 27 passed, 1 skipped`, restated per-file above it. Plan 00110
    hit exactly this: a criterion phrased as a gate count was stale twice over
    because other plans kept moving the number. Whatever Phase 3 builds should
    read the file list and NOT the counts.

### Phase 2: Make the gates run

- [x] ✅ **Task 2.1**: Start a daemon in the CI QA job before the acceptance
  step. ~~reusing whatever the `Daemon load` job already does rather than
  inventing a second way to start one~~ — **there is nothing to reuse**, per the
  struck-through claim above. **Implemented as ONE step** in the existing `qa`
  job, after `mypy` and before `Tests + coverage`, so the gates run on all three
  interpreters without a second job to keep in sync. Re-run pending.
  - [x] ✅ **First attempt ran `install.py --self-install` and the runner
    rejected it** — recorded because the reasoning that produced it was wrong,
    not just the outcome. I read `if <file>.exists() and not force:` in both
    config writers and took it for an early return; it is a **rename-to-`.bak`
    followed by an unconditional template write**, so `force` only decides
    whether a backup happens and every invocation replaces the config. The
    daemon then refused to start because that template is invalid against the
    current schema, and the run went 4 → **31 failures + 7 errors**.
    Full evidence in [RESEARCH-ci-install.md](RESEARCH-ci-install.md).
  - [x] ✅ **Nothing needs installing.** A checkout already carries the config,
    the forwarders and the package. The only missing piece is
    `.claude/hooks-daemon.env`, which the repo guard (`init.sh:246-264`) accepts
    on mere existence and which is gitignored — so CI writes it and the tree
    stays clean. `self_install_mode: true` is already tracked
    (`.claude/hooks-daemon.yaml:7`), and `HOOKS_DAEMON_VENV_PATH` is honoured
    ahead of the fingerprint glob (`resolve_venv.sh:113-121`) so the daemon uses
    the `.venv` that `uv sync` already built.
  - [x] ✅ The gates need a **running** daemon, not an installed one — the skip
    is keyed on a live socket under `untracked/`, which the tests open directly.
    So `init.sh`'s CI passthrough mode (documented in `test_ci_passthrough.py`,
    active under `GITHUB_ACTIONS=true`) governs the forwarder path only and does
    not interfere with them.
- [ ] ⬜ **Task 2.2**: Confirm all 11 tests EXECUTE on all three interpreters
  - [ ] ⬜ Expect first-run failures and treat them as long-standing, not as
    regressions — the LESSONS.md entry on waking skipped tests applies directly
- [ ] ⬜ **Task 2.3**: Verify the CI daemon cannot collide with anything (its own
  `HOSTNAME`-derived socket, per the hostname-isolation design)
  - Analysis done, pending confirmation from the run — see
    [RESEARCH-ci-install.md](RESEARCH-ci-install.md). Short version: collision is
    impossible for a reason stronger than the hostname suffix.
- [x] ✅ **Task 2.4a**: The two failures that were plain defects rather than
  provisioning gaps — neither needed a daemon at all, and both were fixed with a
  test reproducing the CI condition locally. `test_deployed_skill_trees.py`
  asked git about a **directory-only** ignore pattern (`/hooks-daemon/`) for a
  path absent on a runner, so it was testing the container rather than the
  pattern; it now asks about a path inside the directory.
  `test_forwarder_socket_stdin.py` hardcoded `/workspace`; now derived from the
  checkout. Detail in `JOURNAL/`.
- [x] ✅ **Task 2.4b**: `test_relay_guard_fail_open.py`. ~~a real provisioning
  gap and this plan's Decision 1 again … so it requires an `nc` with `-U`
  support (`netcat-openbsd`) on the runner. **Unverified hypothesis**: the
  runner's `nc` lacks it.~~ **The hypothesis was wrong on both counts**: not a
  provisioning gap, and nothing to do with `nc`. It was a **test bug**, and the
  task's own instruction to confirm before fixing is what caught it.
  The test derived its socket path from `os.environ.get("HOSTNAME", "localhost")`,
  omitting the middle rung both real implementations have (`$HOSTNAME` →
  `socket.gethostname()` → `"localhost"`). bash populates `$HOSTNAME` as a
  **shell** variable without exporting it, so on a runner `init.sh` resolved a
  real OS hostname while the test resolved `"localhost"` — server and nc rung
  used different paths. **Reproduced locally** with `env -u HOSTNAME pytest …`,
  so no CI round trip was needed; fixed by calling
  `paths._get_hostname_suffix()`. **Class guarded**:
  `test_hostname_suffix_parity.py` pinned the two production helpers against
  each other but nothing stopped a TEST adding a third computation, so it now
  scans `tests/` for unexempted `$HOSTNAME` reads with a
  `# hostname-suffix-exempt: <reason>` marker and a vacuity class. No silent
  skip was added. Full narrative in `JOURNAL/`.

### Phase 3: Guard the class

- [ ] ⬜ **Task 3.1**: A skip of a declared-blocking acceptance gate fails the
  run, naming the file and that it is declared blocking
- [ ] ⬜ **Task 3.2**: A test that fails when a file is added to the blocking set
  without being covered, so the guard cannot drift from the declaration

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA green, daemon restart RUNNING
- [ ] ⬜ **Task 4.2**: A green CI run in which the 11 tests are reported as
  PASSED rather than absent — which now also requires the three failing files
  in Task 2.4, since `main` is currently red and no amount of skip-fixing
  turns it green on its own

## Dependencies

- Follows: Plan 00245 (the `-rs` change that surfaced this; its Decision 3 is the
  precedent for provisioning over skipping).
- Related: Plan 00243, which handles skip rendering in the playbook rather than
  skip visibility in CI.
- Related: Plan 00244, whose project-handler CI step had the same "wired in but
  not load-bearing" property until CI went green.

## Technical Decisions

### Decision 1: provision the daemon rather than relax the tests

**Context**: the cheap fix is to leave the skips alone — they are honest, and the
tests do pass locally under H-1 during a release.

**Decision**: provision. A gate that only ever runs during a manual release step
is not a gate against the commits that reach `main` between releases, which is
precisely when a regression is cheapest to catch. Plan 00245's Decision 3 already
chose this for `uv`, and the argument is identical.

**Date**: 2026-08-17

## Success Criteria

- [ ] The 11 tests report PASSED in CI on all three interpreters, not skipped
- [ ] A silent skip of a declared-blocking gate fails the run
- [ ] The blocking set has one source of truth
- [ ] Local `llm_qa.py all` still passes

## Risks & Mitigations

| Risk                                                        | Impact | Probability | Mitigation                                                                                     |
| ----------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| The 11 tests fail on a runner for reasons unrelated to this | Medium | High        | Expected — Plan 00245's Phase 3 was exactly this work; treat as long-standing, fix root causes |
| A CI daemon interferes with another job                     | Medium | Low         | Hostname-based isolation already gives each environment its own socket/PID path                |
| Guarding the blocking set duplicates `RELEASING.md`         | Medium | Medium      | Task 1.2 settles the single source of truth BEFORE the guard is written                        |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
