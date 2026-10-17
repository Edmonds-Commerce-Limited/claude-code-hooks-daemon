STOPPING BECAUSE: review pass complete within budget. Findings are below; the parts I did not review are listed at the end.

# v3.70.0 Step 10 review, pass 2: install/, constants/, qa/, docs_qa/, plan_qa/, daemon misc

I found **no defects** in what I reviewed (0 confirmed, 0 plausible). This was read-only: I edited no tracked file and made no commit.

## Scope covered
I read the diffs over `v3.69.0..9513c3d45`. The working tree matches that commit for these paths.
- **install/**:
  - `effective_handlers.py`: `apply_restore` and the text editor behind it. I also traced how `config_cli.py`, `daemon/cli.py` `cmd_check_effective_handlers`, `scripts/upgrade.sh:1150-1240` and `scripts/upgrade_version.sh:615-660` call it.
  - `forwarder_generator.py`, `templates/mkplan.bash`, `agent_assets.py`, `transport_toggle.py`, `transport_verify.py`, `upgrade_guides.py`, `upgrade_gate_standalone.py`.
  - `DocumentationStrategy.core.md`, and the `skills/hooks-daemon/` changes to `SKILL.md`, `check.md`, `optimise.md`, `provision.md` and `upgrade.md`.
- **constants/**: `priority.py` (every added priority checked against the bands), `timeout.py`, `events.py`, `dbf.py`, `protocol.py`, `tools.py`.
- **rule_explain/**: `checks.py`, `defences.py` (plus `cmd_defences` in `cli.py:3880-3955`), `lookup.py`.
- **config_optimisation/**: `qa_runner_agents.py`, `checklist.py`, `state.py`.
- **qa/**: `full_qa_gate.py`, `pytest_text_report.py`.
- **docs_qa/**: every check edit, including `unlisted_fake_value.py` with its new STAGED stage (traced through `utils/git_facts.py`), plus `corpus.is_lintable_path` (traced through `utils/repository_scope.py`) and `comment_finder.py`.
- **plan_qa/**: `readme_index.py`, `row_folder_bijection.py`, `command_journal.py`. I skimmed the roughly 40 small check edits; each one only adds a `STATEMENT` constant.
- **daemon/**: `verdict_log.py`, `hook_probe.py`, `process_verification.py`, `work_queue_cli.py` (traced `make_gh_runner` and `refresh_workable_cache` for what they can raise), `docs_generator.py`, `playbook_generator.py`, `playbook_harness.py`.

## How I checked the riskiest parts
- **`apply_restore` (runs in client projects during upgrades):** I ran it against 11 config shapes using the daemon venv, writing to temporary directories under `untracked/scratch/rr2tmp/`.
  - Shapes that edited correctly: a plain config, no `handlers:` section, inline `handlers: {}`, a null event block, four-space indentation, a leading `---`, a trailing `...`, and a `handlers:` section followed by another top-level key.
  - Shapes that were refused with the file left untouched: a quoted event key, an empty file, and a comments-only file.
  - Every edit is re-parsed and checked before it is written, so in every case the result was either correct or the file was unchanged.
  - The double run is safe. When Layer 2 restores the handlers, the later Layer 1 `--apply` run finds nothing to change (rc 0) and reads Layer 2's report from the handoff file instead.
- **`upgrade_gate_standalone`:** the new load list matches the actual imports: `deliberate_swallow` imports `escape_hatch`, and both are loaded before `upgrade_tasks`. Running it with `-I --help` loads cleanly. Removing `approve` matches the gate, which now only uses exit codes 0 and 3, and matches `upgrade.md`.
- **Forwarder wait for worktree events:** `str(EventType)` gives the same strings as `meta.json_key` (`WorktreeCreate` 60s, `WorktreeRemove` 70s), and these match the `_event_socket_wait` values in `.claude/init.sh`.
- **xdist check in `full_qa_gate`:** I suspected the `pytest_configure` check could run before xdist registers `dsession`. It does not: the gate is loaded early via `-p claude_code_hooks_daemon_full_qa_gate_loader` (pyproject `addopts`), so xdist's own trylast `pytest_configure` runs first. I could not run this for real because xdist is not installed.
- **Priorities:** `WRITE_PROTECTED_PATHS` is 18 (safety band). `SUBAGENT_CONTEXT_BUDGET` and `RESUME_GUARD` are 39 (workflow band). The new advisories are at 60, `UNPROVEN_VENV_ADVISOR` at 72, `DISPATCH_MODEL_RECORDER` at 33 beside its sibling, and the Stop/SubagentStop slots (4, 9, 11) follow their chain-ordering comments. Each one is documented and consistent.

## Non-defects
Each item gives a location, how much it matters, and a fix.
1. **`install/effective_handlers.py:202-216` `_replace_file`.** Minor. It replaces the file by writing a temp file and renaming it, so a config the owner made read-only (0444) in a writable directory is still rewritten. The upgrade's failure message mentions "permissions", which suggests otherwise. Fix: return False when `os.access(real, os.W_OK)` is false, before calling mkstemp.
2. **`templates/mkplan.bash` `scan_plan_tree` and its Python twin `plan_numbering.highest_plan_number`.** Low likelihood. Both recurse through symlinked directories, so a symlink loop under the plan directory never ends (bash) or hits a RecursionError (Python). The two are the same, so this is not a parity gap. Fix: skip symlinked entries in both (`[[ -L "$entry" ]] && continue` and `entry.is_symlink()`), and keep the parity test pinning them.
3. **`rule_explain/defences.py:645-660`, called from `cli.py:3929`.** Minor. If `qa-rules.json` has a malformed `batch_defences` (a list) or `rules` (non-dict entries), the code raises AttributeError or TypeError. The CLI only catches OSError, ValueError and KeyError, so `defences` prints a traceback instead of its "not a usable QA rule registry" message. It only happens when `batch_defences` exists and is malformed. Fix: add `isinstance` checks that raise ValueError, or add `TypeError, AttributeError` to the CLI's except.
4. **`docs_qa/checks/unlisted_fake_value.py:369-382` `_run_staged`.** Design question. The gate allows the commit in two cases: when `recorded_text` returns None (git could not read the file), and when the project root is a subdirectory of the git repository, because the staged path is then not equal to `.claude/fake-values.yaml`. An unparseable registry, by contrast, is blocked. Fix: decide whether an unreadable staged registry should block, and if the project-root-in-subdirectory layout is supported, compare paths against the project prefix.
5. **`priority.py`.** Consistency question only. `SUBAGENT_HANDOFF_GATE = 11` is a cost control placed in the safety band, while its sibling `SUBAGENT_CONTEXT_BUDGET` is placed at 39 "because it is a cost control". The SubagentStop chain ordering justifies 11, so this is not a defect. Fix: optionally add one line to its comment saying why it is below 25.

## Not reviewed
- **install/:** `upgrade_gate.py` (438-line diff), `background_sync.py` (new, 136 lines), `config_cli.py`, `upgrade_tasks.py`, `client_validator.py`, `directory_role_rules.py`, `skills.py`, and the body of the new `agents/hooks-daemon-plan-fact-checker.md`. My only check on that agent file was that its md5 matches `_FACT_CHECKER_MD5`.
- **constants/:** `handlers.py` and `rule_ids.py` (large string and ID tables).
- **daemon/:** `paths.py` (+883), `server.py`, `controller.py`, `spend_report.py`, `tier_report.py`, `synthetic_traffic.py`, `init_config.py`, `metadata.py`, `validation.py`, `permission_audit.py`, `project_handler_health.py`, `issue_validity_cli.py`, `payload_capture.py`, `enforcement.py`, `housekeeping.py`.
- **Other packages:** I did not list the remaining small packages under `src/` (for example `remote_docs/` and `pseudo_events/`). Treat them as not reviewed.
- **Tests:** I did not check that tests exist for each behaviour change, and I ran no test files.

The probe inputs are in this transcript; I wrote no probe script file. The diffs I read are saved in `/workspace/untracked/scratch/`: `rr2-install.diff`, `rr2-md.diff`, `rr2-rq.diff`, `rr2-qa.diff`, `rr2-daemon.diff`, plus the stat listing `rr2-stat.txt`.