# Plan 00463 review (Opus 5.5 code-reviewer)

**Scope:** `git -C untracked/worktrees/worktree-plan-463-full-qa-gate diff main...a1fff052`
(44 files, +2896/-254). Line numbers are as of `a1fff052` unless a file on `main` is named.
No full suite was run. Targeted pytest runs passed: the handler, `run_changed_tests`, `llm_qa changed`,
shell_segmentation, cli enforcement status, process_probe, pipe_blocker wrappers, blocking-handler
evasion, orchestrator_simulate and handler-scope defaults (727 tests).

**Probes (kept as evidence):** `/workspace/untracked/scratch/plan463-review/`
- `probe_matching.py` and `probe_matching_2.py` load the worktree's real `.claude/hooks-daemon.yaml`
  patterns and print DENY/allow for each command in the table below.
- `probe_mapping.py` prints what `run_changed_tests` maps a file to.
- `probe_changed_verdicts.py` drives `run_changed_tests.main` through its own injection points
  with change sets that test nothing.

Run each with `PYTHONPATH=<worktree>/src <worktree>/untracked/venv-*/bin/python <probe> <worktree> [...]`.

**Counts:** 0 blocker, 3 major, 12 minor.

**Branch moved during review.** `644a5939` has been committed after `a1fff052`. It adds coverage
wording and a `handler_scope` docstring. The worktree also has uncommitted edits to
`orchestrator_simulate.py`, to its test, and an untracked
`tests/integration/test_full_qa_gate_is_never_deadlocked.py`. None of that delta is reviewed here.
See finding 15.

---

## Evasion and false-positive table (the repository's own config)

| Command | Verdict | Right? |
|---|---|---|
| `python3 scripts/qa/llm_qa.py all` | DENY | yes |
| `./scripts/qa/llm_qa.py  all` (extra spaces) | DENY | yes |
| `bash -c './scripts/qa/llm_qa.py all'`, `sh -c "cd x; pytest"`, `bash -lc 'pytest'` | DENY | yes |
| `env X=1 ./scripts/qa/llm_qa.py all` | DENY | yes |
| `cd x && ./scripts/qa/llm_qa.py all`, `(cd x && pytest)` | DENY | yes |
| `nohup ./scripts/qa/llm_qa.py all > out.log 2>&1 &` | DENY | yes |
| `timeout 900 ...`, `timeout -k 5 900 ...` | DENY | yes |
| `uv run pytest`, `uv run python -m pytest` | DENY | yes |
| `uv run --frozen pytest`, `uv run -- pytest`, `uv --directory x run pytest`, `poetry run -- pytest` | allow | **no** (finding 4) |
| `python -m pytest`, `python3.11 -m pytest`, `python3 -mpytest` | DENY | yes |
| `pytest tests/`, `pytest .`, `pytest ./tests`, `pytest /abs/tests` | DENY | yes |
| `pytest -x`, `pytest -x -q --tb=short`, `pytest -n 8`, `pytest --cov=src` | DENY | yes |
| `pytest --timeout 60`, `pytest --cov src`, `pytest --numprocesses 8`, `pytest --log-level DEBUG`, `pytest --override-ini addopts=` | allow | **no** (finding 2) |
| `/workspace/scripts/qa/run_all.sh`, `bash scripts/qa/run_all.sh` | DENY | yes |
| `./scripts/qa/llm_qa.py tests`, `llm_qa.py lint tests` | DENY | yes |
| `./scripts/qa/llm_qa.py all>out.txt` (redirect attached) | allow | **no** (finding 5) |
| `pytest $PWD/tests` | allow | **no** (finding 5) |
| `env -C x pytest`, `xargs pytest`, `uvx pytest`, `coproc pytest` | allow | no, minor (finding 5) |
| `echo "$(pytest)"`, bash -c nested 4 deep | allow | documented limit, acceptable |
| `pytest tests/unit/*`, five `tests/unit/<dir>` operands | allow | policy choice ("narrower than tests/unit"), acceptable |
| `llm_qa.py --read-only all`, `llm_qa.py all --read-only`, `llm_qa.py changed`, `llm_qa.py lint type_check` | allow | yes |
| `pytest tests/unit/handlers/x.py`, `pytest --collect-only`, `run_shell_check.sh` | allow | yes |
| `git commit -m "... llm_qa.py all ..."` (single or double quotes, heredoc `-F -`, `"$(cat <<'EOF' ...)"`) | allow | yes |
| `grep 'llm_qa.py all' f`, `grep llm_qa.py all`, `echo ./scripts/qa/llm_qa.py all`, `gh pr create --body "..."` | allow | yes |
| `cat <<'EOF'` body naming `llm_qa.py all` | allow | yes |
| `bash <<'EOF'` body running `pytest` | DENY | yes |
| `pytest --cov . tests/unit/handlers/x.py`, `pytest --confcutdir . tests/unit/x.py` | DENY | **no**, a false deny (finding 2) |
| `cd tests/unit/handlers && pytest` | DENY | **no**, a false deny (finding 6) |

Verdict on matching: the parse-based design is sound. Mentions, commit messages, greps, echoes and
`--read-only` are all clean, and every spelling the brief named is caught. The weak point is the
operand model (finding 2), which fails in both directions.

## Scope and the orchestrator-only claim

- `scope=SUB` works as intended. `scope_admits` refuses synthetic events before MAIN/SUB are checked,
  so the main thread and the acceptance harness are never denied (`core/handler_scope.py:102-115`).
  The handler never reads `agent_id` itself.
- **The "no deadlock" claim holds against the real handler.** In blocking mode,
  `orchestrator_simulate.py` denies only `_BLOCKED_TOOLS = {Write, Edit, NotebookEdit}` (`:183`,
  `:320`). Bash is never denied. The new test in `TestBashIsNeverDenied` runs with `blocking=True`
  (`test_orchestrator_simulate.py:449`), so it pins the real policy.
- The "SIMULATED ... main thread would have been denied — Bash" line seen in this session comes from
  `orchestrator_simulate.py:352-354` on `main`. That handler flags every non-coordination tool in
  simulate mode, including Bash, so it is a misleading message and not evidence of a deadlock. The
  implementer's uncommitted worktree edits change exactly that message (finding 15).
- The Workflow-tool agent is unmeasured. If it carries no `agent_id`, the guard fails OPEN for it: it
  does not deny, and it does not deadlock. `644a5939` documents this honestly.
- A deadlock is still reachable through config: see finding 7.

## Shipped default versus this repository

Consistent everywhere I checked. `get_default_enabled() -> False`, no default patterns, and the
`init_config` template line reads `enabled: false`. `.claude/hooks-daemon.yaml.example` has it
disabled with commented options. HANDLER_REFERENCE says "Disabled, and inert until patterns are
declared". The release note says "opt-in ... Nothing ships by default". The manifest says
`recommended: false, dormant: true`. This repository enables it with five patterns
(`.claude/hooks-daemon.yaml:458-485`), and QA.md lists exactly those.
`hooks-daemon check` reports an enabled handler with no patterns, and the cli tests pin that.
The release note's sentence "When nothing maps to a test, it says that it ran no tests" is true,
but it omits that the run then PASSES (finding 1).

---

## Findings

### 1. MAJOR: `llm_qa.py changed` passes when it tested nothing, and some of those cases are silent

**Where:**
- `scripts/qa/run_changed_tests.py:162-163`: deleted and non-Python files are dropped without being
  listed anywhere.
- `run_changed_tests.py:170-184`: an unmapped source file is listed but does not affect the verdict.
- `run_changed_tests.py:212-213`: an empty selection gives `passed_all = True`.
- `run_changed_tests.py:293`: the exit code is 0.
- `run_changed_tests.py:302-306`: stdout prints "0 passed, 0 failed from 0 test files", the very
  reading the module docstring says it prevents.
- `scripts/qa/llm_qa.py:595-610`: shows a green check with "no tests ran".
- Tests pin the behaviour as intended: `tests/unit/qa/test_run_changed_tests.py`
  `test_nothing_selected_passes_but_says_nothing_ran` and
  `test_non_python_and_deleted_files_are_not_candidates`.

**Failure scenarios** (reproduced by `probe_changed_verdicts.py`, all `exit=0`, pytest never invoked):
- **A module is deleted but `tests/unit/test_foo.py` still imports it.** That test is broken, yet it
  is never selected. The file is not reported as unmapped either.
- **The only change is a source module with no test.** The result is PASS, with "(1 unmapped)" in a
  count that agents do not read (the implementer's own handover quotes "passed 8/8").
- **Only `.claude/hooks-daemon.yaml` changed.** This very plan's dogfood switch is such a change. The
  result is PASS, with no mention at all.
- **Only a `scripts/qa/*.sh` changed.** Also PASS, with no mention.
- **A sub-agent commits directly on `main`.** `merge-base HEAD main` is HEAD, so every committed
  change vanishes from the set, and the run passes on only the uncommitted residue.

Each of these hands the coordinator a green "targeted QA" that verified nothing. The brief's
requirement "must not silently pass" is not met for deleted and non-Python files. For unmapped
files it is met only in letter.

**Fix:**
- (a) Report deleted `.py` files and non-Python files under `unmapped` too, as separate
  `deleted`/`non_python` lists.
- (b) For a deleted module, select the `test_<stem>*.py` files that still exist, because they are
  exactly the tests that will now break.
- (c) Make `passed_all` false when `unmapped` is non-empty, or when a candidate change set yields an
  empty selection. Allow an explicit opt-out (`--allow-unmapped`) for a docs-only delivery.
- (d) Print "no tests ran" from `run_changed_tests.py` itself.
- (e) When HEAD equals the merge base and the branch is `main`, fail with "run from the worktree
  branch, or pass `--base`".
- Invert the two tests that pin the current behaviour.

### 2. MAJOR: the operand model misreads flag values, so it both misses full runs and denies targeted ones

**Where:** `src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py:420-448`
(`_is_full_run`). Any non-flag word counts as a targeting operand unless its flag is declared in
`value_flags`.

**Failure scenarios:**
- **Misses under this repository's config.** `pytest --timeout 60`, `pytest --cov src`,
  `pytest --numprocesses 8`, `pytest --log-level DEBUG` and `pytest --override-ini addopts=` are
  allowed. Each is the whole suite (probe rows above).
- **Misses under the shipped example config.** HANDLER_REFERENCE, the release manifest `example_yaml`
  and `.example` all declare `value_flags: [-k, -m, -n]`. With that, `pytest --tb short`,
  `pytest -p no:randomly` and `pytest --maxfail 1` also pass as "targeted" in every client that
  copies the example.
- **False denies.** `pytest --cov . tests/unit/handlers/x.py` and `pytest --confcutdir . <file>` are
  DENIED, because the flag's value `.` reads as the whole-suite operand.

The design fails OPEN for every value flag the project forgot to list. pytest and its plugins have
dozens, so the list can never be complete.

**Fix:** a word should count as a targeting operand only when it is path-like: it contains `/` or
`::`, ends in `.py`, or exists relative to the event's `cwd`. Every other non-flag word is ignored.
`value_flags` then only matters for disambiguating path-like values, such as `--ignore tests/x` and
`--rootdir .`. Also add `--cov` and `--confcutdir` to this repository's list, or rely on the
path-like rule. Add probe rows from the table above to `_FULL_RUNS` and `_NOT_FULL_RUNS`.

### 3. MAJOR: release-agent pre-validation now reads results of unknown age, and the doc misstates the ordering

**Where:** `.claude/agents/release-agent.md:48-55`. It says "Reads the recorded results of main
Claude's full run (RELEASING.md Step 8)". But the agent's pre-validation is Step 1
(`CLAUDE/development/RELEASING.md:236-262`), and Step 8 (`:488-490`) has not run yet.
`llm_qa.py --read-only` does no provenance check: nothing ties `untracked/qa/*.json` to a commit sha
or to a clean tree.

**Failure scenarios:**
- **Stale green passes.** Green JSON from an earlier commit, or from before uncommitted edits, passes
  the release pre-validation gate. Previously the gate actually ran the suite on HEAD.
- **Fresh checkout aborts.** A fresh checkout, or one whose last full run was elsewhere, gets "NO
  OUTPUT" and aborts, demanding a main-thread run that RELEASING.md does not schedule before Step 1.

Step 8 is still a real gate, so broken code is unlikely to ship. The damage is a pre-validation that
is now either theatre or a spurious abort, plus a document that is wrong about its own order.

**Fix:** choose one.
- (a) Remove the QA check from the agent's pre-validation and say plainly that Step 8 on the main
  thread is the QA gate.
- (b) Have `llm_qa.py` record `git rev-parse HEAD` and a dirty flag in each JSON, and have
  `--read-only` refuse, as a FAIL, results whose sha differs from HEAD. Then add "main Claude runs
  `llm_qa.py all`" to RELEASING.md before the agent is dispatched.

### 4. MINOR: project-runner resolution fails whenever a flag is involved

**Where:** `subagent_full_qa_blocker.py:331-335`. It requires `run` to be the first non-flag word,
and then resolves the words after it without skipping runner flags. `docs/guides/HANDLER_REFERENCE.md`
claims `uv run`/`poetry run` resolution.

**Failure scenario:**
- Allowed: `uv run --frozen pytest`, `uv run -- pytest`, `uv run -q pytest`,
  `uv --directory x run pytest`, `uv run --directory x pytest`, `poetry run -- pytest`.
- The first two are the most common uv spellings.

**Fix:**
- Find `run` after skipping each runner's global value flags (uv: `--directory`, `--project`,
  `--python`, `--config-file`...).
- After `run`, skip `--` and the runner's run flags, with a per-runner value-flag table (uv:
  `--with`, `--python`, `--package`, `--extra`, `--group`, `--env-file`).
- Pin these spellings in `_FULL_RUNS`.

### 5. MINOR: smaller evasions, not documented as limits

**Where:** `_is_full_run` (`:420-448`), `_normalise_operand` (`:399-406`), and
`utils/shell_segmentation.py` `COMMAND_WRAPPERS["env"]`.

**Failure scenarios:**
- `./scripts/qa/llm_qa.py all>out.txt` is allowed: shlex yields the single word `all>out.txt`.
- `pytest $PWD/tests` is allowed.
- `env -C x pytest` is allowed: `-C`/`--chdir` is not an env value flag, so `x` becomes the command.
- `xargs pytest` and `uvx pytest` are allowed.

**Fix:**
- In `_is_full_run`, split a trailing attached redirection off an operand (`^(.*?)(\d*>>?.*)$`).
- Normalise a leading `$PWD/` or `${PWD}/` like `./`.
- Add `-C` and `--chdir` to env's value flags. This is a shared table now, so also check
  process_probe's tests.
- Either resolve `xargs`/`uvx` or list them in the HANDLER_REFERENCE "Limit" paragraph.

### 6. MINOR: bare `pytest` from a test subdirectory is denied

**Where:** `bare_is_full: true` for `pytest-whole-suite` (`.claude/hooks-daemon.yaml:475-481`).

**Failure scenario:**
- `cd tests/unit/handlers && pytest` is DENIED.
- Outside the rootdir, pytest collects the cwd rather than `testpaths`, so this run is targeted.
- The agent loses a retry.

**Fix:** document in CLAUDE/QA.md that the targeted form must name its path explicitly. Optionally
treat a bare run as full only when the event `cwd` is the repository root.

### 7. MINOR: a config `scope:` override silently brings back the deadlock the plan rules out

**Where:** `handlers/registry.py:576` (`resolve_scope`) honours `scope:` from YAML. The handler
relies entirely on SUB (`subagent_full_qa_blocker.py:521`).

**Failure scenario:**
- A project writes `scope: ALL`, perhaps believing it tightens the guard.
- The coordinator's own `llm_qa.py all` is then denied.
- Nobody can run the full gate.

**Fix:**
- In `get_enforcement_status`, report any effective scope other than SUB as a misconfiguration.
- Alternatively, refuse a non-SUB scope at config validation for this handler.
- State it in HANDLER_REFERENCE.

### 8. MINOR: `enforce_llm_qa` still tells sub-agents to run `llm_qa.py all`

**Where:** `.claude/project-handlers/pre_tool_use/enforce_llm_qa.py`, whose deny recommends
`./scripts/qa/llm_qa.py all`. `constants/priority.py` says the new handler's priority 32 exists to
pre-empt this advice. That only works when the new handler matches.

**Failure scenario:**
- Reproduced live by this reviewer, a sub-agent.
- A Bash command that passed `scripts/qa/run_all.sh` as an ARGUMENT to a python probe was denied by
  `enforce_llm_qa`, with "Use ./scripts/qa/llm_qa.py all".
- Once this plan is merged, that advice leads the sub-agent straight into R-SUBAGENT-FULL-QA.

**Fix:**
- Make the message role-aware: `agent_id` present means recommend `llm_qa.py changed`.
- Or name both roles in it.

### 9. MINOR: agent-facing instructions still send sub-agents to the full suite

**Where:**
- `CLAUDE/AgentTeam.md:1604-1609`: "Each developer agent in their worktree: ... Runs
  `./scripts/qa/llm_qa.py all`".
- The acceptance-testing FAIL-FAST cycles: `.claude/skills/acceptance-test/invoke.sh:165` and
  `CLAUDE/AcceptanceTests/GENERATING.md:142`.
- The release skill's FAIL-FAST cycle: `.claude/skills/release/invoke.sh:203`.

**Failure scenario:** an agent follows the documented step, is denied, and loses a turn. The
instructions contradict CLAUDE/QA.md.

**Fix:** change each sub-agent step to `llm_qa.py changed`, with "the coordinator runs the full
gate". For the skills, state which role runs the step.

### 10. MINOR: name-based mapping selects unrelated tests and reports that as "mapped"

**Where:** `run_changed_tests.py:173-184`. It matches `test_<stem>.py` and `test_<stem>_*.py`
anywhere under `tests/`.

**Failure scenario** (`probe_mapping.py`):
- `strategies/pipe_blocker/common.py` selects 7 `test_common.py` files, and 6 of them are in
  unrelated packages (plan_qa, comments, lint, lsp_noise, security, tdd).
- `config/models.py` selects `tests/unit/skill_scan/test_models.py`.
- `constants/handlers.py` maps only to `tests/integration/test_handlers_do_not_match_prose.py`.
- `daemon/cli.py` selects 80 files.
- The "0 unmapped" in the handover reads as coverage it does not have.

**Fix:**
- Prefer the mirrored location first: `tests/unit/<subpath after src/pkg>/test_<stem>*.py`.
- Fall back to the global name search only when the mirror has nothing.
- Record in the JSON which rule selected each file.

### 11. MINOR: `llm_qa.py changed` cannot pass `--base`

**Where:** `scripts/qa/llm_qa.py:485-489`. The command is fixed as `run_changed_tests.py --json`,
and the default base is `main` (`run_changed_tests.py:56`).

**Failure scenario:**
- In a clone with no local `main` (a CI checkout, or a repo whose default branch is named
  differently), `changed` fails with exit 2 on every run.
- It correctly does not pass, but the entry point gives no way to fix it.

**Fix:**
- Resolve the default from `git symbolic-ref refs/remotes/origin/HEAD`, falling back to `main`.
- Or pass `--base` through from `llm_qa.py`.

### 12. MINOR: tests restate configuration and constants instead of exercising behaviour

**Where:**
- `tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py:44-84` restates the repository
  patterns, and a third copy sits in the `test_blocking_handler_evasion.py` configurator.
- The comment says the dogfood YAML "is checked separately, by the integration suites that load it",
  but no test references `subagent_full_qa_blocker` together with the real YAML.
- `tests/unit/qa/test_llm_qa_changed.py:52-63` restates `CHANGED_TOOL_NAMES`, a tautology.
- `test_llm_qa_changed.py:89-95` asserts only registry and dict membership.
- `test_llm_qa_changed.py:139` is the third pin of "smoke_test is last". The others are
  `test_smoke_test.py:121` and `test_project_handler_test_gate.py:142`.

**Failure scenario:** someone edits the YAML (for example, drops `bare_is_full`), and every test
stays green while the live guard changes.

**Fix:**
- Add one integration test that loads `.claude/hooks-daemon.yaml`, configures the handler through
  the registry, and asserts that a sub-agent's `llm_qa.py all` and bare `pytest` are denied while
  `llm_qa.py changed` is allowed.
- Delete the restated-constant and duplicate-pin tests.

### 13. MINOR: duplicated constants, and the CLI reaches into handler internals

**Where:**
- `_FLAG_PREFIX`, `_LONE_DASH` and `_END_OF_OPTIONS` are defined in both
  `utils/shell_segmentation.py:400-402` and `subagent_full_qa_blocker.py:258-261`.
- `daemon/cli.py:2090-2092` uses the literals `"enabled"`, `"options"` and `"full_qa_patterns"`,
  and assigns the private `_full_qa_patterns`, duplicating the registry's option injection.

**Failure scenario:** an option rename in the handler (`_OPTION_PATTERNS`) leaves `check` reading
the old key. It would then report "declares no usable patterns" for a correctly configured project.

**Fix:**
- Export the flag constants from shell_segmentation.
- Give the handler one public `configure(options: Mapping)`, or reuse the registry's injector, and
  call it from both places using the option-name constant.

### 14. MINOR: Task 1.1 is still open while the success criterion reads as universal

**Where:** PLAN.md Task 1.1 (the Workflow-tool measurement) is unticked. The success criterion is
"A sub-agent cannot start a full QA run".

**Failure scenario:** the plan is closed with the criterion ticked, even though Workflow-tool agents
are unmeasured. If they lack `agent_id`, the criterion is false for them.

**Fix:** before completion, either record the probe result or reword the criterion to "an Agent-tool
sub-agent or in-process teammate". `644a5939` does the wording in the docs, but not in PLAN.md's
criterion.

### 15. MINOR: the branch head is not the reviewed commit

**Where:** worktree `worktree-plan-463-full-qa-gate`.
- `644a5939` has been committed after `a1fff052`.
- Uncommitted: `M .claude/project-handlers/pre_tool_use/orchestrator_simulate.py` and its test.
- Untracked: `?? tests/integration/test_full_qa_gate_is_never_deadlocked.py`.

**Failure scenario:** the coordinator merges the branch head believing it was reviewed. The
orchestrator_simulate edit changes an existing handler's verdict and message logic
(`_policy_denies` is split out of `_would_deny`), and that change has had no review.

**Fix:**
- Commit or discard the in-progress work.
- Review `a1fff052..HEAD` before the full gate and the merge.
- The orchestrator edit is the right direction: it makes the simulate record agree with the armed
  policy. It still needs a review.

---

## Positive observations

- Parsing rather than substring matching is done properly, through the shared
  segmentation and inert-span stripping. Every mention, commit message, heredoc and grep shape in
  the brief is clean.
- The role test is delegated to `scope=SUB`, and the handler never reads `agent_id`, so the
  synthetic-event rule is inherited rather than re-implemented.
- A malformed config entry is reported and skipped, never guessed at. An enabled handler with no
  patterns surfaces in `hooks-daemon check`.
- Consolidating `COMMAND_WRAPPERS` into one table removes a real drift source. The invariant pair
  was updated with it, and process_probe's behaviour is preserved: the innermost wait wrapper still
  names the construct.
- `run_changed_tests` treats "no merge base" as an operational failure, not an empty set, and treats
  "selected but collected nothing" as a failure.
- The docs are honest about the Workflow-tool gap and about the guard being a resource guard, not a
  security boundary.

## Verdict

REQUEST CHANGES. No blocker. Findings 1 and 2 go to the heart of the plan's two deliverables: the
targeted entry point must not pass on nothing, and the matcher must not fail open on every
undeclared value flag. Finding 3 weakens a release gate. The rest can be filed as follow-ups.
