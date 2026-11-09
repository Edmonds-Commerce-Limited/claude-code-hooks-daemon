# Plan 00577: forwarder stubs shellcheck clean

**Status**: Complete
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

- [x] ✅ **Task 1.1**: RED test: generate the stubs (every event kind) and run `shellcheck --severity=warning`. It fails
  on SC2034
- [x] ✅ **Task 1.2**: GREEN: the generator emits `export HOOKS_DAEMON_RELAY_UNUSED=...`; regenerate this repository's
  `.claude/hooks/*`
- [x] ✅ **Task 1.3**: release-notes callout

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: targeted QA, merge, verify CI, close #163

## Success Criteria

- [x] The new test failed before the fix (quoted in the sub-agent report) and passes after it
- [x] `shellcheck --severity=warning` over the 31 regular stub files in `.claude/hooks/` (not the `handlers/`
  directory) exits 0 in this repository ([fact-check](subagent-reports/261109-fact-check-plan-00577.md): 11 verified,
  0 refuted)
- [x] The existing forwarder generator and relay tests pass unchanged
- [x] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
  (`015-forwarder-stubs-shellcheck-clean.md`)
- [x] Merged to main with green CI; #163 closed

## Delivery & Milestones

- Fix: `43250b5fb`, fast-forwarded onto main (RED: 27 stubs failed with SC2034; targeted QA 42/42 with the generator and
  4 stubs too-broad, so covered by CI's whole-suite fallback); CI run 42627973690 `success`; #163 closed
- [Implementer report](subagent-reports/261109-issue-163-implementer-sonnet.md)
