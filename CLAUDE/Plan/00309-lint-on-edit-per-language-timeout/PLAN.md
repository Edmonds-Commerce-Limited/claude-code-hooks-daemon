# Plan 00309: lint on edit per language timeout

**Status**: Not Started
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner field report (php-qa-ci client project): `lint_on_edit`'s extended
lint runs under the hardcoded `Timeout.LINT_CHECK` of 15 seconds. A
`php-qa-ci qa -t phpstan -p {file}` extended command takes ~5s warm but
exceeds 15s when cold or lock-contended — and on timeout the check
**silently allows** instead of running, so exactly the runs most likely to
carry stale-cache defects are the ones that skip linting with no signal.

Make the extended-lint timeout configurable per language, e.g.
`handlers.post_tool_use.lint_on_edit.options.timeouts.PHP: 30`, with the
current 15s as the fallback for unconfigured languages. Timeout behaviour
(allow) is unchanged — this plan widens the budget where a project knows
its toolchain is slower, it does not change fail-open semantics.

## Goals

- A project can raise (or lower) the extended-lint timeout for a specific
  language via handler options, without affecting other languages.
- Unconfigured languages keep today's `Timeout.LINT_CHECK` default; zero
  behaviour change for projects that set nothing.
- A timeout that fires is visible (at minimum in daemon logs / advisory
  text), so "silently allows" stops being fully silent.

## Non-Goals

- Changing the fail-open (allow-on-timeout) semantics — a slow linter must
  never hard-block edits by default.
- Per-command or per-file timeout overrides (per-language is the unit).
- Touching `validate_eslint_on_write`'s separate timeout handling
  (R-ESLINT-TIMEOUT denies by design; different handler, different
  contract).

## Tasks

### Phase 1: TDD the configurable timeout

- [x] ✅ **Task 1.1**: Pin current behaviour: unit test that the extended
  lint command runs under `Timeout.LINT_CHECK` when no option is set, and
  that a timeout results in allow.
- [x] ✅ **Task 1.2**: Add `options.timeouts.<LANGUAGE>: <seconds>` to
  lint_on_edit (language keys matching the handler's language registry
  names, case-insensitive; validated: positive number, unknown-language
  keys warn rather than crash). Resolve per file language at check time;
  fall back to `Timeout.LINT_CHECK`. TDD: PHP configured to 30 uses 30,
  Python unconfigured stays 15.
- [x] ✅ **Task 1.3**: Surface the timeout when it fires: log line +
  advisory text naming the language, the budget used, and the config key
  that raises it — so a silent allow becomes a visible, actionable one.

### Phase 2: Config plumbing and docs

- [x] ✅ **Task 2.1**: Config template + `.claude/hooks-daemon.yaml.example`
  entry, options documentation, explain-handler text (via `get_claude_md`),
  and CLAUDE.md-guidance regeneration where applicable.
- [x] ✅ **Task 2.2**: Verify against the field report shape: a fake slow
  extended command configured at 30s for PHP completes where the 15s
  default would have timed out (integration-level test with an injectable
  clock/command, not a real 16s sleep in the suite).

## Success Criteria

- [ ] `handlers.post_tool_use.lint_on_edit.options.timeouts.PHP: 30` gives
  PHP extended lints a 30s budget while other languages keep 15s, pinned
  by tests; full QA green; daemon restart verified.
- [ ] A fired timeout names itself and the config key in its output.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00309-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
