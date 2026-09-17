# Plan 00430 — implementation report

## Verified defect

Confirmed the brief's diagnosis by reading the code directly (not assumed):

- `cmd_block_report` (`src/claude_code_hooks_daemon/daemon/cli.py`) called
  `analyse_transcripts` without ever touching `ProjectContext`.
- Five handler `__init__` methods read `ProjectContext.project_root()` (or a
  helper that does): `ValidateEslintOnWriteHandler`,
  `MarkdownOrganizationHandler`, `NpmCommandHandler`,
  `PlanNumberHelperHandler`, `RemoteDocsProvenanceHandler`.
- `discover_handler_rules()` → `collect_handler_rules()` (in
  `rule_explain/lookup.py`) constructs every handler class to read its
  `get_rules()`; a handler whose `__init__` raises is logged via
  `logger.exception("Failed to inspect handler %s for rule lookup", ...)`
  and skipped, so its rule IDs never enter the attribution index.
- `_init_project_context_for_explain` (renamed to
  `_init_project_context_for_cli` below) already existed and already solved
  this for five other commands (`explain-rule`, `explain-handler`,
  `status-line --explain`, `session-actions`, the routine-qa project-root
  resolver) — `cmd_block_report` was simply not one of its callers.

## RED test (Task 1.1) — failure quoted before the fix

Added `TestCmdBlockReportAttributesProjectContextReadingHandlers` in
`tests/unit/daemon/test_cli_block_report.py`, driving `cmd_block_report`
against a real (locally-initialisable) git project with one transcript
containing a `BLOCKED [R-MARKDOWN-WRONG-LOCATION]: ...` deny — the exact
render shape `RuleFormatter` produces for `MarkdownOrganizationHandler`.

Before the fix, `pytest tests/unit/daemon/test_cli_block_report.py -q`
produced (verbatim, truncated to the first and the decisive lines):

```
ERROR   claude_code_hooks_daemon.rule_explain.lookup:lookup.py:90 Failed to inspect handler ValidateEslintOnWriteHandler for rule lookup
Traceback (most recent call last):
  File ".../rule_explain/lookup.py", line 86, in collect_handler_rules
    instance = handler_class()
  File ".../handlers/post_tool_use/validate_eslint_on_write.py", line 181, in __init__
    self.workspace_root = self._pinned_workspace_root or ProjectContext.project_root()
  File ".../core/project_context.py", line 290, in project_root
    cls._ensure_initialized()
  File ".../core/project_context.py", line 275, in _ensure_initialized
    raise RuntimeError(
RuntimeError: ProjectContext not initialized. Call ProjectContext.initialize(config_path) during daemon startup.
... (same shape for MarkdownOrganizationHandler, NpmCommandHandler, PlanNumberHelperHandler, RemoteDocsProvenanceHandler) ...

FAILED tests/unit/daemon/test_cli_block_report.py::TestCmdBlockReportAttributesProjectContextReadingHandlers::test_attributes_a_deny_from_a_projectcontext_reading_handler
  - AssertionError: markdown_organization missing from attributed rows: dict_ke...
FAILED tests/unit/daemon/test_cli_block_report.py::TestCmdBlockReportDoesNotPoisonTheRuleIndexAcrossRuns::test_a_degraded_run_does_not_poison_a_later_correct_run
  - AssertionError: assert None == 1
2 failed, 6 passed in 1.04s
```

This exactly reproduces the plan's description at unit-test scale — five
`Failed to inspect handler` tracebacks per attribution attempt, and the
markdown_organization deny landing in `unattributed_denies` instead of being
attributed.

## Fix (Task 1.2)

`cmd_block_report` now calls `_init_project_context_for_cli(args)`
immediately after resolving `project_root`, before `analyse_transcripts`
runs — reusing the existing helper rather than writing a second
initialisation path, as instructed.

**Renamed** `_init_project_context_for_explain` → `_init_project_context_for_cli`
and `_find_config_file_for_explain` → `_find_config_file_for_cli` (and
updated all six call sites: `cmd_explain_rule`, `cmd_explain_handler`,
`cmd_status_line_explained`, `cmd_session_actions`,
`_run_routine_project_root`, and the new `cmd_block_report` call) — the name
no longer fit once a sixth, non-"explain" caller existed. No test in the
suite referenced the private names directly, so this was a clean rename with
no other call sites to chase.

Docstrings on both renamed functions were updated to describe the widened
audience rather than "rule/handler enumeration" only.

## Task 1.3 — no-config-file behaviour, pinned and tested

`_init_project_context_for_cli` already degrades quietly when
`_find_config_file_for_cli` returns `None` (no `.claude/hooks-daemon.yaml`
discoverable) or when `ProjectContext.initialize` raises `ValueError`/
`RuntimeError` (e.g. not a git repository, no `origin` remote) — it prints a
`WARNING:` to stderr and returns, leaving `ProjectContext` uninitialized.
`cmd_block_report` was not changed in this respect: it goes straight on to
`analyse_transcripts` exactly as before, so a project with no discoverable
config still produces a report (degraded attribution, as today), never an
error.

Covered by `TestCmdBlockReportNoConfigFileStillReports`: a project directory
with no `.claude/hooks-daemon.yaml` and no git repo still returns exit code
0, prints the "0 transcript" report, and leaves
`ProjectContext.is_initialized()` false. This is the existing 5-test
`TestCmdBlockReport` class's own fixture shape (no git, no full config) —
so those five pre-existing tests were also, incidentally, already exercising
this path once the fix landed; they continued to pass unchanged.

## Task 1.4 — the partial-index guard, asserted not read

`_rule_id_to_config_key()` in `block_report/fingerprints.py` already guards
against memoising a partial index (built while `ProjectContext` is
uninitialised): it only calls the `@lru_cache`-wrapped `_cached_rule_index()`
once `ProjectContext.is_initialized()` is true, and serves every
uninitialised call uncached via `_build_rule_index()` directly. This
invariant is already asserted (not merely commented) by two existing tests
in `tests/unit/block_report/test_fingerprints.py`:
`TestRuleIndexIsNotPoisonedByAnEarlyCall::test_a_lookup_before_initialisation_is_not_memoised`
and `TestThePartialIndexAnnouncesItself` — both pass unchanged, since this
plan does not touch `fingerprints.py`.

To close the gap the plan specifically flags — proving this holds
end-to-end through the newly-fixed `cmd_block_report`, not just at the
`fingerprints` unit level — I added
`TestCmdBlockReportDoesNotPoisonTheRuleIndexAcrossRuns`: it runs
`cmd_block_report` once against a project with no discoverable config (the
degraded, uncached path fires and is discarded), then again against a real
git project in the *same process*, and asserts the second run still
attributes `markdown_organization` correctly with zero unattributed denies.
This was one of the two RED tests above (fails before the fix, for a
different reason than the first: before the fix neither run initialises
`ProjectContext` at all, so the second run's attribution assertion fails
identically). It is not vacuous: an `lru_cache` mistakenly wrapping
`_rule_id_to_config_key` itself (rather than the inner
`_cached_rule_index`) would make this test fail again by serving the first
run's partial dict on the second call.

## Task 2.1 — full QA

One contention-related false alarm along the way, resolved and reported here
for the record: my first `llm_qa.py all` run reported
`10 errored`/`failed` in `tests/acceptance/*` (playbook harness, stop-hook
hard-block, tool-use-error recovery). A stray background `pytest` process
from an earlier `&`-backgrounded shell command (which does not persist
across tool calls in this harness, so `wait` in the next call had nothing to
wait on) was still running concurrently against the same tree and
`coverage.json`. Once that process finished, a clean re-run of
`llm_qa.py tests` reported `25086 passed, 0 failed`, and a subsequent clean
`llm_qa.py all` reported:

```
QA: 35/35 PASSED
QA_EXIT=0
```

`format` had auto-fixed one file (`black` reformatted
`tests/unit/daemon/test_cli_block_report.py`) on the way to that result —
not a manual intervention, just the formatter's own auto-fix step, and the
final run shows 0 format violations.

Daemon restarted after the change (`./bin/hooks-daemon restart`) — new PID
confirmed, socket path confirmed.

## Task 2.2 — release note

Added `CLAUDE/UPGRADES/UNRELEASED/release-notes/08-block-report-now-initialises-projectcontext.md`
(audience: operators), following the existing holding-area schema (`# Callout:`
title, `**Plan**: 00430`, `**Audience**: operators`, prose body).

## Files touched

- `src/claude_code_hooks_daemon/daemon/cli.py` — the fix, plus the rename
  (`_init_project_context_for_explain` → `_init_project_context_for_cli`,
  `_find_config_file_for_explain` → `_find_config_file_for_cli`) and updated
  docstrings.
- `tests/unit/daemon/test_cli_block_report.py` — new `git_project` fixture
  and three new test classes covering Tasks 1.1, 1.3 and 1.4.
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/08-block-report-now-initialises-projectcontext.md`
  — new release-note callout.
- `CLAUDE/Plan/00430-block-report-attributes-before-project-context-init/PLAN.md`
  — task checkboxes updated.

## No disagreement with the brief

The brief's mechanism (reuse the existing helper, rename it, pin the
no-config behaviour, assert the memoisation guard) matched what the code
actually needed; I found nothing to push back on. The one thing worth
flagging for the closing GitHub comment: the `housekeeping.md` skill step 9
claim ("not a second surface — same command") was verified true by
inspection but not re-run end-to-end here, since it invokes this exact
`cmd_block_report` function.
