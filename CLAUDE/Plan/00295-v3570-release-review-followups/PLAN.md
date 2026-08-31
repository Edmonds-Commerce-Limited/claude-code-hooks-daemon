# Plan 00295: v3.57.0 Release Review Follow-ups

**Status**: Not Started
**Created**: 2026-08-31
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.57.0 release ran the Step 10 Code Review Gate early, across three
parallel reviewers (Plan 00116 scope, transport/relay scope, docs-qa/layout
scope). All BLOCKING findings were fixed before the release shipped. This plan
is the mandated never-drop-a-finding ledger (RELEASING.md, Plan 00157 rule 2):
every NON-BLOCKING finding is tracked here with file:line and remediation, to
be fixed after the release closes the loop.

Severity below is the reviewers' own calibration. None is a release blocker;
several are fail-open correctness gaps worth fixing promptly (marked HIGH).

## Goals

- Every finding below is either fixed (with TDD where it touches behaviour) or
  explicitly rejected with a recorded reason.

## Non-Goals

- No new features; no re-litigating the fixed BLOCKING findings.

## Tasks

### Phase 1: HIGH — fail-open correctness gaps

- [ ] ⬜ **Task 1.1**: `matches_skip_path` is still a bare substring test while
  a new comment claims slash-bounded containment
  (`strategies/lint/common.py:19-29`, `validate_eslint_on_write.py:88-94`).
  `src/rebuild/x.py`, `src/myvenv/x.py`, `app/prebuild/y.ts` are all wrongly
  skipped (fail-open lint/ESLint). Bound the left side (match on path
  segments) or correct the comment; prefer fixing the matcher.
- [ ] ⬜ **Task 1.2**: docs_qa checks call `relative_to` on the RAW path while
  scope decisions use the RESOLVED path (`pointer_resolves.py:119`,
  `rules_file_shape.py:240`, `quote_drift.py:138` — no scope gate at all,
  `module_doc_budget.py:225`, `duplicate_block.py:118`, `corpus.py:478`). A
  symlinked file_path raises ValueError inside handle(), which strict-mode
  chain handling turns into a DENY with a stack trace. Resolve once in the
  handler and pass the relative path on CheckContext.
- [ ] ⬜ **Task 1.3**: `layout.source_dirs`/`test_dirs` documented as taking
  paths/globs but only bare segments ever match
  (`config/models.py` LayoutConfig descriptions vs
  `core/project_layout.py:93-95`; `backend/src` can never match). Implement
  path/glob matching or fix the field docs; pick one and pin with tests.
- [ ] ⬜ **Task 1.4**: transport_verify kills nothing on probe timeout
  (`install/transport_verify.py:139-148`) — orphans a forwarder/relay per
  timed-out probe. Add `proc.kill()` + second `communicate()`.
- [ ] ⬜ **Task 1.5**: `probe_stop_hard_block` (`transport_verify.py:231`)
  makes a healthy `transport on` auto-revert for any client that disables the
  stop handler. Gate the probe on the handler being enabled, or treat a
  non-blocking Stop as a skip.
- [ ] ⬜ **Task 1.6**: strip the relay guard block in
  `deploy_hook_scripts` (bash, `scripts/install/hooks_deploy.sh`) BEFORE the
  Python regeneration step, so the F1 guarantee holds without a venv or a
  surviving generator; 25 tracked forwarders at HEAD carry a committed guard
  with `/workspace` paths. Fix the stale claim at `hooks_deploy.sh:456-458`
  and flip `test_no_venv_python_deploy_is_byte_identical`
  (`tests/integration/test_hooks_deploy_relay_guard.py:77-89`) to assert the
  stripped outcome.

### Phase 2: MEDIUM — behaviour and API hygiene

- [ ] ⬜ **Task 2.1**: injected `docs_qa_sweep` guidance says
  source-tree-markdown "stays silent when no `layout:` dirs are declared"
  (`handlers/session_start/docs_qa_sweep.py:127-128`) but the
  COMMON_TEST_DIRECTORIES fallback makes it always-on for test dirs. Fix the
  injected text to match the check's (accurate) module docstring.
- [ ] ⬜ **Task 2.2**: `tdd_enforcement` facade adoption widened test-path
  matching (built-in `('tests','test','__tests__','spec')` short-circuits
  before `strategy.is_test_file()`, `tdd_enforcement.py:288-297`) — the
  comment implies a byte-identical no-op. Decide the intended semantics and
  pin with a test + honest comment.
- [ ] ⬜ **Task 2.3**: relay/build.sh:16 defaults RUSTC to
  `$HOME/.cargo/bin/rustc` while `check_musl_toolchain` prefers
  `shutil.which("rustc")` — pass the resolved RUSTC into the env from
  `deploy_relay_from_build` like RELAY_TARGET already is.
- [ ] ⬜ **Task 2.4**: nothing writes `relay/SHA256SUMS.released`, so
  transport-probe's digest row permanently reads "unknown (no manifest)"
  (`transport_probe.py:134,189`); `deploy_relay_from_download` holds the
  verified digest (`relay_deploy.py:285`) — record it alongside the `.route`
  marker.
- [ ] ⬜ **Task 2.5**: init.sh:906 builds the nc rung's socket path ignoring
  `HOOKS_DAEMON_EVENTS_DIR` and the AF_UNIX-overflow fallback — on deep
  client layouts the nc rung silently never engages. Honour both, matching
  daemon and relay guard.
- [ ] ⬜ **Task 2.6**: daemon/server.py events-dir handling: log rmtree
  failures instead of `ignore_errors=True`, and refuse to bind when
  events_dir is a pre-existing symlink (predictable /tmp fallback path can be
  redirected by a pre-planted symlink).
- [ ] ⬜ **Task 2.7**: block-report/promotion config duplication —
  `block_report/report.py:49-50` re-declares min_blocks/min_sessions defaults
  that PromotionConfig owns; make the parameters required.
- [ ] ⬜ **Task 2.8**: `claude_md_injector.py` promoted-handler-without-prose
  fallback and the STOP_GOAL_LEDGER dead-verbose duplication
  (`auto_continue_stop.py:120-132` vs `_GOAL_LEDGER_CHALLENGE_TEMPLATE:191`;
  docstrings at :577/:925 still say five rules where six exist) — single
  prose source per message; correct the counts. (The lost-rules half of the
  injector issue was fixed pre-release; verify and close.)
- [ ] ⬜ **Task 2.9**: artifact_publish_blocker `source_disable` hygiene:
  `matches()` performs a filesystem write; `_source_disable_checked` set
  before the attempt makes a transient failure permanent until restart; temp
  file leaks if copymode/replace fails; `getattr(self, "_source_disable", False)` guards an attribute `__init__` always sets.
- [ ] ⬜ **Task 2.10**: `core/project_layout.py:43` imports the vendored-dir
  constant via `docs_qa.corpus`, pulling docs_qa (and transitively plan_qa)
  into core import time — import from `constants.layout` directly.
- [ ] ⬜ **Task 2.11**: tool_disable_advisor re-loads config up to three times
  per event (`tool_disable_advisor.py:60-106`) — use the already-loaded
  config; add the missing try/except symmetry in
  `_blocker_source_disable_on`.

### Phase 3: LOW — cleanup

- [ ] ⬜ **Task 3.1**: `_read_event_payload` chunk_size 65536 unnamed
  (daemon/server.py); `_GUARD_MARKER` dead in transport_verify.py:70;
  `_MESSAGE_FLAG_PREFIXES[0]` never read in the (now-shared) commit-gate
  parser and attached `-m"msg"` form unhandled if the pre-release fix did not
  cover it; registry `doc_attrs` one-iteration setattr loop.
- [ ] ⬜ **Task 3.2**: tool_report/analyser.py MAX_LINE_BYTES compares
  characters not bytes and bounds parse cost, not memory — align code and
  docstring.
- [ ] ⬜ **Task 3.3**: docs_qa sweep does three full-repo traversals
  (corpus rglobs + two os.walks) — share one walk between
  module_doc_budget and source_tree_markdown.
- [ ] ⬜ **Task 3.4**: explain-rule UX: `_EXPLAIN_UNKNOWN_HANDLER_HINT` points
  to `explain-rule --list`, which omits rules-less advisory handlers — add a
  `--list` to explain-handler.
- [ ] ⬜ **Task 3.5**: rule_explain/lookup.py imports private
  `_to_snake_case` from handlers.registry — give the mapping a public name.
- [ ] ⬜ **Task 3.6**: stale comment in `constants/handlers.py`: DOCS_QA_EDIT
  says "No commit-gate sibling ships yet" directly above
  DOCS_QA_COMMIT_GATE's definition.
- [ ] ⬜ **Task 3.7**: DisclosureTracker.\_state has no eviction (finished
  sub-agent transcript paths accumulate for the daemon's lifetime — a few KB
  over weeks). Document the bound in the module note or add cheap eviction.
- [ ] ⬜ **Task 3.8**: `.claude/ccy/claude-supervise.py` pre-existing Pyright
  `int | None` fd-argument errors around lines 4498-4631 (surfaced when the
  release bump touched the file; not release-introduced).

## Success Criteria

- [ ] Every task above fixed (TDD where behavioural) or rejected with a
  recorded reason in this plan's JOURNAL/.
- [ ] Full QA green after each phase.

## Delivery & Milestones

- Filed during the v3.57.0 release from the Step 10 early-review reports.
