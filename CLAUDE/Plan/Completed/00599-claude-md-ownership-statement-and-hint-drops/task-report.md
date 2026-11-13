# Plan 00599 task report

Branch `plan-00599-ownership`, built TDD (new tests collected and failed on the missing
module before any source change).

## Delivered

- `config/models.py`: `ClaudeMdOwnership` (own/off/custom), `ClaudeMdConfig.ownership`
  (default `own`) and `ownership_text`; custom needs non-blank text, other modes reject text.
- `core/ownership.py` (new): the sentence, five hint texts, process-wide mode set by the
  controller, `hint_pending` / `hint_once` (once per session and hint), pure helpers for
  the CLI. Unconfigured means inactive, so existing tests and the CLI are unaffected.
- `core/claude_md_injector.py`: `ownership_statement` arg; the sentence sits under the block
  heading, before the intro. `daemon/controller.py` passes it and configures the hints.
- Hints: `plan_workflow` (Write/Edit of plan, ledger, index files; journal entries excluded),
  `lint_on_edit` (appended to the deny reason), `agent_isolation_advisor` (first dispatch of
  a session, even a lone agent; isolation advice unchanged), `branch_sweep` handler and
  `core/branch_sweep.py` (owned-branch hint in the session summary, pool report and
  `branch-sweep`; foreign counter-hint under the Foreign list in `branch-sweep`).
- Init-config template (minimal and full), this repo's `.claude/hooks-daemon.yaml`,
  `docs/guides/CONFIGURATION.md` (modes, hints, measured costs), release note 055.
- PLAN.md filled in (In Progress) and the README row synced.

## Not done

- This repository's `CLAUDE.md` block is not regenerated: a linked worktree never writes it
  by design. After merge, run `bin/hooks-daemon regenerate-docs` on the home branch
  (plan Task 3.2, left unticked). Plan Task 3.3 (review and merge) also unticked.

## QA

- `run_autofix.sh` clean. `llm_qa.py changed --base main --allow-unmapped`: 39 of 42 passed;
  pyright flagged string arguments in my new tests, fixed and re-run clean; `python -m pyright`
  on every changed source and test file: 0 errors.
- `changed_tests`: 5371 passed, 2 failed. `docs_qa/test_corpus.py::test_a_steady_state_ revalidation_logs_nothing` passed on rerun (flaky). `test_qa_walkers_examine_files_from_ any_checkout.py[check_british_english.py]` still fails with a FileNotFoundError on the
  walker's output JSON in a synthetic hostile path; my diff touches nothing it reads, so it is
  most likely environmental to a worktree, but I did not prove it fails on main.
- The 11 changed source files are "unmapped" to tests by the selector; the full gate must
  cover them (coordinator's run).

## Caveats

- Hint state is in-process, keyed by session id; a daemon restart re-arms the hints.
- The SessionStart branch hint fires on new sessions only; `branch-sweep` prints it each run.
