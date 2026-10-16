# N469 implementer report: a dependency change does not build a matching venv on restart

Plan 00474, ledger N469. Branch `worktree-n469-stale-lock-venv`. Model: Opus 5.5.

## Assumptions (for the coordinator to have ruled on)

1. **restart and cold start get a loud advisory, not a build.** Justification below ("The choice").
2. **The advisory fires for a running venv with NO metadata too**, not only a proven mismatch. That is the shape
   of the real incident: both `/workspace/untracked/venv-workspace-py311-81c29529` (stale) and `...-2a519198`
   (built by `repair`) have no `.daemon-metadata.json`. Consequence for dogfood: after this merges, `/workspace`
   session start, `restart` and `status` will show the notice until `bin/hooks-daemon repair` is run once (repair
   now writes the metadata, which clears it).
3. **The advisory lives in the existing `unproven_venv_advisor`** (SessionStart, every session incl. resume,
   silent when clean) rather than a new handler, per the brief's "prefer the existing advisories".
4. **I corrected release note 076's false sentence** ("the venv is keyed on a hash of pyproject.toml and uv.lock,
   so this change selects a new venv"). The venv NAME is keyed on the interpreter only
   (`scripts/install/python_fingerprint.sh:76`, `paths.py:208`: `sys.version|sys.base_prefix|machine`); the lock
   hash only lives in the metadata. Same error as the #122 comment.
5. `check-venv-fresh` gained exit code 3 (proven stale) — an internal stdlib CLI whose only consumer is
   `venv.sh::venv_lock_hash_matches`; two existing tests that asserted 1 for a mismatch were updated.

## 1. Investigation: what each path does when no venv matches the source's lock hash

Root facts:

- The venv directory name does NOT include the lock hash: `venv-<slug>-py<MM>-<md5(sys.version|base_prefix|machine)>`
  (`python_fingerprint.sh:76`, `paths.py:208`). A dependency change therefore does not change which directory a
  build targets; the lock hash lives only in `.daemon-metadata.json`.

- Both resolvers rank a lock-hash match first but never refuse a stale venv: `_best_ranked_scan_candidate`
  (`paths.py:965`) returns rank 1/2 candidates, and the diagnostic resolver logs "step 2: metadata stale" and then
  takes the same venv at step 4 (`paths.py:1335`). Fixture run (`untracked/scratch/n469_fixture_run.py`, one venv
  whose metadata names the old lock, then `uv.lock` changed):

  ```
  hot-path resolver picks: venv-...-py311-aaaaaaaa
  diagnostic resolver picks: venv-...-py311-aaaaaaaa
     step 2: metadata stale — lock_hash mismatch in: venv-...-py311-aaaaaaaa (lock_hash=sha256:37ad306c...)
     step 3: fingerprint-keyed path .../venv-...-py311-2a519198/bin/python missing or not executable
     step 4: scan-fallback hit — using .../venv-...-py311-aaaaaaaa/bin/python
  ```

| Path                                                                                                                  | Builds for the new lock?                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Evidence |
| --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| Client `upgrade` (skill `upgrade.sh` shim -> `scripts/upgrade.sh` -> `upgrade_version.sh`)                            | **Yes** (before and after this fix), via `ensure_venv` at Step 7 / the idempotent path (`upgrade_version.sh:918`, `:1306`). `_venv_is_fresh` (`venv.sh:1078`) found the lock hash mismatched and then fell back to the `.daemon-version` stamp; the stamp is the new tag (or `vX+ref.sha` for a branch install), so it mismatched too and the venv was rebuilt in place, with metadata. **Gap (fixed):** a stamp that happened to match rescued a venv whose metadata proved another lock. Red test below. |          |
| `provision` fresh                                                                                                     | **Yes.** Fresh clone, empty `untracked/`, `venv_bootstrap.sh repair` builds (`provision.sh` Step 4, `"$BOOTSTRAP" repair`).                                                                                                                                                                                                                                                                                                                                                                                |          |
| `provision` sync (and the Plan 00477 background sync, which is the same `_provision_sync_clone`, `provision.sh:1023`) | **Yes.** The target is cloned into an empty stage and its venv built there (`provision.sh:872`), rebound, and swapped in; the old venv stays with the old clone. `_provision_venv_healthy` (`provision.sh:716`) asserts the resolver chose the new venv before the restart.                                                                                                                                                                                                                                |          |
| `init.sh` cold start                                                                                                  | **No.** It builds only when NO venv resolves (`init.sh:2869` -> `_venv_self_heal`, `:2876`). A stale venv resolves, so the daemon starts from it.                                                                                                                                                                                                                                                                                                                                                          |          |
| `bin/hooks-daemon restart`                                                                                            | **No.** The wrapper resolves a venv (`bin/hooks-daemon:262`) and execs the CLI from it (`:322`); `cmd_start` forks that same process, so the daemon runs from whatever the resolver returned. Nothing builds. This is the N469 incident.                                                                                                                                                                                                                                                                   |          |
| `bin/hooks-daemon repair`                                                                                             | **Yes**, `uv sync` into the fingerprint-keyed venv under the build lock (`cli.py:2590`), but it **wrote no metadata** (fixed), so the resolver could not rank it first and nothing could tell it was current.                                                                                                                                                                                                                                                                                              |          |

The incident itself: the system `/usr/bin/python3` build changed between Sep 15 and Oct 16, so `sys.version` and
hence the fingerprint changed (81c29529 -> 2a519198). No keyed venv existed, neither venv had metadata, the scan
took 81c29529, and restart reused it.

## 2. Fix (TDD)

Red output, before any source change:

```
FAILED tests/integration/test_ensure_venv.py::TestEnsureVenvLockChangeBeatsTheStamp::test_stale_lock_hash_is_rebuilt_even_when_the_stamp_matches - AssertionError: assert 'FRESH' == 'STALE'
FAILED tests/unit/daemon/test_paths_check_venv_fresh_under_310.py::test_check_venv_fresh_returns_stale_on_mismatch_when_tomllib_unavailable - AssertionError: check-venv-fresh with non-matching lock_hash must exit 3 (p...
FAILED tests/unit/handlers/session_start/test_unproven_venv_advisor.py::TestUnprovenVenvAdvisor::test_running_venv_built_for_another_lock_is_reported_with_repair - AssertionError: assert 'NOT BUILT FOR THIS SOURCE' in ''
FAILED tests/unit/daemon/test_cli_repair.py::TestCmdRepairTargetsTheDaemonDir::test_repair_records_the_lock_it_built_for - ImportError: cannot import name 'venv_lock_drift' ...
FAILED tests/unit/daemon/test_cli_venv_lock_drift.py (4 tests) - AttributeError: module 'claude_code_hooks_daemon.daemon.cli' has no attribute 'venv_lock_drift'
ImportError while importing tests/unit/daemon/test_paths_venv_lock_drift.py: cannot import name 'venv_lock_drift'
ImportError while importing tests/unit/daemon/test_paths_check_venv_fresh.py: cannot import name 'CHECK_VENV_FRESH_EXIT_STALE'
```

Green: all touched test files pass (91 tests, plus `test_cli_additional_commands.py` and
`test_cli_status_install_stamp.py` for regressions).

Changes:

- **Every build rebuilds a venv proven built for another lock** (upgrade, install, provision, the hook build,
  repair-when-none-resolves all go through `ensure_venv`). `paths.py check-venv-fresh` exits
  `CHECK_VENV_FRESH_EXIT_STALE` (3) when the metadata is readable and names another lock; `_venv_is_fresh`
  (`venv.sh:1078`) then returns stale without consulting the stamp. The stamp fallback is kept only for a venv with
  no usable metadata, which is what its comment always said.
- **`repair` records the lock it synced for** (`_record_repaired_venv_lock`, `cli.py:2679`), through the
  `write-venv-metadata` code now shared as `_write_venv_metadata`. The resolver then ranks the repaired venv first
  (metadata match) and the notice clears. A metadata write failure is a WARNING, not a failed repair (the venv works).
- **One question, three places**: `paths.venv_lock_drift(daemon_dir, venv_dir)` (`paths.py:2989`) says why a venv
  is not proven built for the current source (mismatch, naming both hashes; or no usable metadata), judging only the
  daemon's own `untracked/venv*` and saying nothing when the current hash cannot be computed.
  `venv_lock_drift_lines` renders it with the `repair` command. Asked by the SessionStart `unproven_venv_advisor`
  (for `sys.prefix`, the venv the daemon runs from), by `restart` after a successful start and by `status`
  (`_warn_if_venv_not_built_for_source`, `cli.py:2541`, stderr, for the CLI's own `sys.prefix`, which is the venv
  `start` forks the daemon from).

### The choice: advisory on restart and cold start, not a build

- `restart` cannot move the daemon onto a venv it builds: the daemon is a fork of the CLI process, which already
  runs from the resolved venv. It would need a re-exec, which is a new mechanism.
- In the common case (same interpreter, changed deps) the fingerprint-keyed build target IS the running venv, so a
  build from `restart` would `rm -rf`/sync the interpreter the CLI process is executing from (and, at cold start,
  the venv the live daemon or a concurrent hook is using).
- A cold start is inside a hook (60 s budget). The detached hook build (`venv_bootstrap.sh hook`) is safe only for
  the no-venv case because nothing runs from its target; for the stale case it would hit the point above.
- `repair` already is the right build: it stops the daemon, syncs under the shared build lock, verifies the import,
  and now records the lock. Naming it reuses the existing build path; the notice reuses the existing venv advisory.

## 3. How a client upgrading to the next release gets a new dependency (for the #122 comment)

A client gets a new runtime dependency such as `mdformat-footnote` through the upgrade, not through a restart. The
upgrade (the hooks-daemon skill's `upgrade`, which runs `scripts/upgrade_version.sh`) calls `ensure_venv`, which
rebuilds the daemon venv in place with `uv sync` whenever the venv's recorded hash of `pyproject.toml` + `uv.lock`
differs from the new source's (and, from the next release, regardless of the venv's version stamp), then records
the new hash and restarts the daemon from that venv. `provision.sh` and the background sync build the target's
venv in a fresh stage, so they get it too. The venv directory name is keyed on the Python interpreter, not on the
lock hash, so a dependency change does not by itself select a different venv, and `bin/hooks-daemon restart` or a
hook-started daemon never installs anything: they reuse whatever venv resolves. If a daemon is running from a venv
built before the change, session start, `restart` and `status` now say so, and `bin/hooks-daemon repair` syncs the
venv for the current source. Until the plugin is installed, the formatter keeps working and only skips footnote
support, logging one warning.

## Residuals (not fixed here)

- The bash hot-path cache `untracked/.python-cmd-cache` (`resolve_venv.sh`) is keyed on `untracked/`'s mtime, which
  a lock change does not bump. If a lock-matching venv already exists beside a stale one (e.g. switching branches
  back), hooks keep the cached stale answer until something adds or removes a venv. Not on the paths that move a
  client's source (each creates or replaces a venv directory).
- `upgrade_version.sh` builds with `python3` (or `HOOKS_DAEMON_PYTHON`) while `repair`/the hook build use the
  newest discovered interpreter, so the two can target different venv directories. Pre-existing; unchanged.

## QA

`./scripts/qa/llm_qa.py changed --allow-unmapped`: **QA: 40/40 PASSED, exit 0** (changed_tests: 3548 passed, 0
failed, 5 skipped across 90 test files). `--allow-unmapped` because `daemon/cli.py`, `daemon/paths.py` and
`.claude/HOOKS-DAEMON.md` are too-broad to map; the full gate must cover them. The first run (without the flag)
also flagged `generated_doc_drift` (the advisor's description line changed), fixed by `bin/hooks-daemon generate-docs`, and two test files the autofix reformatted mid-run. No exclusion, allowlist or suppression was
added.
