# Plan 00463 third review (Opus 5.5 code-reviewer)

**Scope:** the four non-merge commits on `worktree-plan-463-full-qa-gate` since the delta review:

- `228ad081`: the fixes for delta findings N1 to N10;
- `480740cc`: the batched integration gate, the gate-lock pin, and the `setup_worktree.sh` targeted-QA
  guidance (ledger 00466 N2);
- `3aedba42`: marks 00466 N2 as remedied;
- `91456ee4`: `llm_qa.py main-moved`.

Line numbers are as of `91456ee4`. The worktree was clean when the review ran.

**Verification run by this reviewer (the full suite was not run):**

- **Targeted pytest: 439 passed.** Files:
  - `tests/unit/qa/`: `test_llm_qa_main_moved.py`, `test_llm_qa_provenance.py`,
    `test_llm_qa_changed.py`, `test_llm_qa_run_lock.py`, `test_run_changed_tests.py`;
  - `tests/unit/scripts/test_setup_worktree_qa_guidance.py`;
  - `tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py`;
  - `.claude/project-handlers/pre_tool_use/test_orchestrator_simulate.py`.
- **Probes** (all under `/workspace/untracked/scratch/`):
  - `probe_review3_blocker.py`: 105 commands against the live `full_qa_patterns`.
  - `probe_review3_n3_n5.py`: the delta review's N5 rows, plus the tests a changed conftest selects.
  - `probe_review3_main_moved.py`: the docs-only path set, plus verdicts on a scratch repository.
  - `probe_review3_md_refs.py`: which tests `changed_tests` maps to each "docs-only" markdown file.
  - `probe_review3_setup_worktree.py`: injects regressions into a copy of `setup_worktree.sh` and
    runs the test's own checks on it.

**Counts:**

- Delta findings: 8 VERIFIED, 2 PARTIAL, 0 NOT FIXED.
- New findings: 1 blocker, 2 major, 6 minor, 4 nit.

---

## Delta findings N1 to N10

| #   | Delta finding                                                | Verdict  | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| --- | ------------------------------------------------------------ | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N1  | Provenance certifies a result the run did not produce        | VERIFIED | A live run unlinks each tool's report before running the tool (`llm_qa.py` `_run_tools`). Each record carries the exit code, the verdict and the report's sha256 (`run_record`, :376). In `--read-only`, `stale_reason` still runs first (HEAD plus tree digest), so a record from an older tree FAILS. `output_reason` then fails three cases: a record with no exit code (the old format), a run that wrote no report, and a report whose hash differs. The recorded exit code is applied again (:1524), and `_summarize_recorded` fails any non-zero exit. Given the same JSON bytes and the same exit code, the read-only verdict equals the live one, so `--read-only` cannot PASS a tool whose live run failed, crashed or had its report replaced. Tests: `test_a_tool_that_crashes_without_output_does_not_certify_the_old_report`, `test_a_green_report_from_a_failing_exit_does_not_pass_read_only`, `test_a_report_replaced_after_the_run_is_not_certified`. An interrupted run is also safe: every tool it re-ran has a new or missing report, which mismatches the old hash. Residual (minor): the hash is taken at the end of the run, not when each tool finishes, and the recorded `passed` is never read (R8). |
| N2  | A tree that changes during the run is recorded silently      | VERIFIED | `_record_run` (:1471) prints `NOT RECORDED FOR THIS TREE` both when `after != before` and when the tree cannot be read. Test: `test_a_tree_that_changes_during_the_run_is_said_at_the_time`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| N3  | "0 unmapped" overstates coverage                             | PARTIAL  | A file's tests are now the union of its declared rule, its mirror, the tests that reference it and one hop of dependents. The probe confirms it: `CLAUDE/HANDLER_DEVELOPMENT.md` maps to `test_priority_bands_match_the_code.py` and 4 other files, and `CLAUDE/Plan/README.md` maps to `test_plan_index_navigability.py` and 5 others. The root conftest and root `CLAUDE.md` read `too-broad`, each with a recorded reason. QA.md:151 says that a `tools:` rule certifies lint only. **Residual:** a nested conftest selects its whole subtree as ONE entry, which gets past the 40-file cap (R6).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| N4  | Path-like rule: false deny, fail-open, doc overclaim         | PARTIAL  | Now allowed: `cd tests/unit && pytest handlers`. Now denied: `pytest --json-report-file out/r.json` with no path (the unknown plugin flag is read as taking a value). HANDLER_REFERENCE:1428-1434 is corrected. **Residual:** `cd` moves only the existence lookup. `full_args` are still compared literally, so `cd tests && pytest unit` runs the whole unit suite and is ALLOWED (R7).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| N5  | Runner and redirect table gaps                               | VERIFIED | Every row the delta review listed now DENIES in the probe: `uv run --color never`, `--exclude-newer`, `--resolution`, `poetry run --directory`, `pdm run -p`, `uvx pytest@8`, `hatch run test:pytest`, `all&>out.txt`, `~/proj/tests` and `$HOME/proj/tests`. `env -S` is gone from the limits list, and `env -S 'pytest'` DENIES. Other gaps not listed as limits: R7.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| N6  | `tool_command` dead; the forwarding test pins the wrong path | VERIFIED | `rg tool_command scripts tests` returns nothing. `test_run_tool_puts_the_forwarded_options_on_the_command_it_runs` drives `run_tool` itself. `test_forwarded_options_reach_changed_tests_and_nothing_else` drives `_run_tools` with a stubbed `run_tool`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| N7  | QA.md misstates bare-pytest behaviour                        | VERIFIED | QA.md:177-182 now calls it policy, and states pytest's real behaviour: `testpaths` applies only from the rootdir.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| N8  | Bugs.md FAIL-FAST says "Run FULL QA" with no role split      | VERIFIED | Bugs.md:319-321 now names each role's run.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| N9  | The orchestrator record states the policy in prose           | VERIFIED | `_recorded_verdict` and `_unblocked_bash_sentence` both derive from `_BLOCKED_TOOLS`. `test_never_denied_is_said_only_of_a_tool_outside_the_blocked_set` monkeypatches Bash into the set and checks both.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| N10 | `worktree_state` reads untracked files whole                 | VERIFIED | It now streams through `hashlib.file_digest`. That needs Python 3.11, and `requires-python` is `>=3.11`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |

---

## New findings

### R1. BLOCKER: the docs-only path set passes files that tests and runtime code read

**Where:**

- `scripts/qa/llm_qa.py:1296-1319`: `_PLAN_FOLDER_FILE` and `is_docs_only_path`. Any `.md`
  outside `src/`, `tests/` and `scripts/` counts as docs-only, as does any file in a plan folder.
- `CLAUDE/QA.md:104-117`.

**Failure scenario.** Every path below reads `docs-only=True` (`probe_review3_main_moved.py`). The
repository's own `changed_tests` mapper names the tests that read each one
(`probe_review3_md_refs.py`):

| Path                               | Read by                                                                                                                       |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `CLAUDE/Plan/README.md`            | `tests/integration/test_plan_index_navigability.py` (byte ceiling and row window), `test_repo_hygiene_check.py`, 4 more tests |
| `CLAUDE/HANDLER_DEVELOPMENT.md`    | `test_priority_bands_match_the_code.py`, `test_claude_md_guidance_coverage.py`, 3 more tests                                  |
| `CLAUDE/CodeLifecycle/General.md`  | `test_ssot_quote_real_content.py`                                                                                             |
| `CLAUDE/core/PlanWorkflow.core.md` | `test_plan_journalling_doc_parity.py`, `test_core_doc_deployment.py`, 2 more tests                                            |
| `BUG_REPORTING.md`, `README.md`    | `test_scratch_path_guidance_is_consistent.py`, `test_upgrade_runs_the_target_versions_steps.py`, …                            |
| root `CLAUDE.md`                   | enough tests that `changed_tests` classes it `too-broad`                                                                      |
| `CHANGELOG.md`                     | parsed at runtime by `install/breaking_changes_detector.py` during upgrades                                                   |

Two more kinds of file get through:

- **Agent configuration that changes runtime behaviour.** `.claude/agents/*.md` (the frontmatter
  `tools:` sets what a sub-agent may do), `.claude/skills/**/SKILL.md` and `.claude/rules/*.md` are
  all docs-only.
- **Executable files in a plan folder.** `CLAUDE/Plan/NNNNN-x/conftest.py` and `run_me.sh` are
  docs-only too.

**How it lands.** A ledger or archival commit on `main` during a batch can overflow the
`CLAUDE/Plan/README.md` row window or byte ceiling. `main-moved` says `docs-only`, and the recheck
runs `plan_qa docs_qa format british_english sensitive_content`. None of those run
`test_plan_index_navigability.py`. `main` is fast-forwarded to a head whose suite fails, and the only
thing that catches it is CI after the push.

**The text contradicts itself.** QA.md:113-117 says CI is "not a substitute" for the gate. It also
admits "A `docs-only` verdict skips a re-run of tests that a markdown change can still reach". For
exactly those tests, CI is then the substitute. This breaks the stated requirement that a change
that can alter test or runtime behaviour never passes as docs-only.

**Fix direction:**

- **Close the test hole mechanically.** In the docs-only recheck, also run `changed_tests` over
  exactly what the merge of `main` brought in: `llm_qa.py changed_tests --base <integration head before the merge>`.
  Its reference search already finds these readers. A `too-broad` or unmapped result then turns the
  verdict into `full-gate`.
- **Narrow the path set.** Treat `.claude/**`, root `CLAUDE.md`, `CHANGELOG.md`, `CLAUDE/core/**`
  and `CLAUDE/UPGRADES/**` as code.
- **Limit plan folders to documents.** Only `.md` files (or an explicit document-suffix list) in a
  plan folder count as docs-only.
- **Pin the boundary in tests.** Add these paths to `_FULL_GATE_PATHS`. Better, add a test asserting
  that no path `changed_tests` maps to a test is ever docs-only.

### R2. MAJOR: the batch base never advances, so the procedure after a re-run either loops or has no exit

**Where:**

- `llm_qa.py:1331-1366`: `main_moved`, which takes a caller-supplied `base`.
- `CLAUDE/QA.md:98-102`, `CLAUDE/development/IssueSdlc.md:349-358`, `CLAUDE/AgentTeam.md:1204`,
  `:1268`, `:1723` and `:1751`.

**Failure scenario** (reproduced in `probe_review3_main_moved.py`, "full-gate loop"):

1. Code lands on `main` during a batch, and `main-moved BASE` says `full-gate`.
2. Following the table, the coordinator merges `main` into the integration branch and runs `all`
   again, green.
3. From here the docs split two ways, and both fail:
   - **Re-check with the recorded base.** The answer is still `full-gate`, although `main` is now
     contained in the integration head and a fast-forward is possible. The table offers no way out,
     so the coordinator runs the full gate again, and again. That is exactly the waste the command
     exists to stop.
   - **Skip the re-check** (the IssueSdlc text: "run Step 5's full suite again before
     fast-forwarding"). A second `main` move during that 20-minute run makes `git merge --ff-only`
     refuse. The "If --ff-only refuses…" instruction was removed in `91456ee4`, so nothing says what
     to do next.

The `docs-only` path has the same no-exit problem.

**The base cannot be carried between steps as written.** It lives in a shell variable,
`BATCH_BASE=$(git rev-parse main)` (AgentTeam.md:1204), and is used several steps later (:1268).
In Claude Code, shell state does not persist between Bash calls, so `"$BATCH_BASE"` expands to `""`.
`git merge-base --is-ancestor "" main` then exits 128 (checked), and the command exits 1. The failure
is safe, but the documented procedure cannot run as written.

**Fix direction:** stop taking the base from the caller.

- Make the command `main-moved <integration-ref> [main-ref]`, with the base computed as
  `git merge-base <integration-ref> <main-ref>`. It then advances by itself when `main` is merged in.
- Define `unmoved` as "`main-ref` is an ancestor of `integration-ref`", which is also exactly when
  `--ff-only` will succeed.
- Document it as a loop: repeat `main-moved` until it says `unmoved`, then fast-forward.

### R3. MAJOR: the `setup_worktree.sh` test cannot catch the regression it was written for

**Where:** `tests/unit/scripts/test_setup_worktree_qa_guidance.py:33` and `:46-53`
(`_COMMAND_STARTS`), and `:62`. The script line it fails to check is `scripts/setup_worktree.sh:400`.

**Failure scenario.** The test only checks echoed lines whose text STARTS with `cd `, `./`,
`bash `, `python`, `pytest` or `uv `. The agent-template lines are prose: "Before committing,
run…". The original 00466 N2 line had the same shape: "Run ./scripts/qa/run_all.sh before
committing." `probe_review3_setup_worktree.py` injected one line at a time into a copy of the script
and ran the test's own checks:

| Injected line                                                 | Result                                      |
| ------------------------------------------------------------- | ------------------------------------------- |
| `echo "  Run ./scripts/qa/llm_qa.py all before committing."`  | MISSED                                      |
| `echo "  Before committing, run ./scripts/qa/llm_qa.py all."` | MISSED                                      |
| `echo "  Before committing, run ./scripts/qa/run_tests.sh."`  | MISSED                                      |
| `echo '  cd x && ./scripts/qa/llm_qa.py all'`                 | MISSED: single quotes don't match `_ECHOED` |
| `echo "  QA: pytest tests/"`                                  | MISSED                                      |
| `printf "  ./scripts/qa/llm_qa.py all\n"`                     | MISSED                                      |
| `echo "  bash scripts/qa/run_tests.sh"`                       | CAUGHT                                      |

Only the literal `run_all.sh` string check guards the original shape, so the denied runner comes back
unnoticed under any other spelling. The ledger entry (`3aedba42`, 00466 NIGGLES.md N2) claims "no
command the script prints is a full run". The probe shows that is not true.

**Fix direction:**

- Scan every command-shaped span in every printed line, whatever `echo` or `printf` quoting it uses.
  One way: take each backticked or `./`-anchored substring, or run `find_full_qa_invocation` on every
  suffix that starts at a token matching a declared pattern's `command`.
- Alternatively, run the script's final `echo` block with a stub `WORKTREE_DIR` and test the output.
- Add the table above as RED cases.

### R4. MINOR: `unmoved` is decided by an empty diff, not by commit identity

**Where:** `llm_qa.py:1350-1362`.

**Failure scenario** (reproduced): `main` gains a commit and its revert, or an `--allow-empty`
commit. The diff is empty, so the verdict is `unmoved`: "main has not moved since …". Yet
`main != base`, so the prescribed `git merge --ff-only` refuses, and no document says what to do.

**Fix direction:** R2's ancestry definition also fixes this. Otherwise, return `unmoved` only when
`rev-parse main == base`, and treat an empty diff with new commits as `docs-only` ("merge main in").

### R5. MINOR: AgentTeam.md is internally inconsistent about the batch

**Where:** `CLAUDE/AgentTeam.md`.

- **:249-257** (Team Lead Decision, the child→parent flow). It says to merge the children "into one
  integration worktree from the parent" and "fast-forward the parent". But :1156 says "the parent IS
  the integration worktree". It then runs `main-moved <batch-base>` with the default `MAIN_REF=main`,
  although the ref that must not move here is the PARENT branch, so the check compares the wrong
  ref.
- **:1186 and :1208.** The generic flow still runs `llm_qa.py all` twice per plan: "Once, after the
  last ready child is merged", then again in Parent→Main STEP 1 after `git merge main`, which says
  "this ONE run is the gate". The worked example at :1719-1726 correctly runs it once, after the
  sync. This is a leftover second full run.
- **:1239 and :1737.** "If REJECTED: fix issues in worktree" contradicts QA.md:87 ("A branch is never
  fixed inside the integration worktree"), and says nothing about re-running the gate after the fix.
- **:1268-1270.** The STEP 5 script runs `main-moved` and then `git merge --ff-only` whatever the
  verdict. It is safe only because `--ff-only` refuses.

**Fix direction:**

- Pick one model: the parent is the integration branch.
- Delete the :1186 run.
- Pass the parent as `MAIN_REF` in the child→parent decision.
- Route rejects back to a child branch.
- Show the verdict branching explicitly: `case $? in 0) …; 4) …; *) stop;; esac`, after R2.

### R6. MINOR: a nested conftest gets past the 40-file cap and runs a whole suite inside a sub-agent

**Where:** `scripts/qa/run_changed_tests.py:624-628` (`own_tests` returns `{subtree}`), and
`:669`/`:710`, which count each selected ENTRY, so a directory counts as 1. `dependent_tests` (:638)
routes any module a nested conftest imports into the same subtree.

**Failure scenario** (`probe_review3_n3_n5.py`):

| Changed file                     | Selected (one entry) | Test files | Unmapped |
| -------------------------------- | -------------------- | ---------- | -------- |
| `tests/integration/conftest.py`  | `tests/integration`  | 180        | none     |
| `tests/unit/plan_qa/conftest.py` | `tests/unit/plan_qa` | 51         | none     |

A sub-agent's `llm_qa.py changed` therefore runs the whole integration suite concurrently with other
agents, which is the load the plan exists to remove. It also reports the file as mapped, not
`too-broad`.

**Fix direction:** count the test files under a selected directory against `MAX_IMPORT_SELECTION`,
and mark `too-broad` past the cap. Add a test with a fixture conftest over more than 40 files.

### R7. MINOR: whole-suite spellings that are allowed and not listed as limits

**Where:** `subagent_full_qa_blocker.py:897` (`_operand_is_full` compares literally) and `:983`
(`_changed_directory` moves only the existence lookup). The limits list is at
`docs/guides/HANDLER_REFERENCE.md:1442-1447`.

**Failure scenario.** Each of these ALLOWED commands runs the whole suite
(`probe_review3_blocker.py`):

- `py.test`, `python -m py.test`. `py.test` is installed in this venv.
- `coverage run -m pytest`, `python -m coverage run -m pytest`. `coverage` is installed, and this is
  the ordinary coverage invocation.
- Unnormalised paths: `pytest tests/unit/../unit`, `tests//unit`, `tests/./unit`,
  `tests/unit/qa/..`.
- `cd tests && pytest unit` and `cd tests/unit && pytest ../unit`.
- `$(which pytest)` and `"$(command -v pytest)" tests`: a substitution in command position, unquoted.

Exotic wrappers are also allowed, but are nits: `ionice`, `taskset`, `xvfb-run`, `script -c`,
`pipx run`, `hatch test`, `tox`, `nox`, and `llm_qa.py $'all'`.

No false denies were found among the 30 targeted forms probed (`-rA`, `-xvs`, `-pno:x`,
`-o addopts=`, `-k 'a or b'`, `cd tests/unit/qa && pytest file.py`, …), apart from the documented
case of an unknown plugin flag placed before the path.

**Fix direction:**

- Resolve each path-like operand against `here` and `normpath` it. Deny when it equals, or is an
  ancestor of, a `full_args` entry resolved against the event's cwd.
- Add `py.test` to the pytest pattern, and teach the resolver `coverage run [-m] X`.
- List a command-position substitution, and the exotic wrappers, as limits.

### R8. MINOR: the report hash is taken at the end of the run, and the recorded verdict is never read

**Where:**

- `llm_qa.py:1471-1495` (`_record_run`). `output_digest` runs after EVERY tool has finished.
- `:270` and `:383`. `passed` is recorded but never read by `--read-only` (`:1519-1526`).

**Failure scenario:**

1. Tool A writes a failing report but exits 0.
2. A later tool in the same run rewrites A's report as passing. For example, a unit test run by
   `tests` writes into the real `untracked/qa/`.
3. The recorded hash is the rewritten file's, and `passed=False` is ignored, so `--read-only` passes
   A.

This is unlikely, which is why it is minor, but it is the same shape as N1.

**Fix direction:** hash each report immediately after its `run_tool` returns, and make
`--read-only` fail when the recorded `passed` is false.

### R9. MINOR: the red-batch and after-merge procedures have undo gaps

**Where:** `CLAUDE/QA.md:76-87`; `CLAUDE/AgentTeam.md:1275-1282` (STEP 6, where the QA-in-main and
`git reset --hard` steps were removed).

**Failure scenarios:**

- **(a) "Each branch stays one revertable merge commit" invites `git revert -m 1`.** Use it to drop a
  branch from the integration branch, and later fast-forward `main` over it. When the fixed branch is
  merged again, git treats its original commits as already merged, so the reverted change silently
  never lands.
- **(b) "Rebuilding the integration head without one branch" has no documented mechanics.** Here
  `git reset --hard` and `git branch -D` are both denied, and `git branch -d` refuses the unmerged
  red integration branch. The agent can neither reset the branch nor discard it.
- **(c) Nothing says what to do if the daemon fails in `main` after the fast-forward.** STEP 6 runs
  `hooks-daemon restart` and `status` after `--ff-only`, with no instruction if they fail.
  - The gate ran under the integration worktree's venv. The main checkout's venv may lack a
    dependency the batch added.
  - The old recovery was full QA in `main`, then `reset --hard`, and it is gone.
  - Nothing says "do not push", or how to back the batch out.

**Fix direction:**

- Say that a red batch is rebuilt on a NEW integration branch from `main`, and that the old one is
  left for a human to delete. Never drop a branch by reverting its merge.
- Replace "revertable" with the re-merge caveat.
- Add a STEP 6 failure line. First, do not push. Then either `git revert -m 1` each batch merge
  (naming the re-merge caveat), or fix forward through a new batch.

### R10. NIT: the docs-only recheck tool list

**Where:** `llm_qa.py:1283-1289`, `CLAUDE/QA.md:101`, `CLAUDE/development/IssueSdlc.md:355`, and
`tests/unit/qa/test_llm_qa_main_moved.py:108`.

- `format` is black. It checks Python only and AUTO-FIXES files, so it adds nothing to a markdown
  recheck, and it can change the tree inside a gate.
- Running the five tools records provenance for those five only. Every other tool reads STALE for a
  later `--read-only all`, so release Step 1b needs a full run anyway after a `docs-only` landing.
  This is worth saying in QA.md.
- The list is written out verbatim in three places. The test pins the literal list, which restates
  the constant rather than testing behaviour. The docs could say "run what the verdict prints", with
  the test asserting only `⊆ TOOL_REGISTRY`.

### R11. NIT: `main-moved` is only recognised as the first argument, and two verdicts share exit 0

**Where:** `llm_qa.py:1411`.

- `llm_qa.py --read-only main-moved X` prints "Unknown tool: main-moved" and "Unknown tool: \<sha>"
  (probed).
- `docs-only` and `unmoved` both exit 0. A script gated on `&&` cannot tell "fast-forward now" from
  "merge `main` in first".

A distinct code for `docs-only` would make the verdict machine-branchable.

### R12. NIT: symlinks and non-document files classify as docs-only

**Where:** `llm_qa.py:1315-1319`.

- `docs/app.md`, a symlink to `../src/app.py`, reads `docs-only` (probed).
- Any file in a plan folder, of any type, is docs-only.

**Fix direction:** use `git diff --raw` and treat mode `120000` as code. This overlaps R1's plan-folder
suffix fix.

### R13. NIT: small leftovers

- `CLAUDE/Plan/00463-…/PLAN.md:43` is one 154-character line inside wrapped prose.
- `orchestrator_simulate._recorded_verdict` prints "None is never denied by this mode" for a payload
  with no `tool_name`.

---

## Other checks (no finding)

- **The `--ff-only` flow.** The `unmoved` case is correct. `--ff-only` really does land exactly the
  head the gate passed. See R2 and R4 for the paths around it.
- **Leftover per-branch full-QA instructions.** None were found in QA.md, Worktree.md, IssueSdlc.md,
  PLAN.md, the agents or the skills. `rg` for "one worktree at a time", "delivered head" and "in the
  child worktree" finds only unrelated hits. The one leftover is AgentTeam.md:1186 (R5).
- **Exit-code handling in `main_moved`.** It is right:
  - `--is-ancestor` exit 1 gives `full-gate`, with a reason;
  - any other exit raises `MainMovedError`, so the command exits 1 and prints no verdict;
  - a failed diff also raises;
  - `-z` and `surrogateescape` handle odd names;
  - `--no-renames` makes a rename count by its old path, which is tested.
- **Gate-lock pin** (`test_llm_qa_run_lock.py:167-203`). It is behavioural, with a leaking control.
- **Wiring into the docs.** `main-moved` is named consistently in QA.md, Worktree.md, IssueSdlc.md,
  AgentTeam.md, PLAN.md, the release note and the `--help` text. See R1 and R2 for where that
  content is wrong.

## Verdict

**CHANGES REQUIRED before merge:**

- **R1:** the docs-only set breaks the plan's own invariant.
- **R2:** as written, the batched procedure never terminates, or cannot be executed.
- **R3:** the test that closes ledger 00466 N2 does not guard the shape it names.

R4 to R13 can be filed as follow-ups. The N1 to N10 work is sound. The two PARTIALs are residuals
now tracked as R6 and R7.
