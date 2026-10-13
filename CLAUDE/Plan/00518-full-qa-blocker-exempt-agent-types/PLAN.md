# Plan 00518: full qa blocker exempt agent types

**Status**: Not Started
**Created**: 2026-10-13
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner, 2026-10-13: "update the sub agent full qa blocker so we can whitelist certain agent types", and "dog food
that in this repo - make a QA agent and lets give it a try". Graduated from ledger 00474 N457.

`subagent_full_qa_blocker` denies a declared full-suite QA command inside any sub-agent. A project that runs its full
QA through a dedicated agent (php-qa-ci's `qa-tool-runner` skill delegates to its `php-qa-ci_full-pipeline-runner`
agent) must therefore leave the handler off, and `optimise` tells it to. The handler reads no `agent_type` and has no
per-agent option, although a sub-agent's PreToolUse payload carries `agent_type` (`core/input_schemas.py`) and other
handlers read it (`dispatch_declaration`, `agent_isolation_advisor`).

The handler exists because concurrent full runs exhaust the host. A single dedicated runner fits that purpose; two at
once do not. So the exemption comes with a one-at-a-time lock (the coordinator's choice where the owner's ruling was
silent; the owner can drop it).

## Goals

- `exempt_agent_types: [<name>, ...]` (exact names, default empty): a full run inside a listed agent type is allowed,
  with an advisory naming the entry that exempted it.
- One exempt full run at a time: while one is live, a second exempt full run is denied, naming the live one (agent
  type, start time). A run that ended or died releases the lock (no stale lock blocks forever).
- The `optimise` review recommends the exemption when it finds a dedicated QA-runner agent, not "leave it off".
- Dogfooded here: a `qa-full-runner` agent in `.claude/agents/` that runs the full gate on a named worktree and reports,
  listed in this repository's `exempt_agent_types`.

## Non-Goals

- Exempting by anything other than the exact agent type (no globs, no model, no prompt text).
- Changing what counts as a full run (`full_qa_patterns`).
- Changing the existing `qa-runner` agent, which stays targeted-only.

## Tasks

### Phase 0: Facts

- [ ] ⬜ **Task 0.1**: Record the `agent_type` value a Bash call carries from an Agent-tool sub-agent of a custom
  `.claude/agents/` type, from a built-in type, and from an in-process teammate (ledger N443: upstream `agent_id` now
  also identifies teammates). Use the daemon's payload capture or a probe; the exemption keys on what is observed.

### Phase 1: Exemption and lock (TDD)

- [ ] ⬜ **Task 1.1**: `exempt_agent_types` option, config validation, and the allow-with-advisory path. Tests: a
  listed type is allowed; an unlisted type, a missing `agent_type`, and a near-miss name are denied as today.
- [ ] ⬜ **Task 1.2**: The lock: a lock file under `untracked/` holding the holder's agent type, session, pid of the run
  where knowable, and start time; released when the run's process is gone or after a bound. Tests over a live holder,
  a dead holder and a second claimant.
- [ ] ⬜ **Task 1.3**: Handler guidance (`get_claude_md`), `explain-handler` text, and the deny text name the option.

### Phase 2: optimise

- [ ] ⬜ **Task 2.1**: The `optimise` checklist detects a dedicated QA-runner agent and recommends
  `exempt_agent_types` for it.

### Phase 3: Dogfood

- [ ] ⬜ **Task 3.1**: `.claude/agents/qa-full-runner.md` (and its install template if agents ship): runs
  `./scripts/qa/llm_qa.py all` in the worktree it is given, never fixes, reports VERDICT and failures to a file.
- [ ] ⬜ **Task 3.2**: `.claude/hooks-daemon.yaml` lists `qa-full-runner` under `exempt_agent_types`; daemon restart.
- [ ] ⬜ **Task 3.3**: Live trial: dispatch `qa-full-runner` on an integration worktree and observe the allow with its
  advisory; dispatch `qa-runner` with a full command and observe the deny; dispatch a second `qa-full-runner` while
  the first runs and observe the lock deny. Record the observations in the journal.
- [ ] ⬜ **Task 3.4**: `CLAUDE/development/IssueSdlc.md` (and `CLAUDE/QA.md`) say when the coordinator may hand the full
  gate to `qa-full-runner`.

### Phase 4: Release

- [ ] ⬜ **Task 4.1**: Release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` and a `config-changes` entry for the
  new option.

## Success Criteria

- [ ] A listed agent type's full run is allowed with an advisory; every other sub-agent's is denied as before.
- [ ] A second concurrent exempt full run is denied; a dead holder never blocks.
- [ ] `qa-full-runner` ran the full gate in this repository through the exemption (journalled trial).
- [ ] Release-bound consequences recorded in `CLAUDE/UPGRADES/UNRELEASED/` (release note, config-changes entry).

## Delivery & Milestones

- Filed from the owner's ruling of 2026-10-13 on ledger 00474 N457.
