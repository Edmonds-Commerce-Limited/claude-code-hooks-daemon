# Plan 00364: v3.63.0 release review follow-ups

**Status**: Complete
**Created**: 2026-09-09
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.63.0 release code-review gate (RELEASING.md Step 10) ran four parallel
reviewers over `git diff v3.62.1..HEAD -- src/`. Every blocking finding was
fixed before the tag. Every NON-blocking finding was left on disk in
`untracked/agent-reports/260909-review-{core,handlers,install,strategies}-opus.md`
and nowhere else. This plan is that residue, filed so that "known defect" and
"filed defect" mean the same thing.

Two further known defects join it because they surfaced in the same window:
a worktree's deployed hook wrapper relays to the MAIN repository's daemon
(found while building Plan 00363 Rule B — the acceptance harness silently
measured the wrong checkout), and the pre-existing priority-20 collision
warning logged for the `plan_done_requires_holding_area` project handler on
every daemon start.

Every item here is an ordinary defect with a contained fix. None needs a
design decision, so the plan is a worklist, grouped by the package the fix
lives in so each phase can go to one worktree agent.

## Goals

- Every non-blocking finding from the four v3.63.0 review reports is either
  fixed (with a TDD test where behaviour changes) or explicitly recorded here
  as declined with a reason.
- A worktree checkout's hook wrapper answers from THAT checkout's daemon, not
  the main repository's.
- Daemon start logs no priority-collision warning for this repository's own
  project handlers.

## Non-Goals

- Re-reviewing the release diff. The findings are taken as given.
- The `tdd_enforcement` `Path.cwd()` anchoring (handlers suggestion 2): three
  pre-existing sites, unreachable for absolute paths, retired together in a
  later plan rather than piecemeal here.
- Re-litigating the venv lock's double-`rmtree` race (core NOTE 2, second
  half): the module mirrors `scripts/install/venv.sh` deliberately; only the
  misreport is fixed here.

## Tasks

### Phase 1: core / daemon / config_optimisation (review-core NOTEs 2-7)

- [x] ✅ **Task 1.1**: `daemon/venv_lock.py` — catch `FileNotFoundError` around
  the stale-lock `stat()` (holder released between `mkdir` and `stat`) and
  retry; narrow `cmd_repair`'s `FileNotFoundError` handler so a lock-layer
  error is never printed as "'uv' not found".
- [x] ✅ **Task 1.2**: `core/release_slate.py` — `_git_lines` signals failure
  instead of returning `[]`; `collect_slate` carries it into a field that
  forces `RELEASE_SLATE_UNDETERMINED` (exit 1, not rescued by `--accept`).
- [x] ✅ **Task 1.3**: `config_optimisation/checklist.py` — extract the
  enablement predicate shared with `HandlerRegistry.register_all` (all four
  gates, including `is_disabled`; truthy `enable_tags` not list-only) and
  pin them together with a test.
- [x] ✅ **Task 1.4**: `config_optimisation/checklist.py` — wrap handler
  instantiation in `build_checklist`; a constructor failure becomes a
  visible `ChecklistItem`, not an aborted report.
- [x] ✅ **Task 1.5**: `core/relevance.py` `_LANGUAGE_MARKERS` keyed on
  `HandlerTag` members; `config_optimisation/areas.py` event sets keyed on
  the event-key constants.
- [x] ✅ **Task 1.6**: `core/acceptance_test.py` — check the
  `hook_input`/`dispatch_as_bash` pair BEFORE deriving `tool_payload`, so
  the error names what the author declared.

### Phase 2: install / plan_qa / docs_qa / skills (review-install NOTE 3 + suggestions)

- [x] ✅ **Task 2.1**: `plan_qa/gitfacts.py` — memoise `staged_changes()` on the
  instance; `row_folder_bijection._folder_findings` computes `_level` only
  when a finding is emitted. Regression test asserts one `git diff` spawn.
- [x] ✅ **Task 2.2**: `install/client_validator.py` — compose the
  `echd-capture` path from `DaemonPath`/`bin_wrapper` constants.
- [x] ✅ **Task 2.3**: `install/handler_key_audit.py` — test pins
  `_DEFAULT_PSEUDO_EVENT_BLOCKS` to the reference config; promote
  `ConfigValidator._find_similar_names` to a public helper;
  `_fill_block_defaults` raises for an unknown relocation target instead
  of emitting a triggerless enabled block.
- [x] ✅ **Task 2.4**: `plan_qa/checks/same_commit_plan_doc.py` — catch
  `(OSError, UnicodeDecodeError)` around `read_text`.
- [x] ✅ **Task 2.5**: `install/forwarder_generator.py` — shell-escape
  `daemon_down_stdout` (or assert shell-safety at the catalogue); hoist the
  `metas_by_bash_key` rebuild out of the per-call path.
- [x] ✅ **Task 2.6**: `install/transport_verify.py` — test for
  `_DAEMON_ERROR_MARKER` ahead of the "exit-code translation broken" branch
  and report the outage instead.
- [x] ✅ **Task 2.7**: `install/settings_merge.py` — write via temp file +
  `Path.replace` so the "atomic" comment is true.
- [x] ✅ **Task 2.8**: `install/templates/echd-capture` — last-resort fallback
  dir via `mktemp -d` (or ownership check) instead of a fixed name in
  `/tmp`; "Tee" comment reworded; `--help` stops at the first non-comment
  line. Tests cover `--label`, `--all`, and the exit-2 bad-argument branch.
- [x] ✅ **Task 2.9**: `skills/hooks-daemon/SKILL.md` description lists
  `optimise`; `dev-handlers.md` copy-paste block drops the literal `"$@"`.
- [x] ✅ **Task 2.10**: `docs_qa/corpus.py` `revalidate_corpus` logs an
  unstattable file at `info`, not `debug`.

### Phase 3: strategies / utils / block_report (review-strategies findings 1-7)

- [x] ✅ **Task 3.1**: `utils/secret_file_matching.py` — reject a bracket range
  wider than `_MAX_BRACKET_EXPANSIONS` before materialising it (fail
  closed, token left unexpanded). Test: a wide literal range costs
  milliseconds, not hundreds.
- [x] ✅ **Task 3.2**: `strategies/lint/kotlin_strategy.py` docstring matches
  the command (no `-script`).
- [x] ✅ **Task 3.3**: Kotlin and Rust lint output directory: one shared
  per-process unpredictable destination from `strategies/lint/common.py`,
  not a fixed `/tmp` name.
- [x] ✅ **Task 3.4**: `utils/cron_cadence.py` uses `unique_temp_path` from
  `utils/temp_names.py`; the `O_EXCL` private-mode open stays.
- [x] ✅ **Task 3.5**: `pipe_blocker` strategies — the eight dead
  `get_acceptance_tests()` methods are either aggregated by
  `PipeBlockerHandler` with `dispatch_as_bash=True` or deleted with their
  non-empty-list tests. Aggregated: all eight drive cleanly as Bash
  payloads, so none had to be deleted.
- [x] ✅ **Task 3.6**: `block_report/fingerprints.py` — one WARNING when the
  uncached rule-index branch is taken, naming the missing `ProjectContext`
  precondition.
- [x] ✅ **Task 3.7**: Drop the redundant `str()` around `scratch_path()` in
  every strategy file. Widened to the nine handler modules carrying the
  same wrapper, so a later consistency sweep does not rediscover them.

### Phase 4: handlers residue (review-handlers suggestions 1 and 3)

- [x] ✅ **Task 4.1**: `sensitive_content._staged_content_haystacks` bounds
  BEFORE materialising: ask git for `--numstat` first and skip oversized
  paths, so `MAX_STAGED_*` bound the peak, not just the scan.
- [x] ✅ **Task 4.2**: Release-notes callout in the holding area for
  `suggest_statusline` recommending `refreshInterval: 1` (tenfold subprocess
  cadence every client is advised to adopt) — if the v3.63.0 notes already
  say it, record that and close. Closed as already-said: `RELEASES/v3.63.0.md`,
  `CHANGELOG.md` and UPGRADES release-note 22 all carry it; no callout added.

### Phase 5: worktree relay and project-handler priority

- [x] ✅ **Task 5.1**: The generated relay hot path in `.claude/hooks/*` bakes
  `_rl_dir="/workspace/untracked"` absolute. A worktree inherits it and
  relays to the MAIN repo's daemon. Fixed by baking the hooks directory the
  guard was generated for and testing `${BASH_SOURCE[0]}` against it (one
  bash builtin, still no spawn) — the paths stay literals, and a copy under
  another checkout falls through to `init.sh`, which resolves its own
  socket. `HOOKS_DAEMON_RELAY_BINARY`/`HOOKS_DAEMON_EVENTS_DIR` overrides
  and the marker-based strip are unchanged; `recorded_project_root` reads
  the new literal back for the dogfooding comparison. Second half (Phase 4
  agent's finding): `scripts/setup_worktree.sh` provisions
  `.claude/hooks-daemon.env` through `install.py`'s own `create_daemon_env`,
  and the not-installed fallback names the checkout in both encoders.
- [x] ✅ **Task 5.2**: `plan_done_requires_holding_area` moves from priority
  20 to 51 (workflow band, free on PreToolUse, after `plan_qa_edit` and
  `plan_workflow`). `tests/integration/test_project_handler_priority_collisions.py`
  reproduces the controller's own collision rule against the real registry.
- [x] ✅ **Task 5.3**: `CLAUDE/Worktree.md` records the fixed relay
  behaviour, the `hooks-daemon.env` provisioning, and a probe for verifying
  which daemon answered. No override is named as a workaround.
- [x] ✅ **Task 5.4**: both audits match the exclusion on the path relative
  to the tree being scanned, and the error-hiding audit fails with a named
  workspace when it collected zero candidate files. Found by the Phase 1
  agent.
- [x] ✅ **Task 5.5**: `scripts/qa/llm_qa.py` resolves the interpreter
  through `scripts/lib/resolve_venv.sh`, falling back to the legacy path
  only when the resolver is absent, and naming both attempts on failure.

### Phase 6: closure

- [x] ✅ **Task 6.1**: Full QA 26/26; daemon restart; release-notes callouts
  in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` for every user-visible
  change; plan archived. One residue found during closure — the worktree
  setup script aborted silently before its new `hooks-daemon.env` step
  because it asked a `pip` that a uv venv does not ship — is fixed on Plan
  00365's branch and recorded in this plan's journal.

## Success Criteria

- [x] Every task above ticked, or its decline recorded in Non-Goals.
- [x] `./scripts/qa/llm_qa.py all` green.
- [x] `bin/hooks-daemon restart` logs no "priority collision" line.
- [x] A worktree's `.claude/hooks/pre-tool-use` reaches the worktree's own
  daemon with no environment override.
- [x] Every release-bound consequence is in the pending-release holding
  area: `UNRELEASED/release-notes/02-repair-names-the-real-failure.md`
  through `09-qa-audits-fail-loudly-when-they-scanned-nothing.md`.

## Delivery & Milestones

- Filed after the v3.63.0 release, from the four Step 10 review reports.
- Phase 1 merged to main at `0560b5ff`; Phase 4 at `718e0375`; Phase 3 at
  `735a4328`; Phase 2 at `befa2c8e`; Phase 5 at `b56c2621`.
- Closure QA 26/26 on `b56c2621` (21,540 tests, coverage 95.4%).
