# Plan 00463: full qa is a main thread gate

**Status**: In Progress
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
tree. So the gate stays BEFORE `main` moves, but it moves to the coordinator.
An agent delivers "targeted QA green plus a commit".

**The coordinator's gate is batched, not per branch** (owner's instruction).
One full run per branch, one at a time, only turns five concurrent runs into a
queue of five. Instead the coordinator merges every ready branch, each
`--no-ff`, into ONE integration branch holding current `main` (in an agent
team, the plan's parent branch), records the batch base with
`llm_qa.py main-moved --start` in a git ref, and runs `llm_qa.py all` once on
that combined head. Green: `main` is fast-forwarded to the integration head, so
there is one push and one CI run. `main` is frozen for code while a batch is in
flight. If it moves anyway, `llm_qa.py main-moved` judges each moved path with
the same test mapper `llm_qa.py changed` uses: a document no test reads
re-runs the doc checks, a document tests read re-runs those tests
(`targeted`), and code or a runtime-read path re-runs the full gate. After the
recheck, `--advance` moves the base on, only when the recheck's provenance
shows it passed. CI on the pushed head is the second line, not a substitute.
Red: the coordinator bisects to the branch whose change broke it, sends it
back to be fixed on that branch or rebuilds the batch without it, and re-runs.
The combined head is also the only place a
break that needs two branches together can show before `main`. Any lock the
coordinator holds around the gate must be released when the run exits, even if
a daemon started under it lives on (the lock-fd finding in the journal).
Canonical description: `CLAUDE/QA.md`, "The Batched Integration Gate".

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
  coordinator runs the full gate once per batch, on an integration worktree
  holding every ready branch, before `main` moves. `scripts/setup_worktree.sh`
  tells a worktree agent the same (ledger 00466 N2).
- When `main` moves during a batch, a checked mechanism decides what re-runs:
  `llm_qa.py main-moved` reads the batch base from
  `refs/integration/base/<branch>` (set by `--start`, which refuses a second
  start without `--restart`) and the certified head from
  `refs/integration/certified/<branch>` (set only by a passing `all` or a
  successful `--advance`, on a clean tree). It exits `head-moved` (7) unless
  HEAD is the certified head on a clean tree, then `unmoved` (0),
  `docs-only` (5), `targeted` (6) or `full-gate` (4). A moved document is
  judged by the `changed` test mapper, never a hand-kept list; the runtime-read
  set is defined once in `llm_qa.py` and pinned by a test. `--advance` refuses
  a dirty tree and any work since the certified head but `main` merged in, and
  moves the base only when the recheck's provenance certifies a pass on this
  tree. `--finish` deletes both refs once `main` holds the certified head.
- 00463 ships no lock of its own. `llm_qa.py`'s existing run lock is
  non-inheritable, and a test pins that a daemon started during a run does not
  keep it after the run exits.
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

- [x] ✅ **Task 1.1**: Decide and record in the journal. Outcome: an in-process
  teammate carries `agent_id` (measured). A Workflow-tool agent is UNMEASURED,
  because the probe needs the owner's opt-in, so the guard's docs claim coverage
  only for Agent-tool sub-agents and teammates. The default is off with no
  patterns. There is no deadlock with orchestrator-only mode: its blocking
  policy never denies Bash, and an integration test proves this on the real
  chain with the mode armed. The simulate record's false "would have been
  denied" for Bash (ledger 00422 N24) is fixed here, so the record now says
  "would have been denied" only when the blocking policy denies. The
  questions were:
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
- [x] ✅ **Task 1.2**: RED tests for the handler.
  - Each pattern form is denied under an `agent_id` payload.
  - It is allowed without one, and on a synthetic event.
  - Targeted forms are allowed everywhere. These include
    `llm_qa.py lint type_check`, `pytest tests/unit/handlers/x.py`,
    `llm_qa.py --read-only all` (a read, not a run), and
    `run_shell_check.sh`.
  - Pattern matching is shlex/word-bounded and not a substring match, so
    a commit message or `grep` mentioning "llm_qa.py all" is not denied.
- [x] ✅ **Task 1.3**: The handler, following the handler lifecycle (a
  HandlerID, Priority and RuleID constant, guidance text, and an
  acceptance test marked for a sub-agent context). Then the targeted QA
  entry point and its tests.
- [x] ✅ **Task 1.4**: The docs and workflow changes listed in Goals,
  plus a release note. Enable the handler in this repo's config.
- [x] ✅ **Task 1.5**: Targeted QA in the worktree, then hand over. Under
  this plan's own rule, the coordinator runs the full gate.

### Round 9: the guarantee moves to the sink

Nine reviews chased command-TEXT evasions in the Bash handler -- perl, node,
`at`, `systemd-run`, `git rebase --exec`, substitution-built paths, oversized
text, files rewritten in the same command -- and review 9 still found 81 of
202 evasion rows allowed. **A Bash-text denylist can never close that set**:
any program can start a whole-suite test run, so no finite pattern list
enumerates every launcher. The guarantee therefore moves to the SINK -- the
one place every route ends up, whatever launched it: pytest itself.

- `claude_code_hooks_daemon.qa.full_qa_gate` (a pytest plugin, wired from
  `tests/conftest.py`) refuses a whole-suite-sized collected selection
  (over 25% of the suite's test files) unless the host-wide full-QA lock
  (`claude_code_hooks_daemon.qa.full_qa_lock`) is held, proven by an
  INHERITED file descriptor on the lock file (never an env var).
  `scripts/qa/run_tests.sh` and CI (`.github/workflows/qa.yml`) acquire it
  before their whole-suite pytest invocation; `llm_qa.py all` and
  `run_all.sh` acquire it transitively (both run `run_tests.sh`).
  `run_changed_tests.py` and `llm_qa.py changed --range/--base` need no lock
  of their own: they invoke pytest directly, so the sink already refuses them
  the moment their selection is whole-suite-sized (this resolves the
  standing M1 finding: a 40-file-per-call cap never bounded the TOTAL).
- The Bash handler (`subagent_full_qa_blocker`) STAYS: it is the fast,
  friendly first line that denies the common shapes early with a helpful,
  actionable message. It is no longer the guarantee -- the sink is. Its own
  fixes this round are narrow and exact, not a widening of the evasion
  parser: `bash|sh -n`/`--noexec` runs nothing (m1); `~+` is bash's own
  `$PWD` (m3); a symlink to a declared runner is judged by its target's
  pattern (m5); a script path built by a shell substitution or backtick is
  UNSEEN, not absent, so it fails closed instead of being silently skipped
  (B1) -- paired with resolving the FIXED script-directory idioms
  (`$(dirname "${BASH_SOURCE[0]}")`, `$(cd "$(dirname ...)" && pwd)`,
  `realpath`/`readlink -f` of a literal) so the tightened B1 rule does not
  turn every script that finds its own directory into a false deny.
- **B1 residual, narrowed (round 9c).** The `while [ -L "$VAR" ]; do ... readlink ...; done` self-location loop (`bin/hooks-daemon`'s own shape) and
  the coreutils-free `${BASH_SOURCE[0]%/*}` dirname spelling (used by
  `scripts/lib/resolve_venv.sh` and others) are now both resolved
  structurally -- the loop by its condition and body signature
  (`_with_resolved_symlink_source`/`_is_self_readlink_reassignment`,
  `subagent_full_qa_blocker.py`), the trim idiom the same way the
  `$(dirname ...)` spelling already was (`_BASH_SOURCE_DIRNAME_TRIM`). A
  look-alike loop whose body reassigns its variable some OTHER way is left
  unseen, on purpose (`TestSelfLocationSymlinkLoopIsResolved` in
  `test_subagent_full_qa_blocker.py`).
  This does NOT clear `bin/hooks-daemon` and the scripts that shell out to
  it end to end: the handler's per-file variable tracking has no visibility
  into a variable set by an EARLIER top-level assignment in the same script
  once that `cd` is reached only through a nested `$(...)` substitution
  (`BIN_DIR="$(cd -P "$(dirname "$_source")" && pwd)"` then `DAEMON_DIR= "$(cd -P "$BIN_DIR/.." && pwd)"` -- the second `cd`'s `$BIN_DIR` is opaque
  to that nested walk). A fix was attempted (threading the enclosing script's
  variables into `_nested`'s recursive `_invocations` call) and reverted: it
  fixed `run_canonical_callers_check.sh`'s own two-hop
  `SCRIPT_DIR`/`PROJECT_ROOT` chain, but newly denied
  `scripts/qa/run_smoke_test.sh` (previously ALLOWED because the whole
  `${PROJECT_ROOT}/bin/hooks-daemon` word was leniently treated as ABSENT
  while `PROJECT_ROOT` stayed opaque -- resolving it exposed a DEEPER,
  separate gap instead of a genuine allow). `bin/hooks-daemon`,
  `run_canonical_callers_check.sh`, `run_semgrep_check.sh` and
  `check_generated_doc_drift.py` (the last two also blocked separately:
  `run_semgrep_check.sh` builds its program path by calling a bash
  FUNCTION, `resolve_venv_python`, which is genuinely uncomputable without
  running it; `check_generated_doc_drift.py` is denied only because its own
  docstring PROSE mentions `bin/hooks-daemon generate-docs`, misread as an
  invocation) remain pinned DENIED in `_SCRIPTS_THAT_RUN_UNSEEN_CODE`
  (`test_subagent_full_qa_blocker.py`), `_B1_RESIDUAL_UNSEEN` and
  `TestBinHooksDaemonIsTheB1Residual` (`..._corpus.py`), with their
  docstrings updated to the CURRENT cause. A real fix needs the nested-`cd`
  "here" tracker to see the enclosing script's own variables WITHOUT
  reintroducing the `run_smoke_test.sh` regression -- likely branch-aware
  variable tracking for `if`, not just the loop idiom -- which is follow-up
  work, not a "documented limit" to leave alone: it sits in code this round
  touches.
- The plan merges AFTER Plan 00466's N24 ledger, whose deadline now fails
  CLOSED on a chain timeout (M7's own budget finding: a chain timeout must
  never read as an allow for a SUB-scoped guard).
- **M7 verified on THIS branch (round 9d), deterministically.** A mid-exchange
  relay timeout for a POSITIVELY SEEN full run (bare `pytest`) still fails
  OPEN here: `relay/hooks_relay.rs`'s `mid_exchange_fail` writes `{}` and
  exits 0 by design once its own `--timeout-ms` budget is spent post-connect.
  Proven with a real relay binary against a fake Unix-socket server that
  accepts the connection, reads the request to EOF, and never replies --
  the elapsed time tracks the configured budget by a ratio, not an absolute
  wall-clock guess, so the result does not depend on host load. Pinned as
  `tests/integration/test_relay_mid_exchange_timeout_fails_open.py`, which
  will FAIL once N24's fail-closed fix lands on this branch -- deliberately,
  so the merge cannot silently drop the finding. Not independently re-fixed
  here: N24 is the active, much larger effort closing this exact gap (the
  relay binary, its build/deploy pipeline and CI asset baking), already 8+
  review rounds deep; a parallel fix here would fork it.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: The batched integration gate: the coordinator merges
  this branch `--no-ff` with the other ready branches into an integration
  branch holding current `main`, runs `llm_qa.py main-moved --start` and full
  QA once there, and on green loops `llm_qa.py main-moved` (recheck, then
  `--advance`) until `unmoved`, then fast-forwards. It restarts the daemon
  before the push, runs `main-moved --finish` after it, then verifies ancestry
  and CI.
- [ ] ⬜ **Task 2.2**: Live dogfood check: a sub-agent's `llm_qa.py all`
  in the main checkout is denied with the targeted forms named, and the
  coordinator's same command runs.

## Success Criteria

- [ ] An Agent-tool sub-agent or in-process teammate cannot start a full
  QA run, and the deny tells it exactly what to run instead. A
  Workflow-tool agent is unmeasured, so it is not claimed.
- [ ] The main thread's full QA and every targeted form are unaffected.
- [ ] The coordinator workflow docs describe the new split, and the next
  dispatch after merge follows it.
- [ ] Full QA passes (run by the coordinator) and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00463-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
