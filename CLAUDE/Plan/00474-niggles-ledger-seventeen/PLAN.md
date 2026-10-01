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

| #          | Verdict                                                                                                          | Origin              | Status                  |
| ---------- | ---------------------------------------------------------------------------------------------------------------- | ------------------- | ----------------------- |
| N281       | A hostile-input sweep failed on slow runners: the 100,000-character scan timed out and denied (fail-closed)      | Main CI             | ✅ Fixed (test only)    |
| N280       | Something with pre-N271 code wrote an older `CLAUDE.md` guidance section into main during a test run             | Coordinator         | ⬜ Open                 |
| N279       | `changed_tests` once selected 50 test files, ran 0 tests and still passed                                        | p477 agent          | ✅ Fixed (ac2306ed4)    |
| N278       | A branch merged with its targeted QA never run; main took three static-check failures                            | Coordinator         | ⬜ Open                 |
| N277       | `_resolve_python_cmd` in `init.sh` returns 0 after a failed resolve, with `PYTHON_CMD` empty                     | p477 agent          | ✅ Fixed (f794ae2d6)    |
| N276       | The SessionStart chain overruns its 20 s budget under load, so declared crons are never asked for                | Coordinator         | ✅ Fixed (aa557cc12)    |
| N275       | `secret_file_guard` judges an Edit of a YAML workflow holding `${{ }}` as an unreadable shell command            | Coordinator         | ✅ Fixed (d66d0ff9b)    |
| N274       | `AskUserQuestion` is denied as "unattended" right after the owner typed a message                                | Coordinator         | ✅ Fixed (93cc3615d)    |
| N273       | A stalled CI job holds main's queue for up to six hours; no job sets `timeout-minutes`                           | Main CI             | ✅ Fixed                |
| N272       | One `llm_qa changed` run reported `project_handlers` as 0 tests collected; it passed 232 alone                   | Coordinator         | ✅ Fixed                |
| N271       | An upgrade fails "uv not found" when the only uv is outside the trusted PATH and `~/.local/bin`                  | Main CI red         | ✅ Fixed (85bea8da6)    |
| N270       | The workspace venv has drifted from `uv.lock` (pytest 9.1.1 against 9.0.3)                                       | Coordinator         | ✅ Fixed (re-synced)    |
| N269       | `secret_file_guard` expands a single-quoted grep regex as a filename glob                                        | Coordinator         | ✅ Fixed (a7ebcae9b)    |
| N268       | A symlinked-project daemon test's teardown refuses a daemon that is exiting                                      | Main CI             | ✅ Fixed (1a61af7d0)    |
| N267       | Dropping a stale branch always needs a human, even when nothing can be lost                                      | Owner               | ✅ Fixed (74dbdc970)    |
| 65 entries | Still open in the archived ledger 00466 ([index](../Completed/00466-niggles-ledger-sixteen/PLAN.md))             | 00466 close-out     | ⬜ Open                 |
| N222 work  | Unfinished `tests/scaling.py` change saved from a merged branch's worktree ([saved](UNFINISHED-N252-SCALING.md)) | 00466 cleanup       | ⬜ Open                 |
| 22 entries | Carried from the dropped `worktree-n466-small-a` branch ([list](CARRIED-REFIX-BRANCHES.md))                      | 00466 cleanup       | ⬜ Open                 |
| 15 entries | Carried from the dropped `worktree-p422-close` branch ([list](CARRIED-REFIX-BRANCHES.md))                        | 00466 cleanup       | ⬜ Open                 |
| 14 entries | Carried from the dropped `worktree-d-00421` branch ([list](CARRIED-REFIX-BRANCHES.md))                           | 00466 cleanup       | ⬜ Open                 |
| 4 entries  | Carried from the dropped upgrade-scripts, 464 and N38 branches ([list](CARRIED-REFIX-BRANCHES.md))               | 00466 cleanup       | ⬜ Open                 |
| N266       | `flaggable_content_channel_guard` denies greps that never touch a flagged path                                   | Coordinator         | ✅ Fixed (ba47e2459)    |
| N265       | `secret_file_guard` spends about 2.2 s of CPU on one realistic Python program                                    | N101 CI red         | ✅ Fixed (e39b1f98f)    |
| N264       | A sub-agent's edits landed, uncommitted, in another branch's worktree                                            | 00466 landing       | ✅ Fixed (7ebef17fb)    |
| N246       | Plan and docs QA judge a same-command `git add` as two partial trees                                             | Carried, N53 branch | ⬜ Open                 |
| N245       | A pathspec commit is judged on the index as well as the named paths                                              | Carried, N53 branch | ⬜ Open                 |
| N244       | The QA commit gates judge the disk, not the tree the commit records                                              | Carried, N53 branch | ⬜ Open                 |
| N189       | No commit gate sees a commit hidden in text only bash reads (`bash -c "$X"`)                                     | Carried, N53 branch | ⬜ Open                 |
| N177       | No commit gate sees a commit after a `case` inside `function f {` in `$( )`                                      | Carried, N53 branch | ⬜ Open                 |
| N176       | No commit gate sees a commit inside `$(( $(…) ))` arithmetic                                                     | Carried, N53 branch | ⬜ Open                 |
| N135       | No commit gate sees a commit run from text, via an alias, or after `builtin cd`                                  | Carried, N53 branch | ⬜ Open                 |
| N256       | Quoted heredoc bodies are glob-walked; a hit cap reads as an evaluation error                                    | Carried from 00466  | ⬜ Open                 |
| N255       | `git commit -F - <<'EOF'` denied as an evaluation error (ENAMETOOLONG)                                           | Carried from 00466  | ⬜ Open                 |
| N254       | Two resolvers disagree on `secret_word_list_path`                                                                | Carried from 00466  | ⬜ Open                 |
| N253       | `secret_file_guard` exemptions parse options from open lists                                                     | Carried from 00466  | ⬜ Open                 |
| N263       | The release empties UNRELEASED post-upgrade tasks but not the README index                                       | v3.67.0 CI          | ✅ Remedied             |
| N262       | The release procedure has no check that the notes fit a GitHub release body                                      | v3.67.0 publish     | ✅ Remedied (ea8dcd542) |

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
