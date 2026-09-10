---
title: Plan 00373 Phase 3 — merge_qa_report build report
date: 2026-09-10
agent: python-developer (sonnet)
---

# Plan 00373 Phase 3: `merge_qa_report` handler

## What was built

A new PostToolUse handler `MergeQaReportHandler`
(`src/claude_code_hooks_daemon/handlers/post_tool_use/merge_qa_report.py`)
that closes the merge bypass named in Plan 00373: `git merge`/`git pull`/
`git rebase` create a commit without invoking `git commit`, so
`plan_qa_commit_gate`, `docs_qa_commit_gate` and `staged_lint_gate` never see
it.

- `matches()`: Bash tool, command shape recognised via the same
  evasion-resistant idiom `staged_lint_gate._is_git_commit_command` uses
  (`normalise_line_continuations`, `split_unquoted`, `ENV_PREFIX` +
  `GIT_INVOCATION` regex over `merge|pull|rebase`), plus a cheap policy gate
  (`_any_corpus_active`) so no git subprocess runs when neither sweep is
  active.
- `handle()`: reads `git diff --name-only ORIG_HEAD HEAD` (`_changed_paths`).
  A non-zero returncode or an empty diff (absent `ORIG_HEAD`, `ORIG_HEAD == HEAD`, or git failing) returns silently — a single frozenset truthiness
  check covers all three per the module docstring.
- Runs the plan-QA and docs-QA **SWEEP**-stage catalogues in process
  (`plan_qa.context.sweep_context` / `docs_qa.context.sweep_context`,
  mirroring `plan_qa_sweep.py`/`docs_qa_sweep.py` exactly, including building
  the docs corpus via `build_and_save_corpus` at the same untracked index
  path).
- Reports only ATTRIBUTABLE findings via `_plan_finding_attributable`/
  `_docs_finding_attributable`: a finding with a path is attributable when a
  changed path equals it or is nested under it; a finding with no path
  (tree-level, e.g. `no-new-collisions`/`stats-recount`) is attributable when
  the operation changed anything in that corpus (under the plan dir; any
  `.md` file for docs). Plan-QA `Finding.path` is non-uniform (bare folder
  name vs project-relative `rel_path`) — handled by trying both the raw and
  plan-dir-rerooted form, the same two-shape precedent
  `plan_qa.runner._excluded` already documents, rather than inventing a
  second convention.
- Report reuses `plan_qa.report.format_advisory`/`docs_qa.report.format_advisory`
  verbatim (check id, path, message, remediation — no re-implementation),
  behind a `MERGE QA REPORT` header naming the defect and each corpus's
  `daemon_cli_command("plan-qa"/"docs-qa", "--sweep")` re-check hint.
- `get_claude_md()`/`get_acceptance_tests()` implemented per the ABC
  contract; the acceptance test uses `harness_cannot_produce` (a real
  `ORIG_HEAD` needs a real merge) and points at the unit test file.

## Wiring

- `src/claude_code_hooks_daemon/constants/handlers.py` — `HandlerID.MERGE_QA_REPORT`
  (`class_name=MergeQaReportHandler`, `config_key=merge_qa_report`,
  `display_name=merge-qa-report`), placed after `MODEL_DOWNGRADE_RECORDER`.
- `src/claude_code_hooks_daemon/constants/priority.py` — `Priority.MERGE_QA_REPORT = 34`
  (PostToolUse advisory band, next free slot after `MODEL_DOWNGRADE_RECORDER = 33`; shares 34 with the PreToolUse `verification_result_gate` the same
  way `staged_lint_gate`/`plan_qa_commit_gate` already share 43/44 — disjoint
  events, comment explains why it never collides).
- `src/claude_code_hooks_daemon/handlers/post_tool_use/__init__.py` — export added.
- `src/claude_code_hooks_daemon/daemon/init_config.py` — example config
  comment line added to the generated `post_tool_use:` block.
- `.claude/hooks-daemon.yaml` and `.claude/hooks-daemon.yaml.example` — both
  needed a `merge_qa_report:` entry (`enabled: true, priority: 34`); found
  via the four failing integration/unit tests below, not by inspection alone.
- `tests/integration/test_claude_md_guidance_coverage.py` — added
  `MergeQaReportHandler` to `_EARNS_GUIDANCE` with a T3 reason (mirrors
  `PlanQaSweepHandler`/`DocsQaSweepHandler`'s "drift findings are worked
  through across the session" framing, plus the attribution-rule context the
  fire-time report alone would not teach).

## What the full-repo test run caught that inspection alone did not

After wiring the handler and its own test file, `./scripts/qa/llm_qa.py tests` (run twice, ~22k tests each run) surfaced four failures purely from
the wiring gap, all fixed:

1. `test_claude_md_guidance_coverage.py::test_no_handler_is_unclassified` —
   every handler needs a recorded `get_claude_md()` verdict.
2. `test_dogfooding_config.py::test_all_production_handlers_are_enabled` —
   this repo dogfoods its own handlers; `merge_qa_report` had to be enabled
   in `.claude/hooks-daemon.yaml`.
3. `test_example_config.py::test_example_config_includes_all_library_handlers`
   — `.claude/hooks-daemon.yaml.example` must list every library handler.
4. `test_claude_md_guidance_coverage.py::test_every_earning_handler_has_a_section_in_claude_md`
   — the injected `<hooksdaemon>` block only regenerates on daemon restart;
   needed a second `bin/hooks-daemon restart` after enabling the handler in
   the dogfood config.

(`test_reference_config_completeness.py` failed transiently on the first run
and was fixed by the example-config addition above — no separate change
needed.)

A **fifth, unrelated** failure appeared on the first full run
(`tests/unit/qa/test_audit_error_hiding.py::TestRealRepoSelfScan::test_repo_is_clean_under_widened_scope`,
flagging `scripts/qa/run_corpus_qa.py:182`) from a concurrent agent's
in-flight edits to `scripts/qa/run_corpus_qa.py` /
`tests/unit/daemon/test_cli_global_project_root.py` /
`tests/unit/daemon/test_cli_plan_qa.py` in the same shared working tree
(confirmed via `git status` before/after — none of those three files are
touched by this change). It was gone by the final full run once that
concurrent `llm_qa.py all` process finished; not something this task fixed
or needs to fix.

## Verification performed

- `tests/unit/handlers/post_tool_use/test_merge_qa_report.py` (29 tests, all
  written before the handler — confirmed RED via
  `ModuleNotFoundError` before implementation, GREEN after): initialisation,
  `matches()` evasion-resistance (global options, `env` prefix, line
  continuation, chained commands, non-merge commands), silence on absent/
  equal `ORIG_HEAD`, foreign-repo exemption, plan-QA attribution (replays the
  Plan 00373 scenario — a merge resurrecting an unindexed
  `00372-worktree-reap-two-defects`-shaped folder — and separately proves an
  UNRELATED pre-existing drift stays silent), docs-QA attribution (a merged
  dead link), missing-plan-dir non-crash, `get_claude_md()`/acceptance-test
  presence.
- `ruff check` / `black --check` / targeted and repo-wide `pyright` (0
  errors, 1581 files) on every touched file — all clean.
- `./scripts/qa/llm_qa.py lint format pyright` — 3/3 PASSED.
- `./scripts/qa/llm_qa.py tests` (final run) — **22225 passed, 0 failed, 6
  skipped, 95.3% coverage**.
- `bin/hooks-daemon restart` (twice — second time after the dogfood-config
  enable, so the injected CLAUDE.md guidance would regenerate) — both
  succeeded; `bin/hooks-daemon handlers` shows `[-] 34 merge-qa-report`
  under `PostToolUse:`.

## Note: two auto-commits happened, not made by me

`bin/hooks-daemon restart`'s `ClaudeMdInjector` auto-commits `CLAUDE.md`
whenever the regenerated `<hooksdaemon>` block leaves it dirty (documented,
daemon-owned behaviour, not a `git commit` I ran). Two such commits landed
from the two restarts this task required:
`Auto: hooks daemon regenerated CLAUDE.md handler guidance` (x2). No other
commits were made; everything else described above is left in the working
tree, per instructions.

## Files created

- `src/claude_code_hooks_daemon/handlers/post_tool_use/merge_qa_report.py`
- `tests/unit/handlers/post_tool_use/test_merge_qa_report.py`

## Files modified

- `src/claude_code_hooks_daemon/constants/handlers.py`
- `src/claude_code_hooks_daemon/constants/priority.py`
- `src/claude_code_hooks_daemon/daemon/init_config.py`
- `src/claude_code_hooks_daemon/handlers/post_tool_use/__init__.py`
- `.claude/hooks-daemon.yaml`
- `.claude/hooks-daemon.yaml.example`
- `tests/integration/test_claude_md_guidance_coverage.py`
- `CLAUDE.md` (daemon auto-commit, see note above — not hand-edited)
