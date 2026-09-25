# Reconciling the two upgrade redesigns (Plan 00376 and upgrade-scripts / Plan 00464)

Read-only design report (Opus 5.5). No source changes and no merges.

| Branch                                          | Worktree                                       | HEAD        | Merge-base with main (`306a5258d`) |
| ----------------------------------------------- | ---------------------------------------------- | ----------- | ---------------------------------- |
| `worktree-d-00376` (Plan 00376)                 | `untracked/worktrees/worktree-d-00376`         | `ef4aab732` | `a276f971e`, 164 commits behind    |
| `worktree-upgrade-scripts` (Plan 00464 upgrade) | `untracked/worktrees/worktree-upgrade-scripts` | `63d6b21bb` | `19e80abe3`, 142 commits behind    |

Twenty-one files are touched by both branches. The ones that matter are
`scripts/upgrade.sh`, `scripts/upgrade_version.sh`, both copies of the skill's
`scripts/upgrade.sh`, `upgrade.md` and `SKILL.md`, `CLAUDE/LLM-UPDATE.md`,
`CLAUDE/UPGRADES/{README,upgrade-template/README}.md`, `cli.py`,
`rule_ids.py`, `test_upgrade_runs_the_target_versions_steps.py` and
`test_upgrade_recovery_hints.py`. The `cli.py` and `rule_ids.py` overlaps are
additive only, so they are textual conflicts with no semantic clash.

---

## 1. What each branch does today (read from the code)

### 1a. Plan 00376 at `ef4aab732`: a gate inside the old one-command flow

**Flow.** The documented command is still one command.

1. The skill shim curls **main's** `scripts/upgrade.sh` (Layer 1) and runs it.
   The shim's only change is the offline-recovery text and a new flag in the
   usage line.
2. Layer 1 runs `fetch --tags --force`, then `reset --hard <tag>` in the daemon
   dir (`upgrade.sh:678`).
3. Layer 1 launches the target's Layer 2 through `env -i` with an allowlist
   (`upgrade.sh:742-788`).
4. Layer 2 runs its own Steps 1-6: a snapshot (`rollback.sh`), a daemon stop,
   config-baseline capture, and another checkout.
5. **`run_pre_deploy_phase`** (`upgrade_version.sh:411`) runs after Step 6 and
   before Step 7 builds the venv. It launches
   `upgrade_gate_standalone.py` under `env -i PATH=$GATE_SAFE_PATH`,
   `python -I -S` and `timeout`, and the verdict file must carry a nonce.
   The possible verdicts:
   - proceed;
   - exit 3: a reading acknowledgement is needed. The caller re-runs with
     `--skip-reading-confirmation=<digest>`.
   - exit 4: the owner's approval is needed. The owner runs
     `hooks-daemon approve-upgrade` on a TTY.
6. Then the old Steps 7-17 run, plus a second pass
   (`exec bash $LAYER2_TARGET_SCRIPT`, `:1689`) when the target ships a
   different Layer 2.

**Trust boundary.**

- **Inside the run:** the gate subprocess uses fixed tool locations, `env -i`
  and a nonce.
- **Between Layer 1 and Layer 2:** a one-shot handoff file whose writer PID
  must equal `$PPID` (`_read_handoff`, `:153`). Only a valid handoff makes
  `UPGRADE_FLAGS` count.
- **Outside the run:** the new PreToolUse handler `upgrade_approval_guard.py`
  denies these on the agent's command line:
  - `approve-upgrade`;
  - writing an approval marker;
  - forging a venv stamp;
  - `HOOKS_DAEMON_UPGRADE_HANDOFF=`;
  - a steering variable assigned on the same command as an upgrade entry
    point. The list is `_UPGRADE_STEERING_VARS`, `:148`.

**Env and PATH.**

- Layer 1 sets `GIT_CONFIG_GLOBAL=/dev/null` and `GIT_CONFIG_NOSYSTEM=1`
  before the fetch (`:548`).
- Layer 2 calls `_sanitise_layer2_env` from `scripts/install/env_sanitise.sh`
  at entry. It also unsets every imported function (`:29-31`).

**Rollback.**

- A gate stop runs `abort_before_deploy` (`:302`). It sends the daemon dir back
  with `git reset --hard <installed ref>`. The ref is resolved by
  `_restore_target`: the venv stamp first, then `HOOKS-DAEMON.md`, then the
  handoff ref.
- A failure after the gate uses the old `rollback.sh` snapshot.

**What an OLD client sees.**

- The old shim fetches main, so it gets this Layer 1 at once.
- If the target predates `env_sanitise.sh`, Layer 1 falls back to a bare
  `bash`, and the old Layer 2 runs with no gate.
- If an old or pinned Layer 1 calls a gated Layer 2, `UPGRADE_CALLER=pre-gate-layer1`.
  Layer 2 warns that Layer 1 will report success anyway (`:284-291`).

**Review 4 at `ef4aab732`.** The commit message says "review4 follow-up", but
review 4 is a review OF `ef4aab732`. Its file is dated 10:28 and the commit
10:14, and the file is still **untracked** in that worktree.

What the commit actually fixed:

- `HOOKS_DAEMON_UNSAFE_TRACK_REF`/`_BECAUSE` now reach Layer 2.
- The unknown-range guide listing.
- A root-safe EACCES test.

**None of B1, M1, M2 or M3 is fixed at `ef4aab732`.** I checked each in the
code:

| Item         | State at `ef4aab732`                                                                                                                                                                                                                       |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1           | **Open.** The allowlist at `upgrade.sh:759-775` still lacks `HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION`, `HOOKS_DAEMON_OLD_DEFAULT_CONFIG`, `_OLD_DEFAULT_PID` and `HOOKS_DAEMON_OLD_DEFAULT_SETTINGS`, which are exported at `:434/:461/:479` |
| M1           | **Open.** `_STEERING_ASSIGN_RE` (`upgrade_approval_guard.py:175-180`) is unchanged: `declare -gx`, `export --`, `set -a`, `printf -v` and `read` all pass                                                                                  |
| M2           | **Open.** `scripts/install/venv.sh:26-28` still prepends `$HOME/.local/bin` after `_sanitise_layer2_env`                                                                                                                                   |
| M3           | **Open.** `upgrade.sh:548-549` is unchanged, so a foreign-owned clone that relies on a global `safe.directory` still fails                                                                                                                 |
| m1-m4, n1-n2 | Open. m3 (the off-root early return) and m4 (release-note renumbering) are unchanged                                                                                                                                                       |

### 1b. upgrade-scripts at `63d6b21bb`: the two-command staged upgrade

**Flow.**

- **Step 1** is `scripts/upgrade.sh`, 441 lines. It:

  1. refuses self-install;
  2. clones the daemon dir if it is missing and a config exists;
  3. reads FROM from `HOOKS-DAEMON.md` or the clone;
  4. runs `ls-remote` for the latest `vX.Y.Z`;
  5. runs `git clone --depth 1 --branch <tag>` into
     `.claude/hooks-daemon/untracked/upgrade-staging/<stamp>-<pid>/`, after an
     `rm -rf` of any earlier staging;
  6. checks that the staged HEAD is the tag's commit;
  7. requires the line `# layer2-capability: staged-apply` in the staged Layer 2;
  8. prints the step-2 command and an `UPGRADE_STAGED` block, then exits **3**.

  It **runs none of the fetched code and never touches the installed checkout.**
  "Verifies the tag" means only the HEAD-equals-tag check and the capability
  line. There is no signature check and no check of the remote's identity.

- **Step 2** is the **staged** `upgrade_version.sh`, run by its literal path.

  - It sources every library from the staged tree **before** the swap, and
    runs no script file after it.
  - `APPLY_MODE` is `staged` or `in-place`.
  - It checks that the checkout's HEAD equals `TARGET_VERSION`.
  - It runs `stop_daemon_if_any`, which stops through the CLI (the verified
    PID file).
  - It runs `swap_in_staged_tree` (`scripts/install/staged_swap.sh`). This is
    rename-only: the old tree, drift included, moves to
    `untracked/upgrade-backups/<stamp>`.
  - Then it rebuilds the venv, redeploys, restarts, and emits
    `UPGRADE_METADATA` (`scripts/install/upgrade_report.sh`). Backups are
    pruned to 3.

- **Skill shim.** It now runs the **installed** Layer 1, found relative to
  itself, not a copy curled from main.

- **Install.** It is two-step. `--force` means an upgrade to the installed
  version, and the venv-aside machinery is deleted.

**Trust boundary.** The Plan 00464 PreToolUse gates read the exact bytes of
the step-2 script before it runs. A tampered staged Layer 2 is therefore
denied: the e2e test covers `tampered staged layer 2`.

- There is **no** pre-deploy gate.
- There is **no** owner approval.
- There is **no** environment sanitising in Layer 2.

**Env and PATH.**

- Nothing is sanitised, so M2's `venv.sh` PATH prepend applies here too.
- Branch-install variables travel as literal assignments in the printed
  command.
- FROM travels as `--from-version` on argv.

**Rollback.**

- `cleanup_on_failure` (`:213`) swaps the backup back and restarts the old
  daemon.
- It covers **only the daemon dir.**
  - The `rollback.sh` project snapshot is gone.
  - Hook forwarders, skills and slash commands already redeployed from the
    target are **not** restored when a later step fails.
  - `settings.json` keeps its own backup.

**Removed behaviour (not called out in the brief).**

- Step 10 config preservation (`merge_custom_config`) is gone. The module
  docstring of `test_upgrade_old_default_baseline.py` states it: "never
  rewrites the client's config".
- The `CompatibilityChecker` / `BreakingChangesDetector` report is gone.
- The second-pass re-exec is gone. That removal is correct: it cannot be
  judged by the gates.

**What an OLD client sees.**

1. Its shim curls **main's** Layer 1, which is now the staging script.
2. Step 1 exits 3 with a printed command. The old `upgrade.md` expects exit 0
   and `UPGRADE_METADATA`, so the old agent has to follow the printout.
3. The old client's gates do not read scripts, so they allow step 2.
4. **The catch:** Layer 1 refuses any target whose Layer 2 lacks the
   capability line. **Every release published today lacks it.** Between the
   merge to main and the first release that carries it, every old client
   behind the latest release gets "predates staged upgrades… a person can
   apply it" instead of an upgrade (see Q1).

**Readiness.**

- `TestN61SameCommandAddIsNotYetCaught` is committed RED on purpose
  (`2b0701875`), waiting on N53. The gate cannot pass until N53 lands.
- The branch carries the whole Plan 464 tip (`3666b06d9`), which is **not on
  main**.
- The round-2 report names HEAD `3ce762a41`. Since then, `2b0701875`,
  `1bfe8cc62` and a merge of origin/main have been added.

---

## 2. Agreement, conflict and subsumption

**They agree on:**

- the owner's rule;
- the branch-install gate;
- the self-install refusal;
- reading FROM from the tracked `HOOKS-DAEMON.md` marker;
- the metadata contract;
- verified-PID stops and no broad signals;
- the principle that the upgrade must not run code nobody judged. 00376
  enforces this in-process (a nonce'd gate on trusted tools). upgrade-scripts
  enforces it at the hook boundary (gates read the bytes).

**They conflict on the following:**

| Topic                               | Plan 00376                                                            | upgrade-scripts                                       | Resolution                                                                                                                                                                                                 |
| ----------------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| How the daemon dir changes          | `reset --hard` in Layer 1, and again on abort                         | rename-only swap with a timestamped backup            | **Take upgrade-scripts'.** Delete `abort_before_deploy`'s reset and `_restore_target`                                                                                                                      |
| Layer 1 → Layer 2 channel           | one process tree: handoff file, `env -i` allowlist, env data handover | two commands: argv and the printed command            | **upgrade-scripts' subsumes it.** The handoff file, `UPGRADE_CALLER`, `pre-gate-layer1`, the `_LAYER2_ENV_ALLOWLIST` and B1 all disappear. The env data B1 lost comes from the backup tree instead (below) |
| Where the shim's Layer 1 comes from | main, via curl                                                        | the installed copy                                    | **upgrade-scripts'.** Drop 00376's shim edit                                                                                                                                                               |
| Exit code 3                         | "reading acknowledgement needed" (Layer 2)                            | "staged" (Layer 1)                                    | Keep 3 for "staged": it is what old clients meet first. Renumber the gate's stops to 4 (acknowledgement) and 5 (approval)                                                                                  |
| Config merge                        | kept, and B1 breaks its baseline                                      | removed outright                                      | **Owner decision (Q2).** I recommend restoring it with the backup tree as the baseline                                                                                                                     |
| Rollback scope                      | `rollback.sh` project snapshot plus git ref                           | daemon dir only                                       | Keep the swap, and restore the `create_state_snapshot` project snapshot for `.claude/hooks`, skills, commands and the config (it is a data copy, not a script run)                                         |
| Git config handling                 | `GIT_CONFIG_GLOBAL=/dev/null` (M3 regression)                         | none (a global `insteadOf` still redirects the clone) | Neither is right. Use review 4's M3 direction, applied to step 1's `ls-remote` and `clone`                                                                                                                 |
| Direct Layer 2 call                 | a "supported entry point", and M1's bypass                            | the **only** entry point                              | Step 2 is always a direct call, so M1's class becomes the main path. Enforce one canonical launch shape (below) rather than chasing spellings                                                              |

**Where one subsumes the other:**

- **upgrade-scripts subsumes 00376's Layer 1 entirely:** env-i launch, git
  config isolation, handoff, recovery text in the shim, second pass and
  pre-gate warning.

- **00376 adds what upgrade-scripts lacks entirely:**

  - the pre-deploy gate (`upgrade_gate.py`, `upgrade_gate_standalone.py`,
    `upgrade_guides.py`, `upgrade_tasks.py`);
  - the owner-approval flow (`cli.py cmd_approve_upgrade`, `OneShotApprovalStore`
    markers);
  - `check-post-upgrade-tasks`;
  - pre-upgrade and post-upgrade task docs and templates under `CLAUDE/UPGRADES/`;
  - `upgrade_approval_guard.py`;
  - `env_sanitise.sh`'s trusted-tool resolver (`_gate_tool`,
    `_gate_trusted_path`, `_gate_dir_is_trusted`);
  - `run_config_compatibility_check`.

  **None of this is invalidated by staging.** It moves into step 2, before
  the swap.

---

## 3. The combined design and the merge order

### 3a. The combined design

**Step 1: stage.** This is upgrade-scripts' `scripts/upgrade.sh`, plus:

- **Git fetch hardening (M3), without dropping the user's global config.**
  - Unset `GIT_CONFIG_COUNT`, `GIT_CONFIG_PARAMETERS` and the
    `GIT_CONFIG_KEY_*`/`GIT_CONFIG_VALUE_*` families.
  - Refuse to stage when
    `git -C "$DAEMON_DIR" config --show-origin --get-regexp '^(url\..*\.(push)?insteadof|include\.|includeif\.|core\.sshcommand)$'`
    returns anything.
  - Refuse an origin URL that is not the canonical https URL or a local path
    (Q4).
  - `safe.directory` and credential/proxy/CA config keep working.
- Print a step-2 command in **one canonical shape** (Q3):
  `<trusted env> -i HOME=… LANG=… [proxy/CA vars as literals] [TRACK_REF pair] <trusted bash> <staged>/scripts/upgrade_version.sh <root> <dir> <target> --from-version vX [--skip-config-optimisation]`
  - Layer 1 cannot source libraries, so it carries its own copy of the
    `GATE_SAFE_PATH` trusted-directory resolver. Keep the copy "in step",
    pinned by a test the way `branch_install.sh` is.
  - `env -i` in the command removes `BASH_ENV`, `ENV` and `BASH_FUNC_*` before
    bash starts. No in-process check can do that, which is review 4's point
    about M1.
- Optionally list the staged tree's `CLAUDE/UPGRADES/**` guide **paths** as
  data. **Never run the gate here**: it is fetched Python.

**Step 2: apply.** This is upgrade-scripts' staged `scripts/upgrade_version.sh`,
plus the following, in this order:

01. `_sanitise_layer2_env` (from 00376's `env_sanitise.sh`), sourced first as
    00376 does it.
02. **Re-apply `PATH="$(_gate_trusted_path)"` after the last `source`** (M2).
    Also delete the source-time `export PATH="$HOME/.local/bin:$PATH"` in
    `venv.sh:26-28`, and resolve `uv` as an explicit `$HOME/.local/bin/uv`
    fallback in `prerequisites.sh`. upgrade-scripts' uv bootstrap already
    installs into a daemon-owned venv, so this fits.
03. Step 1, the safety checks, unchanged.
04. Step 2, reading `INSTALLED_VERSION` from the **venv stamp**, then
    `_installed_release_from_docs`.
    - **`--from-version` stays informational only.** It is an argv value the
      agent can edit, so the gate must never take its range from it. Unknown
      means escalate, exactly as 00376's `_unknown_range_report` does.
05. **New Step 2a, the pre-deploy gate (`run_pre_deploy_phase`), run BEFORE
    `stop_daemon_if_any` and the swap.**
    - The gate reads guides from the **staged** tree. Pass `--daemon-dir "$THIS_CHECKOUT"`
      for the target, and keep approvals and stamps keyed to the installed
      `DAEMON_DIR`'s `untracked/`.
    - A stop just exits 4 or 5:
      - nothing was stopped, swapped or deployed;
      - the daemon keeps running the old version;
      - the staging is kept, so the same step-2 command is simply re-run after
        the acknowledgement or approval.
    - `abort_before_deploy`, `_restore_target`, `_read_handoff`,
      `_warn_about_a_pre_gate_layer1`, `UPGRADE_FLAGS` and the handoff are all
      **deleted**.
    - `_take_acknowledgement` reads argv only.
    - `consume_used_approval` runs after `UPGRADE_DONE=true`.
06. Step 3: stop, then swap. In-place mode (see the note after this list) sits
    here.
07. Step 4: venv, `verify_venv`, then **`run_config_compatibility_check`**
    (00376, report only), then the deploys.
08. **Config merge restored (Q2).**
    - `merge_custom_config` gets `OLD_DEFAULT_CONFIG="$SWAP_BACKUP_DIR/.claude/hooks-daemon.yaml.example"`,
      the same way upgrade-scripts already takes the settings baseline from
      `$SWAP_BACKUP_DIR/.claude/settings.json`.
    - **This is B1's fix in the combined design:** the baseline is a file in
      the backup, not an environment variable, so there is nothing for `env -i`
      to drop.
09. Project snapshot: `create_state_snapshot` before the first deploy.
    `cleanup_on_failure` restores it as well as swapping the daemon dir back.
10. `check-post-upgrade-tasks` at the end (00376 Task 4.2).

**In-place mode when the target does not match the installed stamp.** This is
an old or pinned Layer 1 that has already run `reset --hard`, then calls the
new Layer 2 from the daemon dir.

- Run the gate as usual.
- On a stop, move the daemon dir back to the installed ref with a
  **non-forcing** `git -C "$DAEMON_DIR" checkout --quiet --detach <ref>`. The
  tree is clean after the old Layer 1's reset. Refuse, and print the command,
  if it is not clean.
- Never use `reset --hard`.

**The guard (`upgrade_approval_guard.py`).**

- Keep `R-UPGRADE-APPROVAL-AGENT` as it is.
- Redefine `R-UPGRADE-APPROVAL-ENV-BYPASS`: **executing** `upgrade_version.sh`
  is allowed only in the canonical shape above, as the whole command.
  - Deny it when it is chained or prefixed.
  - Deny it under any other wrapper.
  - Deny any `NAME=` other than the allowlisted literals.
  - This replaces the spelling denylist that M1 keeps defeating (`declare -gx`,
    `export --`, `set -a`, `printf -v`, `read`, indirect export).
- Drop `ENV_VAR_UPGRADE_HANDOFF`: there is no handoff.
- Add the daemon clone's `.git/config` to the path predicates (review-3 m2
  residual).
- Narrow the `UV_*`/`PIP_*` passthrough to `UV_CACHE_DIR` and `UV_LINK_MODE`
  (m1). Record the other knobs from m2 as kept or dropped, one reason each, in
  the allowlist comment.

### 3b. Merge order

The steps are sequential. Each lands on main only after its own gate run
shows `exit=0 head=<its HEAD>`.

0. **Prerequisites (not these branches).** N53's fix, then
   `worktree-plan-464-commit-gate-repo` (tip ≥ `3666b06d9`), land on main.
   upgrade-scripts already contains the 464 tip, and its committed-RED N61 test
   needs N53.

1. **upgrade-scripts lands first**, after a merge of current main.

   - It is the structural redesign.
   - It already carries e2e tests through the real hooks.
   - Its Layer 1 would delete 00376's Layer 1 changes whatever the order.
   - Before it lands:
     - restore the config merge from the backup baseline (Q2) in
       `scripts/upgrade_version.sh` Step 4, using `config_preserve.sh`
       `resolve_old_default_config`/`merge_custom_config`;
     - restore the project snapshot (`rollback.sh create_state_snapshot`,
       plus `cleanup_on_failure`);
     - apply the M2 fix (`venv.sh`, `prerequisites.sh`), which is independent
       of the gate;
     - apply the M3 fetch hardening in `scripts/upgrade.sh` Steps 5-6;
     - add the old-shim e2e test (§4 T1).
   - **Cut a release from that merge at once (Q1).** Main's Layer 1 is what
     every old client's shim runs.

2. **Plan 00376 becomes a port, not a rebase.** Start a fresh branch from main
   after step 1 and carry over by path. Rebasing its 22 commits would conflict
   on every Layer 1 hunk it is about to delete.

   **Ported unchanged:**

   - `src/.../install/upgrade_gate.py`, `upgrade_gate_standalone.py`,
     `upgrade_guides.py`, `upgrade_tasks.py`, `upgrade_compatibility.py`
     changes, and their unit tests;
   - `cli.py`: `cmd_approve_upgrade`, `cmd_check_post_upgrade_tasks` and the
     parsers;
   - `rule_ids.py`: the two IDs;
   - `CLAUDE/UPGRADES/**` pre-upgrade and post-upgrade tasks, the template and
     the v3.63-to-v3.64 pre-upgrade task;
   - `scripts/qa/check_daemon_dir_cd_in_docs.py`;
   - `scripts/lib/resolve_venv.sh` and `python_discovery.sh` (N37);
   - the release notes, renumbered at merge (m4).

   **Ported and adapted:**

   - `scripts/install/env_sanitise.sh`: keep it as is.
   - `upgrade_version.sh`:
     - add `run_pre_deploy_phase`, `_pick_gate_python`, `_target_release`,
       `_installed_release_from_docs`, `_take_acknowledgement` (argv only),
       `consume_used_approval` and `run_config_compatibility_check` into the
       staged Layer 2 at the positions in 3a;
     - gate exit codes become 4 and 5.
   - `upgrade_approval_guard.py`: the canonical-shape rule (M1), the
     `.git/config` predicate, and the handoff removal.
   - `scripts/upgrade.sh`: the canonical `env -i` step-2 printout (Q3), plus
     its trusted-tool copy.
   - `upgrade.md`, `SKILL.md`, `LLM-UPDATE.md`: gate stops in step 2, and the
     re-run with `--skip-reading-confirmation=DIGEST`.

   **Dropped:**

   - 00376's entire `scripts/upgrade.sh` diff: the `env -i` launch,
     `GIT_CONFIG_GLOBAL`, the handoff, and the Step 5-8 reset path;
   - `abort_before_deploy`, `_restore_target`, `_read_handoff`,
     `_warn_about_a_pre_gate_layer1`, `UPGRADE_CALLER`, and the second-pass
     re-exec;
   - its skill shim edit;
   - `test_layer1_launches_layer2_via_trusted_bash.py` and the Layer 1 half of
     `test_upgrade_pre_deploy_phase_runs_on_layer1.py`. Rewrite that file as
     "gate runs in the staged step 2 before the swap".

   Fix m3: replace the `geteuid() != 0` early return in
   `test_upgrade_pre_deploy_phase_placement.py:227` with a monkeypatched `stat`.

   Commit the untracked review-4 file into the 00376 plan folder.

3. Release again. The gate lives in the staged target, so a client on the
   step-1 release upgrading to this one meets the gate with no further
   compatibility work.

Landing 00376 first instead would mean fixing B1 and M3 in code that step 1
then deletes, and it would put a second Layer 1 on main that every old client
runs.

---

## 4. The e2e tests that must pass before anything merges

All of these go through the **real** PreToolUse chain, in a fresh dummy client
(`scripts/dummy-client-repo.sh`) and in this repository. They must end
RUNNING where relevant, and none may be skipped or marked xfail.

T1 and T3-T6 are new. T2, T4's tampered case, T13 and T15 exist on
upgrade-scripts. T10 and T11 partly exist on 00376.

| #   | Test                                                                                                                                                                                                                                                                                                                                                                                                                                       | Gate for step |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------- |
| T1  | **Old client, last real release, via its OWN deployed shim**, using `HOOKS_DAEMON_UPGRADE_BASE_URL=file://…` and `_REF` pointing at the tree's `scripts/upgrade.sh`. Step 1 exits 3. The OLD gates allow the printed command, which runs. The daemon is RUNNING, `UPGRADE_METADATA` is emitted, drift is kept in the backup, config customisations survive, and a new default arrives                                                      | 1             |
| T2  | Old client, the documented LLM-UPDATE route (a lone scratch copy of Layer 1). Exists as `TestFromAnOlderRelease`                                                                                                                                                                                                                                                                                                                           | 1             |
| T3  | Old client two or more releases back, including one whose shim still sends `--already-bootstrapped`                                                                                                                                                                                                                                                                                                                                        | 1             |
| T4  | Tree to next through the new shim with the tree's gates live. Every documented command is allowed. A tampered staged Layer 2 is DENIED, **and so is a tampered staged library that Layer 2 `source`s** (e.g. `scripts/install/venv.sh`). Only the first of these is tested today                                                                                                                                                           | 1             |
| T5  | Failure after the swap (for example, forced `verify_venv` failure). The daemon dir is swapped back, the project snapshot is restored (hook forwarders, skills, config), and the old daemon is RUNNING                                                                                                                                                                                                                                      | 1             |
| T6  | Fresh install from nothing, two-step, RUNNING. `install --force` means upgrade to the same version and keeps a backup. The retired curl-to-shell branch and a FORCE on an existing checkout fail loudly with the exact command                                                                                                                                                                                                             | 1             |
| T7  | Fresh-clone teammate (config present, no daemon dir): step 1 clones and stages, step 2 applies, RUNNING                                                                                                                                                                                                                                                                                                                                    | 1             |
| T8  | An agent-run downgrade to a pre-staged release is refused with the `!` message. The human-run printed command works                                                                                                                                                                                                                                                                                                                        | 1             |
| T9  | Self-install (this repo): step 1 refuses with the git instructions. `bin/hooks-daemon restart` still RUNNING                                                                                                                                                                                                                                                                                                                               | 1             |
| T10 | Branch install through both steps: both `TRACK_REF` variables reach Layer 2, and (step 2 of the merge order) the gate receives `--include-unreleased`                                                                                                                                                                                                                                                                                      | 1, 2          |
| T11 | Git config: a foreign-owned clone with a global `safe.directory=*` upgrades (M3 regression). A global or clone `url.insteadOf`, or an `include.path`, refuses to stage. `GIT_CONFIG_COUNT` is ineffective                                                                                                                                                                                                                                  | 1             |
| T12 | PATH: logging `git`, `cksum`, `uv` and `python3` are planted in `~/.local/bin`, and none of them runs in step 2. Layer 2's PATH is asserted **after the last `source`**                                                                                                                                                                                                                                                                    | 1             |
| T13 | N61: literal `git add leak.txt && git commit` is DENIED, and the clean control is allowed                                                                                                                                                                                                                                                                                                                                                  | 1             |
| T14 | Gate paths. A minor release proceeds. A guide stop exits 4 with nothing stopped or swapped and the old daemon still RUNNING; the re-run with the digest proceeds. A major exits 5. The agent's `approve-upgrade` is DENIED. After the owner approves over a TTY, the upgrade proceeds and the marker is consumed. With an unknown FROM (no stamp, no `HOOKS-DAEMON.md`) it escalates. An edited `--from-version` does not shrink the range | 2             |
| T15 | Env. The canonical step-2 command is allowed. Each M1 spelling (`declare -gx`, `export --`, `set -a`, `printf -v`, indirect `export "$n=…"`, `declare -f -x`), any chaining, and any extra `NAME=` are DENIED. A `BASH_ENV` or exported function present in the session environment never runs in Layer 2                                                                                                                                  | 2             |
| T16 | B1 in its new form: the config and settings merge baselines come from the backup. A new default reaches a client that had accepted the old one. The "Current version" line shows the FROM version                                                                                                                                                                                                                                          | 1, 2          |
| T17 | A pinned old Layer 1 into an in-place new Layer 2: the gate runs. On a stop, the dir returns to the installed ref by non-forcing checkout, and the old daemon is RUNNING                                                                                                                                                                                                                                                                   | 2             |
| T18 | A second upgrade after a first: the earlier staging is removed and backups are pruned to 3                                                                                                                                                                                                                                                                                                                                                 | 1             |

---

## 5. Owner questions (each with my recommended answer)

- **Q1.** Every old client's skill shim runs main's `scripts/upgrade.sh`. Once
  upgrade-scripts is on main, that script refuses every existing release for
  an agent, because none carries the staged-apply capability line. So any
  client behind the latest release cannot upgrade through an agent until a
  release with the line exists. **Should the merge and a release be one
  action?**
  **Recommended: yes.** Tag a release from the merge commit in the same
  session, and do not merge upgrade-scripts to main on any day a release
  cannot follow.
- **Q2.** upgrade-scripts removed the config merge. Main merges a client's
  customisations onto each new default, and upgrade-scripts "never rewrites
  the client's config". Without the merge, a new default never reaches a
  client that had accepted the old one. **Should the merge come back?**
  **Recommended: yes, restore it.** Take the baseline from the backup tree's
  `.claude/hooks-daemon.yaml.example`. That also fixes B1 structurally.
- **Q3.** **Should the printed step-2 command itself be the sanitised launch,
  and should the guard allow executing `upgrade_version.sh` in that one shape
  only?** The shape is `<trusted env> -i` with a fixed allowlist of HOME,
  LANG, proxy/CA variables, `UV_CACHE_DIR`/`UV_LINK_MODE` and the two
  branch-install variables, then `<trusted bash>`.
  **Recommended: yes.** It closes M1's class and the persistent-environment
  route that the guard cannot see, and it needs no in-process detection.
  The cost is that other operator knobs (`HOOKS_DAEMON_VENV_*`, `CI`,
  `VERBOSE`) no longer pass through unless they are listed.
- **Q4.** **Is a daemon clone whose `origin` is not the canonical GitHub https
  URL (a fork or a mirror) supported for agent-run upgrades?**
  **Recommended: no.** Step 1 refuses a non-canonical origin, or any
  `insteadOf`/`include`/`sshCommand` config, and prints a human-run command
  for the rare mirror user. A redirected fetch stages code whose Python the
  gates never read.
- **Q5.** **When the FROM version cannot be told** (a fresh-clone teammate
  whose `HOOKS-DAEMON.md` has no stamp, and there is no venv), **should the
  gate still need the owner's approval?**
  **Recommended: yes, fail closed.** It applies only when both sources are
  missing. A teammate whose committed `HOOKS-DAEMON.md` carries a stamp gets
  an ordinary known range.
