# Plan 00484 Phase 1 (Tasks 1.1-1.3) report

Branch: worktree-p484-phase1-dbf-links. Task 1.4 (GitHub comments) deliberately not done.

## Changes

- README.md: new "Defence Before Fix" subsection after "Guardrails, not armour". It names the
  method, links https://defence-before-fix.github.io, says handlers are defences running at
  tool-call time, and restates that no defence against a hostile agent or prompt injection is
  claimed.
- `src/claude_code_hooks_daemon/constants/dbf.py` (new): `DefenceBeforeFix.URL` and
  `DefenceBeforeFix.EXPLAIN_LINE`, the single source for the URL and the CLI line.
- `daemon/cli.py`: `cmd_explain_rule` prints the line after `formatter.verbose(rule)`;
  `cmd_explain_handler` prints it last. Unknown rule or handler paths do not print it.
- Tests (RED first, confirmed by the missing-module ImportError): `tests/unit/constants/test_dbf.py`
  (new) and three added tests in `tests/unit/daemon/test_cli_explain_rule.py`.
- Agent tree: `CLAUDE/Security/README.md` and `CLAUDE/HANDLER_DEVELOPMENT.md` gain one pointer each
  to the vendored `remote-docs/defence-before-fix.github.io/SPEC.md`. `CLAUDE/CodeLifecycle/Bugs.md`
  already had a full DBF section, so its "vendored copies live in the remote-docs tree" mention now
  links the exact path instead of adding a second pointer.
- PLAN.md: Tasks 1.1-1.3 marked done with a short note.

## Verification

- pytest: test_cli_explain_rule.py, test_dbf.py, test_claude_md_guidance_coverage.py: 353 passed.
- pytest: british_english, doc_truth, check_doc_snippets, scratch_path_guidance,
  documented_commands/probes, repo_hygiene, tests/unit/docs_qa, validate_instruction_content:
  726 passed.
- ruff check, black --check --target-version py311, mypy on touched py: clean.
- scripts/qa/check_generated_doc_drift.py: no drift.
- `./bin/hooks-daemon docs-qa`: 0 findings.
