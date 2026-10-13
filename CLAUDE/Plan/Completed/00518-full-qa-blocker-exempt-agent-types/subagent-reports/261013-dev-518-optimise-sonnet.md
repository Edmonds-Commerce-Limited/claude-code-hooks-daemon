# Plan 00518 Phase 2 Task 2.1 and Phase 3 Task 3.4 report

## Task 2.1: optimise recommends exempt_agent_types

- New `src/claude_code_hooks_daemon/config_optimisation/qa_runner_agents.py`:
  `find_full_qa_runner_agents(project_root)` reads `.claude/agents/*.md`, takes the
  frontmatter `name` (else the file stem) and keeps a type whose `-`/`_` tokens contain
  `full`, `runner` and one of `qa`/`pipeline`/`gate`/`suite`. Matches `qa-full-runner` and
  `php-qa-ci_full-pipeline-runner`; rejects `qa-runner`, `full-qa-fixer`, `full-runner`.
  Descriptions are not matched: `qa-runner`'s own description mentions the full suite.
- `checklist.py`: `ChecklistItem.exempt_agent_types` (set only on the full-QA blocker);
  `render_report` adds `with exempt_agent_types: [<types>]` under that recommendation;
  `report_as_json` carries the list. No agent found: output unchanged.
- Tests: `tests/unit/config_optimisation/test_qa_runner_agents.py` (found, not found,
  targeted-only not proposed, name vs stem, sorted/unique, other handlers never carry it, JSON).
- Plugin agents are not enumerated by the checklist, so they are not covered.

## Task 3.4

- `CLAUDE/QA.md`: canonical paragraph "The one exemption: `qa-full-runner`" (unnamed or by type,
  one at a time via the lock, reports and never fixes, points at the handler guidance).
- `CLAUDE/development/IssueSdlc.md` Step 5: short pointer to that paragraph.
- Release note 053 extended with one paragraph on the optimise recommendation.

## Notes

- A newly added `.claude/agents/*.md` is not available to a running Claude Code session
  until a new session starts (not fixed, as instructed).
- `llm_qa.py changed` reports `checklist.py` as unmapped `[too-broad]`: its dependent
  `daemon/cli.py` reaches past the selection cap. This is structural and pre-existing for any
  edit to that file (no map rule suppresses it), so the run used `--allow-unmapped`.
- The host-wide QA lock was held by another worktree for over 10 minutes; see the summary line
  in the reply for the final result.
