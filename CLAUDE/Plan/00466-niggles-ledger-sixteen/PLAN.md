# Plan 00466: niggles ledger sixteen

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger fifteen
([00422](../00422-niggles-ledger-fifteen/PLAN.md)) stays open for its own
entries: four are waiting on stated owner questions, and several are
graduated to plans still in flight. But its PLAN.md passed the 25,000-byte
warning line with N29. So new entries are filed here, and 00422 takes no
more.

Each entry gets enough evidence for someone else to reproduce it, and ends
in a terminal state: fixed, graduated to its own plan, or dismissed as
not-a-defect with the reasoning kept.

## Goals

- Record each niggle with reproducible evidence in [NIGGLES.md](NIGGLES.md).
- Resolve each entry to a terminal state.

## Non-Goals

- Becoming a feature plan. A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.

## Niggles

Full write-ups are in [NIGGLES.md](NIGGLES.md). One line each here:

| #   | Verdict                                                                                                   | Origin             | Status                |
| --- | --------------------------------------------------------------------------------------------------------- | ------------------ | --------------------- |
| N1  | `resolve_venv_python`'s fallback accepts a venv interpreter that cannot run on this host                  | Plan 00457's agent | ✅ Remedied           |
| N2  | `setup_worktree.sh` tells every agent to run the full suite through the denied `run_all.sh`               | Coordinator        | 🔄 Graduated to 00463 |
| N3  | `goal_injection` treats any edit of an In Progress plan as the plan starting, and displaces the live goal | Coordinator        | 🔄 In progress        |
| N7  | The regenerated CLAUDE.md guidance block is not deterministic, so a restart commits a reorder             | Coordinator        | 🔄 In progress        |
| N8  | `reference_repo_freshness` says BLOCKED on a call it allows                                               | Coordinator        | ✅ Remedied           |
| N9  | `docs_qa` judges gitignored markdown, so installing a Claude Code plugin fails local full QA              | Coordinator        | ✅ Remedied           |
| N10 | A wildcard in the middle of a protected filename gets past `secret_file_guard`                            | 00466 review       | 🔄 In progress        |
| N11 | Any exception in `secret_file_guard.matches()` lets the call through unless `strict_mode` is on           | 00466 review       | 🔄 In progress        |
| N12 | A hand-built probe payload is logged as real traffic, because nothing tells a prober to mark it           | 00467 audit        | ⬜ Open               |
| N13 | The plan-index statistics arithmetic is checked only by full QA, so a wrong count reaches main            | Coordinator        | ⬜ Open               |
| N14 | Log and payload redaction ignore a configured secret word list path                                       | 00414 agent        | 🔄 In progress        |
| N15 | `remote-docs add` scans a capture with an unconfigured `sensitive_content` handler                        | 00468 docs agent   | 🔄 In progress        |
| N17 | `skill_opportunity_detector` never receives its configured options                                        | N13/N14 agent      | 🔄 In progress        |
| N18 | PlanWorkflow.core.md says the plan index is linted against one rule                                       | N13/N14 agent      | 🔄 In progress        |
| N19 | The registry's options-collection failure is logged at debug level                                        | N13/N14 agent      | 🔄 In progress        |
| N20 | The capture-corruption auditor judges a multi-line single-quoted string one line at a time                | B1 integration     | ⬜ Open               |
| N21 | The semgrep QA gate passes when a rule times out                                                          | 00414 agent        | 🔄 In progress        |
| N22 | `lsp_enforcement` takes another command's argument for a grep symbol lookup                               | Coordinator        | ⬜ Open               |
| N23 | `recovery_cron_advisor` hands one request's lifecycle phase to another through the singleton              | Plan 00449's agent | ⬜ Open               |
| N24 | `daemon.strict_mode` never reaches the live daemon, so every guard fails open on a handler exception      | guards review 2    | 🔄 In progress        |
| N25 | A slow handler runs out the client's budget, and a timeout ALLOWs the whole PreToolUse chain              | guards review 2    | 🔄 In progress        |
| N26 | `check_skill_references.py` scans zero files when run from a worktree, and passes                         | 00468 core agent   | ⬜ Open               |
| N27 | `skill_scan` and `tool_report` build the transcript directory name two different ways                     | 00468 core agent   | ⬜ Open               |
| N28 | `project_containment` resolves a relative target against the payload cwd, ignoring a same-command `cd`    | Plan 00464 agent   | 🔄 In progress        |
| N29 | `error_hiding`'s return-None-in-except check is evaded by returning a local assigned in the handler       | Coordinator        | ⬜ Open               |
| N30 | More shell code that must survive a hostile PATH depends on a PATH command (`date`, `pgrep`)              | 00467 dogfood      | ⬜ Open               |
| N31 | The dispatch-declaration advisory does not recognise "File to write to: <path>"                           | 00467 dogfood      | ⬜ Open               |
| N32 | `pipe_blocker` splits at a `\|` inside double quotes and reads the next word as a pipe stage              | Plan 00463 agent   | ⬜ Open               |
| N33 | A worktree agent's `secret_file_guard.exclude_paths` change had no effect after a daemon restart          | Integration B2 fix | ⬜ Open               |
| N35 | `daemon_sync_after_merge` judges a `cd <worktree> && git merge` against the session root's ORIG_HEAD      | Plan 00421 agent   | ⬜ Open               |
| N36 | `destructive_git` denies a `grep` whose search pattern is the text of a force branch delete               | Plan 00463 agent   | ⬜ Open               |
| N37 | `resolve_venv.sh` caches an override's interpreter for later callers that set no override                 | Plan 00376 agent   | 🔄 In progress        |
| N38 | The PreToolUse chain takes quadratic time on a command of quoted heredoc openers                          | 463 review 6       | 🔄 In progress        |
| N46 | `budget_exhaustion_detector` fires on a tool result that merely contains budget wording                   | Guard review 6     | ⬜ Open               |
| N45 | A NUL byte in a configured word-list path makes the never-raising secret-term lookup raise                | Plan 00421 agent   | 🔄 In progress        |
| N44 | A PreToolUse handler raises `ValueError: no path specified` on an Edit, and the Edit goes through         | Plan 00464 agent   | 🔄 In progress        |
| N43 | Log and payload redaction is inert while the daemon runs degraded on an unloadable config                 | Plan 00421 agent   | 🔄 In progress        |
| N42 | Quoted-heredoc blanking hides text that bash executes from the Bash command guards                        | N38 review         | 🔄 In progress        |
| N39 | Nine unit tests fail in a whole-suite run and pass when their files run alone                             | guard-defects fix  | 🔄 In progress        |
| N47 | The ccy supervisor and Claude Code's settings.json both own effort, and they fight                        | Owner              | 🔄 In progress        |
| N48 | `sed_blocker`'s git-commit exemption reaches across a newline                                             | N38 review 2       | ⬜ Open               |
| N49 | `daemon_location_guard` denies a daemon-directory `cd` that is only text inside a quoted argument         | Coordinator        | ⬜ Open               |
| N50 | A handler option named like a method overwrites it, and the handler crashes open                          | N23 review 2       | 🔄 In progress        |
| N51 | `pipe_blocker` reads an escaped alternation in a quoted grep pattern as a pipe into `head`                | 00421 review 2     | ⬜ Open               |
| N52 | The sensitive_content commit gate let a matching session UUID into a commit                               | N46 review 2       | 🔄 In progress        |
| N53 | WorktreeCreate fails with exit 127 when the daemon runs a `git worktree add` that succeeds from a shell   | Coordinator        | 🔄 In progress        |
| N54 | Every Stop and SubagentStop rebuilds a default `Config()` (about 50 ms) while the config is broken        | Goal-flip review 8 | ⬜ Open               |
| N55 | `register_all` ignores a handler's `get_default_enabled()` when its config block is absent                | Goal-flip review 8 | ⬜ Open               |
| N56 | Tests skip when run as root, so this container never runs them                                            | Owner              | 🔄 In progress        |
| N57 | `secret_file_guard` misses a protected path reached through an earlier assignment, alias or written file  | Guard-defects fix  | ⬜ Open               |
| N58 | R-CHMOD-WORLD-WRITABLE denies a safe chmod when a later argument contains digits                          | N53 review 2       | ⬜ Open               |
| N59 | A signal went to a PID nobody proved was the intended process, and killed the container twice             | Infra owner        | ✅ Remedied           |
| N60 | `curl_pipe_shell` denies a double-quoted `echo` argument that only mentions the pattern                   | Coordinator        | ⬜ Open               |
| N61 | The `sensitive_content` commit gate misses a file that a same-command `git add` stages                    | upgrade-scripts    | 🔄 In progress        |
| N62 | Nothing bounds a subagent's context, so long-lived agents burn the usage budget                           | Owner              | ⬜ Open               |
| N63 | Supervisor unit tests read the ambient `CCY_*` environment, so a ccy session fails a test CI passes       | N24 fixer          | ✅ Remedied           |
| N64 | `subagent_report_path_verifier` resolves a worktree-relative report path against the main checkout        | N47 verify agent   | ⬜ Open               |
| N65 | `plan_number_helper` denies an `ls` of one named plan's folder as a next-number scan                      | Coordinator        | ⬜ Open               |
| N66 | Two singleton race tests depend on `time.sleep(0.02)`, so they can pass without the race happening        | N23 review 5       | ⬜ Open               |

## Tasks

### Phase 1: Resolve entries

- [ ] ⬜ **Task 1.1**: Bring every entry to a terminal state.

## Success Criteria

- [ ] Every row is terminal: remedied, graduated, or dismissed with reasoning.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00466-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened with N1.
