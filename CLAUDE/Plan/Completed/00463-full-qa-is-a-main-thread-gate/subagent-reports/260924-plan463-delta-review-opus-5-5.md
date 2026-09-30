# Plan 00463 delta review (Opus 5.5 code-reviewer)

**Scope:**

- `git diff a1fff052..4a6101ff`: the orchestrator investigation, the coverage wording, and the fixes
  for the first review's 3 major and 12 minor findings.
- Extended at the coordinator's request to `4a6101ff..e467a5cc`: the orchestrator_simulate record fix
  (ledger 00422 N24).

Line numbers are as of `e467a5cc`. `scripts/qa/*` and the handler did not change between `4a6101ff`
and `e467a5cc`.

**Verification run by this reviewer (no full suite):**

- Targeted pytest: 1009 passed. Files: the handler, run_changed_tests, llm_qa changed/provenance/
  wiring, cli enforcement status, registry option injection, the deadlock integration test,
  orchestrator_simulate, enforce_llm_qa, evasion, shell_segmentation, process_probe.
- `./scripts/qa/llm_qa.py changed` on `e467a5cc` in the worktree: 12/12, with 2617 passed from 107
  test files, mapped from 58 changed files, 0 unmapped. Before that run, `--read-only changed`
  correctly marked all 12 results STALE, because they had been recorded at `4a6101ff`.
- Probes: the first reviewer's `probe_matching.py` and `probe_matching_2.py` were re-run unchanged.
  `probe_changed_verdicts.py` and `probe_mapping.py` no longer load against the new API (the
  dataclass needs `sys.modules` registration, and `select_tests` has a new signature), so their
  scenarios were re-driven inline through the same injection points, plus new ones.

**Counts:**

- Prior findings: 13 FIXED, 2 PARTIAL, 0 NOT FIXED, 0 REGRESSED.
- New findings: 0 blocker, 1 major, 6 minor, 3 nit.

---

## Per-finding verdicts

| #   | First-review finding                                 | Verdict | Evidence                                                                                                                                                                                                                                                                                                                    |
| --- | ---------------------------------------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `changed` passes when it tested nothing              | FIXED   | Probe: orphan module exits 1 and is named; `.yaml`/no-suffix hook files under src are unmapped and exit 1; a deleted module selects its surviving mirror test; base branch exits 2; empty set exits 1; `--allow-unmapped` exits 0 labelled ALLOWED; stdout says "no tests ran". Residual under-selection is new finding N3. |
| 2   | Operand model misreads flag values                   | FIXED   | All first-review rows now correct (`--timeout 60`, `--cov src`, `--log-level DEBUG`, `--override-ini addopts=` deny; `--cov . <file>`, `--confcutdir . <file>` allow). The grammar pin test is sound (below). Residuals are N4.                                                                                             |
| 3   | Release pre-validation reads results of unknown age  | PARTIAL | RELEASING.md Step 1b, release-agent.md, the release skill and QA.md now order it correctly, and a result from another HEAD or tree reads STALE (seen live). But provenance marks a result as current even when the run did not produce it: N1.                                                                              |
| 4   | Runner resolution fails whenever a flag is involved  | FIXED   | `uv run --frozen/--/-q`, `uv --directory x run`, `uv run --directory x`, `poetry run --`, `uvx`, `uv tool run` all deny. Unlisted runner flags still fail open: N5.                                                                                                                                                         |
| 5   | Smaller evasions                                     | FIXED   | `all>out.txt`, `all>>out.txt`, `$PWD/tests`, `${PWD}/tests`, `env -C`, `env --chdir` deny; `xargs` documented as a limit. `all&>out.txt` still allowed: N5.                                                                                                                                                                 |
| 6   | Bare `pytest` from a test subdirectory is denied     | PARTIAL | QA.md now tells agents to name paths, but its stated reason is false about pytest: N7.                                                                                                                                                                                                                                      |
| 7   | A `scope:` override brings the deadlock back         | FIXED   | `get_enforcement_status` reports a non-SUB scope; `check` now goes through `apply_handler_config`, so a YAML `scope: ALL` is reported (`test_a_scope_override_is_reported`); HANDLER_REFERENCE and the manifest say so.                                                                                                     |
| 8   | `enforce_llm_qa` tells sub-agents to run `all`       | FIXED   | Role-aware deny, pinned both ways. Seen live during this review: the main checkout's daemon still runs the pre-merge text. That is expected until merge.                                                                                                                                                                    |
| 9   | Agent instructions send sub-agents to the full suite | FIXED   | AgentTeam.md:1609, acceptance-test/invoke.sh, GENERATING.md, release/invoke.sh. One unnamed sibling remains: N8.                                                                                                                                                                                                            |
| 10  | Name mapping selects unrelated tests                 | FIXED   | The mirror is tried first, and each mapping records its rule. `pipe_blocker/common.py` now maps to its own `test_common.py`. The name fallback still over-reaches for short stems (N3e).                                                                                                                                    |
| 11  | `changed` cannot pass `--base`                       | FIXED   | `--base`/`--base=` and `--allow-unmapped` are forwarded, and are an error without changed_tests. The default base follows origin/HEAD, then a local `main`, then exits 2 with a remedy.                                                                                                                                     |
| 12  | Tests restate config                                 | FIXED   | Handler and evasion tests load the live YAML. `test_full_qa_gate_is_never_deadlocked.py` drives `register_all()` on the real config (full runs deny, targeted runs allow). The tautology and duplicate pins are gone. A new vacuous test is N6.                                                                             |
| 13  | Duplicated constants; CLI reaches into internals     | FIXED   | `FLAG_PREFIX`/`LONE_DASH`/`END_OF_OPTIONS` are exported from shell_segmentation and used by process_probe and the handler. The CLI uses `apply_handler_config` and `ConfigKey`, and no longer uses literals.                                                                                                                |
| 14  | Task 1.1 open while the criterion reads as universal | FIXED   | Criterion: "An Agent-tool sub-agent or in-process teammate cannot start…". Task 1.1 ticked with Workflow recorded as unmeasured.                                                                                                                                                                                            |
| 15  | Branch head is not the reviewed commit               | FIXED   | Tree clean. The head moved again to `e467a5cc`, and that delta is reviewed below at the coordinator's request.                                                                                                                                                                                                              |

### The pytest option grammar pin

`test_every_value_option_of_the_running_pytest_is_known`
(`tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py:301`) is sound, for these
reasons:

- It reads the installed parser's `_actions` and takes each action with `nargs != 0`, which includes
  the optional-value `?` options (`--cov`, `--debug`, `--cache-show`).
- It asserts installed ⊆ `PYTEST_VALUE_OPTIONS`, which is the right direction.
- It guards against a vacuous empty set.
- It would error rather than silently pass on a private-API rename.
- pytest builds its parser with `allow_abbrev=False` (checked in the venv), so abbreviations cannot
  sneak past.
- Handling `--cov` as a value flag matches argparse. `pytest --cov tests/unit/x.py` really does run
  the whole suite with `x.py` as the coverage source, so denying it is correct.

Limits:

- It can only vouch for installed plugins.
- It cannot help a flag the grammar does not list whose value is path-like (N4).

### Orchestrator record fix (`4a6101ff..e467a5cc`, ledger 00422 N24)

**Sound.** The simulate message and the armed verdict share one predicate for every tool:

- `_policy_denies()` holds the whole policy: one of the blocked tools, no `agent_id`, not
  synthetic, not in the plan tree.
- `_would_deny() = self._blocking and self._policy_denies()`.
- `handle()` prints "main thread would have been denied" iff `_policy_denies()`.

In blocking mode, the allow path can therefore never claim a would-be denial. In simulate mode, the
claim appears exactly where the armed handler denies.

**Nothing else in the handler changed:**

- `git diff 644a5939 4a6101ff` on the file is empty.
- `main...e467a5cc` is +29/-10, and covers only four things:
  - `_recorded_verdict`;
  - the predicate split;
  - the verdict string in `handle()`;
  - the `get_claude_md` paragraph.
- `matches()`, `_BLOCKED_TOOLS`, the plan-tree exemption, the deny reason, priority, tags and
  terminal are untouched.

**Tests:**

- `TestTheSimulatedRecordTellsTheTruth` checks the claim against the armed verdict across 7 tools,
  including the plan-tree Write, NotebookEdit and an unknown tool.
- The integration test asserts that the chain-level record for the main thread's `llm_qa.py all`
  carries no "would have been denied".

The only remark is nit N9.

---

## New findings

### N1. MAJOR: provenance certifies a result the run did not produce, so `--read-only` can PASS what the live run FAILED

**Where:** `scripts/qa/llm_qa.py:1301-1305`. After the loop, `record_provenance(QA_OUTPUT_DIR, tools, state)` stamps the current tree on EVERY tool that was run, whatever the tool did:

- whether it rewrote its JSON;
- whether it exited 0.

In read-only mode `exit_code` is None, so `_summarize_recorded` (`:1088`) loses the exit-code
cross-check that exists "to catch cases where JSON lies".

**Failure scenario (reproduced):**

1. Seed a green `magic_values.json` from an older run.
2. The live run's tool exits 1 without writing JSON (a crash, a timeout, a missing binary).
3. The live run prints `❌ ... QA: 0/1 PASSED`, exit 1.
4. Immediately after, on the same tree, `--read-only` prints `✅ magic_values ... QA: 1/1 PASSED`,
   exit 0.

The same happens for a tool that writes a passing JSON but exits non-zero. The release agent's
Step 1b gate, which exists because of finding 3, then passes a tool that failed on the
coordinator's run of this HEAD.

**Fix:**

- Record per tool, alongside HEAD and digest:
  - the live verdict (`passed`, `exit_code`);
  - the sha256 of the JSON file as the run left it.
- `--read-only` then fails when:
  - the recorded verdict is false; or
  - the JSON on disk no longer hashes to the recorded value.
- Alternatively, unlink each tool's JSON before running it, and record provenance only for tools
  whose JSON exists afterwards. That closes the missing-output half, but not the exit-code half.
- Add a `_run_tools` test with a stub `run_tool` covering both halves.

### N2. MINOR: a tree that changes during the run is recorded silently

**Where:** `llm_qa.py:1302-1305`.

**Failure scenario:**

- The coordinator runs `all` in the background for 15-20 minutes and edits a journal meanwhile.
- The live summary prints all green and exit 0.
- Provenance quietly records `changed-during-run`, so every later `--read-only` (the release
  agent's) fails STALE, with no hint at the time of the run.

**Fix:** when `after != before`, print one line in the live summary saying the tree changed
during the run and the results will not certify it.

### N3. MINOR: "0 unmapped" still overstates coverage; the mapping stops at the first rule

**Where:** `scripts/qa/run_changed_tests.py:422-433` (a declared rule ends the search),
`:370-390` (a mirror or name hit ends it before the import search), and
`scripts/qa/changed_tests_map.yaml:12-40`.

**Failure scenarios (probed on the real tree):**

- **(a) Declared rules only name lint tools.** `*.md` maps to docs_qa and plan_qa, and `*.sh` to
  shell_check, so no test runs:
  - 276 test files name a `.md` path, and 189 a `.sh` path;
  - `CLAUDE/Plan/README.md` selects no test, though `test_plan_index_navigability.py` parses it;
  - `scripts/qa/run_tests.sh` gets shellcheck only;
  - `.claude/hooks-daemon.yaml` selects 2 tests, though 149 test files load it.
- **(b) A mirror hit hides every dependent.** `utils/shell_segmentation.py` runs only its own 2
  files. The tests of process_probe and of the full-QA handler, which consume its changed
  `COMMAND_WRAPPERS`, are not selected.
- **(c) `tests/conftest.py` maps to 10 importers.** Every test loads it implicitly.
- **(d) A deleted module is checked against test sources only.** A module imported only by other
  `src` modules is "deleted-unreferenced", so no tests run and the verdict is PASS. mypy catches a
  static import; a dynamic one is missed.
- **(e) The name fallback `test_<stem>_*` over-reaches for short stems:**
  - `constants/handlers.py` maps to only `tests/integration/test_handlers_do_not_match_prose.py`;
  - `config/models.py` also pulls in `tests/unit/skill_scan/test_models.py`.
- **(f) "Too broad" is not recorded as the reason.** A file over the 40-importer cap lands in
  `unmapped` with no reason given.

The coordinator's gate is the backstop, but the summary tells the coordinator "0 unmapped".

**Fix:**

- After a declared or mirror hit, take the UNION with a reference search over test sources: the
  relative path, the basename and the dotted name, within the same cap.
- Treat any `conftest.py` as too broad.
- Record `reason: too-broad` in the JSON.
- Say in QA.md that `tools:` rules certify lint only.

### N4. MINOR: the path-like rule adds a false deny, still fails open for path-valued plugin flags, and the doc overclaims

**Where:** `subagent_full_qa_blocker.py:653-672` and `:861-866`, and
`docs/guides/HANDLER_REFERENCE.md:1412`.

**Failure scenarios:**

- **False deny.** `cd tests/unit && pytest handlers` is DENIED. Existence is checked against the
  event's `cwd`, not the directory after `cd`. At `a1fff052` this was allowed.
- **Fails open.** `pytest --json-report-file out/r.json` and `pytest --some-plugin out/x` are
  allowed: a flag the grammar does not list, with a value containing `/`, reads as a target.
- **Doc overclaim.** HANDLER_REFERENCE says "an unlisted flag cannot make a full run look
  targeted". That is false for path-shaped values. It also says "exists in the command's directory",
  when the check uses the event's cwd.

**Fix:**

- Correct the two doc sentences.
- Optionally, resolve a leading `cd <dir> &&` in the same chain into the cwd used for the existence
  test.

### N5. MINOR: remaining evasions from incomplete runner and redirect tables

**Where:** `subagent_full_qa_blocker.py:383-435` and `:460` (`_ATTACHED_REDIRECT_START = [<>]`).

**Allowed (each is a whole-suite run):**

- `uv run --color never pytest`
- `uv run --exclude-newer 2024-01-01 pytest`
- `uv run --resolution lowest pytest`
- `poetry run --directory x pytest`
- `pdm run -p x pytest`
- `uvx pytest@8`
- `hatch run test:pytest`
- `./scripts/qa/llm_qa.py all&>out.txt`. The operand becomes `all&`.
- `pytest ~/proj/tests`, `pytest $HOME/proj/tests`

Nit: HANDLER_REFERENCE:1418 lists `env -S` as unseen, but `env -S 'pytest'` is DENIED.

**Fix:**

- After a runner's `run`, fail closed: take the first following word that equals a declared
  pattern's `command`, rather than the first non-flag word.
- Strip `@<version>` from a `uvx` tool name.
- Split attached redirects on `&?[<>]`.
- Treat a leading `~/` or `$HOME/` like an absolute path for `_operand_is_full`.
- Drop `env -S` from the limit list.

### N6. MINOR: `tool_command` is dead code, and the forwarding test pins it instead of the real path

**Where:**

- `llm_qa.py:1050`. `tool_command` is called only by
  `tests/unit/qa/test_llm_qa_changed.py:157`.
- `run_tool` builds its argv itself.

**Failure scenario:**

- `_run_tools` could stop passing `forwarded` to `run_tool`, or pass it to every tool, and
  `test_the_forwarded_options_end_up_on_the_runners_command` stays green.
- No test covers `_run_tools`' before/after provenance logic either.

**Fix:**

- Have `run_tool` use `tool_command`, or delete it.
- Test `_run_tools` with a stubbed `run_tool`. It should assert the forwarded argv, the recorded
  state and `changed-during-run`. The same test can pin N1.

### N7. MINOR: QA.md misstates pytest's behaviour (finding 6 residual)

**Where:** `CLAUDE/QA.md:95-97`: "Bare `pytest` is the whole suite wherever it is typed, including
from `cd tests/unit/handlers`".

**Failure scenario:**

- Measured: from `tests/unit/core`, bare pytest collects 2143 tests. `testpaths` applies only when
  pytest is invoked from the rootdir.
- An agent that knows pytest will conclude the deny is a bug.

**Fix:** state it as policy: "the guard cannot see the directory a bare run collects, so a
targeted run must name its path".

### N8. NIT: one FAIL-FAST cycle still says "Run FULL QA" with no role split

**Where:** `CLAUDE/CodeLifecycle/Bugs.md:319`. It is the same cycle as the ones fixed in
GENERATING.md and acceptance-test/invoke.sh.

**Fix:** use the same wording as those two.

### N9. NIT: the orchestrator record re-states the policy in prose

**Where:** `orchestrator_simulate.py` `_recorded_verdict`, and the new `get_claude_md` sentence.
Both say "Bash is never denied by this mode" as a literal, rather than deriving it from
`_BLOCKED_TOOLS`.

**Failure scenario:**

- The mode gains a Bash branch.
- An allowed Bash call's record then still says "never denied".
- The agreement test would not catch it, because it only checks the "would have been denied" half.

**Fix:** use the phrase only when `"Bash" not in _BLOCKED_TOOLS`, or drop the parenthetical.

### N10. NIT: `worktree_state` reads every untracked file whole

**Where:** `llm_qa.py:309`.

**Cost:** measured at 34-36 ms on both the worktree and the main checkout (0 untracked files), so
there is no cost problem today. A large untracked, non-ignored artefact would be read into memory
twice per run.

**Fix (optional):** hash via `git hash-object --stdin-paths` over the untracked list.

---

## Observations (not findings)

- Evasion rows still allowed and unchanged from the first review: `echo "$(pytest)"`, `coproc`,
  4-deep `bash -c`, and `pytest tests/unit/*`. These are documented limits or policy.
- While probing, the main checkout's `enforce_llm_qa` denied a python heredoc that merely mentions
  `run_all.sh` in a string. That is its own pre-existing mention false positive, not this plan's.

## Verdict

**APPROVE WITH CHANGES.**

- The first review's three majors are addressed in substance.
- N1 should be fixed before merge: it reopens finding 3's release-gate hole in a narrower form.
- N2 to N10 can be filed as follow-ups.
- The orchestrator N24 fix is correct and self-contained.
