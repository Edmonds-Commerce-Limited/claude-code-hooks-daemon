# Plan 00463: full qa is a main thread gate

**Status**: Not Started
**Created**: 2026-09-24
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

**Owner request:** restrict sub-agents' ability to run full QA. Parallel
agents run tightly targeted QA, full QA is left to the main thread, and
the daemon enforces it through command patterns marked "full QA" that only
the main thread may run. The reason: several concurrent agents each running
the heavy full suite exhaust resources and waste CPU, and full QA has to run
again at merge anyway.

**Measured, not assumed.** When the request arrived, five `llm_qa.py all`
runs were executing at once, one per worktree (issue-55, 00460, 00461,
00462, N22). Each is about 25,700 tests over 15–20 minutes, on an
8-core host with a load average of about 4.6. The waste is worse than the
concurrency alone. An agent re-runs full QA after every fix round: Plan
00456's agent ran it at least three times. The coordinator then re-verifies
before merging, and CI runs it again. The per-checkout run lock
(`untracked/qa/.llm_qa.lock`, Plan 00262) only stops two runs in the SAME
checkout; it does nothing across worktrees.

**Why full QA must not simply move to after the merge.** Agents run full
QA for a real reason. Cross-cutting checks break from changes far away:
handler-guidance coverage, docs QA, plan QA, the handler reference, and
the acceptance probes. If the first full run happens on `main`, every
such break lands on `main`, and merges queued behind it build on a red
tree. So the gate stays BEFORE the merge, but it moves to the coordinator.
The coordinator runs full QA on the agent's branch head, in that worktree,
one run at a time. An agent delivers "targeted QA green plus a commit". The
coordinator's gate then runs once per delivery, not once per fix round.

**Enforcement reuses what exists.** The main-thread/sub-agent
discriminator is already solved: `core/handler_scope.py` uses the absence
of `agent_id` plus a synthetic-event guard (issue #40, Plans 00418 and
00423). The new guard is a PreToolUse Bash handler with `scope: SUB`, so
it never fires on the main thread. A deny with no way forward is the same
defect as Plan 00460. The message must therefore name the targeted
commands that ARE allowed, and they must exist.

## Goals

- In a sub-agent, a Bash command matching a configured full-QA pattern is
  DENIED. In this repo: `llm_qa.py all`, `llm_qa.py tests` (the whole
  suite), `run_all.sh`, and a pytest run with no path or only the whole
  `tests/` tree. The deny names the targeted forms: named `llm_qa.py`
  tools and pytest on explicit test paths. It also says the coordinator
  runs the full gate.
- The same command on the main thread is allowed and draws nothing.
- Patterns are handler options (`full_qa_patterns`). This repo's config
  declares its own. The shipped default is decided in Task 1.1: clients
  run different QA commands, and a default this repo's commands populate
  could never fire in a client project.
- A targeted QA entry point exists, so the allowed path is one command and
  not a judgement call. For example `llm_qa.py changed`: static tools, plus
  pytest on tests mapped from the files changed since the merge base.
- Coordinator workflow: the dispatch-brief guidance, `IssueSdlc.md`,
  `AgentTeam.md` and `Worktree.md` say agents run targeted QA and the
  coordinator runs the full gate, serially, on the branch head before
  merging.
- Dogfooded: enabled in this repo's `.claude/hooks-daemon.yaml`, and
  confirmed live. A sub-agent's `llm_qa.py all` is denied, and the
  coordinator's is allowed.

## Non-Goals

- Changing what full QA contains. (Adding shellcheck is 00422 N22,
  separately.)
- A machine-wide QA scheduler or queue. Serial runs by the coordinator
  make it unnecessary here. Task 1.1 records whether a client needs one.
- Removing CI's full run.

## Tasks

### Phase 1: TDD in a worktree

- [ ] ⬜ **Task 1.1**: Decide and record in the journal:
  - Does an in-process teammate's PreToolUse payload carry `agent_id`,
    like an Agent-tool sub-agent's? Measure it live, not from docs. Do
    the same for a Workflow-tool agent. If either lacks it, the guard
    cannot see that agent type, and the plan must say so.
  - The shipped default for `full_qa_patterns`, and whether the handler
    is enabled by default.
  - How this interacts with orchestrator-only mode (Plan 00418). Once it
    goes live it denies the main thread's Bash. The full-QA gate is
    orchestration, so it must be on that mode's allowlist, or the two
    features deadlock: nobody can run full QA.
- [ ] ⬜ **Task 1.2**: RED tests for the handler.
  - Each pattern form is denied under an `agent_id` payload.
  - It is allowed without one, and on a synthetic event.
  - Targeted forms are allowed everywhere. These include
    `llm_qa.py lint type_check`, `pytest tests/unit/handlers/x.py`,
    `llm_qa.py --read-only all` (a read, not a run), and
    `run_shell_check.sh`.
  - Pattern matching is shlex/word-bounded and not a substring match, so
    a commit message or `grep` mentioning "llm_qa.py all" is not denied.
- [ ] ⬜ **Task 1.3**: The handler, following the handler lifecycle (a
  HandlerID, Priority and RuleID constant, guidance text, and an
  acceptance test marked for a sub-agent context). Then the targeted QA
  entry point and its tests.
- [ ] ⬜ **Task 1.4**: The docs and workflow changes listed in Goals,
  plus a release note. Enable the handler in this repo's config.
- [ ] ⬜ **Task 1.5**: Targeted QA in the worktree, then hand over. Under
  this plan's own rule, the coordinator runs the full gate.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: The coordinator runs full QA on the branch head,
  merges `--no-ff`, verifies ancestry and CI, and restarts the daemon.
- [ ] ⬜ **Task 2.2**: Live dogfood check: a sub-agent's `llm_qa.py all`
  in the main checkout is denied with the targeted forms named, and the
  coordinator's same command runs.

## Success Criteria

- [ ] A sub-agent cannot start a full QA run, and the deny tells it
  exactly what to run instead.
- [ ] The main thread's full QA and every targeted form are unaffected.
- [ ] The coordinator workflow docs describe the new split, and the next
  dispatch after merge follows it.
- [ ] Full QA passes (run by the coordinator) and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00463-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
