# Task 2.3 report: s5 ci-state reading

Handler `ci_state_reading` (PostToolUse, priority 44, advisory, never denies, never terminal).

Spec on disk: one PLAN.md Goals line and one 00630 DESIGN.md section 19 table row ("ci-state: GitHub 'queued' versus stuck; never assert another seat's code without asking"). No further s5 text exists, so only the deterministic part was built (Task 2.2 precedent).

Built:

- `utils/ci_state.py`: reads output a `gh` command already printed; no command, no network. Shapes verified against `gh` 2.105 non-TTY output: `gh run list` rows (9 tab columns, status first, ISO `createdAt` last), `--json` objects with `status`/`createdAt`, `gh pr checks` rows and `--json` `bucket`.
- Readings: QUEUED (queued, age under `options.stuck_after_minutes`, default 30, valid 1..1440); STUCK (at or past it, names `gh run view <id> --json status,createdAt,jobs`); PENDING (`gh pr checks` folds queued and running, names the `gh run list --json` command that can tell); UNKNOWN (missing/unparseable/zone-less/future time, `pending`/`requested`/`waiting` statuses, output reshaped by `--jq`/`--template`). Unknown never says either state.
- `gh` must be in command position (`simple_commands`); `echo "gh run list"` is no reading. Text `gh run view` is not read (no status column).
- Block text: a reading, not a verification anyone can cite; ends with the s5 rule (never tell the team what another seat's code does, or why its CI is red or stuck, without asking that seat on the bus). The same rule is resident guidance (`get_claude_md`), regenerated into `.claude/HOOKS-DAEMON.md`.
- Gate: extracted `team_role_gate.coordinator_advisory_armed` (declared coordinator, coordinator duty, unreadable role, unresolved probe arm; declared worker, no team, sub-agent do not); `owner_directives_register` now uses it instead of its own copy. A raising resolver counts as armed (advisory only adds text). The probe runs only when there is a reading to give.
- Paperwork: HandlerID, Priority, post_tool_use `__init__`, init_config, both yaml files, HANDLER_REFERENCE, config-changes v3.77.0 under `added:`, release note 097, one acceptance test (silent default), PLAN.md.

Left out and why:

- Detecting that a seat asserted another seat's code: needs bus reads and judgement.
- A run stuck while `in_progress` (long-running): s5 names queued versus stuck only.
- The default threshold (30 min) is the builder's choice; owner/coordinator to confirm.

Tests: new unit tests for the reader, the gate helper and the handler (red first: import errors), plus registry, init_config, acceptance coverage, guidance coverage, config-changes manifest, example config, handler reference, release notes, generated-doc drift and perf_sweep marker suites. No full QA run.
