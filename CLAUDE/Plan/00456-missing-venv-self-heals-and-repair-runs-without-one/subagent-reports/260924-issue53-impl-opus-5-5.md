# Plan 00456 / #53: implementation report (Opus 5.5)

Branch `worktree-issue-53-venv`, worktree
`untracked/worktrees/worktree-issue-53-venv/`. Nothing is pushed or merged.
Phase 2 (merge, CI, daemon restart, #53) is for the lead.

## Commits (oldest first)

| Commit     | Unit                                                                                       |
| ---------- | ------------------------------------------------------------------------------------------ |
| `2f5d04af` | `paths.py bootstrap-decision` gate verb (no venv needed); `cmd_repair` keyed on daemon dir |
| `c4a770e3` | `scripts/venv_bootstrap.sh` (hook / repair / build) plus non-blocking lock primitives      |
| `c3449948` | `init.sh` self-heals from the venv-missing branch                                          |
| `b453f6bc` | `bin/hooks-daemon repair` builds the venv before resolution; shared test sandbox           |
| `20cbfcd3` | Skill `install.sh` never auto-forces; `--force` keeps every `untracked/venv-*`             |
| `e11bbcaa` | SELF_INSTALL / LLM-UPDATE / TROUBLESHOOTING / skill `install.md`; release note 06          |
| `21b5cf8d` | Venv-free verbs are one dispatch (`_run_venv_free_verb`), ready for `signal`               |
| `0f181704` | This report, draft (the QA run's target)                                                   |
| (last)     | QA result in this report and the journal (Task 1.5 left unticked, see QA)                  |

## Design as built

- **Gate.** `python3 <daemon>/src/.../daemon/paths.py bootstrap-decision --daemon-dir D` runs by file path under a bare interpreter (stdlib only,
  Plan 00431's technique). It prints `allowed=`, one `missing=` and one
  `fix=<id>: <text>` per failed `can_inline_bootstrap` condition, plus
  `python=`, `fingerprint=` and `inputs=` (a hash of lock_hash, the
  interpreter and `uv`'s path). No fix text names install or `--force`. The
  Python comes from `find_latest_python 3.11`. When there is none, the
  driver reports `compatible-python` itself, using the discovery helper's
  diagnostic.
- **Driver.** `scripts/venv_bootstrap.sh`:
  - `hook` never blocks. It first makes a read-only check for whether the
    lock is held. It then try-acquires the venv lock
    (`untracked/.venv-bootstrap.lock`, flock or the mkdir fallback) and
    hands it to a `setsid` (else `nohup`) child running `build`. The child
    adopts the lock and runs `ensure_venv_locked`.
  - The parent forgets the lock and prints `state=started|running|failed| refused|disabled|error` and `log=`, with `missing=`/`fix=`/`detail=`
    where they apply.
  - State files, all under `untracked/`: `.venv-bootstrap-<fp>.log`, the
    marker `.venv-bootstrap-<fp>.failed` (it records `inputs=`), and
    `.venv-bootstrap.current`.
- **init.sh.** `_venv_self_heal` runs ONLY in the VENV_MISSING branch, and
  only when the clone is present and its version reads. Its state picks the
  one venv-missing message's remedy line: building (with the log),
  failed (with the log and `repair`), refused (each condition with its
  fix), or disabled. The message no longer claims the skill escalates to
  `--force`.
- **`bin/hooks-daemon`** (deployed copy and template, byte-identical): when
  resolution fails and `$1 = repair`, it runs `venv_bootstrap.sh repair` in
  the foreground (blocking lock, clears the marker), re-resolves, and
  continues into the Python `repair`. Every other verb still exits 5, and
  its message now names `repair`. `resolve_venv.sh` names it too.
- **`cmd_repair`** now uses the DAEMON dir for the venv name, the lock and
  `uv sync`'s cwd. Before, in client mode, it built a venv keyed on the
  project root, which the resolver refuses (Plan 00313 slug check).
- **Skill `install.sh`** (deployed copy and template, identical):
  - A healthy install behaves as before.
  - A runtime-only shell (no clone, no venv) is removed, then a normal
    install runs.
  - A clone with a readable version runs `bin/hooks-daemon repair`, then
    probes again. On failure it exits 1 with "Nothing was deleted", naming
    `repair`, then the same-version upgrade, with `--force` last as an
    explicit choice.
  - Anything else exits 1 with nothing changed.
  - An explicit `--force` moves every `untracked/venv-*` aside to
    `.claude/.hooks-daemon-venvs.XXXXXX` and restores it from an EXIT trap.
    If a name collides, the freshly built venv wins, and a `rmdir` failure
    is warned about.

## Decisions (brief points 1-5)

1. **Detached build and retry policy.** The build runs detached under the
   existing venv lock, and the hook returns in about 0.3s. A second hook
   while it runs sees the lock held and reports `running`. A failure
   writes a marker carrying the inputs signature, and later hooks report
   `failed` with the log and do NOT respawn. **Retry happens only when the
   inputs change** (uv.lock hash, interpreter, `uv` path), or on an explicit
   `repair`, which clears the marker. Reason: retrying an unchanged
   failure every hook is the loop the plan forbids. The inputs that would
   make a retry worthwhile are exactly the ones hashed.
2. **Gate and failure message.** The gate is the five
   `can_inline_bootstrap` preconditions, evaluated without a venv. On any
   failure, nothing on disk changes (snapshot-tested), and each failed id
   is named with its own fix. 00454's tests stay green.
   **No `venv_missing_advisor` handler.** A SessionStart handler runs
   inside the daemon, and the daemon cannot start without the venv it would
   be advising about. The init.sh message already reaches the session on
   every hook, so a handler would be dead code in exactly the state it
   targets.
3. **init.sh without a venv, only in venv-missing.** It uses the bare
   Python gate and the shell lock; nothing needs the venv. It is called
   from the VENV_MISSING branch only, so a stale clone, a missing install
   or an orphan venv never trigger a build.
4. **`repair` intercepted before resolution.** It runs `ensure_venv` in
   the foreground under the lock, clears the marker, re-resolves, then
   runs the Python repair. With a venv present, nothing changes.
   **Extension point for `signal` (Plan 00457, #55):** the intercept is a
   dispatch, `_run_venv_free_verb()` at `bin/hooks-daemon:108`, called
   from `bin/hooks-daemon:129`. The template
   (`src/claude_code_hooks_daemon/install/templates/hooks-daemon`) is
   byte-identical.
   - Each verb is one `case` arm. An arm either makes a venv resolve (sets
     `PYTHON` and returns 0), or `exec`s a venv-free implementation itself;
     `signal` needs the second shape.
   - `*)` returns 1, which gives the exit-5 refusal.
   - `TestVenvFreeVerbsAreOneDispatch` pins this shape.
   - `signal` is NOT implemented.
5. **The skill never auto-forces.** It repairs in place with the clone's
   own `repair`, not the same-version `upgrade`. `repair` is local and
   offline and touches only this path's venv. The upgrade fetches from
   GitHub and rewrites tracked files. `upgrade.sh` was checked: its
   idempotent same-version path exits before eager cleanup, so it did not
   need a change.

Docs (point 6): `SELF_INSTALL.md` now separates the cases:

- A MISSING venv is built from the hook path.
- A STALE venv is rebuilt only by install, upgrade or `repair`.
- Other views' venvs are kept, EXCEPT by a version-changing upgrade's eager
  cleanup (Plan 00100 3.9), which the doc now names.

Release note 06 is written. No post-upgrade task: nothing an upgrading
client must act on (reasoning in the journal, 10:22).

## Tests (all TDD, with RED captured in the journal)

- `tests/unit/daemon/test_bootstrap_decision_cli.py`: new.
- `tests/unit/daemon/test_cli_repair.py`: new class
  `TestCmdRepairTargetsTheDaemonDir`, plus an existing lock assertion that
  had to change: it now expects the daemon dir.
- `tests/unit/daemon/test_cli_venv_management.py`: updated to the
  daemon-dir-keyed venv.
- `tests/integration/test_venv_bootstrap_driver.py` (17 tests): one build
  under concurrent hooks, running/failed/refused/disabled, marker and
  inputs retry, lock handoff.
- `tests/integration/test_init_sh_venv_self_heal.py` (15 tests): the hook
  starts exactly one build. The next hook after it finishes starts the
  daemon. The second environment's `venv-*` is byte-identical. With `uv`
  missing, nothing changes and neither install nor `--force` is suggested.
- `tests/integration/test_bin_hooks_daemon_repair_without_venv.py` (7
  tests).
- `tests/integration/test_skill_install_never_auto_forces.py` (12 tests,
  fake curl and fake installer).
- `tests/integration/test_skill_install_health_guard.py`: the static
  assertion is inverted to "never escalates".
- Shared harness: `tests/venv_bootstrap_sandbox.py` (fake `uv`, tmp
  clones, snapshots). Slow tests are marked `slow`.

**Real E2E** (journal, E2E entry). A client project under `/tmp/e456` with
no venv:

- Hook 1 (0.31s) started a real `uv` build.
- Hook 4 got the daemon's own `{}`, and `status` said RUNNING.
- A real `bin/hooks-daemon repair` with no venv, in `/tmp/e457`, exited 0
  in 3s.

Both daemons were stopped afterwards.

## QA

Full `./scripts/qa/llm_qa.py all` on HEAD `0f181704`: one foreground-polled
run, no daemon restarts, no commits during it.

```
❌ tests: 25603 passed, 2 failed, 24 skipped | coverage: 95.1%
QA: 34/35 PASSED, 1/35 FAILED
```

Every other tool passes: format, lint, mypy, pyright, shell_audit,
capture_corruption, plan_qa, docs_qa, smoke_test and the rest.

**The two test failures are pre-existing and depend on location. They are
not caused by this branch.** The failing tests are
`test_acceptance_contract.py::...produces_its_declared_verdict` and
`test_playbook_harness.py::...matches_its_expected_decision_and_reason`.
Both fail on the same 14 DENY probes: QaSuppression, CommentChangelog (13
languages) and CommentSize, each with "matches() returned False for its own
declared input". The probes write under
`$CLAUDE_PROJECT_DIR/untracked/scratch/`, which from a worktree is inside
`untracked/worktrees/`, and those handlers skip that tree.

- **A/B.** The same input to `QaSuppressionHandler.matches()` is False
  under this worktree's path and True under `/tmp/elsewhere-project/`.
- **Merge base.** At `46f5c5b1`, in this worktree, the same 14 probes fail.
- **Branch diff.** The branch diff over the handlers, core, the project
  config and those tests is empty.

The expectation is that they pass from a normal checkout: CI, or main after
the merge. That has not been verified from here. **Task 1.5 and "Full QA
passes and CI is green" are therefore left unticked** for the lead to
confirm after the merge. For the niggles ledger: the acceptance suite cannot
be fully green from any `untracked/worktrees/` checkout, because the probe
scratch path falls inside the handlers' own worktree exclusion. Evidence is
in the journal entry at 11:04.

## Unresolved / out of scope (not changed here)

- **Leftover E2E directories.** `/tmp/e456` and `/tmp/e457` are still
  there, because the permission system denied the `rm -rf`. Removing them
  is left to the owner.
- `list-venvs`' "current" marker uses the project-root slug in client mode,
  so it can mark nothing as current. This is the same keying bug that was
  fixed in `cmd_repair`.
- The root `install.sh` run directly with `FORCE=true` still wipes every
  venv. Only the skill's wrapper now preserves them.
- The skill's `daemon-cli.sh`, `health-check.sh` and `init-handlers.sh`
  still say "Run the installer/upgrade". This is now safe, but it is
  imprecise, and `repair` is the better advice.
- `resolve_venv.sh` prints `exit=0` in its failure message: a pre-existing
  `$?`-after-test bug.
- The hook path runs the driver with no `timeout` wrapper. The driver never
  blocks by design, but the gate's `python3` is unbounded.
- `cmd_repair` runs `uv sync` without `--frozen`.
- `llm_qa.py`'s dev-mode message still names the install action.
- Pre-existing failures seen in a broad regression run, not caused by this
  branch:
  - `tests/acceptance/test_playbook_harness.py` fails because of this
    session's orchestrator-simulate/team environment.
  - A `docs_qa/test_corpus.py` `...logs_nothing` test fails only in some
    orders; it passes alone.

## Correction to the QA section: the probe-failure mechanism (review I5)

The conclusion above stands: the 14 acceptance-probe failures predate this
branch, and this branch does not cause them. The stated mechanism is
**wrong**, and the proposed niggle must not be ledgered.

- The cause is **not** `untracked/worktrees/`. Another checkout there
  (`worktree-issue-55-signal`) passes, and so does
  `/tmp/untracked/worktrees/x`.
- The cause is this worktree's **name**: `worktree-issue-53-venv/`
  contains the substring `venv/`. QaSuppression, CommentChangelog and
  CommentSize skip any file whose absolute path merely contains a
  skip-dir string (`skip_dir in file_path`, with `venv/`, `build/`,
  `dist/`, `vendor/`, `migrations/`). `/tmp/foo-venv` and `/tmp/myvenv`
  are skipped too.
- The real, pre-existing defect is a guard false-negative for any
  project whose path contains one of those substrings. It is **Plan
  00458**, being fixed in another worktree. The handlers are not touched
  here.
- The `test_playbook_harness.py` failure listed above, which I put down
  to the session's orchestrator-simulate mode, fails on the same 14
  probes. It is the same cause.

The journal's 11:37 correction entry records this.

## Review findings and their resolution

The review is `subagent-reports/260924-review-opus-5-5.md`, committed as
delivered at `9607ea07`. Every fix was TDD, with RED quoted in the journal
at 11:37.

| Finding                                                              | Resolution                                                                                                                                                                                                                                                            | Commit      | Test (RED first)                                                                                               |
| -------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------- |
| B1: CI=true and the opt-out break `repair` and fake a failed build   | One `venv_bootstrap_switched_off_by`. The hook reports `disabled` with `detail=<setting>`. A switched-off build writes no marker. An explicit `repair` announces the override and builds. init.sh names the setting                                                   | `271040e7`  | driver `TestSwitchedOffMeansSwitchedOff` (5); init.sh `test_ci_true_is_named_never_reported_as_a_failed_build` |
| B2: Python repair's bare `uv` misses `~/.local/bin`                  | `paths.find_uv()` checks `$HOME/.local/bin` first, then PATH. Used by the gate, the signature and `cmd_repair`, which spawns its absolute path                                                                                                                        | `271040e7`  | unit `TestFindUv` (5), `TestCmdRepairUsesTheBuildsUv` (2); wrapper `test_uv_only_in_uv_home_repairs_cleanly`   |
| I1: hung detached build, no bound, no pid                            | `timeout -k 30 $HOOKS_DAEMON_VENV_BUILD_TIMEOUT` (900s) around the child. A TERM trap writes the marker and logs "timed out". The record holds the pid, `running` shows pid and elapsed, and the log names the pid. Without `timeout` it is unbounded, with a warning | `271040e7`  | driver `TestADetachedBuildIsBoundedAndNamed` (2)                                                               |
| I2: mkdir backend reclaims a live build; exit deletes another's lock | A heartbeat keeps a live holder's lock fresh. Release removes only a lock whose `pid` is `$$`. Age stays the staleness rule, because a pid is not checkable across views                                                                                              | `271040e7`  | driver `TestTheMkdirLockSurvivesALongBuild` (2)                                                                |
| I3: a KILLed `--force` strands venvs in an unignored dir             | The aside dir holds a `.gitignore` of `*`. Every run adopts stranded aside dirs and restores them from the EXIT trap                                                                                                                                                  | `b868330e`  | skill `TestVenvsStrandedByAKilledForceAreRecovered` (2)                                                        |
| I4: repair, skill and upgrade hit the 120s wait behind a hook build  | `acquire_venv_lock` extends the wait to the recorded build's remaining bound, and announces it                                                                                                                                                                        | `271040e7`  | driver `test_repair_outwaits_the_generic_lock_bound`                                                           |
| I5: wrong probe-failure diagnosis                                    | Not this branch's (Plan 00458). The report and journal are corrected                                                                                                                                                                                                  | this report | n/a                                                                                                            |
| I6: marker checked before the lock                                   | The marker is judged after `try_acquire`, and the lock is released before reporting `failed`                                                                                                                                                                          | `271040e7`  | driver `test_a_marker_written_just_before_the_acquire_is_honoured` (a fake `flock` plants it at acquire)       |
| S1: in-place `uv self update` is not an input change                 | The signature hashes uv's path, size and mtime. The wording is now "the uv binary changes"                                                                                                                                                                            | `271040e7`  | unit `test_changes_when_uv_is_updated_in_place`                                                                |
| S2: source-shape tests                                               | Declined for now. The dispatch-shape test pins the lead's extension point, and the behaviour beside it is tested. Plan 00457 replaces it with per-arm behaviour when `signal` lands (journal 11:37)                                                                   | n/a         | n/a                                                                                                            |
| S3: verb only read from `$1`; `repair --help` builds                 | `_subcommand_of` skips global options and their values. `repair --help` prints usage and builds nothing                                                                                                                                                               | `271040e7`  | wrapper `TestTheVerbIsFoundPastGlobalOptions` (2)                                                              |
| S4: missing driver gives circular advice                             | The `repair` arm names `scripts/venv_bootstrap.sh` and exits 5                                                                                                                                                                                                        | `271040e7`  | wrapper `test_a_missing_driver_is_named`                                                                       |
| S5: adopt trusts any `mkdir:<dir>`                                   | The mkdir spec must equal the daemon's lock dir. The flock fd is checked via `/proc` where present. The variable is unset after adoption                                                                                                                              | `271040e7`  | driver `test_a_foreign_directory_is_refused_and_untouched`                                                     |
| S6: gate cost in failed/refused                                      | Declined. Measured median 101 ms (failed) and 94 ms (refused), only while the daemon is down anyway (journal 11:37)                                                                                                                                                   | n/a         | `untracked/scratch/s6_measure.py`                                                                              |
| S7: three version.py readers                                         | Declined. The three live in units that cannot share code, so moving one would not remove one (journal 11:37)                                                                                                                                                          | n/a         | n/a                                                                                                            |

Of the earlier "Unresolved" items, one is now resolved by I1: the hook's
driver has a bound on its BUILD. The gate's own `python3` spawn is still
unbounded; it takes about 0.1s.

**Full QA after the review fixes:** QA_REVIEW_PLACEHOLDER
