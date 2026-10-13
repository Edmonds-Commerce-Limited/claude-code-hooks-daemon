# Release doc fixes for Plans 00450 and 00451

Branch worktree-release-doc-fixes-450-451. `llm_qa.py changed`: QA: 40/40 PASSED.

## Plan 00450

- `.claude/skills/release/invoke.sh`: the parallel-Haiku batching lines now say the main thread runs every test sequentially and the acceptance-test skill owns the method. There is no src/ source copy: only docs-qa and hooks-daemon are bundled skills, so `.claude/skills/release` is itself the source.
- `CLAUDE/development/RELEASING.md` Step 12 intro also told the reader to delegate tests to parallel sub-agents (a third conflicting place). It now says main thread, sequential, sub-agents forbidden, and points at `.claude/skills/acceptance-test/SKILL.md`.
- New test `tests/integration/test_release_acceptance_gate_method.py` (7 cases). It failed on release/invoke.sh and RELEASING.md before the edits and passes after.
- Plan ticks: Tasks 1.1, 2.1, 2.2, 2.3. Task 1.2 (why Plan 00324's contract test excluded these skills) not investigated. Status In Progress.

## Plan 00451 (version-file list only)

- RELEASING.md Step 3 now holds the single list of six version-carrying files. RELEASING.md Step 1b and `.claude/agents/release-agent.md` (capabilities, validation, Version Update, output summary) point at it. release-agent.md no longer names CLAUDE.md as a version target, since RELEASING.md says it carries no version string.
- Not done: the completeness test and all of Phase 2 (stale dependencies.json). No tasks ticked. Status In Progress.

Journal entries appended to both plans (category action).
