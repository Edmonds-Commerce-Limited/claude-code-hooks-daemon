# Plan 00463 implementation report (Opus 5.5, teammate plan463-impl)

Branch `worktree-plan-463-full-qa-gate`. The worktree is
`untracked/worktrees/worktree-plan-463-full-qa-gate/`. Phase 1 Tasks 1.2 to 1.4 are
done. Task 1.1 is done except the Workflow-tool measurement. Task 1.5 is this handover.
Phase 2 is untouched.

## What the handler does

`subagent_full_qa_blocker` (`handlers/pre_tool_use/subagent_full_qa_blocker.py`):

- PreToolUse Bash, `scope: SUB`. The chain applies it before `matches()`, so the main
  thread and synthetic probe events never reach the handler.
- HandlerID `SUBAGENT_FULL_QA_BLOCKER`, priority 32 (it runs before `enforce_llm_qa` at 41),
  terminal, RuleID `R-SUBAGENT-FULL-QA`, with guidance in `get_claude_md`.
- It is disabled by default and ships with no default patterns. The patterns are
  project-declared `full_qa_patterns` entries with these keys: `id`, `command`,
  `full_args`, `bare_is_full`, `read_only_flags` and `value_flags`.
- `targeted_qa_commands` is the RUN INSTEAD list the deny prints. With none declared, the
  deny gives generic advice to name explicit files.
- Matching works on parsed commands, never on substrings. The parser normalises line
  continuations and strips inert spans (quotes, heredoc bodies, comments). It splits on
  `&&`, `||`, `;`, `|`, newlines, subshells, backticks and a lone `&`. It then resolves
  assignments, shell keywords, command wrappers, project runners (`uv run` and similar),
  `python -m`/script and `bash -c` recursion (depth 3). It skips redirects, `--`,
  read-only flags and value flags. It normalises `./` prefixes, trailing `/` and
  absolute-path suffixes.
- A malformed config entry is reported once in the log and in `hooks-daemon check`
  (`get_enforcement_status`), and it does not match anything.
- The shared wrapper table was moved from `utils/process_probe.py` into
  `utils/shell_segmentation.py` (`COMMAND_WRAPPERS`, `peel_command_wrappers`), so both
  consumers read one table. The invariant pair and the docstrings that pointed at the old
  name were updated.

## The targeted entry point

`./scripts/qa/llm_qa.py changed` runs magic_values, format, lint, type_check, pyright,
error_hiding, project_handlers, docs_qa, plan_qa, shell_check, declared_invariant_pairs and
`changed_tests`. `changed_tests` (`scripts/qa/run_changed_tests.py`) collects the files
changed since the merge base, plus untracked files, with renames split into a deletion and
an addition. A test file selects itself. Any other file's coverage is the UNION of four
parts, since delta review N3:

- its declared rule in `scripts/qa/changed_tests_map.yaml`;
- its mirror, `tests/unit/<path>/test_<stem>*.py`;
- the tests that refer to it by path, by a path built from its parts, by a unique basename,
  or by importing it. These are read from the syntax tree, so a comment or docstring does
  not count;
- one hop of dependents' own unit tests.

A nested conftest runs its subtree. The root conftest is too broad, and so is any reach past
40 test files; a too-broad file still runs its own tests. A deleted file that a source
still refers to is unmapped. Each unmapped file carries its reason (`uncovered`,
`too-broad`, `deleted-but-referenced`), and it fails the run. `--allow-unmapped` is the
explicit escape. `--base` overrides the merge base, which defaults to origin/HEAD and
falls back to `main`. The run refuses to start on the base branch or with no changes. It
writes `untracked/qa/changed_tests.json`, and `changed_tests` is excluded from `all`.

## Review fixes (every finding except 15, which is the coordinator's review of the range)

- **M1**: an unmapped file fails the run, as described above. The two tests that pinned
  the silent pass are gone. Deleted and non-Python files are listed in the report.
- **M2**: `option_grammar: pytest` merges `PYTEST_VALUE_OPTIONS`, which covers pytest core,
  cov, xdist, timeout, randomly, rerunfailures, asyncio and html. A test pins the set
  against the installed pytest's argparse actions. Only a path-like operand narrows a run.
  An operand is path-like if it contains `/` or `::`, ends in `.py`, or exists under the
  event's `cwd`. So `pytest --cov . tests/unit/x.py` is allowed and `pytest --cov src` is
  denied.
- **M3**: `llm_qa.py` writes `untracked/qa/provenance.json`, with HEAD and a working-tree
  digest for each tool. It records "changed-during-run" when the tree moved mid-run.
  `--read-only` marks a mismatched result STALE and fails it.
- **Evasions**:
  - project runners are resolved through their own flag grammar: `uv run --frozen`,
    `uv run --`, `uvx`, `uv tool run`, poetry, pipenv, pdm and hatch;
  - attached redirects (`all>out.txt`) are split off;
  - `$PWD/` and `${PWD}/` prefixes are normalised;
  - `env -C`/`--chdir` take a value.
- **Minors**:
  - `hooks-daemon check` builds the handler through the shared `apply_handler_config`,
    so the options it reports are the ones dispatch uses. It reports a `scope` other
    than SUB.
  - The handler and evasion tests load patterns from the live YAML.
  - The flag constants are shared from `shell_segmentation`.
  - The `enforce_llm_qa` deny is role-aware.
  - The tautology test is gone.
  - QA.md warns about bare pytest.
  - The success criterion names only the two measured agent kinds.

## Delta review fixes (N1 to N10, `260924-plan463-delta-review-opus-5-5.md`)

The tests came first. Each new test was run against the code as it stood and failed before
the fix; for N3 the scenarios were also driven through HEAD's `run_changed_tests.py`, and
all six failed there.

- **N1**: each tool's provenance entry now carries the live verdict, the exit code and the
  sha256 of the report it wrote. A run deletes a tool's old report before running it.
  `--read-only` re-applies the recorded exit code, and fails a missing, replaced or unwritten
  report. `_run_tools` is tested end to end with `run_tool` stubbed: a crash with no output,
  a green report with exit 1, a replaced report, and a clean run.
- **N2**: a tree that changes during the run is printed at the end of that run. It fired for
  real during this work, when the `format` tool rewrote two files mid-run.
- **N3**: the union mapping above, with a JSON reason for each unmapped file. On this
  branch it selects 196 test files, up from 107, and it found a real defect. The new
  opt-in handler was missing from `test_default_enabled_template_consistency.py`'s expected
  set, a test the old mapping never ran. That test is now fixed. Eleven files are honestly
  `too-broad`: the constants modules, `cli.py`, `registry.py`, `handler_scope.py`,
  `init_config.py`, the handler, the dogfood config, CLAUDE.md and HOOKS-DAEMON.md.
- **N4**: each `cd` in a command moves the directory that path lookups use, and one the
  shell would expand drops back to shape. Under `option_grammar`, a flag in neither
  `PYTEST_VALUE_OPTIONS` nor the new `PYTEST_FLAG_OPTIONS` is read as taking a value, so
  it fails closed. Both sets are pinned against the installed parser. HANDLER_REFERENCE
  now says where a path-shaped value can still target a run.
- **N5**: a word after an unlisted runner flag is tried both as that flag's value and as
  the command, for the global flags and the `run` flags alike. The other fixes:
  - `uvx pytest@8` and `uv tool run pytest@8` drop the version pin;
  - `hatch run env:cmd` is split into the environment and the command;
  - `&>` splits an attached redirect;
  - `~/`, `$HOME/` and `${HOME}/` read as absolute;
  - `env -S` is off the limits list, because it is seen.
- **N6**: `tool_command` is deleted. The forwarding test now drives `run_tool`, and the
  `_run_tools` tests pin that forwarding reaches `changed_tests` only.
- **N7**: QA.md now states bare pytest as policy. Bare `pytest` from `tests/unit/core`
  collects only that directory, but the guard cannot see the shell's directory.
- **N8**: the Bugs.md FAIL-FAST cycle has the role split.
- **N9**: "never denied" and the guidance's Bash sentence are derived from `_BLOCKED_TOOLS`.
- **N10**: untracked files are hashed streamed (`hashlib.file_digest`), never read whole.

## Task 1.1 measurements

- **In-process teammate: `agent_id` is present.** Measured live on this teammate's own
  payload: `agent_id` was 30 characters, `agent_type` was `plan463-impl`. The journal
  records it as a finding with ref T1.1.
- **Agent-tool sub-agent: `agent_id` is present.** The evidence is from Plans 00418 and
  00423 (17 characters).
- **Workflow-tool agent: UNMEASURED.** The probe needs the owner's explicit opt-in to the
  Workflow tool, and the lead has asked the owner for it. The handler's docstring and
  guidance, HANDLER_REFERENCE.md, CLAUDE/QA.md and release note 13 claim coverage only for
  Agent-tool sub-agents and teammates. Admission keys only on a non-empty `agent_id`, so
  nothing changes if Workflow agents turn out to carry it. A parametrised scope test pins
  this: ids of 17, 30 and 1 characters are admitted, and an empty id is not. The
  `handler_scope.py` docstring records the 30-character teammate measurement. Task 1.1 is
  ticked with the Workflow point recorded as unmeasured.
- **Default:** disabled, with empty patterns. Client QA commands vary, so a default
  populated from this repo's commands would never fire in a client project.
- **Orchestrator-only mode (00418): no deadlock, now proven on the real chain.** The
  first version of this report said "no deadlock", and that stands; the coordinator's
  reviewer confirmed it against the real handler. The only test pinning it ran the
  handler on its own, though. Meanwhile, on every main-thread Bash call, the simulate
  record said "main thread would have been denied — Bash: ...", which looked like
  contrary evidence.
  - **Cause.** `orchestrator_simulate.py` `handle()` printed that text for every call
    `matches()` flags. The blocking policy (`_would_deny`) refuses only Write, Edit and
    NotebookEdit outside `CLAUDE/Plan/`. The record was false; the policy was not.
  - **Fixed here; this remedies ledger 00422 N24.** The fix was committed at `14c0b806`,
    reverted at `f330cf41` on an earlier direction, and restored once the coordinator
    accepted it as the N24 remedy. `_policy_denies()` holds the policy, and `_would_deny()`
    gates it on the switch. The simulate record says "would have been denied" only when
    that policy denies. Other matched calls read "recorded, not a would-be denial", and
    Bash adds "Bash is never denied by this mode". `TestTheSimulatedRecordTellsTheTruth`
    ties the record to the armed verdict across the tool surface. The integration test
    checks that the full gate's record carries no would-be denial. The coordinator ticks
    N24 when 00463 merges.
  - **The real policy against the real gate (kept).**
    `tests/integration/test_full_qa_gate_is_never_deadlocked.py` builds the live PreToolUse
    chain: library handlers via `register_all()` on this repo's config, plus all discovered
    project handlers, with orchestrator-simulate ARMED. The main thread's
    `./scripts/qa/llm_qa.py all` gets ALLOW, both from the chain and from the orchestrator.
    Two controls show the chain is armed: a main-thread Edit is denied
    (R-ORCHESTRATOR-MAIN-THREAD-WRITE), and a sub-agent's `llm_qa.py all` is denied by
    subagent-full-qa-blocker.
  - **No allowlist entry.** Bash is outside the policy's blocked-tool set, so an entry for
    `llm_qa.py all` would never run. The integration test is the explicit pin, and it fails
    first if the policy ever gains a Bash branch.

## Configuration and docs

- `.claude/hooks-daemon.yaml` enables the handler with these patterns:
  - `llm_qa.py` with `all` or `tests`;
  - `run_all.sh`;
  - `run_tests.sh`;
  - `validate_worktrees.sh`;
  - whole-suite pytest: bare, `tests`, `tests/unit` or `.`.
- The `.example` file and the `init_config` template carry a disabled entry.
- The release note is `UNRELEASED/release-notes/13-...md`. The config-changes manifest
  is `UNRELEASED/config-changes/v3.67.0.yaml`. That filename may collide with other
  in-flight plans' manifests at merge.
- Docs:
  - CLAUDE/QA.md has the canonical section "Full QA Is the Coordinator's Gate; Sub-Agents
    Run Targeted QA".
  - AgentTeam.md, IssueSdlc.md and Worktree.md carry the split.
  - CodeLifecycle General, Features and Bugs point to QA.md.
  - docs/guides/HANDLER_REFERENCE.md has the new handler.
  - The agent definitions (qa-runner, qa-fixer, release-agent) never run the full suite.
- `.claude/HOOKS-DAEMON.md` and CLAUDE.md were regenerated. The daemon auto-committed
  the CLAUDE.md block on this branch (`9a7a5ac2`). On main it regenerates on the first
  restart after merge, so a conflict there resolves by taking either side and restarting.

## Verification (targeted only, under this plan's rule)

- After the delta review fixes, `./scripts/qa/llm_qa.py changed --allow-unmapped` passed
  12/12. That was 6979 tests from 196 test files, mapped from 59 changed files. The 11
  unmapped files are the too-broad ones listed above, and they are the full gate's. Without
  `--allow-unmapped` the run fails on exactly those 11. A further targeted run of the QA
  scripts, handler, evasion, shell utility, CLI status, registry, deadlock and doc/config
  integration tests passed 2100.
- docs_qa, plan_qa, doc_truth, repo_hygiene, british_english, handler_reference,
  declared_invariant_pairs and security were clean.
- The broader targeted pytest runs all passed:
  - `tests/unit/handlers/pre_tool_use`, `tests/unit/core`, `tests/unit/config` and
    `tests/config`: 6561 passed, 2 xfailed (the xfails were there before this work);
  - the integration wiring suites and guidance coverage;
  - the doc and command integration tests: 236 passed.
- Live probes through `.claude/hooks/pre-tool-use` against this worktree's daemon:
  - a sub-agent's `llm_qa.py all` was DENIED with the full reason;
  - a sub-agent's `llm_qa.py changed` was allowed;
  - the main thread's `llm_qa.py all` was allowed;
  - a synthetic sub-agent event was allowed.

## For the coordinator

- Run the full gate on this branch head in this worktree (Task 2.1).
- The Workflow-tool probe is the only open measurement.
