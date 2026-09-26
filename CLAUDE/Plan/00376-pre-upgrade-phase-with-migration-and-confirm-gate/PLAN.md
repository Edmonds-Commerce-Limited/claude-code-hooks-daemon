# Plan 00376: pre upgrade phase with migration and confirm gate

**Status**: In Progress
**Created**: 2026-09-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A pre-upgrade phase already exists — Plan 00062 built it — but it validates
only the user's CONFIG, and the confirmation gate it added never fires for an
agent. So an upgrade still tells a project what its SOURCE must change only
after the change has landed, and no agent ever reaches a decision point. This
plan extends that phase rather than inventing one.

**Prior art, and the reason this is an extension**: Plan 00062 ("Breaking
Changes Lifecycle", Complete) delivered `install/upgrade_compatibility.py`
(its Phase 4) and the "confirm you have read the breaking-change docs" gate
(its goal 6). Its Non-Goal — "Automatic config migration (too risky — user
confirmation required)" — is upheld here: detection and proposal, never silent
rewriting.

**The bootstrapping constraint does NOT apply, verified.** It is natural to
assume pre-upgrade instructions cannot be read before install because they ship
with the incoming version. That is false here: `scripts/upgrade.sh` Step 6
("Land the daemon dir on the target version FIRST (before Layer 2)") checks out
the target, and Step 8 then delegates to `$DAEMON_DIR/scripts/upgrade_version.sh`
— the NEW version's script. The whole incoming tree, including its upgrade
manifests, is readable before anything is deployed. The existing compat check
was written to rely on this, reading the new `CHANGELOG.md` from `$DAEMON_DIR`,
but on the supported route it never runs (see Task 1.1).
"Pre-upgrade" here means pre-DEPLOY, not pre-fetch.

Three measured facts drive the remaining work:

- **The one confirmation gate that exists is dead for agents.** Step 5a of
  `scripts/upgrade_version.sh` (as the plan found it) prints "REQUIRED
  READING" and asks yes/no — but its prompt tests `[ ! -t 0 ]` and, on any
  non-interactive stdin, falls through to "Review upgrade guides after
  upgrade". Every
  agent-driven upgrade takes that branch. The gate protects humans at a
  terminal and nobody else. (Task 1.1 found it could not fire at all, and
  removed it; the reading list now runs in `run_pre_deploy_phase`.)
- **It would not be pre-install even if it fired.** Layer 1
  (`scripts/upgrade.sh`) checks the new version out in its Step 6, then
  delegates to Layer 2 in its Step 8. By the time Step 5a runs, the new code
  is already on disk.
- **`post-upgrade-tasks/` is a dead letter box.** Its own README states
  (`CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md:20`) "There is no
  runner. Nothing executes these tasks automatically." Nothing in the upgrade
  path reads it, `.claude/skills/hooks-daemon/upgrade.md` never mentions it,
  and unlike `release-notes/` it has no schema test. Plans are required to
  write tasks there as part of their definition of done; those tasks are then
  read by nobody. (Task 4.3 closes the "read by nobody" half; Tasks 2.3 and
  4.1 add the schema test and the runner.)

The motivating change is Plan 00375, which renames a public CLI JSON key. The
owner's ruling is that deprecation windows are not the answer — they are delay,
they make the defect correct by policy for a release, and they do not avoid the
break. The alternative is that the upgrade **migrates the consumer** instead of
announcing to it, which this system is uniquely placed to do: the daemon is
installed inside the consumer's repository and upgraded by an agent with full
read/write access to it. That is a codemod, except the migrator can read intent
rather than only matching syntax.

## Goals

- A pre-upgrade phase that runs BEFORE the new version is on disk, and states
  what the incoming version will change.
- Migration tasks that are **detected and applied**, not announced: scan the
  target project for affected call sites and report them with file:line.
- An explicit proceed/abort gate that works for an AGENT (non-interactive), not
  only for a human at a TTY, with escalation to the owner when the change
  warrants it.
- Proper semver: a breaking change is declared MAJOR and carries its migration,
  rather than being softened into a window.

## Non-Goals

- Auto-applying migrations without the gate. Detection and proposal come first;
  silent rewriting of a user's repository is exactly the failure mode this must
  not introduce.
- Replacing `post-upgrade-tasks/`. Some work genuinely can only happen after
  install; that surface stays, and is fixed separately rather than merged in.
- Covering consumers outside the upgraded repository. A local scan cannot see
  them; release notes remain their only channel and that is accepted.

## Tasks

### Phase 1: Establish where the phase runs

- [x] ✅ **Task 1.1**: Site the phase alongside the existing compat check in
  Layer 2 (`scripts/upgrade_version.sh`, around `run_pre_install_checks` and
  the config compatibility check), which is already after checkout and before
  any deploy. No new fetch mechanism is required — see the Overview.
  **Measured while fixing 4.2 and 4.3**: on the supported route that site
  never ran. Layer 1 checks the target out before it calls Layer 2, so the
  "already at target" test was always true and the idempotent path exited
  before the compat check and the Step 5a reading list. Invoked directly,
  both read the PRE-checkout tree, which holds no guide for the version being
  installed. **Done**: both now live in `run_pre_deploy_phase`
  (`scripts/upgrade_version.sh`). It is called on the idempotent path right
  after the target's venv is verified, and on the direct path after Step 7.
  Either way that is before the first deploy. It compares `CURRENT_VERSION`
  (the FROM side, handed over by Layer 1) against the release part of
  `INSTALL_STAMP` and the target's guides, and passes `include_unreleased`
  from `BRANCH_INSTALL_STATE`. The old pre-checkout blocks and their TTY
  prompt are removed. (Phase 3 turned the reading list into the gate and moved
  it before `ensure_venv`; the config check stayed after `verify_venv` as
  `run_config_compatibility_check`: see Tasks 1.2 and 3.1.) Pinned end to end by
  `tests/integration/test_upgrade_pre_deploy_phase_runs_on_layer1.py`, which
  runs the real Layer 1 route on release and branch fixtures, and cheaply by
  `test_upgrade_pre_deploy_phase_placement.py`.
- [x] ✅ **Task 1.2**: Characterise what "abort" must undo at that point. The
  daemon dir is ALREADY on the target checkout (Layer 1's Step 6) while nothing
  has been deployed — so an abort is not free, and the plan must define whether
  it restores the previous ref or documents the daemon dir as intentionally
  moved. **Characterised**: on the Layer 1 route, by the time Layer 2 runs,
  Layer 1 has stopped the daemon (Step 4) and force-reset the clone to the
  target (Step 6). Then Layer 2's `ensure_venv` REBUILDS the venv for the
  target (a stamp mismatch recreates it), so a stop after that point would
  also have to undo the venv. Nothing else has changed: no hook, settings,
  config or skill has been deployed yet. **Decided (unattended, 2026-09-24):
  restore the previous ref**, and run the gate BEFORE `ensure_venv` so the
  checkout is the only thing to undo. Reasons: (1) Layer 1 Step 3b reads the
  next run's FROM version from the clone's own `pyproject.toml`, so a clone
  left "intentionally moved" to the target makes the re-run see an empty
  range and skip the gate that stopped it: the documented alternative would
  turn every stop into a one-time speed bump; (2) the old venv and the
  restored checkout match, so the previous daemon starts again on the next
  hook event, and the install is exactly as it was. After review-00376:
  "previous" means the INSTALLED version, on every route. `abort_before_deploy`
  (`scripts/upgrade_version.sh`) resets the clone to the venv stamp's commit or
  tag, else the tag `.claude/HOOKS-DAEMON.md` names, else the ref a genuine
  Layer 1 handed over; with none it says so and exits non-zero. A direct Layer
  2 call's slow path stops inside the existing snapshot rollback
  (`UPGRADE_STARTED=true` after Step 3), which already restores. Assumption:
  the owner's "no known defects" instruction; the owner can reverse this with
  one message.

### Phase 2: The `pre-upgrade-tasks/` surface

- [x] ✅ **Task 2.1**: Add `CLAUDE/UPGRADES/UNRELEASED/pre-upgrade-tasks/` as a
  peer of `post-upgrade-tasks/`, with a README stating the schema. **Done**,
  plus `upgrade-template/pre-upgrade-tasks/README.md` for the per-release
  index. **Decided (unattended, 2026-09-24)**: pre- and post-upgrade tasks
  share ONE schema and ONE loader (`install/upgrade_tasks.py`, `TaskKind`
  selects the directory). The schema is written down once, in the post README,
  and the pre README states only what it adds. Reason: two schemas for one
  concept is the defect class Plan 00375 exists to remove. Assumption: the
  owner's "no known defects" instruction; the owner can reverse this with one
  message.
- [x] ✅ **Task 2.2**: Give it a **detection contract** — a task declares how
  to find affected call sites (a pattern to scan for), not only prose. This is
  what makes it silent when a project is unaffected, which is the property that
  keeps agents reading it rather than skimming it. **Decided (unattended,
  2026-09-24)**: a `**Detect**:` field holding one backticked Python regex (required for a pre-upgrade
  task, optional for a post-upgrade one) plus optional `**Detect in**:` fnmatch
  globs, matched line by line (the first 4096 characters of each); the scan
  reads git's file list in a work tree (so `.gitignore` holds), skips VCS,
  dependency and cache directories, top-level vendored/build/local roots and
  the daemon's own clone, and caps the listing at 20 hits with a count. The
  schema requires the backticks and rejects a nested quantifier. A regex over lines rather than a script: a task is data, the gate
  must run it before the target's venv exists, and a script shipped in a guide
  would be code the upgrade executes in the client's repository. The pattern
  finds candidates; the task's prose still decides. Assumption: the owner's
  "no known defects" instruction; the owner can reverse this with one message.
- [x] ✅ **Task 2.3**: A schema test over the real holding area, mirroring
  `tests/integration/test_pending_release_notes_holding_area.py`, so a
  malformed task fails CI at the plan's commit rather than at upgrade time.
  **Done**: `tests/integration/test_upgrade_task_schema.py` checks every task
  of both kinds, staged and released, with `upgrade_tasks.schema_errors`. It
  found two released v3.53.0 post-upgrade tasks without the required sections,
  which are fixed. `test_post_upgrade_tasks_are_reachable.py` now covers both
  kinds.
- [x] ✅ **Task 2.4**: Wire it into the release skill's UNRELEASED move, which
  currently handles four shapes and must handle five. **Done**:
  `CLAUDE/development/RELEASING.md` Step 6 (a "Move UNRELEASED
  pre-upgrade-tasks" subsection, the pre-release checklist, the manual-release
  summary), the release skill's pointer, `UNRELEASED/README.md` and
  `UPGRADES/README.md`.

### Phase 3: The gate that works for agents

- [x] ✅ **Task 3.1**: Replace the TTY-only gate. A non-interactive caller must
  get a real decision point, not a silent fall-through. The Step 5a prompt's
  test in `upgrade_version.sh` is a COMPOUND condition —
  `[[ "$*" == *"--skip-reading-confirmation"* ]] || [ ! -t 0 ]` — so it has two
  skip paths and only ONE of them is the bug. The explicit flag is a deliberate
  opt-out a caller asked for and must survive; it is the `[ ! -t 0 ]` INFERENCE
  ("no terminal, therefore nobody to ask") that silently disarms the gate for
  every agent. Remove the inference, keep the flag. **Note after Task 1.1**:
  that prompt is gone. It read the pre-checkout tree, so it could not fire.
  Build the gate inside `run_pre_deploy_phase`, which is where the report it
  acts on now runs. **Done**: `run_pre_deploy_phase` is now the gate. It runs
  `install/upgrade_gate.py` through `install/upgrade_gate_standalone.py`, a
  stdlib-only entry that needs no venv, and is called before `ensure_venv` on
  both paths. The report-only config check moved to
  `run_config_compatibility_check`, after `verify_venv`. With something to
  read and no `--skip-reading-confirmation` (argument or `UPGRADE_FLAGS`;
  Layer 1 now accepts and forwards it), the gate stops with exit 3. There is
  no TTY test anywhere in Layer 2. **Decided (unattended, 2026-09-24)**:
  (a) "something to read" is a crossed guide, a staged document on a branch
  install, a pre-upgrade task with hits (or whose scan could not run), or an
  escalation. A pre-upgrade task that finds nothing is not shown, so an
  unaffected project that crosses no guide hears nothing. (b) A range the gate
  cannot read (no venv stamp and no `HOOKS-DAEMON.md` version, or a target that
  is not a release version) runs every pre-upgrade task up to the target and
  needs the owner (review MINOR 2). (c) A downgrade crosses no guide and
  passes; a venv already stamped with the target's exact stamp passes (NIT 3).
  (d) A gate that crashes or runs past 300 s STOPS the upgrade (exit 1, with
  the same restore): an undecided gate that lets an upgrade through is the
  fail-open shape this repository is removing everywhere else. (e) The FROM
  side is the installed version, never the checkout (review MAJOR 1). (f) The
  acknowledgement is `--skip-reading-confirmation=<digest>`, a hash of what
  was listed (MINOR 6); no environment variable skips the gate (MAJOR 4).
  Assumption: the owner's "no known defects" instruction; the owner can
  reverse this with one message.

- [x] ✅ **Task 3.2**: Define escalation: which changes an agent may accept on
  its own, and which require the owner. Breaking/MAJOR is the obvious
  escalation trigger. Reuse the existing one-shot approval-marker mechanism
  (`utils/one_shot_approval`, as used by `approve-plan-close` and
  `approve-merge`) rather than inventing a second idiom. **Decided
  (unattended, 2026-09-24)**: the agent may acknowledge (exit 3 →
  `--skip-reading-confirmation`) anything that does not break the project.
  The owner must approve (exit 4) when the target's MAJOR is higher than the
  FROM's; when a crossed config-changes manifest (or, on a branch install, a
  staged one) declares `breaking: true`; or when a `critical` pre-upgrade
  task finds call sites in the project. The last trigger is what lets a
  breaking change that shipped in a minor, as 00375's did, still reach the
  owner, but only for the projects it actually breaks. The approval is a
  `OneShotApprovalStore("upgrade-approvals")` marker holding the from/to
  versions and the daemon and project paths, written only by
  `upgrade_gate.run_approval`: `hooks-daemon approve-upgrade <version> --from <installed>`,
  or the standalone's `approve` run from the target's own code, which the stop
  prints for an installed daemon too old to have the command. It needs a
  terminal on stdin and the typed phrase `approve upgrade from vX to vY`, so an
  agent's shell cannot run it; a marker that does not match is INVALID. Bash
  removes it only once the upgrade it let through completes (NIT 5). The
  `upgrade_approval_guard` handler denies an agent running either command,
  writing under `upgrade-approvals/` or a venv stamp, or setting
  `HOOKS_DAEMON_UPGRADE_HANDOFF` (Layer 1's one-shot handoff file, bound to
  Layer 1's PID). **Decided (unattended, 2026-09-24), review MAJOR 3**:
  v3.65.0's manifest said `breaking: true` while renaming, removing and
  changing nothing, so it is corrected to `false`: a data error, not policy.
  v3.58.0 stays breaking and gates only clients that cross it. A v3.64.x to
  current hop exits 3 at most, never 4 (pinned by `TestTheRealTree`). Release
  note 64 and RELEASING.md say who stops and how the owner approves.
  Assumption: the owner's "no known defects" instruction; the owner can
  reverse this with one message.

- [x] ✅ **Task 3.3**: An abort must leave the install in a state the next run
  can proceed from, per Task 1.2 — the checkout has already happened, so
  "untouched" is not achievable without an explicit restore. **Done**:
  `abort_before_deploy` restores the installed version on the fast path; the
  slow path exits into the snapshot rollback. Layer 1 now propagates Layer 2's
  exit code (`if ! bash …; then LAYER2_EXIT=$?` captured the negation's status,
  so Layer 1 exited 0 on every Layer 2 failure). A pre-gate Layer 1 still has
  that bug, so Layer 2 restores by itself and prints `THE UPGRADE DID NOT COMPLETE` with the command that runs the target's own Layer 1 (review MAJOR
  2); the skill shim's offline recovery and LLM-UPDATE's manual route run the
  target's Layer 1 too. Pinned end to end by
  `tests/integration/test_upgrade_pre_deploy_phase_runs_on_layer1.py` on the
  release, branch, MAJOR, fresh-clone, manual, environment-bypass, direct and
  pre-gate-Layer-1 routes (all eight RED against 713a68c0).
  **Decided (unattended, 2026-09-25), environment-steered gate**: (a) the gate
  runs on the installed venv's Python, else on a Python 3.11+ found on `PATH`,
  resolved with `HOOKS_DAEMON_PYTHON` and `HOOKS_DAEMON_VENV_PATH` unset, and
  always with `-I`. Layer 1 still honours `HOOKS_DAEMON_PYTHON` to build the
  venv, a legitimate non-gate use. (b) The installed version is read only from
  one of the daemon's own `untracked/venv-*` directories, checked on the
  physical path. The resolver served an override's cached result to a later
  call that set none; that is fixed at its source (00466 N37: an override
  call neither reads nor writes the cache, and only the daemon's own venvs are
  cached), and the check stays as defence in depth. (c) The `**Detect**` scan honours only the
  project's own `.gitignore` files and drops every `GIT_*` variable, so
  `.git/info/exclude`, `core.excludesFile` and `GIT_INDEX_FILE` cannot hide a
  call site. (d) `upgrade_approval_guard` denies, on a command that runs an
  upgrade entry point, setting the interpreter, venv, `PATH`, `HOSTNAME`,
  clone/base URL, pass-state, `UPGRADE_FLAGS` or `GIT_*` variables. It does
  not cover `HOOKS_DAEMON_UPGRADE_REF`, which picks only which published
  Layer 1 runs while the gate stays in the target's Layer 2, nor
  `HOOKS_DAEMON_UNSAFE_TRACK_REF`, which has its own owner guard and only
  makes the gate stricter. (e) No live doc, template or recovery text
  upgrades forward through the installed Layer 1; a rollback or a reinstall
  still may, since it is never older than what it installs. Pinned by
  `test_upgrade_pre_deploy_phase_runs_on_layer1.py`,
  `TestUpgradeSteeringVariables` and
  `test_no_document_upgrades_forward_through_the_installed_layer1`.
  Assumption: the owner's "no known defects" instruction; the owner can
  reverse this with one message.
  **Decided (unattended, 2026-09-25), fresh review BLOCKER 1 and MAJOR 1**
  (the review is `subagent-reports/260925-00376-fresh-review-opus-5-5.md`;
  this supersedes (a) and (d) above):

  - (a) The gate takes its tools from fixed system locations
    (`GATE_SAFE_PATH` in Layer 2, `TRUSTED_TOOL_PATH` in
    `install/upgrade_tasks.py`: `/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin`).
    It runs under `env -i` with only that `PATH`, `LANG` and `HOME`, through
    the `timeout` and Python 3.11+ found there, with `-I -S`. It no longer
    runs on the installed venv's Python: that venv is in the project, and a
    `.pth` planted in its site-packages ran inside the gate even under `-I`
    and could write the verdict itself (RED:
    `test_code_planted_in_the_installed_venv_does_not_answer_for_the_gate`).
    The cost: a host whose only Python 3.11+ is a pyenv or uv one stops with
    exit 1 until the user installs or links one into a system location. Its
    verdict comes back in a
    file inside a directory Layer 2 creates, opened `O_EXCL` with mode 0600
    and headed by a nonce Layer 2 draws from `/dev/urandom`. A zero exit
    without that file stops the upgrade (exit 1). Reason: a planted
    `timeout`, `git` or `python3.99` on the caller's `PATH` answered for the
    gate, and a stdout verdict line is what any wrapper can print.

  - (b) Every function that feeds or decides the gate (the installed
    version, the target release, the restore target, the abort) declares
    `local PATH="$GATE_SAFE_PATH"`. Layer 1 unsets every shell function
    `declare -F` names before anything else runs, but review3 found this is
    not a guarantee in pure bash: any builtin, including `unset` itself, can
    be shadowed by an exported function first, so this loop is best-effort
    against an ordinary planted function, not a boundary against one crafted
    to survive it. review3 MAJOR 2 closes the launch of Layer 2 differently
    and completely: Layer 1 now runs Layer 2 through the trusted `env -i`
    with an explicit allowlist, so no imported function -- however it is
    named -- reaches Layer 2's process at all; there is nothing to drop
    because there is nothing inherited to import from. Reason: an exported
    `timeout()` or `git()` shadows the tool by name, whatever `PATH` says.

  - (c) The installed == target shortcut counts only when the gate itself
    recorded letting that exact stamp through
    (`upgrade-approvals/gated-install.json` in the daemon's untracked dir, written on PROCEED,
    in the directory the guard already keeps agents out of). A stamp with
    no matching record is a range the gate cannot read, so it goes to the
    owner. Reason: `git checkout` of the target plus `hooks-daemon repair`
    writes the target's stamp legitimately, and the shortcut then waved a
    MAJOR through.

  - (d) `upgrade_approval_guard` recognises an upgrade by what the command
    is, not the file's name. It matches an entry point by name, Layer 1's
    `--skip-reading-confirmation`, or a readable script carrying
    `HOOKS_DAEMON_UPGRADE_HANDOFF`. It also matches a script it cannot read
    (`bash "$tmp"`, stdin, `bash -c` strings scanned recursively) that is run
    with `--project-root` or the daemon clone as an argument. The steering
    list adds `HOME`, `TMPDIR`, `BASH_ENV`, `ENV`, `BASH_FUNC_*`, `SHELLOPTS`,
    `BASHOPTS`, `LD_*`, `DYLD_*` and `PYTHON*`, plus `export -f`. Moving
    `.claude/hooks-daemon` to another ref by hand (`checkout`, `switch`,
    `pull`, `merge`, `rebase`, `reset`, `cherry-pick`, `am`, `revert`) is
    denied under the agent-action rule; fetch, show, log and describe are
    not. Reason: the documented route runs Layer 1 from a temp file, which
    the name-only check never saw.

  - (e) Layer 1 is NOT re-executed through a canonical path or under
    `env -i`. Its own launch of Layer 2 used to resolve `bash` from the
    caller's `PATH` (`bash "$LAYER2_SCRIPT"`) -- a caller able to plant a
    fake `bash` ahead of the real one controlled what interprets Layer 2
    before anything below got to run. review3: closed. Layer 1 now resolves
    `bash` via `_gate_tool` (`scripts/install/env_sanitise.sh`, sourced from
    the daemon dir it has just checked out to the target -- the same tree
    `$LAYER2_SCRIPT` itself is read from), the same fixed, root-owned,
    non-group/world-writable system location the gate subprocess already
    trusts, never the caller's `PATH`. A target predating this file (a
    downgrade below the release that introduced it) has no such resolver to
    fall back on, so the caller's `PATH` is used there -- the prior
    behaviour, not a new gap. Pinned by
    `test_layer1_launches_layer2_via_trusted_bash.py`: a hostile `bash`
    planted ahead on `PATH` never runs, against the REAL `upgrade.sh`.

    Closing the interpreter left the LAUNCH environment open (review3 MAJOR
    2): `BASH_ENV`/`ENV` run inside Layer 2 before its own
    `_sanitise_layer2_env` ever gets a say, and no importing shell can strip
    an exported function by name reliably enough to promise none survives.
    Layer 1 now launches Layer 2 through the same trusted `env` with `-i` and
    an explicit allowlist instead of a bare inherited environment, so nothing
    outside that list reaches Layer 2 at all. Pinned by
    `TestLayer2EnvIsIsolatedFromTheCaller`: a planted `BASH_ENV` and an
    exported `unset() { :; }` both fail to reach the real Layer 2 process.
    review4 BLOCKER 1 / m2: the list is named per group in `upgrade.sh`, each
    kept or dropped with a reason, and includes Layer 1's own handover (the
    previous version and the old default config/settings baselines) and the
    runtime settings of the daemon Layer 2 restarts. Pinned by
    `TestLayer1HandsItsBaselinesToLayer2` and
    `TestLayer2EnvAllowlistIsDecidedPerSetting`.

    review4 MAJOR 2: Layer 2 sets the trusted `PATH` again after its LAST
    library source (`venv.sh` prepends `$HOME/.local/bin` when sourced) and
    reaches `uv` by name through `_venv_uv`. Pinned by
    `TestLayer2PathAfterEveryLibrarySource`.

    review4 MAJOR 3: Layer 1 keeps the user's git config (dropping it
    wholesale broke `safe.directory` clones), drops the `GIT_CONFIG_*`
    environment overrides, requires one origin URL, and refuses a fetch that
    config rewrites to a different repository. Pinned by
    `TestLayer1FetchesOnlyFromOrigin` and `TestRemoteIdentity`.

    Once that `bash` process starts, Layer 2's OWN first action is
    `_sanitise_layer2_env` (`scripts/install/env_sanitise.sh`), sourced and
    called before any other library: it resets `PATH` to the same fixed
    system locations the gate subprocess trusts, and unsets `BASH_ENV`,
    `ENV`, `CDPATH`, `GLOBIGNORE`, `NODE_OPTIONS`, every
    `PYTHON*`/`LD_*`/`DYLD_*`/`GIT_*`/`PERL5*`/`RUBY*` variable and resets
    `IFS`; `SHELLOPTS`/`BASHOPTS` are bash-maintained and readonly, so the
    options they primed at shell startup are turned back off instead of the
    variable being unset. `HOOKS_DAEMON_PYTHON` (a user's venv-python
    choice), `HOME`, proxy variables and `uv`/cache settings are
    deliberately NOT touched -- they are data the rest of the upgrade
    legitimately needs (building a venv, running `uv`, deploying files is
    not something a fixed-tool sandbox can do), not a way to change what
    code runs. review2 MAJOR 1: this is a fixed, named list of variable
    FAMILIES known to steer execution, not a default-deny allowlist -- on a
    direct Layer 2 call, which skips Layer 1's `env -i`, a variable the list
    has not anticipated still reaches Layer 2, and there the guard (which
    since review4 MAJOR 1 treats every spelling of a steering assignment as
    steering) is the only barrier. The approval gate is therefore a procedural control against an
    agent following the documented route, backed by `upgrade_approval_guard`'s
    best-effort recognition of that route's shape -- not a boundary against a
    same-user process determined to install by hand instead, which no
    in-process check can be. The guard keeps an agent from steering the rest.

  Pinned by the planted-timeout, planted-git and planted-python cases in
  `test_upgrade_pre_deploy_phase_runs_on_layer1.py`,
  `TestUpgradeRecognisedByWhatItIs` and `TestManualCheckoutOfTheDaemonClone`,
  and `TestAlreadyInstalled` in `tests/unit/install/test_upgrade_gate.py`.
  Assumption: the owner's "no known defects" instruction; the owner can
  reverse this with one message.

  - **Owner decision (open, review4 MAJOR 3)**: a daemon clone fetched
    through a `url.<mirror>.insteadOf <github-url>` rewrite. Layer 1 now
    refuses a fetch that config rewrites to a different repository, so a
    project that reaches a corporate mirror that way stops at Step 5 with the
    rewrite named and the remedy printed (point origin at the mirror
    directly). An https-to-ssh rewrite of the same repository still passes.
    Implemented: option A, the fail-closed one.
    - A. Refuse any rewrite to another repository; the owner points origin
      at the mirror (implemented).
    - B. Allow a rewrite to any host, with a loud warning naming both URLs:
      never breaks a mirror setup, but a rewrite an agent planted in the
      user's global config then launches that repository's Layer 2.
    - C. A config key listing trusted mirror URLs that a rewrite may target:
      no breakage for listed mirrors, one more setting to document.

### Phase 4: Fix what the survey exposed

- [x] ✅ **Task 4.1**: `post-upgrade-tasks/` has no runner and no schema test.
  Either give it both or stop requiring plans to write into it; a surface that
  plans are obliged to feed and nothing reads is worse than no surface.
  **Done**: the schema test is Task 2.3's, shared. The runner is
  `check-post-upgrade-tasks`, with the shared loader. It now takes
  `--project-root` and runs any task's `**Detect**` pattern. Layer 1 runs it at
  the end of every upgrade (the way the pre-deploy phase reports). Upgrade.md
  step 6 and LLM-UPDATE.md make carrying the tasks out mandatory. **Decided
  (unattended, 2026-09-24)**: the runner reports and does not act. A task
  changes the client's repository, which is the upgrading agent's job under
  the task's own "ask the user" rules, not a script's (the plan's Non-Goal).
  Assumption: the owner's "no known defects" instruction; the owner can
  reverse this with one message.
- [x] ✅ **Task 4.2**: `install/upgrade_compatibility.py`'s
  `suggest_upgrade_guides` (as the plan found it) scans only
  `CLAUDE/UPGRADES/v{major}/` and never `UNRELEASED/`, so unreleased breaking
  changes are invisible to compatibility checking. Fixed:
  `suggest_upgrade_guides` resolves guides through
  `install/upgrade_guides.py` and takes `include_unreleased` (`None` asks the
  install stamp). The same sweep found that it also missed every
  patch-numbered guide (`v3.62.1-to-v3.63.0` and the three after it) and every
  README-only guide; those are fixed too. Pinned by
  `TestSuggestUpgradeGuidesSeesTheWholeTree` in
  `tests/unit/install/test_upgrade_compatibility.py`. The Layer 2 caller of
  this list is unreachable on the supported route: see Task 1.1.
- [x] ✅ **Task 4.3**: `.claude/skills/hooks-daemon/upgrade.md` has no STEP that
  reads the post-upgrade tasks for the versions just crossed. Do not close this
  on a grep: line 108 does say "follow any referenced post-upgrade task", but
  that is a passing clause inside the config-advisory step, reachable only when
  a config key happens to carry a migration Note. An upgrade that changes no
  config key never reaches it, so the tasks go unread. What is missing is a
  step of its own in the numbered procedure. Fixed: the new
  `hooks-daemon check-post-upgrade-tasks --from --to` lists the tasks of
  every crossed guide (plus `UNRELEASED/` for a branch install). It is run by
  upgrade.md mandatory step 6, by a mandatory Post-Update section in
  `CLAUDE/LLM-UPDATE.md`, and by `scripts/upgrade.sh`, which had the same gap.
  Pinned by `tests/integration/test_post_upgrade_tasks_are_reachable.py`.

### Phase 5: Prove it on Plan 00375

- [x] ✅ **Task 5.1**: Ship 00375's `level` → `severity` rename as the first
  real pre-upgrade migration: detect call sites, propose the rewrite, gate on
  approval because it is MAJOR. **Done, with one part that cannot be done
  from here.** 00375 already shipped, in v3.64.0, as a MINOR release with a
  critical post-upgrade task. A release cannot be re-numbered after it is
  published, so "gate on approval because it is MAJOR" cannot apply to
  v3.64.0: its tag, notes and version are published, and changing them is the
  owner's release decision, not a plan's. What this plan ships instead is
  `CLAUDE/UPGRADES/v3/v3.63.0-to-v3.64.0/pre-upgrade-tasks/01-rewrite-plan-qa-json-level-to-severity.md`,
  a `critical` pre-upgrade task whose `**Detect**:` pattern
  (`plan[-_]qa\b[^\n]*--json`) matches an invocation with `--json`, not a
  `plan_qa.json` file name (review MINOR 5). Any
  upgrade that crosses v3.64.0 (from v3.63 or earlier) to a target carrying
  the gate now names the project's `plan-qa --json` call sites at
  `file:line` before deploying. Where there are any, it needs the owner's
  approval through the critical-with-hits escalation (Task 3.2). The existing
  post-upgrade task stays and points at its twin. Nothing else blocks it: the
  rename (00375) is complete on main.

## Success Criteria

- [x] An agent upgrading to a version with breaking changes is told what will
  break BEFORE anything is installed.
- [x] A project with no affected call sites hears nothing — silence is the
  default, so the signal stays worth reading.
- [x] A project WITH affected call sites gets them named at file:line.
- [x] The proceed/abort gate fires for a non-interactive agent, and aborting
  leaves no partial install.
- [x] Plan 00375's rename ships through this path rather than through a
  deprecation window (as a pre-upgrade task for every upgrade that crosses
  v3.64.0; see Task 5.1 for why v3.64.0 itself stays a minor).
- [ ] Full QA passes and CI is green. Targeted QA passes on the branch. Full
  QA and CI run when the branch is merged, which is not this plan's call.

## Delivery & Milestones

- Motivated by Plan 00375 and the owner's ruling against deprecation windows:
  "i dont like delay - its over complex".
