VERDICT: FAIL

# Release 3.75.0, Step 10 code review gate (git diff v3.74.0..HEAD -- src/)

Branch: release/3.75.0 at 70c48bf55. This was a read-only review: nothing was edited, committed or pushed.
Scope: 89 files under src/ (+7959/-1302 lines) across 394 commits. The review was split into four areas, each covered by a code-reviewer pass, and the coordinator re-checked the highest-severity findings against the source.

- Area A: the branch-lifecycle guards.
- Area A2: the remaining branch files.
- Area B: the secret guard and the command-parsing guards.
- Area C: daemon core, the CLI, install and state.

Full per-area reports:

- untracked/agent-reports/auto/261116-213955-code-reviewer-a601365a616597296.md (A)
- untracked/agent-reports/auto/261116-214616-code-reviewer-a8b4e77d4795232c3.md (A2)
- untracked/agent-reports/auto/261116-214704-code-reviewer-a3708832e2d8e03b8.md (B)
- untracked/agent-reports/auto/261116-214339-code-reviewer-a712cef269222f798.md (C)

Probe repositories: untracked/scratch/s10a/ and untracked/scratch/s10a2/.

**Totals: 38 findings.**

- 5 blocking
- 20 non-blocking defects
- 13 nits

**Severity note.** The area-B reviewer rated B-3 to B-5 as non-blocking or borderline. The coordinator raised them to blocking, because each one is a fail-open in the secret guard that this release introduced. The exemption code is absent at v3.74.0.

Under "A release carries no known defect" (RELEASING.md, "Review Early, Never Drop Findings"), every DEFECT below has to be fixed before the tag, or explicitly accepted by the human in the release session. That includes the non-blocking ones. The gate is a FAIL.

"Re-checked" means the coordinator re-read the code path. "Probed" means the reviewer ran a reproduction.

## Blocking

### B-1: delete-branch can delete unpushed work, and no recovery copy remains

`src/claude_code_hooks_daemon/daemon/branch_safety.py:769-783`. Invoked from `daemon/cli.py:6969` (no `content_tier` argument and no unpushed check in front of it), where `content_tier` keeps its default of True.

- **What is wrong.** `content_unique_paths_of` (:550) proves the `content-preserved` tier like this: every blob in the tip's tree exists somewhere in the base's reachable objects. That check ignores the path, ignores deleted files, and ignores which version of a file is current.
- **What changed.** Commit 64a74a1f1 removed the recovery bundle that used to back this tier. The weak proof is now the only thing standing between the user and a deletion. The fallback is a printed `git branch <name> <sha>` restore line, and that stops working once git garbage-collects the commit.
- **Repro (probed, untracked/scratch/s10a/cp).**
  1. On main, change `a.txt` from v1 to v2.
  2. Branch `feat` deletes `b.txt` and sets `a.txt` back to v1. It is never pushed.
  3. `delete_branches(repo, ["feat"], dry_run=True)` returns tier `content-preserved`, refused=False and no blockers. A real run deletes it.
- **Fix.** Use the per-path net-change proof (`remote_branch_proof._holds_net_change`), or drop the content tier from delete-branch.
- **Status:** re-checked.

### B-2: the stop guard hands over any worktree under `.claude/worktrees/` (or any locked one) without checking that an agent is alive

`src/claude_code_hooks_daemon/core/branch_stop_gate.py:121-147`, applied at :187.

- **What is wrong.** `_owned_branches` treats a harness-directory or locked worktree as owned by a live agent. The main thread then drops every finding for that branch, including its own `full` findings. It also reports the branch as "handed over to running agents", which nothing checked.
- **Who is hit.** A `claude --worktree` session, and the leftover worktree of a sub-agent that has finished. Neither is ever judged.
- **Repro (probed, s10a2/probe p1).**
  1. Touch branch `x` from the main thread.
  2. `git worktree add .claude/worktrees/x x`.
  3. Commit, and leave a dirty file. Do not push.
  4. `decide_stop(agent_id=None)` returns reason=None.
- **Fix.** Never hand over a branch in the session's own set. For the directory signal, require liveness (a queue record or a lock), as worktree-reap does.
- **Status:** re-checked.

### B-3: the secret guard allows `git grep -G <protected>`

`src/claude_code_hooks_daemon/utils/secret_file_matching.py:2086-2127`, and `_opens_files` at :2322-2326, where `_ends_in_git_search_option(words)` is tested whatever the git subcommand.

- **What is wrong.** This release added `_GIT_SEARCH_VALUE_OPTIONS`, which assumes `-S` and `-G` take a search-string value on every git subcommand. On `git grep`, `-G` is `--basic-regexp` and takes no value, so the next word is a file that git reads.
- **Repro.**
  - `git grep --no-index -e . -G <name matching a protected glob>` is ALLOWED.
  - The same command without `-G` is denied.
  - `git grep --no-index -c -e . -G README.md` shows that git does read the file.
- **Fix.** Apply the exemption only to the log/show/diff/rev-list/format-patch/whatchanged family. Add deny tests for git grep.
- **Status:** re-checked (the set is not scoped to any subcommand).

### B-4: the secret guard allows `git blame -S <protected> f`

Same code as B-3, plus :2381-2382, where the attached `-S<P>` spelling is exempted by `_git_search_value_prefix_before`. The coordinator re-checked the code path; the reproduction was the reviewer's probe.

- **What is wrong.** On blame, `-S` names a revs-file that git reads. On a bad line git prints `error: bad graft data: <line>`, so the file's lines reach the output.
- **Repro.** `git blame -S<P> f` and `git blame -S <P> f` are both allowed, where `<P>` is a name matched by a protected glob.
- **Note.** Exact protected basenames still deny in this shape; names that match only a glob get through.
- **Fix:** same as B-3.

### B-5: the grep/rg path exemption skips the first searched path when the pattern comes from `-eX` or `--regexp=X`

`src/claude_code_hooks_daemon/utils/secret_file_matching.py:2164-2167`, `paths = operands[1:]`.

- **What is wrong.** The code always treats the first word that does not start with `-` as the pattern. When the pattern is attached (`-ezz`, `--regexp=zz`), that first word is really a searched directory, and it is never checked against the protected-file index.

- **Repro (direct call with a stub index in which only `held` contains a protected file).** Each of these is judged clean, which is a fail-open:

  - `grep -r --regexp=zz held src --include=*`
  - `grep -r -ezz held src --include=*`
  - `rg --regexp=zz held src --glob=*`

  The controls with a separate `-e zz`, or a bare pattern, are judged not clean.

- **Not yet confirmed** end to end through the live guard.

- **Fix.** When any `-e`/`--regexp`/`-f`/`--file` spelling is present, treat every operand as a path.

- **Status:** re-checked (logic confirmed).

## Non-blocking defects

### N-1: a malformed park record fails OPEN in several guards

`src/claude_code_hooks_daemon/core/branch_park.py:114`.

- **Cause.** `int(values[_AT_KEY])` is not guarded, so it raises ValueError, not BranchParkError.
- **Impact 1.** The PreToolUse branch-creation guard (tagged workflow, not safety) has the exception swallowed by `chain.py:~1240`, so every branch creation in the repo is allowed whatever the cap.
- **Impact 2.** The Stop guard's catch-all at `handlers/utils/branch_stop_guard_base.py:115` allows the whole stop, for every branch.
- **Impact 3.** The SessionStart `_ended_park_lines` (`handlers/session_start/branch_sweep.py`) catches only BranchParkError.
- **Impact 4.** `branch_inventory.py:1292` and `_clear_parks` also break.
- **Repro (probed).** Set all four `branch.feat.hooksDaemonParked*` keys, with `ParkedAt=notanint`. Then:
  - `creation_verdict(repo, BranchesConfig(), "newb")` raises ValueError.
  - `_handed_over_by_park` raises.
- **Fix.** Treat an unparsable record as "no record" and log it, or raise BranchParkError. Add tests for the unreadable-record path.

### N-2: bulk `--clean --apply` checks a worktree, then removes it much later

`src/claude_code_hooks_daemon/core/branch_cleanup.py:862` (check) and :1025-1027 (removal).

- `worktree_blockers` runs long before `_remove_worktree`. In between come the classification, the `ls-remote` and earlier batches.
- A plain `git worktree remove` deletes ignored files, so ignored files added in that gap are lost.
- **Fix:** re-check immediately before the removal.

### N-3: a park record is cleared even when the delete is then refused

`core/branch_cleanup.py:1034` and :671, and `delete_if_merged`.

- The park record is cleared before the delete runs.
- **Repro.** The tip moves after classification. `tip_moved_since_proof` then refuses the delete, but the record is already gone.
- **Fix:** clear the record only for names in `report.deleted`.

### N-4: hook paths now make network calls

`core/branch_cleanup.py:557/569`, `remote_delete_advice`.

- This now runs the full `prove_remote_merged` (`ls-remote` plus the diff, ls-tree and log walks) once per merged branch. It is called from the PostToolUse `cleanup_after_merge` handler and from WorktreeRemove's `delete_if_merged`.
- `cleanup_after_merge.py:181` (`_pool_clear_lines`) also runs a full `creation_report` after every merge.
- **Fix:** batch the proof, or give owner-only wording on hook paths.

### N-5: one git process per local branch on every branch-creation check

`core/branch_park.py`, `read_park_record`.

- It runs four `git config --get` calls with no timeout, once per local ref, on every PreToolUse creation check (via `_with_standing_parks`). The inventory does the same.
- In the stop guard these calls run outside `_Budget`.
- **Fix:** one `git config --get-regexp` per pass.

### N-6: `park_branch` can report "nothing changed" after it has moved the branch

`core/branch_park.py:384`.

- `_record_park` runs after `update-ref`. A config-lock failure there raises BranchParkError, whose contract promises "nothing changed". In fact the park commit stands, there is no record, and nothing was pushed.

### N-7: `wip.mode: warn` and `dormancy.mode: warn` still deny a stop

`core/branch_stop_guard.py:215-222`.

- The code only tests `!= "off"`, and `advisory` is never set from the mode.
- **Repro (probed, p2).** Set cap 1 and `wip.mode: warn`, with two of the session's own pushed open branches. The stop is denied with "open pool over cap".
- The creation path never denies in warn mode.
- There is no test for this.

### N-8: the stop guard's over-cap count disagrees with the other counts

`core/branch_stop_guard.py:218`.

- The stop guard counts branch NAMES. `open_work_count`, `pool_count` and `creation_report` count identical tips once.
- **Repro (p3).** Put branches `a` and `a2` on the same pushed tip, set cap 1, and touch `a`. The stop is denied, but `open_work_count` returns 1.

### N-9: `--json` has no `action` for park-carried branches

`core/branch_sweep.py`, `_record_json`.

- `action` is set only for merged and patch-equivalent branches. The text report prints a delete line for park-carried branches, so the two outputs disagree.
- Found by reading the code.

### N-10: `git_repo.write_config` can wait longer than the hook deadline

`src/claude_code_hooks_daemon/utils/git_repo.py:599`, which calls `utils/git_config_write.py:102`.

- It now raises GitConfigLockError, which is not in its docstrings or in `write_plan_counter`'s.
- It waits up to 30s for the config lock (load-scaled). It is reachable on a PreToolUse path (plan allocation), which runs under a 20s guard-chain deadline. A timeout there ends as an ALLOW.
- From reading only.
- **Fix:** use a short ceiling on hook paths.

### N-11: long-running classifier: a trailing `&` exempts a whole `;` list

`utils/long_running_command.py:407`.

- **Repro.** `sleep 300; echo x &` and `pytest tests/; true &` produce no findings, although only the last statement runs in the background.
- The handler ships disabled.

### N-12: long-running classifier: never-ending and long shapes are missed

`utils/long_running_command.py:115, :379, :392`.

- **Repro.**
  - `tail -f log` and `sleep infinity` produce no finding.
  - `bash -c "sleep 100"` produces no finding.
  - `(sleep 100)` is misread as an unbounded `(sleep`.
  - `sleep 100 & wait` gets only an advisory.

### N-13: the long-running deny message breaks long commands

`handlers/pre_tool_use/long_running_command_guard.py:343`.

- The "exact" background command it offers is cut at 240 characters and given a ` ...` suffix, so a long command copied from it is broken.

### N-14: a bad regex in the long-running policy silently drops configured patterns

`long_running_command_guard.py:281`.

- On ValueError, both the extra slow patterns and the exempt patterns are dropped, with no log line.

### N-15: config validation accepts a value the reader then rejects

`src/claude_code_hooks_daemon/config/models.py:2091`, against `utils/permission_surface.py:143`.

- **Repro (probed).** `omit_permission_surface: "true"` passes validation, because pydantic's lax bool accepts it. The reader requires a real bool, so the switch is silently off.
- **Fix:** StrictBool.

### N-16: `session-state --interval` is not validated

`daemon/cli.py:11842` (used at ~2469).

- `--watch --interval -1` crashes on `time.sleep` after the first line (probed).
- `--interval 0` makes back-to-back IPC calls.
- **Fix:** a positive-float argparse type.

### N-17: the version check can drop the branch-install advisory

`handlers/session_start/version_check.py:564`.

- `int(ttl_hours)` is outside any try. A string TTL such as "1.5" raises (probed). From the second session start on (the first cache hit), `handle()`'s broad except returns empty context, so the branch-install warning disappears.
- `_is_cache_valid` guards the same conversion. Share one helper.

### N-18: a relay repair can outlive the daemon stop

`install/relay_repair.py:227` and :268.

- A `_start_relay_repair` that has already passed the shutdown check can `spawn_owned` after `stop_owned_repairs` has emptied `_owned`. That repair keeps writing after the stop.
- From reading only.
- **Fix:** refuse spawns under `_owned_lock` once stopping has begun.

### N-19: test gaps for handler and utility changes (checklist item "tests exist for every handler change")

- No tests were changed or added for the `omit_permission_surface` wiring in `handlers/session_start/hook_registration_checker.py`, `install/client_validator.py` or `utils/settings_repair.py`.
- `handlers/session_start/relay_binary_checker.py` was refactored onto `repair_unusable_relay`, and its tests are unchanged.
- The tests that mention `omit_permission_surface` (excluding fixtures) cover only `permission_surface`, `settings_merge` and the `permission-surface` CLI verb. The commit that introduced the switch (684a6f965) is itself labelled "untested". `utils/hook_registration.py` was changed in that commit.
- The new-test check for `utils/workable_issues.py` and `utils/cron_hosts.py` (changed in d696d45cc) was by file name only, so it is not a confirmed gap.
- The tests named in B-2, N-1 and N-7 are also missing.

### N-20: `scan_scope` uses its own timeout and treats every fatal git error as "not a repository"

`utils/scan_scope.py:51`.

- It uses a local 120s timeout constant and a direct subprocess call, instead of a Timeout constant and `run_git`.
- It reads exit 128 (git's general fatal exit) as "not a repository", so other failures are misread the same way.

## Nits

- **T-1.** `core/remote_branch_proof.py` (~:104): `RemoteProof.evidence` is computed but read only by tests.
- **T-2.** `core/branch_cleanup.py:908`: the dry-run says "proven merged into {default}" whatever the evidence tier (content-preserved, patch-equivalent, park-carried).
- **T-3.** `handlers/pre_tool_use/branch_creation_guard.py:76` and the R-BRANCH-WIP-CAP row say the deny happens at the cap. It now happens only at cap + `creation_grace`; at the cap itself it only warns.
- **T-4.** `handlers/worktree_create/worktree_create_handler.py:467-490`: the docstring says `_remove_unregistered_directory` removes only a directory git no longer owns, but the code never checks registration. `rmtree` also runs outside the event budget.
- **T-5.** `core/branch_sweep.py`: the `render_report` docstring says the ownership hint is on for anything but "off", but the CLI turns it on only for "own". The hint condition also leaves out park_carried.
- **T-6.** SessionStart may print the cap twice: in the "Open work" note and in the BRANCH POOLS section, which also runs on resume. Not probed.
- **T-7.** `utils/git_branch_creation.py`, `_interpreter_script`: `bash -s scripts/setup_worktree.sh x` is read as running the script, but with `-s` the name is only an argument. False positive; not probed.
- **T-8.** `config/models.py:3090`: `ownership_text` rejects `\n` and `**` but accepts `\r` (probed).
- **T-9.** `daemon/venv_lock.py:234`: `stat()` inside `max()` can raise FileNotFoundError if a record vanishes between the glob and the stat. Only ValueError is caught.
- **T-10.** `daemon/paths.py:1956`: the temp file is left behind when `write_text` fails.
- **T-11.** `utils/permission_surface.py:107-108`: the docstring says an unreadable config restores nothing, but `merge_settings` still adds the PermissionRequest hook back.
- **T-12.** `daemon/cli.py:13500/13533`: help text hard-codes `50` and exit code `4` instead of `BULK_BATCH_SIZE` / `EXIT_CREATION_REFUSED`. Also, `metadata.record_tracking` silently drops `--tracked-sha` / `--last-release-tag` when no `--tracked-ref` is given.
- **T-13.** `utils/long_running_command.py:255-256`: `_skip_prefix` returns no words when a segment begins with a redirect word, so a leading redirect hides the command. `>out.txt pytest tests/` gets no finding. From reading only; the handler ships off.

## Speculative, not counted

- `remote_branch_proof._live_tip_problems` puts `ls-remote` stderr into the problem text verbatim. A credentialed remote URL could appear there, depending on how git redacts it.
- The `_proven_refnames` cache key can miss when local and remote main differ. If so, it errs toward the safe side.

## Checked and found clean

- **Destructive-git:** the blanking of print-only substitutions (`| sh`, `$m`, `tee x` and `cat -` are still judged).
- **Permission surface.**
- **ssh_agent and load_scaling.**
- **The protected-index glob matcher.**
- **pipe_blocker:** the heredoc change.
- **Forwarder:** the root derivation and the location-file trust check.
- **PEER_PID:** it comes from socket credentials.
- **Branch housekeeping:** `constants/branch_guard`, `ownership`, `branch_keep` and `branch_practice`.
- **Priorities:** the new guard is at 40, which is in range.
- **Leftovers:** no debug code or leftover TODOs were found.

## Coverage limits

- The coordinator read `constants/rule_ids.py` (five new R-LONG-RUNNING-\* ids, clean) and lines 130-280 of `utils/long_running_command.py` (T-13).
- `core/branch_sweep.py` and `utils/git_branch_creation.py` were reviewed from the diff only, not probed.
- **Remote branch deletion.** Area A read `core/remote_branch_proof.py` and the `--remote` paths in `core/branch_cleanup.py` in full: the remote delete runs only on a `prove_remote_merged` proof. Findings N-3 and N-4 concern these paths; no fail-open deletion was found there.
- **Use of the content tier.** The coordinator confirmed that only `delete-branch` (`daemon/cli.py:6969`) uses it. The `branch_cleanup.py` callers (:678, :753, :1037) and `worktree_reaping.py:769` all pass `content_tier=False`, so B-1 is confined to `delete-branch`.
- **Repository untouched.** After the review, the working tree was clean, HEAD was still 70c48bf55, and no `hooksDaemonParked*` config key was set in this repository. All probes ran in scratch repos.
