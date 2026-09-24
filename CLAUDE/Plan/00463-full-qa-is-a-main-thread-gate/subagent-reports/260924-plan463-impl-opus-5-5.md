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
error_hiding, project_handlers and `changed_tests`. `changed_tests`
(`scripts/qa/run_changed_tests.py`) collects the files changed since the merge base with
`main`, plus untracked files. It maps each file to tests:

- a test file selects itself;
- `module.py` selects `test_module.py` and `test_module_*.py`;
- a file with no mapped test is reported as unmapped.

It runs pytest on the selection and writes `untracked/qa/changed_tests.json`.
`changed_tests` is excluded from `all`.

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
- **Orchestrator-only mode (00418):** it denies only Write, Edit and NotebookEdit on the
  main thread, never Bash. The coordinator's full gate therefore cannot deadlock.
  `test_the_coordinators_full_qa_gate_is_never_denied` pins that.

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

- `./scripts/qa/llm_qa.py changed` passed 8/8: 2338 tests from 107 test files, mapped from
  43 changed files, with 0 unmapped.
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
