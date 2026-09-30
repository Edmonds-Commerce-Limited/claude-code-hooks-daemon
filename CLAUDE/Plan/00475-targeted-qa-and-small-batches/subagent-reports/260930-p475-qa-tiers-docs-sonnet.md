# Plan 00475 Tasks 3.1 and 3.3: QA tiers documentation (report)

Agent: Sonnet. Scope: Tasks 3.1 and 3.3, and ticking 3.1, 3.2, 3.3 in PLAN.md.

## Where the work was done

The task named the worktree `/workspace/untracked/worktrees/worktree-p475-qa-tiers-docs`.
The harness refused every command that changed into it (a worktree-isolated agent
may only run git from its own worktree,
`/workspace/.claude/worktrees/agent-a37f293fc9386d825-a6cad2f9`). I fast-forwarded
this worktree's branch to `worktree-p475-qa-tiers-docs` (which holds 1a5214069,
Task 3.2), worked here, and push under the branch name
`agent-a37f293fc9386d825-a6cad2f9`, not `worktree-p475-qa-tiers-docs`. That branch
is checked out in the other worktree, so the coordinator merges or fast-forwards
from mine.

## What changed

- `CLAUDE/QA.md`: new "QA Tiers" section (targeted, post-merge, full), what the
  targeted tier certifies, the unmapped and too-broad fallback, "Before Merging:
  the Coordinator's Check" (the static checks for a branch with no targeted
  result), the full gate as a release step. "The Batched Integration Gate" is kept
  as the mechanism for running the full gate on an integration branch, and now
  also holds the errexit-safe `main-moved` script. CI tiers section corrected to
  the code. Workflow, when-to-run, failure, quick-reference sections and the QA
  agent prompt no longer require `all` for everyday work. Anchors other documents
  cite are kept ("Full QA Is the Coordinator's Gate...", "The Batched Integration
  Gate", "A red batch", "CI tiers", the `qa-summary-example` anchor).
- Pointed at QA.md and stopped requiring `all` or a whole-tree `pytest`:
  `PlanWorkflow.md`, `CodeLifecycle/{Features,Bugs,General,README}.md`,
  `AgentTeam.md` (merge flow rewritten to a targeted run, then fast-forward to
  the tested sha), `Worktree.md`, `development/IssueSdlc.md`,
  `DEBUGGING_STOP_HOOK.md`, `SELF_INSTALL.md`, `DocumentationStrategy.md`,
  `AcceptanceTests/GENERATING.md`, `Code/HooksSystem.md`, `Code/StrategyPattern.md`,
  `src/claude_code_hooks_daemon/qa/CLAUDE.md`, `.claude/agents/qa-runner.md`,
  `.claude/agents/qa-fixer.md`, `.claude/skills/acceptance-test/invoke.sh`.
- Task 3.3: `CLAUDE/development/RELEASING.md` already required `llm_qa.py all` at
  Step 1b and Step 8, and the release skill and `release-agent.md` already said
  the main thread runs it and the agent reads `--read-only all`. They are
  consistent with QA.md and were left alone, except one added note in RELEASING's
  release-slate bullet that a docs or code tier CI green is not full-matrix
  evidence (QA.md says so; RELEASING did not).
- Test updated: `tests/integration/test_main_moved_branching_survives_errexit.py`
  read its two `main-moved` snippets from AgentTeam.md. The flow there is gone
  (it needed a certified head, which needs `all`), so the test now reads the one
  snippet in QA.md. 14 tests pass.
- PLAN.md: Tasks 3.1, 3.2, 3.3 ticked.

## Plan and code disagreements (the doc follows the code)

1. The old QA.md said a push classifies `before..sha`. `scripts/ci/emit_tier.bash`
   uses the head sha of the newest `main` qa.yml run that reached a verdict.
   QA.md now says that.
2. The plan says the post-merge tier is a QA sub-agent running
   `changed --range`. No such agent exists yet (Task 2.2 is open). QA.md names
   the command and CI, and does not claim an agent chooses the scope.
3. `llm_qa.py changed` and `run_changed_tests.py` still print "the coordinator's
   full gate must cover them" for an allowed unmapped file. That wording predates
   the tiers. QA.md notes it. Not changed (code).
4. The task lists "mypy and pyright on touched files". `run_pyright_check.py`,
   `audit_error_hiding.py` and `check_input_contract.py` take no file list; they
   scan the project. QA.md says so. `black --target-version py311` is as the task
   states; pyproject lists py311 to py313.
5. Plan 00359's release slate gate (`core/release_slate.py`) does not tell CI
   tiers apart, confirmed in code. Task 3b.2 is still open.

## Left unchanged, and why

- `CLAUDE/core/PlanWorkflow.core.md`: generic "this project's full QA suite"
  wording for shared core text; the project-specific `PlanWorkflow.md` defines
  what it means here, and now says targeted.
- `CLAUDE/LLM-UPDATE.md:1150`: a client-install verification after a major
  upgrade, not everyday work.
- `docs/QA.md`, `CONTRIBUTING.md` (`run_all.sh`): human-at-a-terminal docs.
- `CLAUDE/development/LESSONS.md`, `CLAUDE/Security/*`, `CLAUDE/Routine/*`,
  `CLAUDE/AcceptanceTests/PLAYBOOK-v1-manual-archived.md`: history or references
  to the runner, not requirements.
- `.claude/skills/release/*`, `.claude/agents/release-agent.md`,
  `RELEASING.md` Steps 1b, 8, 12 and the release template: the full gate is
  required there by design.
- `docs/guides/HANDLER_REFERENCE.md`: generated from handler code.
- The plan's Success Criterion "No doc outside the release documents requires
  `llm_qa.py all`" is left unticked: the items above remain, and the tool
  messages (item 3) still say otherwise.

## Verification

- `llm_qa.py changed --base main` (this worktree's own venv, built with
  `bin/hooks-daemon repair`): 27 of 28 checks passed; `changed_tests` failed on
  `test_documented_commands_are_not_self_denied.py` (a `<placeholder>` command in
  Bugs.md that project_containment read as a redirect). Fixed with a real path;
  that test and the errexit test then passed (18 passed). The same run reported
  `CLAUDE/PlanWorkflow.md` as unmapped, `too-broad`, exactly the case QA.md
  describes. Its reach passes 40 test files, so it is covered only by a
  whole-suite run (CI's fallback, the release).
- Not verified: a second full `changed` run after the last Bugs.md edit; the
  whole pytest suite; CI; the commit gate's docs QA result (see the commit).
