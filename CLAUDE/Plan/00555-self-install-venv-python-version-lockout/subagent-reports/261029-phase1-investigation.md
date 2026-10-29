# Plan 00555 Phase 1 investigation (Tasks 1.2, 1.3 and related questions)

This was a read-only investigation. No code was changed, nothing was committed and no build was run. Every
`file:line` below refers to the tree at `7e53c0211`.

## 0. A correction to INCIDENT.md, found on disk (read this first)

The daemon that is running now does NOT use the venv the owner rebuilt.

- `untracked/daemon-5ea73c89892d.pid` holds 510367. That is the PID that "Daemon started successfully" reported.
- Its `/proc/510367/cmdline` is
  `/workspace/untracked/venv-workspace-py313-0d6d49c6/bin/python -m claude_code_hooks_daemon.daemon.cli --project-root /workspace restart`.
- `untracked/venv-workspace-py313-0d6d49c6/` exists. It is uv 0.13.6, `version_info = 3.13.5`, with
  `.daemon-metadata.json` written at `2026-10-29T11:09:25Z` and a lock_hash that matches the current source.
- `untracked/.venv-bootstrap-workspace-py313-0d6d49c6.log` shows that a hook-started background build began at
  `11:09:22Z` (build pid 508719) and ended with "venv bootstrap SUCCEEDED".
- `untracked/.python-cmd-cache` points at the py313 venv, and `untracked/lsp-venv` now links to it.
- The py311-named venv (pyvenv.cfg mtime 11:09, rebuilt by stdlib venv) has **no** `.daemon-metadata.json`. It is
  now an unused orphan: the resolver's metadata step (below) picks py313.

**Most likely sequence.** `python3 -m venv --clear` deleted the py311 venv's contents, including its
`.daemon-metadata.json`, and left `bin/python` briefly absent. A hook fired inside that window. It found no
resolvable venv, so it took the `! _is_daemon_installed` branch (`init.sh:2876`), which calls
`_venv_self_heal` → `venv_bootstrap.sh hook`. That started the first real build of the whole incident.

The owner's `restart` then resolved the new py313 venv. The fix worked by coincidence, not because of the py311
rebuild. Task 3.1's premise ("the live venv is the mislabelled py311") is therefore wrong: the py311 dir is residue
to prune, not to re-key.

## 1. Task 1.3: the venv resolvers and where they diverge

| Component                                                                 | How it picks the venv                                                                                                                                                                                                                                                                                                                                                                             | Key used                                                                                                                                                                                                                                                                                                                              |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Wrapper `.claude/hooks-daemon/bin/hooks-daemon`                           | This is a symlink to `bin/hooks-daemon`. Its `DAEMON_DIR` is `/workspace` (`bin/hooks-daemon:79-93`). It sources `scripts/lib/resolve_venv.sh` (`:95-104`), then runs `PYTHON="$(resolve_venv_python "$DAEMON_DIR")"` (`:270`) and execs `$PYTHON -m ...cli` (`:330`).                                                                                                                            | Shared resolver (below)                                                                                                                                                                                                                                                                                                               |
| Hook-side health check, `init.sh` (`.claude/init.sh` is a symlink to it)  | `_resolve_python_cmd` → the same `resolve_venv_python` (`init.sh:1424-1446`). `_is_daemon_installed` is just `-f $PYTHON_CMD` (`init.sh:2196-2198`).                                                                                                                                                                                                                                              | Shared resolver                                                                                                                                                                                                                                                                                                                       |
| Shared resolver: `scripts/lib/resolve_venv.sh` + `paths.py resolve-venv`  | 1. Hot-path cache `untracked/.python-cmd-cache`, keyed only on the mtime of `untracked/` (`resolve_venv.sh:466-487`). 2. Otherwise it ranks-scans `venv-*/bin/python` to get an interpreter (`:295-336`); the run-probe there is only `-c 'import sys'` (`:216`). 3. It runs `paths.py resolve-venv` (`:501-511`), which calls `resolve_existing_venv_python_with_diagnostics` (`paths.py:1097`). | **Step 2 is metadata first:** any slug-eligible `venv-*` whose `lock_hash` matches the current pyproject+uv.lock, in sorted order (`paths.py:1197-1243`). Its only "usable" test is `_venv_interpreter_runs`, again `import sys` (`paths.py:943-968`). Step 3 is the fingerprint key (`:1301-1325`). Step 4 is a scan (`:1331-1347`). |
| Background builder, `scripts/venv_bootstrap.sh` (`hook`/`repair`/`build`) | `_vb_gate` picks the interpreter with `find_latest_python` and runs `paths.py bootstrap-decision` (`venv_bootstrap.sh:137-174`). `ensure_venv_locked` builds `untracked/venv-<fingerprint>` (`scripts/install/venv.sh:1186-1203`, fingerprint at `:1243`).                                                                                                                                        | **Python fingerprint plus project-path slug** (Plan 00099/00124; `paths.py:191-224`, keyed with `sys.version`)                                                                                                                                                                                                                        |
| Python `repair` (`cli.py` `cmd_repair`)                                   | `venv_path = untracked/venv-{python_venv_fingerprint(daemon_dir)}` under `venv_lock` (`cli.py:2858-2868`).                                                                                                                                                                                                                                                                                        | Fingerprint of the **running** interpreter. It is unreachable while that interpreter cannot import the package.                                                                                                                                                                                                                       |
| Wrapper `repair` with no venv                                             | Runs only when `resolve_venv_python` FAILS (`bin/hooks-daemon:270-275`, `:149-175`), then calls `venv_bootstrap.sh repair`.                                                                                                                                                                                                                                                                       | Fingerprint (builder)                                                                                                                                                                                                                                                                                                                 |
| `restart`                                                                 | Has no venv logic of its own: wrapper → resolver → exec.                                                                                                                                                                                                                                                                                                                                          | Shared resolver                                                                                                                                                                                                                                                                                                                       |

### Where they diverge

1. **The resolver keys on lock_hash, the builder on fingerprint.** The uv-built py311 venv had metadata with a
   matching `lock_hash`, and its `bin/python` (a symlink into `/usr/bin`, now 3.13) passes `import sys`. So step 2
   returned it (`paths.py:1228-1243`) before the fingerprint step ever ran. The resolver never asks whether that
   interpreter's version matches the one the venv was built for.

   As a result, the wrapper, `restart`, `repair` and `_is_daemon_installed` all saw the venv as **present**. The
   wrapper's `repair` arm is gated on the resolver failing (`bin/hooks-daemon:270-271`), so `repair` exec'd the
   broken interpreter. That is why it failed identically.

2. **init.sh labels a venv that resolves as "venv missing".** After a start failure, `init.sh:2901-2911` runs:
   `elif _daemon_clone_present && _venv_build_running; then _HOOKS_DAEMON_VENV_MISSING=true`. This is the Plan 00488
   "build window" branch. Whenever ANY process held `untracked/.venv-bootstrap.lock`, the hook printed "clone present
   but venv missing for this project path … a venv build is running in the background" (`init.sh:858`, state
   `running` at `:815-827`), even though the venv resolved.

   This branch only probes. It never starts a build (`_venv_build_running` → `venv_bootstrap.sh probe`,
   `init.sh:2345-2352`; `venv_bootstrap.sh:292-299`). When the lock was free, the result was the plain "Hooks daemon
   not running" (`init.sh:1117-1121`). That explains the alternation. The divergence is therefore not two resolvers
   disagreeing. It is one resolver saying "present" while init.sh's status vocabulary reports "missing" whenever the
   lock is held.

3. **The hot-path cache can also pin the stale answer.** `resolve_venv.sh:473-486` serves the cached py311 path
   with no probe and no version check, for as long as the mtime of `untracked/` does not change.

## 2. Task 1.2: why the background build never left a usable venv

**Where it writes.** `untracked/venv-<slug>-py313-<hash>` (`venv.sh:1203`). The log is
`untracked/.venv-bootstrap-<fp>.log` (`venv_bootstrap.sh:112`, written at `:378-379` and `:396`). The failure marker
is `.venv-bootstrap-<fp>.failed` (`:113`). The holder record is `untracked/.venv-bootstrap.current` (`:114`, `:380`).

**The lock.** `flock` on `untracked/.venv-bootstrap.lock` (`venv.sh:432`, `:774-787`). A mkdir fallback exists at
`:789-803`. Python `venv_lock` shares the same file (`venv_lock.py:51-53`). It is taken by `cli.py` repair (`:2867`)
and by the start-time stale-venv cleanup (`cli.py:3417`). The `hook` verb hands the lock to a detached child
(`venv_bootstrap.sh:383-397`, `:627`).

**The "Build log: not recorded here" text.** `init.sh:822` prints it when the probe reports `running` with no `log=`.
`_vb_print_running` reads `log` only from `.venv-bootstrap.current` (`venv_bootstrap.sh:226-244`), and only the
`hook` verb writes that record. So the lock holder was NOT a hook-started background build. It was a repair, an
upgrade, the Python start-time cleanup, or an inherited descriptor (bash `exec {fd}>` at `venv.sh:780` is not
close-on-exec).

No process holds the lock now: a `/proc/*/fd` scan found none.

**On failure.** `_vb_build_under_lock` judges success by `resolve_venv_python` (`venv_bootstrap.sh:279-289`). A
failure writes the `.failed` marker, and hooks do not retry until the inputs change (`:353-358`). A stop inside the
bound records nothing (`:559-583`). No code deletes the built venv afterwards, and none renames it.

### Hypotheses, ranked by evidence

1. **(Strong) No hook-path build ran during the drift hours.** `_venv_self_heal` is reached only from
   `! _is_daemon_installed` (`init.sh:2876-2884`), and the drifted py311 venv kept resolving. The evidence:

   - the only bootstrap log on disk starts at 11:09:22, during the owner's fix;
   - the incident observed no py313 dir before that;
   - every "running" message had no log or record, which means the holder was not a hook build.

   "Each build finished" in the incident was really the lock being released by some other holder.

2. **(Strong) If a build had run during the drift, it would still have "succeeded" without fixing anything.** The
   success judge `resolve_venv_python` (`venv_bootstrap.sh:279`) runs metadata step 2 over a sorted glob.
   `venv-workspace-py311-…` sorts before `…-py313-…` and both match the lock_hash, so the judge returns py311. It
   logs SUCCEEDED, and the next start uses py311 again. Interpreter drift is invisible to the judge.

3. **(Medium) The lock holder was a repair/restart chain, the 00517 start-cleanup, or a QA, worktree or upgrade
   process.** Any of them could hold the flock on a process that later lived on. This is not determinable from
   current state. Task 2.7 should record every holder, not only hook builds.

4. **(Weak) The output was deleted.** No code path deletes a fingerprint venv on build failure. 00517 cleanup only
   removes `stale` (lock_hash-differs) venvs (`cli.py:3398-3425`, `paths.py:2982-3016`). This is ruled out.

## 3. Is pyvenv.cfg's version compared with the running interpreter?

**No.** The only reader is `paths.py:3280-3291` (`_read_pyvenv_cfg`). Its result feeds the display-only evidence in
`gather_venv_evidence` (`paths.py:3303-3330`, "python_version" for list-venvs). `git_file_states.py:149` only uses
the file as a venv marker. Neither `classify_venv` (`paths.py:2982`) nor the resolver nor `_venv_is_fresh`
(`venv.sh:1078-1103`) looks at the interpreter version.

**Where the check belongs:**

- **Primary:** in the resolver's usability test, so that every consumer (wrapper, init.sh, builder success judge,
  repair arm) agrees. Replace or extend `_venv_interpreter_runs` (`paths.py:943`) and its bash twin
  `_rv_candidate_runs` (`resolve_venv.sh:212`). The probe should check that the interpreter's `major.minor` equals
  pyvenv.cfg's `version_info`/`version`, or more robustly that the venv's `site-packages` is on its `sys.path`. On a
  mismatch, report the venv as STALE, not usable.
- Then `classify_venv` (`paths.py:2982`) should return `stale` for it.
- `_venv_is_fresh` (`venv.sh:1078`) should rebuild it.
- The hot cache (`resolve_venv.sh:473`) must not serve it. One option is to also key the cache on the
  `/usr/bin/python3` target or version.
- A drift test belongs at the `paths.py` level (Task 1.1).

## 4. Fail-closed allow-list and the daemon-down Stop block

**Allow-list.**

- PreToolUse is denied in the "standard" down state unless `_hooks_daemon_stdin_is_recovery_command` passes
  (`init.sh:695-707`).
- The predicate is `_is_daemon_recovery_command` (`init.sh:249`). It requires `tool_name == "Bash"` (`:250`), so
  **Read, Grep and Agent are always denied**.
- The command must be exactly a launcher (`.claude/hooks-daemon/bin/hooks-daemon` or `bin/hooks-daemon`, `:168-169`)
  plus one of `restart status logs stop start repair` (`init.sh:170`), padded only by spaces or tabs.
- The relay/transport path applies the same predicate (`init.sh:3378-3379`).

Note that the VENV_MISSING, NOT_INSTALLED, VERSION_MISMATCH and REPO_UNCONFIGURED states are excluded from the deny
(`init.sh:696-701`) and fail open. So during the "venv missing" phases tools were actually ALLOWED. Only the plain
"not running" phases denied everything.

**The Stop block.** "Hooks daemon not running - protection not active" is produced at:

- `init.sh:1117-1121` (jq encoder, standard branch);
- `init.sh:1195` (python encoder twin);
- `init.sh:3371` (the `send_request_stdin` transport-failure path).

The "venv missing" Stop block is at `init.sh:1096-1101` (reason from `:858`). The stop forwarder is
`.claude/hooks/stop:38-45`.

**Bound.** There is **none**. init.sh never reads `stop_hook_active` or keeps a count, has no `[awaiting-human]`
handling, and the relay has no equivalent either. Each stop is judged afresh.

## 5. Related plans and overlap with Phase 2

- **00099** (Completed, `CLAUDE/Plan/Completed/00099-python-fingerprint-venv-isolation`): introduced the
  fingerprint key that the builder and the Python repair use. It is not the cause of the "missing" message (see
  1.2), but its key is what diverges from the resolver's lock_hash-first lookup. Relevant to Tasks 2.1 and 2.2 (the
  re-key).
- **00313** (Completed): the slug-eligibility check (`paths.py:249-270`). It did not cause this. Task 2.1 must keep
  it.
- **00456** (Completed): the hook self-heal plus wrapper `repair` with no venv. It covers only "resolver fails",
  which is the gate at `bin/hooks-daemon:270`. Task 2.3 extends it so that `repair` also runs when the resolver
  returns a STALE/drifted venv. Task 2.7 covers the record that only hook builds write today.
- **00517** (Completed): one staleness rule, `classify_venv`, and start-time cleanup. Its rule is lock_hash plus
  slug only. Task 2.2 adds interpreter drift to that same rule (`paths.py:2982`). That also lets the cleanup prune
  the py311 orphan.
- **00100** (Dormant; residue Phases 4 to 6): it is the venv SSoT plan, and Task 2.1 is essentially its subject.
  Phase 4 (the lock) has since shipped (`venv_lock.py`, Plan 00100 Phase 4 header). Task 2.1 should fold into it or
  supersede it.
- **00488** (not listed, but directly implicated): the "build window" branch at `init.sh:2901-2911` is what
  mislabels a resolved-but-broken venv as "missing". This is relevant to Tasks 2.4 and 2.7.

### Phase 2 adjustments suggested by the evidence

- **Task 2.2:** the drift check must live inside the shared resolver's "usable" test. Otherwise the builder's
  success judge (`venv_bootstrap.sh:279`) will keep certifying the stale venv.
- **Task 2.4:** split init.sh's "resolves but cannot start" state from VENV_MISSING. Run the `sys.path` probe there.
- **Task 3.1:** prune the py311 directory rather than re-keying it. The live venv is already the correctly named
  py313.
