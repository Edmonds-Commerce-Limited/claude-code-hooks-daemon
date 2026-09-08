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
accounts for 6 of the 16 skips, is not mentioned in that file at all.** It is
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
does not: there was nothing to reuse.

**The answer turned out to be that there is no install** — see
[RESEARCH-ci-install.md](RESEARCH-ci-install.md). A checkout already has the
config, the forwarders and the package; the only missing piece is the gitignored
`.claude/hooks-daemon.env`, which the repo guard accepts on mere existence. CI
writes that and starts the daemon, touching no tracked file.

Running the installer was tried first and the runner rejected it; the mechanism
and the misreading behind it are in Task 2.1's first sub-bullet.

## The same gap has a louder sibling, and CI is no longer green

**This plan was written from "the first fully green CI run". That premise has
expired.** `Tests + coverage` was RED on `main` for a long stretch — 9 failures
per interpreter across three files when found. All three are fixed; two were
NOT this plan's subject, being plain defects that would fail on any machine
without a deployed install, found by reproducing the runner condition locally
rather than reading a CI log. See
[RESEARCH-ci-failures.md](RESEARCH-ci-failures.md).

**Consequence**: Task 4.2 ("a green CI run") needs those fixed whatever happens
to the skips — **16** of them, per Task 1.1; the "11" this plan was written with
was already stale.

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

Both tasks are complete and both found the plan's own premises stale. Evidence
and tables: [RESEARCH-ci-failures.md](RESEARCH-ci-failures.md).

- [x] ✅ **Task 1.1**: Observed by running the suite in a `git worktree` (whose
  own `untracked/` holds no socket — a runner's condition, at no cost to the
  session). **16 skips across four files, not the 11 across three this plan was
  written with.** The extra file is `test_playbook_harness.py`, which post-dates
  the plan, IS in the blocking set, and had been skipping in CI uncounted ever
  since — the plan's own thesis reproducing itself while it sat unstarted.
  Separately, 11 more skips in `test_transport_toggle_cycle.py` are a different
  provisioning gap (relay binary), out of scope but recorded.

- [x] ✅ **Task 1.2**: The set is **one hardcoded `pytest` invocation** at
  `RELEASING.md` Step 12.0 naming six files, and it **can** be read
  mechanically — so Phase 3 needs no second copy and must not make one. Two
  consequences: `test_absolute_path_socket_deny.py` is **not** in the set
  despite being 6 of the 16 skips (**recommendation: add it** — the set contains
  the playbook harness yet omits the one file covering what that harness
  structurally cannot reach; left to the owner, since the set defines what a
  human release gates on), and the expected **counts** beside the command were a
  stale second copy, now **removed from RELEASING.md** in favour of *0 failed,
  0 skipped*.

### Phase 2: Make the gates run

- [x] ✅ **Task 2.1**: Start a daemon in the CI QA job before the acceptance
  step. ~~reusing whatever the `Daemon load` job already does rather than
  inventing a second way to start one~~ — **there is nothing to reuse**, per the
  struck-through claim above. **Implemented as ONE step** in the existing `qa`
  job, after `mypy` and before `Tests + coverage`, so the gates run on all three
  interpreters without a second job to keep in sync. **Verified on a runner**:
  `Start daemon (for the acceptance gates)` reports `success` on Python 3.11,
  3.12 and 3.13, which is the first time this pipeline has ever had a live
  daemon during `Tests + coverage`.
  - [x] ✅ **First attempt ran `install.py --self-install` and the runner
    rejected it** — recorded because the reasoning that produced it was wrong,
    not just the outcome. I read `if <file>.exists() and not force:` in both
    config writers and took it for an early return; it is a **rename-to-`.bak`
    followed by an unconditional template write**, so every invocation replaces
    the config. The run went 4 → **31 failures + 7 errors**. Full evidence in
    [RESEARCH-ci-install.md](RESEARCH-ci-install.md).
  - [x] ✅ **Nothing needs installing.** A checkout already carries the config,
    the forwarders and the package. The only missing piece is
    `.claude/hooks-daemon.env`, which the repo guard (`init.sh:246-264`) accepts
    on mere existence and which is gitignored — so CI writes it and the tree
    stays clean. `self_install_mode: true` is already tracked
    (`.claude/hooks-daemon.yaml:7`), and `HOOKS_DAEMON_VENV_PATH` is honoured
    ahead of the fingerprint glob (`resolve_venv.sh:113-121`) so the daemon uses
    the `.venv` that `uv sync` already built.
  - [x] ✅ The gates need a **running** daemon, not an installed one — the skip
    is keyed on a live socket the tests open directly, so `init.sh`'s CI
    passthrough mode governs the forwarder path only.
- [x] ✅ **Task 2.2**: **11 of the 16 execute and PASS.** First daemon-enabled
  run, identical on all three interpreters:
  `test_absolute_path_socket_deny.py` 6 passed, `test_stop_hook_hard_block.py`
  3 passed, `test_tool_use_error_recovery.py` 2 passed. The suite went from
  4 failed to **1 failed, 18605 passed, 5 errors**, coverage 95.46%.
  - [x] ✅ The remaining 5 (`test_playbook_harness.py`) ERRORED rather than
    passed, for a reason worth keeping: it runs `bin/hooks-daemon generate-playbook` as a **subprocess**, which resolves the venv itself and
    could not see `HOOKS_DAEMON_VENV_PATH` set only on the daemon-start step.
    Now set at JOB level. I had scoped it narrowly on the guess that job-wide
    would disturb the venv-resolution tests; measured instead — those 83 tests
    and a full local QA run both pass with it set.
  - The 11 `test_transport_toggle_cycle.py` skips remain and are **out of
    scope**: a separate provisioning gap (relay binary not built), recorded by
    Task 1.1 so it is not mistaken for daemon fallout.
- [x] ✅ **Task 2.3**: No collision, and for a stronger reason than the hostname
  suffix — see [RESEARCH-ci-install.md](RESEARCH-ci-install.md). Borne out by
  three matrix jobs each starting a daemon successfully.
- [x] ✅ **Task 2.4d**: The three failures the newly-running gate *found* — the
  point of the plan, not fallout from it. Two are real handler defects that
  deny valid code on any machine with the real linter installed (Rust's
  `clippy-driver` framed the file as a binary crate; Kotlin's command used
  `-script` on `.kt` and carried a `2>&1` no shell was ever going to expand),
  and one is a harness budget equal to the handler's own, so `lint_on_edit`'s
  fail-open could never be reached and one slow lint killed all 201 probes.
  Each fixed with a class-level guard rather than a one-off. Detail and the
  reproduction in [RESEARCH-ci-failures.md](RESEARCH-ci-failures.md).
- [x] ✅ **Task 2.4c**: `test_dogfooding_hook_scripts.py::test_hook_scripts_match_installer`.
  The comparison now generates for the root the deployed forwarders **record**
  (`recorded_untracked_dir` reads `_rl_dir="…"` back out), not for the current
  checkout's — so it is byte-exact on any machine, and refuses to guess when two
  forwarders disagree. Root-normalisation was the first attempt and was **not
  sufficient**: a runner-length checkout crosses the AF_UNIX limit and takes a
  different generator branch. The prior question is settled — `hooks_deploy.sh`
  copies the tracked forwarders into client projects and hard-fails without
  them, so they must stay tracked. Hostname headroom measured at 54 characters
  and pinned. See [RESEARCH-ci-failures.md](RESEARCH-ci-failures.md).
- [ ] ⬜ **Task 2.4e**: Playbook probe **#144** (Swift lint — invalid code
  blocked) reports "no decision at all" on Python 3.11 while passing on 3.12 and
  3.13, same runner image. Not a timeout (that branch returns an advisory, so it
  would show text, not silence) and not a missing tool (`required_tools` gates
  it). Needs a reproduction, not a patch.
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
  omitting the middle rung both real implementations have
  (`socket.gethostname()`). bash sets `$HOSTNAME` as a **shell** variable without
  exporting it, so a runner resolved a real hostname where the test resolved
  `"localhost"`. **Reproduced locally** with `env -u HOSTNAME pytest …`; fixed by
  calling `paths._get_hostname_suffix()`. **Class guarded**:
  `test_hostname_suffix_parity.py` now scans `tests/` for unexempted `$HOSTNAME`
  reads, with an exemption marker and a vacuity class. Full narrative in
  `JOURNAL/`.

### Phase 3: Guard the class

- [x] ✅ **Task 3.1**: `tests/acceptance/blocking_gate_guard.py` rewrites a
  skipped report into a failed one naming the file, the declaration and the
  **original skip reason**. Proven end-to-end by a nested pytest run, not only
  by unit tests of the predicate: the declared file fails, an undeclared one
  still skips.
- [x] ✅ **Task 3.2**: the guard **reads** the set off Step 12.0's command line,
  so "in the set but not covered" is unreachable rather than merely tested. The
  risk that replaces it is a parser that quietly stops finding the declaration,
  so parsing **raises** on a missing, duplicated or argument-less declaration —
  each covered, plus "every declared file exists on disk".

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA green, daemon restart RUNNING
- [ ] ⬜ **Task 4.2**: A green CI run in which the 16 tests are reported as
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

- [ ] The 16 tests report PASSED in CI on all three interpreters, not skipped
- [ ] A silent skip of a declared-blocking gate fails the run
- [ ] The blocking set has one source of truth
- [ ] Local `llm_qa.py all` still passes

## Risks & Mitigations

| Risk                                                        | Impact | Probability | Mitigation                                                                                     |
| ----------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| The 16 tests fail on a runner for reasons unrelated to this | Medium | High        | Expected — Plan 00245's Phase 3 was exactly this work; treat as long-standing, fix root causes |
| A CI daemon interferes with another job                     | Medium | Low         | Hostname-based isolation already gives each environment its own socket/PID path                |
| Guarding the blocking set duplicates `RELEASING.md`         | Medium | Medium      | Task 1.2 settles the single source of truth BEFORE the guard is written                        |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed at the commit that adds this plan.
