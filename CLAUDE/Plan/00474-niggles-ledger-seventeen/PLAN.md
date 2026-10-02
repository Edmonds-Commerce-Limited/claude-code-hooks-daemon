# Plan 00474: niggles ledger seventeen

**Status**: In Progress
**Created**: 2026-09-30
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger sixteen
([00466](../Completed/00466-niggles-ledger-sixteen/PLAN.md)) stays open for its own
entries, whose remaining branches the owner parked. But its PLAN.md reached
the 35,000-byte hard limit with N261, so its index table cannot take another
row. New entries are filed here, and 00466 takes no more.

Numbering continues from 00466, so an entry number stays unique across both
ledgers.

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

| #          | Verdict                                                                                                          | Origin              | Status                      |
| ---------- | ---------------------------------------------------------------------------------------------------------------- | ------------------- | --------------------------- |
| N309       | `remote-docs add` refuses a docs page whose example carries a session-UUID-shaped id                             | P479 agent          | ⬜ Owner decision           |
| N308       | Owner ruling: block unguarded `;` chaining (`bash_safe_mode` to block mode in this repository)                   | Owner               | 🔄 In progress              |
| N307       | In a command with two `git commit`s, the second commit's pathspecs are never scanned                             | N299 review         | ⬜ Open                     |
| N306       | The commit-move reader records both directories of `cd a \|\| cd b`                                              | N299 review         | ⬜ Open (in N299 round 2)   |
| N305       | `staged_lint_gate` judges a `cd other-repo && git commit` as this repository's commit                            | N299 agent          | ⬜ Open                     |
| N304       | `guard_config_commit_gate` misses `cd .claude && git commit hooks-daemon.yaml`                                   | N299 agent          | ⬜ Open                     |
| N303       | The pause-gate merge left a PreToolUse handler unclassified; main was red (N278/N297 again)                      | N299 agent          | ✅ Fixed (1c4f8e25f)        |
| N302       | `subagent_full_qa_blocker` reads `grep -c` / `awk -e` as interpreter inline code (advisory noise)                | P483 triage, Fable  | ⬜ Open                     |
| N301       | Each commit gate checks every pathspec with two git calls per path, separately                                   | N245 review         | ⬜ Open                     |
| N300       | `remote_docs_commit_gate` judges a nested worktree's commit against this repository                              | N245 review         | ⬜ Open                     |
| N299       | After `cd sub`, `sensitive_content` resolves `git commit -m x f.txt` from the repo root                          | N245 review         | ⬜ Open                     |
| N298       | `R-PLAN-NUMBER-DISCOVERY` denies a read-only `ls CLAUDE/Plan/*/PLAN.md`, even as quoted text                     | P483 triage         | ⬜ Open                     |
| N297       | The coordinator merged `merge_qa_advisor` without a targeted run; main failed two tests (N278 again)             | Coordinator         | ✅ Fixed (3dadb3d8c)        |
| N296       | `audit_error_hiding.py` sees log-and-continue only as a direct `logger.<level>()`; a helper call evades it       | N294 review         | ⬜ Open                     |
| N295       | The prompt-cache chip parses every sub-agent sidecar (3,369 files) on every render: 84–427 ms                    | Coordinator         | ✅ Fixed (b44e395a5)        |
| N294       | A status-line client that hangs up still logs an ERROR: `writer.wait_closed()` raises in `finally`               | Coordinator         | ✅ Fixed (fc6782bf1)        |
| N293       | #68: secret/quarantine guards fail closed on an absolute glob with 2+ wildcards under an existing literal prefix | GitHub #68          | ✅ Fixed (92b9b49e0)        |
| N292       | `upgrade_approval_guard` denies `PYTHONPATH=… $V/python script.py`, which runs no upgrade                        | Coordinator         | ✅ Fixed (15fe504c1)        |
| N291       | `secret_file_guard` denies a grep regex inside `$( )` as a mention of a protected path                           | Coordinator         | ✅ Fixed (4a30b9248)        |
| N290       | The coordinator stated a confident, unsearched, false claim ("the supervisor is outside this repository")        | Owner               | 🔄 Plan 00480               |
| N289       | In this repository the slow SessionStart sweeps appear never to reach a session, unreported                      | Coordinator         | ✅ Fixed (76cf82266)        |
| N288       | An event-socket test fails wherever the pytest process exports a hostname override                               | Task 4.1 agent      | ✅ Fixed (test only)        |
| N287       | `semgrep` and `dependencies` fail on main; neither runs in CI or in `changed`                                    | Plan 00475 timing   | ✅ Fixed (9342fa898)        |
| N286       | Main full CI went red after N264/N266: a playbook probe, a blindness verdict and a skip-list finding             | Main CI             | ✅ Fixed (1bbf676a0)        |
| N285       | `PYTHONPATH=` before an interpreter held in a variable is denied as an upgrade-approval bypass                   | N283 agent          | ✅ Fixed (a9d6d9aa0)        |
| N284       | The pipe blocker reads `\|` inside a double-quoted grep pattern as a pipe                                        | Coordinator         | ✅ Fixed (72e9018e3)        |
| N283       | `secret_file_guard` misses a protected name in git `rev:path` syntax at the repository root (security)           | N253 analysis       | ✅ Fixed (caa8ff966)        |
| N282       | The N264 cross-worktree guard judges an in-process teammate by the coordinator's working directory               | Coordinator         | ✅ Fixed (8eeead3e5)        |
| N281       | A hostile-input sweep failed on slow runners: the 100,000-character scan timed out and denied (fail-closed)      | Main CI             | ✅ Fixed (test only)        |
| N280       | Something with pre-N271 code wrote an older `CLAUDE.md` guidance section into main during a test run             | Coordinator         | ⬜ Open                     |
| N279       | `changed_tests` once selected 50 test files, ran 0 tests and still passed                                        | p477 agent          | ✅ Fixed (ac2306ed4)        |
| N278       | A branch merged with its targeted QA never run; main took three static-check failures                            | Coordinator         | 🔄 Plan 00475 Task 4.2      |
| N277       | `_resolve_python_cmd` in `init.sh` returns 0 after a failed resolve, with `PYTHON_CMD` empty                     | p477 agent          | ✅ Fixed (f794ae2d6)        |
| N276       | The SessionStart chain overruns its 20 s budget under load, so declared crons are never asked for                | Coordinator         | ✅ Fixed (aa557cc12)        |
| N275       | `secret_file_guard` judges an Edit of a YAML workflow holding `${{ }}` as an unreadable shell command            | Coordinator         | ✅ Fixed (d66d0ff9b)        |
| N274       | `AskUserQuestion` is denied as "unattended" right after the owner typed a message                                | Coordinator         | ✅ Fixed (93cc3615d)        |
| N273       | A stalled CI job holds main's queue for up to six hours; no job sets `timeout-minutes`                           | Main CI             | ✅ Fixed                    |
| N272       | One `llm_qa changed` run reported `project_handlers` as 0 tests collected; it passed 232 alone                   | Coordinator         | ✅ Fixed                    |
| N271       | An upgrade fails "uv not found" when the only uv is outside the trusted PATH and `~/.local/bin`                  | Main CI red         | ✅ Fixed (85bea8da6)        |
| N270       | The workspace venv has drifted from `uv.lock` (pytest 9.1.1 against 9.0.3)                                       | Coordinator         | ✅ Fixed (re-synced)        |
| N269       | `secret_file_guard` expands a single-quoted grep regex as a filename glob                                        | Coordinator         | ✅ Fixed (a7ebcae9b)        |
| N268       | A symlinked-project daemon test's teardown refuses a daemon that is exiting                                      | Main CI             | ✅ Fixed (1a61af7d0)        |
| N267       | Dropping a stale branch always needs a human, even when nothing can be lost                                      | Owner               | ✅ Fixed (74dbdc970)        |
| 65 entries | Still open in the archived ledger 00466 ([index](../Completed/00466-niggles-ledger-sixteen/PLAN.md))             | 00466 close-out     | ⬜ Open                     |
| N222 work  | Unfinished `tests/scaling.py` change saved from a merged branch's worktree ([saved](UNFINISHED-N252-SCALING.md)) | 00466 cleanup       | ⬜ Open                     |
| 22 entries | Carried from the dropped `worktree-n466-small-a` branch ([list](CARRIED-REFIX-BRANCHES.md))                      | 00466 cleanup       | ⬜ 12 open (triaged)        |
| 15 entries | Carried from the dropped `worktree-p422-close` branch ([list](CARRIED-REFIX-BRANCHES.md))                        | 00466 cleanup       | ⬜ 6 open (triaged)         |
| 14 entries | Carried from the dropped `worktree-d-00421` branch ([list](CARRIED-REFIX-BRANCHES.md))                           | 00466 cleanup       | ⬜ 8 open (triaged)         |
| 4 entries  | Carried from the dropped upgrade-scripts, 464 and N38 branches ([list](CARRIED-REFIX-BRANCHES.md))               | 00466 cleanup       | ✅ 0 open (triaged)         |
| N266       | `flaggable_content_channel_guard` denies greps that never touch a flagged path                                   | Coordinator         | ✅ Fixed (ba47e2459)        |
| N265       | `secret_file_guard` spends about 2.2 s of CPU on one realistic Python program                                    | N101 CI red         | ✅ Fixed (e39b1f98f)        |
| N264       | A sub-agent's edits landed, uncommitted, in another branch's worktree                                            | 00466 landing       | ✅ Fixed (7ebef17fb)        |
| N246       | Plan and docs QA judge a same-command `git add` as two partial trees                                             | Carried, N53 branch | ⬜ Open                     |
| N245       | A pathspec commit is judged on the index as well as the named paths                                              | Carried, N53 branch | ✅ Fixed (17b0aa491)        |
| N244       | The QA commit gates judge the disk, not the tree the commit records                                              | Carried, N53 branch | ✅ Fixed (52fd9cd9b)        |
| N189       | No commit gate sees a commit hidden in text only bash reads (`bash -c "$X"`)                                     | Carried, N53 branch | ✅ Dismissed (threat model) |
| N177       | No commit gate sees a commit after a `case` inside `function f {` in `$( )`                                      | Carried, N53 branch | ✅ Dismissed (threat model) |
| N176       | No commit gate sees a commit inside `$(( $(…) ))` arithmetic                                                     | Carried, N53 branch | ✅ Dismissed (threat model) |
| N135       | No commit gate sees a commit run from text, via an alias, or after `builtin cd`                                  | Carried, N53 branch | ✅ Dismissed (threat model) |
| N256       | Quoted heredoc bodies are glob-walked; a hit cap reads as an evaluation error                                    | Carried from 00466  | 🔄 Part 1 (efe0ec517)       |
| N255       | `git commit -F - <<'EOF'` denied as an evaluation error (ENAMETOOLONG)                                           | Carried from 00466  | ✅ No repro (efe0ec517)     |
| N254       | Two resolvers disagree on `secret_word_list_path`                                                                | Carried from 00466  | ✅ Fixed (9b589c4fc)        |
| N253       | `secret_file_guard` exemptions parse options from open lists                                                     | Carried from 00466  | ✅ Fixed (dbb744f26)        |
| N263       | The release empties UNRELEASED post-upgrade tasks but not the README index                                       | v3.67.0 CI          | ✅ Remedied                 |
| N262       | The release procedure has no check that the notes fit a GitHub release body                                      | v3.67.0 publish     | ✅ Remedied (ea8dcd542)     |

## Tasks

### Phase 1: Work the ledger

- [ ] 🔄 **Task 1.1**: Bring every entry above to a terminal state.

## Success Criteria

- [ ] Every entry is fixed, graduated with a pointer, or dismissed with the
  reasoning recorded.
- [ ] Every release-bound consequence is in the pending-release holding area,
  or the entry says it has none.

## Delivery & Milestones

- Opened when ledger sixteen (00466) reached its PLAN.md size limit.
