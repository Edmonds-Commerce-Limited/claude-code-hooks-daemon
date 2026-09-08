# Plan 00330 Phase 3 — delivery report (fable)

Branch `agent-a073f504443a0bb26-67bdb7aa`, three commits, nothing pushed or
merged.

## What shipped

| Commit     | Content                                                                                                                                                                                                                                                                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `59b11a0a` | `src/claude_code_hooks_daemon/daemon/housekeeping.py` (pure step list, `plan_pass`, `render_procedure`), `cmd_housekeeping` + `housekeeping` argparse verb in `daemon/cli.py`, `idle_housekeeping_advisor.py` deriving its audit list from `report_only_steps()`; tests `test_housekeeping.py`, `test_cli_housekeeping.py`, one new advisor test |
| `f458057e` | SKILL.md trim to 8 routed arms + "Capabilities (CLI verbs)" section; new `housekeeping.md`; `health.md`/`regen-docs.md`/`rule-explain.md`/`check.md`/`dev-handlers.md` rewritten to the CLI form; `SkillCommand.RULE_EXPLAIN` → `CliCommand.EXPLAIN_RULE`, rule pointer prints `bin/hooks-daemon explain-rule`; deployed tree synced             |
| (this)     | PLAN.md ticks for 3.1–3.3 and two Success Criteria, journal day-file, release-notes callout `29-…`, this report                                                                                                                                                                                                                                  |

## Design as delivered

- **Step list (Task 3.1)**: 20 steps. Report-only, in order: `plan-qa --sweep`,
  `docs-qa --sweep`, `check-worktree-seed`, `audit-handler-keys`,
  `check-permissions`, `disk-usage`, `remote-docs check`, `verdicts`,
  `block-report`, `harvest-background`, `worktree-reap` (no `--reap`),
  `skill-scan`. Mutating, in order: `format-markdown .`, `regenerate-docs`,
  `reconcile-settings`, `remote-docs refresh`, `prune-venvs`,
  `check-permissions --fix`, `worktree-reap --reap`, `optimise` (last;
  `restarts_daemon=True`).
- **Disposition (Task 3.2)**: `plan_pass(apply)` marks every
  `confirmation_required` step HELD unless named on `--apply`; only
  `format-markdown` and `regenerate-docs` are mutating-but-unconfirmed.
  Unknown `--apply` names raise `UnknownStepError` listing the valid names
  (CLI exit 2).
- **Orchestration (Task 3.3)**: the CLI verb prints a three-phase procedure —
  Phase A report-only steps dispatched in parallel, one sub-agent each;
  Phase B mutating steps sequential; Phase C a single collation table. Each
  sub-agent's reply is capped at five lines (step, verdict, findings count,
  report path, what it CHANGED) and must not paste command output. The idle
  advisory (Decision 7) reuses the same list and directs the session at
  `bin/hooks-daemon housekeeping`, never `--apply`.
- **`optimise`** is a step with `cli_argv=()` and `via_skill="optimise"`,
  rendered as `Skill tool: skill=hooks-daemon, args=optimise`. The checklist,
  `optimise-invoke.sh` and the Handler base class were not touched.

## Tests and QA

- New: 41 tests in `tests/unit/daemon/test_housekeeping.py` (ordering,
  disposition, every CLI step's verb accepted by the real argparse, plan and
  render), 7 in `tests/unit/daemon/test_cli_housekeeping.py`, 1 in the
  advisor tests, `tests/unit/constants/test_skill_commands.py` rewritten.
- Updated: `tests/unit/daemon/test_cli_config_validate.py` (routed-verb
  guard now asserts `restart`/`bug-report`/`housekeeping`; the
  `validate-config` test asserts the skill documents both spellings and the
  parser accepts the alias).
- `tests/unit` + `tests/integration`: 20302 passed, 17 skipped, 1 xfailed
  with `tests/integration/test_forwarder_socket_stdin.py` deselected — those
  7 cases fail in this worktree on `resolve_venv: no usable venv found`
  because the venv here is `.venv`, not `untracked/venv-*`; environmental,
  not touched by this work. Skill-surface suites (`tests/unit/scripts`,
  `test_deployed_skill_trees.py`, `test_cli_config_validate.py`,
  `tests/unit/docs_qa`, guidance coverage) pass.
- `ruff check`, `black` (reformatted two new files), `mypy --strict` on all
  touched Python: clean. `check_skill_references.py` and
  `check_doc_truth.py` run directly (the `llm_qa.py` wrapper hard-codes
  `untracked/venv/bin/python`, which this worktree does not have): both
  report no violations. No shell files touched.

## Things the next agent should know

- `init-handlers.sh` stays bundled and is invoked from `dev-handlers.md` with
  `"$@"` because `test_skill_scripts_are_referenced` requires every
  argument-reading bundled script to be invoked with arguments by some skill
  markdown.
- The advisory's `get_claude_md` text changed, so the generated
  `.claude/HOOKS-DAEMON.md` / `CLAUDE.md` block will differ after the next
  daemon restart in the main checkout; no restart was run here.
- The `housekeeping` verb is a candidate for Phase 4's gate: every step's
  verb is already asserted against the parser, which is the "documented CLI
  command that does not exist" check in miniature.
