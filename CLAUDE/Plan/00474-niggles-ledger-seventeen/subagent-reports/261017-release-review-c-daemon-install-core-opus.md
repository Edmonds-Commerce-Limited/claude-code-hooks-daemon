# Release v3.70.0 code review C: daemon/, install/, core/, config/ and the small packages

Scope: `git diff v3.69.0..HEAD` (HEAD 9513c3d45) over src/claude_code_hooks_daemon/ minus handlers/, strategies/, utils/.
153 files, +6521/-1245. Read-only review. I stopped early because the subagent context budget ran out, so the
"Not reviewed" section is long. Treat it as unfinished coverage, NOT as a clean bill.

## Scope covered (files read)

Read in full or hunk by hunk with the surrounding code:

- daemon/tier_report.py (new): read in full
- daemon/spend_report.py (new): read in full
- install/background_sync.py (new): read in full
- install/upgrade_gate.py: whole diff (owner approval removed, phasing advice added). I cross-checked
  scripts/upgrade_version.sh verdict handling and looked for leftover approval references (none, apart from the
  merge-approval and plan-close stores, which are separate)
- daemon/paths.py: whole diff (ranked venv scan fallback, `_load_package_module_by_path`, the runtime-set sweep,
  `classify_venv` and friends, the /proc process scan, venv evidence, `list-stale-venvs`)
- daemon/server.py: whole diff (SO_PEERCRED peer pid stamping, deferred start-up, the log_and_continue conversions)
- daemon/controller.py: whole diff (deferred start-up, reuse of the loaded config, per-event deadline)
- daemon/cli.py: these sections only: `_reap_stale_runtime_files` (runtime-set sweep and stale-venv cleanup on start),
  daemon start wiring (~880-975), `cmd_restart` + `_warn_if_venv_not_built_for_source`, `_record_repaired_venv_lock`,
  `_enumerate_venvs`, `_entries_with_verdict`, `_cleanup_proven_stale_venvs`, `_stale_venv_advisory`, list-venvs
  markers, `_prune_one_unproven`, `cmd_prune_venvs`, `_write_venv_metadata`
- scripts/install/venv.sh `eager_cleanup_stale_venvs`: outside my paths, but it is the consumer of paths.py
  `list-stale-venvs`. I compared it against v3.69.0

## DEFECTS

Count: 1 (1 CONFIRMED, 0 PLAUSIBLE)

### D1. Any zombie process, or any kernel thread when the daemon is not root, turns off the start-time stale-venv cleanup (CONFIRMED)

Location: `src/claude_code_hooks_daemon/daemon/paths.py:3152-3187` (`processes_using_venvs`, the
`if not any(found.values()): if entry.exists(): unreadable += 1` branch at :3180), consumed at
`src/claude_code_hooks_daemon/daemon/cli.py:3155` (`if scan.unreadable: ... return []`).

What goes wrong: a pid is counted as "unreadable (another user's)" whenever its `exe` link, its `cwd` link and its
argv[0] all come back empty, and the pid entry still exists. Two common kinds of process look like this without
belonging to another user:

- a zombie, even one owned by this user. Its cmdline is empty and both links fail with ENOENT, and `/proc/<pid>` still
  exists until the parent reaps it;
- every kernel thread, when the scan runs as a non-root user on a host with no PID namespace (a normal developer
  machine). The cmdline is empty, `exe` fails, and `cwd` gives EACCES to a non-root user.

`_cleanup_proven_stale_venvs` refuses to remove anything when `scan.unreadable` is non-zero. On a non-root host
install it therefore never removes a proven-stale venv: there are always kernel threads. In a container, one
unreaped zombie anywhere in the PID namespace has the same effect. The documented contract (cli.py ~640: "venvs
PROVEN stale ... are removed on every start, restart and provision") is not kept. The cleanup fails closed, so
nothing unsafe is deleted, but the Plan 00517 Task 4.1 disk reclaim silently never happens. All you get is an INFO
log line, "Kept stale venvs: N process(es) could not be read". The same false count also goes into the
`VenvEvidence` that `list-venvs` and the SessionStart advisory print, as "N process(es) could not be read (another
user's), so 'no process' is not certain". That text puts the blame on another user's processes when the cause is
zombies or kernel threads.

Failing input / reproduction: `untracked/scratch/crev-c/probe_zombie.py` (kept as evidence). It forks a child that
exits at once and is not reaped, then calls `processes_using_venvs([Path("/nonexistent-venv")])`. Output in this
container:

    zombie pid 3466979 state: Z
    unreadable = 1
    after reap unreadable = 0

Run: `untracked/venv-workspace-py311-2a519198/bin/python untracked/scratch/crev-c/probe_zombie.py`.

Why the tests miss it: tests/unit/daemon/test_paths_venv_evidence.py and test_cli_stale_venv_cleanup_on_start.py
build a fake `proc_root`. Its fake pids either have readable links or are deliberately unreadable "other user"
entries. None models a zombie or a kernel thread (empty cmdline, failing links, entry still present), and the suite
runs as root inside a PID namespace, where neither case shows up.

Suggested fix: skip, rather than count, a pid whose `/proc/<pid>/stat` state is `Z`, and a pid whose cmdline is
empty because it has no user memory (kernel threads: `exe` fails with ENOENT, not EACCES). Count only a pid where
something was actually refused with EACCES/EPERM. Add fake-proc fixtures for a zombie and a kernel thread, and assert
`unreadable == 0` and that the cleanup removes the stale venv.

## NON-DEFECTS

N1. Two different safety models for removing stale venvs (design question). The daemon-start path
(cli.py `_cleanup_proven_stale_venvs`) will not remove anything while `peer_runtime_sets_not_proven_dead()` finds a
peer host, or while a /proc scan shows a user. The upgrade path (scripts/install/venv.sh `eager_cleanup_stale_venvs`
-> paths.py `_cli_list_stale_venvs`, paths.py ~3314) does an `rm -rf` on every `remove` line with neither check.
This is not a regression: v3.69.0 removed every non-current venv. But cli.py says that, with a possible peer sharing
the checkout, "the removal is manual only", and the upgrade path does not honour that. Remediation: have
`list-stale-venvs` downgrade `remove` to `keep` when `peer_runtime_sets_not_proven_dead` is non-empty or a
`processes_using_venvs` scan finds a user. Note this depends on D1 being fixed first, or upgrades will stop
reclaiming too.

N2. `paths.py:3117` `_is_inside` needs `candidate.startswith(prefix + os.sep)`, so a process whose cwd IS the venv
directory (not a sub-path) is not reported as using it. Low impact. Remediation: also accept `candidate == prefix`.

N3. `processes_using_venvs` only matches an absolute argv[0]. A daemon launched as a relative
`untracked/venv-x/bin/python` with cwd at the daemon dir shows `exe=/usr/bin/python3.x`, a cwd outside the venv, and
a relative argv0, so it is not found. Mitigated because the live/resolver venv is excluded by `live_venv_realpaths`.
Remediation: resolve a relative argv0 against that pid's cwd link.

N4. `server.py` `_run_deferred_startup` runs in the default executor. `deferred_startup_task.cancel()` at shutdown
does not stop the worker thread, so a slow CLAUDE.md injection or index pre-warm keeps running, and
`asyncio.run`'s executor shutdown waits for it. Shutdown is delayed, nothing is wrong. Remediation: check
`_shutdown_requested` between steps in `_run_deferred_steps`.

N5. `paths.py:965` `_best_ranked_scan_candidate` recomputes the pyproject + uv.lock hash on every scan-fallback call
of `resolve_existing_venv_python`, and the docstring says that function sits on hot paths. Remediation: memoise on
(path, mtime) of the two files.

N6. Magic number: `paths.py:2699` `ledger_max_age_days * 86400`. Remediation: use a named seconds-per-day constant
(the sibling `max_age_seconds` computation probably has the same literal; share one).

N7. `install/background_sync.py:98-101` accepts `pid=0` (`"0".isdigit()`), and `os.kill(0, 0)` signals the process
group and always succeeds, so a corrupt `pid=0` RUNNING record reads as alive forever. Only provision.sh writes the
file, so this is unlikely. Remediation: treat `pid <= 0` as None.

N8. `daemon/tier_report.py:106-123` `unjoined` adds two different units: dispatch rows that are not pre-recorded or
have no resolved model, plus agents with neither a row nor a toolUseId. An agent whose toolUseId matches no row is
not counted at all. The header calls the total "unjoined dispatch rows". Remediation: report rows and agents as
separate counts, and count an agent with an unmatched toolUseId.

N9. `upgrade_gate.py` approval removal (Plan 00503) is consistent: the bash caller handles exit 0/3/timeout/other,
the verdict file no longer carries `approval-marker=`, and nothing in src/ or scripts/ still references
`APPROVE_COMMAND`, `NEEDS_APPROVAL` or `upgrade-approvals`. The gated-install receipt moved from `upgrade-approvals/`
to `upgrade-gate/`. A receipt left in the old directory is ignored, so a same-version re-run after upgrading lists the
range as unknown and asks for a reading once. Acceptable; noted for the release notes.

## Positive observations

- `_runtime_set_is_dead` fails closed at every point of doubt: grace window, sockets outside the tree, an unreadable
  discovery file, a verified pid. The start-time sweep is wrapped fail-open, so a race cannot stop a start.
- Peer pid stamping (`_set_peer_pid`) drops any caller-supplied `hooks_daemon_peer_pid` before stamping the
  kernel-reported one, on both the legacy and the event-socket paths.
- Config validation (degraded mode) is correctly kept out of the deferred start-up set.

## Not reviewed (context budget ran out)

Not read at all; they need a second reviewer before the gate closes:

- daemon/cli.py beyond the sections listed above: `cmd_tiers`, `cmd_spend`, `_resolve_ledger_session`,
  `cmd_exceptions`, `_loaded_handler_keys`, `_with_project_handler_keys`, `cmd_defences`, the remote-docs fetcher
  and refresh changes, `_capture_value_swapper`, the explain-rule changes, the parser additions, `cmd_status` changes
- core/utils.py (+362), core/usage_snapshot.py, core/transcript_reader.py, core/project_context.py,
  core/claude_md_injector.py, core/chain.py, core/hook_result.py, core/result_types.py, core/rule.py, core/router.py,
  core/handler_scope.py, core/worktree_reaping.py, core/worktree_paths.py, core/debouncer.py
- config/exceptions_listing.py (new), config/yaml_loading.py (new), config/models.py, config/loader.py,
  config/validator.py
- install/effective_handlers.py, install/forwarder_generator.py, install/templates/mkplan.bash, install/agent_assets.py,
  install/transport_*.py, install/upgrade_guides.py, install/upgrade_gate_standalone.py, and the template/skill markdown
- constants/ (priority.py ranges NOT checked), rule_explain/checks.py (new) and defences.py,
  config_optimisation/qa_runner_agents.py (new), qa/full_qa_gate.py, docs_qa/ (unlisted_fake_value.py),
  plan_qa/ (readme_index.py, row_folder_bijection.py; the 40 three-line check edits were not opened),
  daemon/verdict_log.py, hook_probe.py, process_verification.py, work_queue_cli.py, docs_generator.py,
  playbook_*.py, and the remaining small packages
- I did not check for missing tests per behaviour change, beyond the two test files named under D1
