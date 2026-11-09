# Plan 00577: forwarder stubs shellcheck clean

**Status**: In Progress
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #163

## Overview

Every generated `.claude/hooks/*` forwarder stub sets `HOOKS_DAEMON_RELAY_UNUSED="$_rl_bin"` in its relay hot path.
That code comes from `src/claude_code_hooks_daemon/install/forwarder_generator.py`. `shellcheck --severity=warning`
reports SC2034 (appears unused) on the line, once per stub, so a client that lints its shell scripts fails after every
upgrade. The stubs are regenerated on every upgrade, so the client cannot fix this locally.

The variable is not dead. The stub then sources `.claude/init.sh`, which reads `HOOKS_DAEMON_RELAY_UNUSED` and unsets
it at once (init.sh ~127-128). shellcheck cannot follow the `source`. The fix emits the assignment with `export`. That
is the form shellcheck treats as used externally, so no suppression directive is needed. It changes no behaviour:
init.sh unsets the variable before the stub spawns the daemon or any transport.

The repository's own `shell_check` QA scans only `*.sh` / `*.bash` (`scripts/qa/run_shell_check.sh`), so the
extensionless stubs were never linted. That is why this shipped. The regression test therefore shellchecks every
generated stub, which covers the class (any future warning in generated stub text), not only this line.

## Goals

- Every forwarder stub the generator emits passes `shellcheck --severity=warning`.
- A test generates the stubs and shellchecks them, so a new warning in generated text fails CI.

## Non-Goals

- No change to the relay hot path's behaviour or to `init.sh`'s handling of the variable.
- No change to `run_shell_check.sh`'s file selection. The new test covers the generated stubs, and the scope of the QA
  scanner is a separate decision.
- Plan 00421's forwarder interpolation work is untouched.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED test: generate the stubs (every event kind) and run `shellcheck --severity=warning`. It fails
  on SC2034
- [ ] ⬜ **Task 1.2**: GREEN: the generator emits `export HOOKS_DAEMON_RELAY_UNUSED=...`; regenerate this repository's
  `.claude/hooks/*`
- [ ] ⬜ **Task 1.3**: release-notes callout

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: targeted QA, merge, verify CI, close #163

## Success Criteria

- [ ] The new test failed before the fix (quoted in the sub-agent report) and passes after it
- [ ] `shellcheck --severity=warning .claude/hooks/*` (the stubs) exits 0 in this repository
- [ ] The existing forwarder generator and relay tests pass unchanged
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
- [ ] Merged to main with green CI; #163 closed

## Delivery & Milestones

- (pending)
