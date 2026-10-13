# N458 report: one home for the acceptance method

Branch worktree-n458-acceptance-method.

## Changes

- `.claude/skills/acceptance-test/SKILL.md`: the "Main Thread Only ... forbidden" section is replaced by "Execution Routing":
  `Requires Main Thread: yes` runs in the main thread, sequentially, never delegated (v2.9.0 race-condition lesson kept);
  `no` may be delegated, batched by `Recommended Model`. Other lines that said "NOT sub-agents" are aligned.
- `.claude/skills/acceptance-test/invoke.sh`: the "Sub-agent testing is FORBIDDEN" paragraph carries the same routing.
- `CLAUDE/development/RELEASING.md` Step 12 intro: now points at the skill as the method's home, one routing sentence.
- No source copy exists: `src/claude_code_hooks_daemon/skills/` bundles only `docs-qa` and `hooks-daemon`, so the
  acceptance-test skill is tracked only under `.claude/skills/`; nothing to keep byte-identical.
- Already aligned, left alone: `CLAUDE/AcceptanceTests/GENERATING.md` (SUB-AGENT EXECUTION section) and the playbook
  generator's "Execution Routing" text. Nothing in docs/ or the release skill claimed a blanket ban.
- New test `tests/integration/test_acceptance_method_single_home.py`: fails if the skill, invoke.sh, RELEASING.md,
  GENERATING.md or the playbook generator forbids sub-agents outright; requires the skill to name both routing fields and
  v2.9.0; requires Step 12 to link the skill.

## Note for the coordinator

`.claude/skills/CLAUDE.md` names `CLAUDE/AcceptanceTests/GENERATING.md` as the canonical source for the acceptance test
process, and `.claude/rules/claude-skills.md` says skills are thin shims. This task made the skill the home of the
routing, so that table row is now partly stale; I did not edit it. The skill points at GENERATING.md for the measured
hook-visibility table.

## Verification

- New test plus the two neighbouring tests: 19 passed.
- `./scripts/qa/llm_qa.py changed`: QA: 40/40 PASSED (changed_tests 357 passed, 0 failed).
