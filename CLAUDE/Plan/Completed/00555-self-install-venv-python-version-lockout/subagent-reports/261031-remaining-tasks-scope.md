# Plan 00555: scope of the remaining tasks on current main

This was a read-only investigation at `3076124b0` on main. No code was changed. Line numbers are at that commit.

## Ground truth established first

- **Orphan gone.** `untracked/` holds only `venv-workspace-py313-0d6d49c6` and `lsp-venv`. The py311 orphan no longer exists.
- **The wrapper and its template are byte-identical.** `diff bin/hooks-daemon src/claude_code_hooks_daemon/install/templates/hooks-daemon` printed no difference. Every wrapper change must be made to both, and `tests/unit/install/test_bin_wrapper.py` covers the template.
- **Every bash consumer already shares one resolver.** Each of these sources `scripts/lib/resolve_venv.sh`:
  - the shim `scripts/install/venv_resolver.sh:65` (Plan 00104), used by about 14 scripts;
  - the skill shim `skills/hooks-daemon/scripts/_resolve-venv.sh`;
  - `init.sh` `_resolve_python_cmd`;
  - `bin/hooks-daemon:104`;
  - `venv_bootstrap.sh:98`.
- **Drift no longer resolves.** Both gates now check the interpreter version: `venv_python_usable` (`resolve_venv.sh:351`) and `venv_interpreter_usable` (`paths.py:963`). As a result:
  - the wrapper repair arm (`bin/hooks-daemon:270-275`) and `_venv_self_heal` (`init.sh:2887-2895`) both fire on drift;
  - `_repair_venv_locked` checks the built minor (`cli.py:2926-2938`).

## Task 2.1: one venv-resolution SSoT. Partly done; real divergences remain

**Already done:**

- Plan 00104 put every bash entry point on one library.
- Plan 00555 DBF (`b51912cb8`) made every gate version-aware.

**Still divergent:**

1. **Two Python resolvers with different precedence.**
   - `resolve_existing_venv_python` (`paths.py:1146`) goes override → fingerprint → scan → legacy, with **no metadata step**. It also carries a TODO at `:1217` that names Plan 00100 Phase 2. Its callers are `current_venv_dir` (`:3100`, used by list-venvs and prune), `live_venv_realpaths` (`:3122`) and `client_validator.py:607`.
   - `resolve_existing_venv_python_with_diagnostics` (`:1224`) goes override → **metadata** → fingerprint → scan → legacy. This is the one the bash `resolve-venv` CLI uses.
   - The two can name different venvs whenever two usable venvs exist.
2. **Bash pre-empts Python.** `_rv_resolve_python_impl` serves its hot cache (`resolve_venv.sh:575-590`), then ranks and scans to pick an interpreter (`_rv_pick_python`, `:445-507`), and only then asks paths.py. The precedence is therefore split across two languages.
3. **The builder targets something the resolver does not look up first.**
   - `_vb_gate` picks `find_latest_python` (`venv_bootstrap.sh:150`) and builds `venv-<fingerprint of that>` (`venv.sh:1192`, `:1208-1244`).
   - Python `cmd_repair` builds `venv-<python_venv_fingerprint(running interpreter)>` (`cli.py:2862`).
   - The success judge is `resolve_venv_python` (`venv_bootstrap.sh:279`), which is metadata-first. It can therefore certify a different, older venv, for example a still-usable py312 whose lock_hash matches, as the build's success. The task asks for one answer, and today there are three keys.

**Remaining work:**

- Make `resolve_existing_venv_python` delegate to the diagnostics resolver, or delete it, so Python has one precedence.
- Make the build target and the success judge agree. Either:
  - (a) the judge checks that `resolve_venv_python` returns the venv just built; or
  - (b) a `paths.py build-target --daemon-dir` verb returns the target dir that both `venv_bootstrap.sh` and `cmd_repair` use.
- Decide what happens to the bash ranked scan. It should become a pure "find an interpreter to run paths.py with" step and never choose the answer.
- This folds into Plan 00100 (Dormant, `CLAUDE/Plan/00100-venv-ssot-consolidation`, Phase 2 residue). Record supersession or merge in both plans.

**Red-first tests:**

- In `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py`, build two usable venvs: one fingerprint-keyed, one metadata-matched under another name. Assert that `resolve_existing_venv_python == resolve_existing_venv_python_with_diagnostics[0]`. This fails today.
- In `tests/integration/test_venv_bootstrap_driver.py`, `_vb_build_under_lock` must fail when the venv it built is not the one that resolves. This also fails today.

**Files touched:** `paths.py` (resolver section, about `:1146-1350`, and `current_venv_dir`/`live_venv_realpaths`), `scripts/lib/resolve_venv.sh`, `scripts/venv_bootstrap.sh` (judge), `cli.py` `cmd_repair` (target) and `client_validator.py:607`.

## Task 2.3: `repair` must not need a working venv. Drift case done; one hole remains

**Already done:**

- Plan 00456 (Completed) added the venv-free `repair` arm (`bin/hooks-daemon:149-175`) and `venv_bootstrap.sh repair` (`:667-699`). That path is stdlib-only: `_vb_gate` runs `paths.py` by file path.
- Plan 00555 DBF made a drifted venv unresolvable, so on drift `repair` now takes the venv-free arm.

**What remains:**

- A venv can resolve (its version matches) yet fail to import the package. Causes include a missing or stale editable `.pth`, a partial `uv sync`, or an uninstalled dist.
- In that state:
  - the wrapper's arm is skipped (`:270` succeeds);
  - `venv_python_usable` passes (`:281`);
  - `exec $PYTHON -m ...cli repair` (`:333`) dies with `ModuleNotFoundError`, the incident's exact symptom by another cause.
- Even forcing `venv_bootstrap.sh repair` would not help. `_ensure_venv_build` → `_venv_is_fresh` (`venv.sh:1069-1094`, re-checked at `:1253`) reuses any venv whose lock_hash matches, so the broken venv is kept.

**Concrete fix:**

1. **Wrapper (`bin/hooks-daemon` and the template).** When the verb is `repair`, probe `"$PYTHON" -c 'import claude_code_hooks_daemon.daemon.cli'` before the exec. On failure, run the venv-free arm. That calls `_run_venv_free_verb` with a "resolves but cannot import" reason rather than the "no venv resolves" text at `:166`.
2. **`venv_bootstrap.sh repair`.** Give it a force mode, for example a third argument `--rebuild` or an env var, that makes `_ensure_venv_build` bypass `_venv_is_fresh` for the target venv. The DBF detector exempts a package-import probe (DBF-REPORT "Deliberate exclusions"), so the probe causes no `venv_interpreter_trust` finding.

**Red-first tests:**

- In `tests/integration/test_bin_wrapper_*` or a new `test_wrapper_repair_unimportable_venv.py`, build a venv whose version matches and whose package is not installed (the `pyvenv.cfg` symlink fixture used in DBF fixes). Assert that `hooks-daemon repair` invokes `venv_bootstrap.sh repair` (use a stub bootstrap) and does not exec the CLI.
- In `test_venv_bootstrap_driver.py`, assert that a forced repair rebuilds a lock_hash-fresh venv.

**Files touched:** `bin/hooks-daemon`, `install/templates/hooks-daemon`, `scripts/venv_bootstrap.sh` (`_vb_repair`, `_vb_main`) and `scripts/install/venv.sh` (`_ensure_venv_build` force flag).

## Task 2.4: start-failure diagnosis. Nothing done

**Current state:**

- `init.sh` `validate_venv` (`:1675-1714`) prints only "Cannot import claude_code_hooks_daemon. Venv may be broken (stale .pth files or Python version mismatch). Run: cd $HOOKS_DAEMON_ROOT_DIR && uv sync" (`:1709`).
  - It reports no interpreter version, no `pyvenv.cfg` `version_info` and no `sys.path` check.
  - Its fix command is wrong. It should be `bin/hooks-daemon repair`, which is what every other message in the file names.
  - The same `uv sync` advice appears at `:1690`, `:1697` and `:1703`.
- `start_daemon` echoes it at `:1999`. The timeout path (`:2117-2121`) only dumps the launcher output.
- The wrapper's `exec` (`bin/hooks-daemon:333`) surfaces the raw `ModuleNotFoundError` with no diagnosis.
- No probe of `sys.path`, `no_site` or site-packages exists anywhere in `src`, `scripts`, `bin` or `init.sh`. A grep for `no_site`, `getsitepackages` and similar found nothing.

**Remaining work:**

1. Add one stdlib-only diagnosis function in `paths.py`, for example `diagnose_venv_start(venv_dir) -> list[str]`, plus a CLI verb `paths.py diagnose-venv --venv-dir`, so it runs with no venv. It runs `<venv>/bin/python -c "import sys,site; …"` and reports:
   - the interpreter's `sys.version`;
   - `pyvenv.cfg` `version_info` (reuse `venv_cfg_major_minor`, `:1021`, and `_read_pyvenv_cfg`);
   - `sys.flags.no_site`;
   - whether `<venv>/lib/pythonX.Y/site-packages` is on `sys.path`;
   - whether `import claude_code_hooks_daemon` resolves;
   - the fix line `<daemon_dir>/bin/hooks-daemon repair`.
2. Call it from `validate_venv`'s import-failure branch (`:1708-1711`) and replace the `uv sync` texts.
3. Optionally, call it from the wrapper before the exec when the import probe from 2.3 fails. That is a shared touchpoint with 2.3.
4. This is the natural core of the later Task 2.5 `hooks-daemon diagnose` verb, so give it an API that verb can reuse.

**Red-first tests:**

- In `tests/unit/daemon/`, call `diagnose_venv_start` on a fixture venv with matching version and no package. Assert the output contains the interpreter version, the cfg version, `site-packages on sys.path: yes` and the `repair` command.
- For a cfg-mismatch fixture, assert `site-packages on sys.path: no`.
- An integration test sources `init.sh`, runs `validate_venv` on that fixture and asserts that `VENV_ERROR` contains the diagnosis and does not contain `uv sync`.

**Files touched:** `paths.py` (new function and CLI subparser near `:3541-3600`), `init.sh` (`validate_venv`), and optionally `bin/hooks-daemon` and its template.

## Task 2.7: background build log path and last result. About half done

**Already done (Plans 00456 and 00488):**

- A hook-started build writes `untracked/.venv-bootstrap-<fp>.log` (`venv_bootstrap.sh:112`, `:378-379`, `:396`).
- The failed marker is `.venv-bootstrap-<fp>.failed`, holding `inputs`, `failed_at` and `exit` (`:193-204`).
- The holder record is `.venv-bootstrap.current` (`:380-381`, `:647`).
- `init.sh` prints `Build log:` for the started, running and failed states (`:806-836`).

**What remains:**

1. **Unrecorded lock holders.** Only `hook` writes the record, so every other holder shows "not recorded here" (`init.sh:822`). The unrecorded holders are:

   - foreground `venv_bootstrap.sh repair` (`:693-697`);
   - Python `cmd_repair` (`venv_lock`, `cli.py:2870`);
   - `ensure_venv` from an upgrade (`venv.sh:1161`);
   - the start-time cleanup (`cli.py` about `:3417`).

   `acquire_venv_lock`/`venv_lock` should write a minimal record: holder kind, pid, started time and a log path when there is one. The foreground repair should also tee its output to the same `<fp>.log`.

2. **No last result on success.** A success deletes the marker and the record (`:280`, `:616`). The only trace is the "SUCCEEDED" line at the end of the log. There is no machine-readable `last_result` (succeeded/failed/timed-out, finished time, exit). Add a `.venv-bootstrap-<fp>.result` file, or extend the record, and have `probe` emit `last_result=` and `log=` in the idle state too.

3. **No surface outside the venv-missing branch.** The plain "Hooks daemon not running" stop block (`init.sh:1117-1121`, `:1195`, `:3371`) and `cmd_status` (`cli.py:1594`) never name the log or the last result.

**Red-first tests:**

- In `tests/integration/test_venv_bootstrap_driver.py`, after a stubbed successful build, `probe` prints `state=idle`, `last_result=succeeded` and `log=<path>`. Today it prints only `state=idle`.
- While `acquire_venv_lock` is held by a non-hook caller, `probe` prints `holder=` and `pid=`.
- `init.sh`'s not-running reason contains `Build log:` when a result file exists.

**Files touched:** `scripts/venv_bootstrap.sh` (`_vb_probe`, `_vb_print_running`, `_vb_build_under_lock`, `_vb_repair`), `scripts/install/venv.sh` (lock and record helpers, about `:489-1060`), `venv_lock.py`, `init.sh` (`:800-860` and the not-running reasons) and `cli.py` `cmd_status`.

## Task 3.1: prune the orphan; dev extras on self-install. The prune is done; the extras are not

- **The prune is satisfied.** The orphan is gone, as checked above.
- **The dev extras are not installed by any builder.**
  - `pyproject.toml:43-44` declares them as `[project.optional-dependencies] dev`, an extra and not a dependency group, so a plain `uv sync` omits them.
  - Every bootstrap sync runs `uv sync --frozen --project … "${python_args[@]}"` with no `--extra dev` (`venv.sh:1462`, `:1470`, `:1488`, in `create_venv_at_path`).
  - `cmd_repair` runs bare `uv sync` (`cli.py:2905`).
  - Only `venv-include.bash:208-210` (the QA venv helper) installs `.[dev]`.

**Remaining work:**

- When the daemon dir is a self-install, add `--extra dev` to the three `uv sync` calls in `create_venv_at_path` and to `cmd_repair`. Two ways to tell the cases apart:
  - by layout: daemon_dir is a self-install unless `basename == hooks-daemon` and its parent is `.claude`, the same rule as `bin/hooks-daemon:290-295`;
  - or via `install_layout.is_self_install_mode` (`paths.py:1768` wraps it).
- `uv.lock` already resolves every extra, so `--frozen --extra dev` needs no re-lock.
- Client installs must stay without the extras. `run_semgrep_check.sh:14-15` relies on that.

**Red-first tests:**

- In `tests/integration`, use a stub `uv` that records its argv (the `venv_bootstrap_sandbox.py` pattern). Assert that `create_venv_at_path` passes `--extra dev` for a self-install layout and omits it for `.claude/hooks-daemon`.
- In `tests/unit/daemon/test_cli_*repair*`, `_repair_venv_locked` passes `--extra dev` in self-install mode.

**Files touched:** `scripts/install/venv.sh` (`create_venv_at_path`, `:1340-1556`) and `cli.py` (`_repair_venv_locked`, `:2892-2911`).

## Task 3.3: release note. Nothing done

`CLAUDE/UPGRADES/UNRELEASED/release-notes/` holds `001`-`009`, so the next file is `010-<slug>.md`.

**Structure** (from `release-notes/README.md`):

- one callout per plan, named `NNN-kebab-slug.md` with three digits;
- the mandatory schema is `# Callout: <title>`, then `**Plan**: 00555`, then `**Audience**: operators | handler authors | client projects | everyone`, then one to three sentences in release-notes voice;
- `(reported as issue #N)` when it answers an external issue.

**Sibling directories** (see `UNRELEASED/README.md`):

- `post-upgrade-tasks/` is for actions users must take;
- `pre-upgrade-tasks/` takes a `**Detect**` pattern;
- `truth-changes/` holds `v*.yaml` `was`/`now`;
- `config-changes/` already holds `v3.72.0.yaml`.

**Likely needs:**

- a release-notes callout: a drifted venv now self-heals, a new blocking QA check `venv_interpreter_trust`, and later the dev extras and the diagnosis;
- possibly a truth-change, because docs that say "fix with `uv sync`" become wrong once 2.4 lands;
- no post-upgrade task, since nothing needs doing.

Plan rule R-PLAN-DONE-HOLDING-AREA requires a Success Criteria line that cites the artefact. The current line at PLAN.md:117 already does.

**Timing:** write it last, or write it now and amend the text as each task merges. Only one file is touched.

## Overlaps and parallelism

| Task | Files                                                                                                                  |
| ---- | ---------------------------------------------------------------------------------------------------------------------- |
| 2.1  | `paths.py` (resolver), `resolve_venv.sh`, `venv_bootstrap.sh` (judge), `cli.py` `cmd_repair`, `client_validator.py`    |
| 2.3  | `bin/hooks-daemon` + template, `venv_bootstrap.sh` (`_vb_repair`/`_vb_main`), `venv.sh` `_ensure_venv_build`           |
| 2.4  | `paths.py` (new function + CLI verb), `init.sh` `validate_venv`, optionally wrapper + template                         |
| 2.7  | `venv_bootstrap.sh` (probe/record), `venv.sh` (lock/record), `venv_lock.py`, `init.sh` messages, `cli.py` `cmd_status` |
| 3.1  | `venv.sh` `create_venv_at_path`, `cli.py` `_repair_venv_locked`                                                        |
| 3.3  | `UNRELEASED/release-notes/010-*.md` only                                                                               |

**Conflict pairs:**

- 2.1 and 2.3 both change `cmd_repair`/target selection and `venv_bootstrap.sh`.
- 2.3 and 2.7 both change `_vb_repair`.
- 2.3 and 2.4 share the wrapper's pre-exec block.
- 2.7 and 2.4 both change `init.sh`, but in different functions.
- 3.1 and 2.1 both change `cmd_repair`, but in different functions.
- 3.1 and 2.3 both change `venv.sh`, at different functions: `create_venv_at_path` and `_ensure_venv_build`.

**Suggested waves:**

1. **Wave A, in parallel:**
   - 3.1, a small and isolated change;
   - 2.4, whose paths.py diagnosis function is new code and whose init.sh change is confined to `validate_venv`;
   - 3.3, drafted now.
2. **Wave B:** 2.3, after 2.4 if the wrapper reuses the diagnosis. Otherwise it can run in parallel with an agreed wrapper hunk.
3. **Wave C:** 2.7, after 2.3, because both change `_vb_repair` and 2.7 adds the foreground repair's log.
4. **Wave D:** 2.1 last. It is the widest refactor, the one most likely to conflict, and it overlaps Plan 00100. Settle the plan relationship before dispatching it.

**Fully satisfied tasks:** none in full. The prune half of 3.1 is done. The drift half of 2.3 is done, through the DBF.
