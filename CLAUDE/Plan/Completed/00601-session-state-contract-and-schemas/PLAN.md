# Plan 00601: session state contract and schemas

**Status**: Complete
**Created**: 2026-11-11
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Another team's coordinator needs each seat's state (working, idle, blocked, rate-limited until, gone). The daemon already records that state in files under `untracked/`, but only `mode-history --json` is a command contract. Consumers should read a documented, versioned interface, not internal files whose layout may change. The ask came from the owner through a peer team (niggle N616 in Plan 00474) and the owner confirmed it.

The work adds a `session-state --json --session ID` command and a `--watch` form that prints one JSON line per change. Every `--json` output carries a `schema_version` field and has a JSON Schema (2020-12) with a versioned `$id`. The schemas ship in the release, and the daemon's own tests validate each output against them. Consumers pin a major version and refuse an unknown one.

## Goals

- Confirm whether a main-thread usage-limit stop is recorded with its reset time, and record the answer here.
- `hooks-daemon session-state --json --session ID` returns modes with `since`, the last turn edge (start, stop, stop_failure with the error), usage (five_hour and seven_day with `used_percentage` and `resets_at`, plus `observed_at`), and the usage pause state.
- `--watch` streams one JSON line per change, with no polling by the consumer.
- A JSON Schema for each `--json` output (session-state, mode-history, the watch line); every document has `schema_version`; semver, a breaking change is a new major.
- The command is cheap enough to run on every hook edge.

## Non-Goals

- No schema for the `untracked/` file layout; layout stays internal.
- No HTTP surface, so no OpenAPI. The owner may overrule this choice of JSON Schema.
- No consumer code in this repository.

## Tasks

### Phase 1: Facts

- [x] ✅ **Task 1.1** (answer in `FINDINGS.md`): Confirm point 4. Verified so far: a `rate_limit` StopFailure is recorded in `stop-failures.json` with `session_id`, `error`, `recorded_at` and `resolved_at`, and carries no reset time. `resets_at` lives in `usage-snapshot.json` (seven_day seen; five_hour not checked). Establish whether the reset time can be joined reliably to the stop, and for a stop without a snapshot.
- [x] ✅ **Task 1.2**: Inventory every record the command needs (session-mode transitions, stop events, stop failures, usage snapshot, usage pause) with owner module and write path.

### Phase 2: Schemas first

- [x] ✅ **Task 2.1**: Write the schemas and a test that validates recorded sample output against them (red before the command exists).
- [x] ✅ **Task 2.2**: Add `schema_version` to `mode-history --json` output without breaking its current fields.

### Phase 3: The command

- [x] ✅ **Task 3.1**: `session-state --json --session ID`, read-only, fail-open on a missing record.
- [x] ✅ **Task 3.2**: `--watch` stream, one JSON line per change.
- [x] ✅ **Task 3.3**: Measure run time per call; keep it cheap for per-hook use.

### Phase 4: Contract

- [x] ✅ **Task 4.1**: Document the contract (versioning rule, compatibility promise) and ship the schemas in the release; release note and manifest entry.
- [x] ✅ **Task 4.2**: Tell the consuming team the plan number, the schema location and the version to pin.

## Success Criteria

- [x] Point 4 is answered in writing with evidence (`FINDINGS.md`), and the consuming team has it.
- [x] Every `--json` output validates against its shipped schema in the daemon's own tests (`test_state_schemas.py`, `test_cli_mode_history.py`, `test_cli_session_state.py`).
- [x] A consumer can build against the schema without reading any file under `untracked/` (`docs/guides/SESSION_STATE_CONTRACT.md`).
- [x] The pending-release holding area has a release note for the command and the schemas (release note 056).

## Delivery & Milestones

- Plan filed and the point-4 finding recorded in the journal.
