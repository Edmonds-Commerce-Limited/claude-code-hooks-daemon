# What depends on `.claude/hooks/*` being tracked in git

Explore agent report, 2026-09-08. Scope: read-only survey. No recommendation is
made about whether tracking should be kept; this records only what exists.

## 0. Baseline facts

- `git ls-files .claude/hooks/` returns **49 paths**: 31 top-level forwarder
  scripts plus an 18-path `handlers/` subtree.
- **27 of the 31 forwarders bake `/workspace`** as a literal
  (`_rl_dir="/workspace/untracked"`, `_rl_bin="/workspace/untracked/bin/hooks-relay"`).
  Confirmed by grep; matches the count stated at
  `src/claude_code_hooks_daemon/install/forwarder_generator.py:216`
  ("two distinct lines, in 27 of the 31 tracked hook files").
- No `.gitignore` anywhere ignores `.claude/hooks/`. `.claude/.gitignore:9`
  ignores only `/hooks-daemon/`; `:11-13` ignore `hooks.bak/` and `hooks.bak.*/`
  (backup dirs, not the live dir).
- The baked content is written by *runtime* commands and then committed:
  `git log -- .claude/hooks/` shows `16fdac8e "Plan 00294: Phase 3 - relay
  dogfood re-enabled via transport on"`, `9d353fd3 "EMERGENCY: suspend relay
  dogfood"`, `54422e79 "Plan 00290: dogfood the relay transport in this repo"`.

---

## 1. Q2 (the crux) - the installer COPIES the repo's tracked hooks

**Load-bearing for client installs. Tracking cannot simply be dropped.**

The client path is:

1. `install.sh:83` - `git clone --branch "$DAEMON_BRANCH" --depth 1
   "$DAEMON_REPO" "$DAEMON_DIR"` into `<client>/.claude/hooks-daemon`. The
   tracked `.claude/hooks/*` arrive with that clone.
2. `install.sh:93` - `exec bash "$LAYER2_SCRIPT" "$PROJECT_ROOT" "$DAEMON_DIR"`
   (`scripts/install_version.sh`).
3. `scripts/install_version.sh:372` -
   `deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "normal" "$VENV_PYTHON"`.
4. `scripts/install/hooks_deploy.sh:130-131`:

   ```sh
   local source_hooks="$daemon_dir/.claude/hooks"
   local target_hooks="$project_root/.claude/hooks"
   ```

   then `scripts/install/hooks_deploy.sh:154` enumerates
   `find "$source_hooks" -maxdepth 1 -type f` and `:168` does a plain
   `cp "$source" "$target"`.
5. `scripts/install/hooks_deploy.sh:142-145` **hard-fails** if `$source_hooks`
   is absent (`print_error "Source hooks directory not found"; return 1`), and
   `:156-158` warns then returns 0 (silently deploying nothing) if the
   directory exists but is empty.

**`install_version.sh` never invokes `install.py`.** Grep for `install.py` in
that file returns only a comment at line 70. The primary Layer-2 client install
has no generator path at all - the tracked files ARE the deployment source.

The same copy runs on upgrade: `scripts/upgrade_version.sh:304` and
`scripts/upgrade_version.sh:855`, both `deploy_all_hooks ... "normal" ...`.

The **only** generating path is the legacy fallback in `install.sh:120-123`
(`python3 "$DAEMON_DIR/install.py" --force`), used only when
`scripts/install_version.sh` is missing. `install.py` genuinely creates the
files: `install.py:1447` `create_all_hooks(hooks_dir)` -> `install.py:662-682`
-> `create_forwarder_script` (`:376-492`, `hook_file.write_text(hook_content)`
at `:489`) and `create_status_line_script` (`:495-543`).

Post-copy, `scripts/install/hooks_deploy.sh:534` calls
`regenerate_forwarders_for_transport`, which runs `forwarder_generator`
(`:470-471`). That module **strips any foreign guard block unconditionally**
before re-applying per the client's own config -
`src/claude_code_hooks_daemon/install/forwarder_generator.py:153-172` and
`:326-336`. Its docstring at `:158-170` states the reason explicitly:

> "the deployed forwarder a client receives is a copy of THIS repository's own
> `.claude/hooks/*`, which (since this repo dogfoods the relay) already carries
> a guard block pointing at THIS repository's own paths."

So the machine-specific `/workspace` literal in the tracked files is a known,
actively mitigated contamination vector (Plan 00290 findings F1/F2/F4), not an
unnoticed one. Note `regenerate_forwarders_for_transport` is best-effort:
`hooks_deploy.sh:465-468` skips it entirely when no venv python is available,
and `:472` downgrades failure to a warning, in which case the client keeps the
`/workspace`-bearing copy.

Also relevant: the ownership manifest declares this as an official deployed
asset - `src/claude_code_hooks_daemon/install/client_owned_assets.py:135-144`,
`source=".claude/hooks/*"`, `deployed_to=".claude/hooks/*"`,
`deployed_by="install.py"` (the `deployed_by` attribution is stale relative to
the shell path above).

---

## 2. Q1 - Readers of `.claude/hooks/*` from a checkout

### 2a. Assume presence in a PRISTINE checkout, before any install step

This is the sharp category, because **CI deliberately runs no install**:
`.github/workflows/qa.yml:135-149` says "DO NOT add `python install.py
--self-install` here... Nothing needs installing. A checkout already has the
config, **the forwarders** and the package". CI writes only
`.claude/hooks-daemon.env` (`:157-159`) and starts the daemon. Every test below
therefore runs against the git-checked-out files.

| Location | What it does with them |
| --- | --- |
| `tests/integration/test_dogfooding_hook_scripts.py:37` | reads every file in the repo's `.claude/hooks/`; `:41-45`, `:120-231`, `:233-249` |
| `tests/integration/test_hook_coverage_completeness.py:108,200-205` | `assert forwarder.is_file()` + `os.access(..., X_OK)` for **every wired event** - the hardest structural dependency |
| `tests/integration/test_forwarder_jq_free.py:42,159,220-228` | executes `bash <repo>/.claude/hooks/<wrapper>` as a subprocess, and iterates the whole directory asserting no `jq` |
| `tests/integration/test_hook_exec_bit_irrelevant.py:20,37,66` and `:87,107,130` | `shutil.copy` of the real `pre-tool-use` and `status-line` into tmp, then runs them |
| `tests/integration/test_hooks_deploy_relay_guard.py:20,48,70,88,116,148,212` | `_SOURCE_HOOKS_DIR = _REPO_ROOT/".claude"/"hooks"`; builds its fake daemon_dir by copying real tracked forwarders into it |
| `tests/integration/test_relay_event_socket_real_payloads.py:68,267-269` | `assert source_path.is_file(), f"{meta.bash_key}: no deployed forwarder found"` then reads it |
| `tests/unit/test_ci_passthrough.py:37,160-161` | `assert hook_path.exists(), f"Hook script not found: {hook_path}"` |
| `tests/acceptance/test_stop_hook_hard_block.py:42-43` | `STOP_HOOK = REPO_ROOT/".claude"/"hooks"/"stop"`, `SUBAGENT_STOP_HOOK = .../"subagent-stop"`; invokes them as subprocesses. One of the gates Plan 00250 is wiring into CI |
| `tests/acceptance/test_transport_toggle_cycle.py:158-164` | `shutil.copytree(REPO_ROOT/".claude"/"hooks", claude_dir/"hooks")` to build its isolated fixture project |
| `tests/unit/install/test_client_owned_assets.py:64-72` | `test_every_source_glob_resolves` - fails if the `.claude/hooks/*` glob matches nothing. `:74-79` `resolve_sources` must return existing files. `:236-252` asserts each resolved file carries the ownership banner |
| `tests/integration/test_client_owned_asset_lint.py:102,297-312` | resolves the same manifest globs and runs `shellcheck --norc -x` over each `.claude/hooks/*` file; `:297-302` `test_manifest_has_shell_assets` is an explicit anti-vacuity control |
| `scripts/qa/run_smoke_test.sh:23-24,102-104` | `HOOK_STOP="${PROJECT_ROOT}/.claude/hooks/stop"`, `HOOK_PRE=".../pre-tool-use"`, executed; invoked by `scripts/qa/llm_qa.py:343` |
| `scripts/qa/check_python_var_guidance.py:55-62` | scans `.claude/` as a tree (soft: an empty dir yields no violations). `:188` excludes `.claude/hooks.bak` |

Plus a runtime, non-test dependency on the tracked **subtree**:
`.claude/hooks-daemon.yaml:967-971` registers
`plugins.paths: [".claude/hooks/handlers/session_start"]` with handler
`dogfooding_reminder`. The tracked
`.claude/hooks/handlers/session_start/dogfooding_reminder.py` (and its test) is
loaded by this repo's own daemon. This is *separate content from the 31
forwarders* and would be lost by a blanket ignore of the directory.
(`install.py:44-48` notes the scaffolder was moved off `.claude/hooks/handlers`
to `.claude/project-handlers` precisely because it was "a path nothing ever
loaded" - but this repo's own config still points at the old location.)

### 2b. Read the DEPLOYED hooks in a live install (present after install; NOT a tracking dependency)

- `scripts/install/hooks_deploy.sh:252` (`set_hook_permissions`), `:380`
  (`git_force_executable`), `:566` (`verify_hooks_deployed`) - all operate on
  `$project_root/.claude/hooks`, post-deploy.
- `scripts/health_check.sh:186` - `HOOKS_DIR="$PROJECT_ROOT/.claude/hooks"`.
- `src/claude_code_hooks_daemon/install/transport_toggle.py:347,386,411` and
  `src/claude_code_hooks_daemon/install/transport_verify.py:168-234,352-381,449-463`
  - `transport on|off|verify` rewrites and probes the deployed dir. **In this
  self-install repo the "deployed dir" IS the tracked dir**, which is how the
  `/workspace` literals came to be committed.
- `install.py:713` - `create_settings_json` emits
  `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/{bash_key}`; `.claude/settings.json`
  is tracked and Claude Code executes those paths at runtime.

### 2c. Ambiguous / structural

- `scripts/setup_worktree.sh:120-122` uses `git worktree add`. Tracked
  forwarders come along automatically; untracked ones would not, so every
  worktree would start hookless until an install ran. Line 159 only creates
  `.claude/hooks-daemon/untracked`.
- `tests/unit/install/test_settings_sources_ssot_drift.py:68-79` reads
  `_DAEMON_HOOK_BASENAMES` out of `hooks_deploy.sh` text and compares it to the
  event catalogue - depends on the *list*, not the files.

---

## 3. Q3 - `.gitignore` entries, tests and docs that state or assume tracking

**Docs that state it affirmatively:**

- `CLAUDE/LLM-INSTALL.md:700-702` - "**The rest of the list is not git-ignored,
  and that is deliberate** - these files only work if they are committed, so
  your teammates receive them." The table row at `:707` is `.claude/hooks/*` |
  Hook forwarder scripts | "Claude Code executes them by the path in
  `settings.json`".
- `CLAUDE/LLM-INSTALL.md:153` - `.claude/hooks/*` listed under files created by
  the installer; `:178` `git commit -m "Install Claude Code Hooks Daemon"`;
  `:112` `git add .claude/ && git commit -m "Save hooks before daemon install"`.
- `CLAUDE/LLM-INSTALL.md:749-761` - tells clients to
  `extend-exclude = [..., ".claude/hooks"]` in ruff and to set
  `source-path=SCRIPTDIR` in `.shellcheckrc`, i.e. presumes the files are in
  their tree and inside their linters' scope.
- `README.md:300` - `.claude/hooks/*` - Forwarder scripts (route events to the
  daemon).
- `install.py:1468`, `:1478` - printed guidance `git add .claude/hooks/*`;
  `:1471`/`:1480` a `git update-index` call applying the executable bit to each
  hook path; `:1542` "Remember to commit `.claude/` files (except
  `hooks-daemon/`) to git!"
- `src/claude_code_hooks_daemon/install/client_owned_assets.py:10-16` -
  "Everything this manifest lists is deliberately NOT ignored, because it must
  be committed to work."
- `CLAUDE/development/RELEASING.md:590-599` - the Step 12.0 blocking gate
  `test_stop_hook_hard_block.py` "invokes the production bash wrappers
  `.claude/hooks/stop` and `.claude/hooks/subagent-stop` as subprocesses".

**Code that acts on the assumption:**

- `scripts/install/hooks_deploy.sh:366-404` (`git_force_executable`) does
  `git ls-files --full-name` then a `git update-index` executable-bit call on
  each hook - a no-op unless the files are tracked in the target repo.
- `install.py:571-600` (`update_git_index_executable`) - same intent.

**`.gitignore` entries:** none exclude `.claude/hooks/`. The only near-misses
are `.claude/.gitignore:9` (`/hooks-daemon/`, deliberately anchored - see its
comment at `:3-8`) and `:11-13` (`hooks.bak/`, `hooks.bak.*/`).

---

## 4. Q4 - Other tracked-vs-generated comparisons

`test_dogfooding_hook_scripts.py` is the only **full-fidelity**
tracked-vs-installer-output diff
(`tests/integration/test_dogfooding_hook_scripts.py:120-209`), and it is the
only importer of `install.create_forwarder_script` /
`create_status_line_script` (`:66`, `:98`, `:108`). Grep for those symbols
across `tests/`, `scripts/`, `src/` returns only that file plus a comment
reference at `tests/unit/install/test_settings_sources_ssot_drift.py:91`.

But three others **feed tracked hook content through the generator** and assert
properties of the result:

1. `tests/integration/test_relay_event_socket_real_payloads.py:263-279` - reads
   the real tracked forwarder for each relay-ineligible event, runs
   `generate_forwarder_content(source, ..., relay_enabled=True, ...)`, asserts
   no guard block appears. A *partial* tracked-vs-generated comparison.
2. `tests/integration/test_hooks_deploy_relay_guard.py:44-48, 66-70, 86-116,
   145-148, 203-229` - copies tracked forwarders into a fake daemon_dir, runs
   the real `deploy_all_hooks`, then compares deployed output against the
   tracked source. `:55-57` explicitly acknowledges the tracked source "may
   already carry a guard block".
3. `tests/unit/install/test_client_owned_assets.py:236-252` - asserts every
   resolved `.claude/hooks/*` file carries `OWNERSHIP_MARKER`, with remediation
   text at `:249-251` telling you to "regenerate this repo's own
   `.claude/hooks/` so the dogfooding comparison still matches".

Two supporting guards live inside the dogfooding test itself and are new (Plan
00250 Task 2.4c): `test_no_other_machine_specific_path_survives` (`:211-231`)
backed by `normalise_project_root` / `surviving_absolute_paths` at
`src/claude_code_hooks_daemon/install/forwarder_generator.py:205-237`. Their
docstrings (`:128-135` in the test, `:208-218` in the module) already record
that a verbatim byte comparison "additionally asserted 'this checkout sits at
the same absolute path as the machine that generated the committed file'. True
on one box, false on every CI runner."
