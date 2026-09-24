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
| (last)     | QA result, Task 1.5 tick, this report                                                      |

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

QA_LINE_PLACEHOLDER

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
