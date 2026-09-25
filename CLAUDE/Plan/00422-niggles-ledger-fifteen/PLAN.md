# Plan 00422: niggles ledger fifteen

**Status**: In Progress
**Created**: 2026-09-16
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger fourteen
([00419](../Completed/00419-niggles-ledger-fourteen/PLAN.md)) closed with eleven of its
fifteen entries terminal. The other four are re-filed here rather than counted
as terminal, because nothing downstream re-reads a closed plan: an unresolved
entry left inside an archived ledger is indistinguishable from a resolved one
to everybody except the person who wrote it.

So this ledger opens with four entries already in it, and collects the rest as
they are found. Their diagnoses are not reopened — what is inherited is the
unfinished remedy, not the finding.

**Closed to new entries.** From N30 on, niggles go to ledger sixteen
([00466](../00466-niggles-ledger-sixteen/PLAN.md)). This PLAN.md passed its
size warning with N29.

**In progress again.** The ledger was Blocked on six owner questions. They
are now decided AND built (DECISIONS.md), so the four inherited entries
(N1, N3, N4, N7) are all terminal.

**One of the four carries a class that now has three sightings**, and naming it
is a goal of this plan rather than a footnote in it. 00419's N3 (the two
plan-close gates), N12 (the three journal rules) and N13 (a declared cron that
cannot be paused for one session) are the same defect wearing three costumes: a
guard that is RIGHT about the state it judges and WRONG about the moment it
judges it. Three is a pattern. A ledger that meets it a fourth time and files it
as a fresh niggle would be repeating exactly the failure a ledger exists to
catch.

## Goals

- Record each niggle with enough evidence that someone else can reproduce it.
- Resolve each entry to a terminal state: fixed, graduated to its own plan, or
  dismissed as not-a-defect with the reasoning kept.
- Carry the four inherited entries to a terminal state rather than re-filing
  them onward a second time. An entry that crosses two ledgers unchanged is
  evidence that a ledger is the wrong container for it, and the answer then is
  to graduate it to its own numbered plan.
- Recognise the fourth sighting of the "right about the state, wrong about the
  moment" class as that class, instead of as a new finding.

## Non-Goals

- **Becoming a feature plan.** A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.
- **Re-deciding the inherited four.** 00419 assessed each of them and its
  reasoning stands; this plan owns their remedies, not their verdicts.

## Niggles

Full write-ups are in [NIGGLES.md](NIGGLES.md). One line each here so the
ledger's shape is readable without opening it:

| #   | Verdict                                                                        | Origin                                                              | Status                                                                                                                                                                                                                                                                 |
| --- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N1  | the `Priority` constants are not the numbers a fresh install ships             | [00419 N8](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)   | ✅ Decided (unattended, 2026-09-24) and built — whole-template test; four divergences found, constants won all four; `c1822548`, merged `d28b25fa`                                                                                                                     |
| N2  | the linter runs on gitignored scratch output                                   | [00419 N11](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)  | ✅ Resolved — depth-scoped exclusions shipped                                                                                                                                                                                                                          |
| N3  | a committed future-dated entry makes the journal uncorrectable                 | [00419 N12](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)  | ✅ Decided (unattended, 2026-09-24) and built — `correction` journal category; `14bdb525`, merged `d28b25fa`                                                                                                                                                           |
| N4  | a cron cannot be both cancelled for a session and declared in config           | [00419 N13](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)  | ✅ Decided (unattended, 2026-09-24) and built — session-scoped `cron-pause`/`cron-resume`; `8b388a2a`, merged `63dea9f08`                                                                                                                                              |
| N5  | the v3.65.0 release reviews' NON-defects had no durable home                   | the v3.65.0 release reviews                                         | ✅ CLOSED — all twelve rows resolved; (f) corrected, not built                                                                                                                                                                                                         |
| N6  | a worktree cannot run the acceptance gates, and says the wrong reason          | Plan 00424                                                          | ✅ CLOSED — fault 1 by Plans 00431/00443; fault 2 by Plan 00445, and it was never a worktree fault: the autouse env-isolation fixture stripped the documented `CLAUDE_HOOKS_SOCKET_PATH` workaround from every wrapper subprocess. 14.75s against a run killed at 480s |
| N7  | the supervisor's effort floor cannot see an effort set from the selector       | owner report, in session                                            | ✅ Decided (unattended, 2026-09-24) and built — an unattributed drop is latched as manual; `8ffe9ffe`, merged `63dea9f08`                                                                                                                                              |
| N8  | the socket-path guard fails open exactly where it is needed                    | in session, hours after N6 fault 1 shipped                          | ✅ Remedied by Plan 00431                                                                                                                                                                                                                                              |
| N9  | worktree isolation plus an explicit worktree instruction nests them            | in session, by causing it                                           | ✅ Remedied by Plan 00433                                                                                                                                                                                                                                              |
| N10 | a QA checker's own tests overwrite that checker's real QA artefact             | a full `llm_qa all` run's intermediate artefacts                    | ✅ Remedied by Plan 00432                                                                                                                                                                                                                                              |
| N11 | acceptance probe fixtures live in the sanctioned human scratch directory       | surfaced by N2's second failure                                     | ✅ Remedied (B1) — decided unattended as `untracked/acceptance/` (DECISIONS.md); the probe fixtures moved there                                                                                                                                                        |
| N12 | the supervisor asset has been red under its own lint gate since v3.65.0        | in session, after v3.65.0 shipped                                   | ✅ Corrected — the gate is green; no code change due                                                                                                                                                                                                                   |
| N13 | the plan-dedupe scout cleared a plan tree it never read                        | a dispatch before filing Plan 00430                                 | ✅ Remedied by Plan 00434                                                                                                                                                                                                                                              |
| N14 | four more `utils`/`docs_qa` → `plan_qa` edges, found by N5 row (h)'s fix       | the guard written for Plan 00439                                    | 🔄 Both `gitfacts` edges cleared by Plan 00444 (a split, not the move this entry assumed — `plan_counter()` IS plan-specific); the two design questions graduated to Plan 00469                                                                                        |
| N15 | the dedupe scout reported a file path for a report it never wrote              | the dispatch before filing Plan 00441                               | ✅ CLOSED by Plan 00446 — a SubagentStop handler blocks a stop claiming a path that is not on disk; neither listed remedy as written (both were costed against the wrong surface)                                                                                      |
| N16 | the failsafe cron has two zero-token defences; `issue-sdlc` has neither        | in session, on the receiving end of three consecutive no-op ticks   | ❌ SUPERSEDED — already held by Plan 00388 as graduated 00392 N1 (its Task 2.4). Filed without a dedupe check; 00388 also shows the two halves are ONE mechanism, not two gaps                                                                                         |
| N17 | a stale `paths.py` docstring produced a confident wrong verdict                | triaging issue #53, by checking a sub-agent's finding before acting | ✅ Remedy (1) SHIPPED — both resolver docstrings now name the slug filter and which steps apply it; the sibling had the same gap and said "fully usable", which was worse. Remedies (2)/(3) not taken: a test pinning prose shape is not truth                         |
| N18 | LSP.md relies on an `untracked/venv` symlink nothing creates                   | chasing a Pyright diagnostic during issue #53                       | ✅ Remedied by "Ledger 00422 N18: create and maintain untracked/lsp-venv so LSP.md's claims are true" — a new name avoids the `LEGACY_VENV` collision; ProjectContext creates/repoints it from `sys.prefix` on self-install daemon start                               |
| N19 | the Python nested-install check can never fire in a real client                | reviewing Plan 00455, whose agent copied it into `init.sh`          | ✅ Remedied by "Ledger 00422 N19: delete the pyproject.toml exemption so the nested-install cleanup fires for real clients" — cleanup is now unconditional; the destructive branch also handles a symlinked nested path and symlinks inside it                         |
| N20 | the acceptance probes cannot pass in a worktree whose daemon is running        | Plan 00456's final QA in its worktree                               | ✅ Remedied by Plan 00458. It was not a worktree fault: six guards matched skip lists as a bare substring. They now match whole path segments relative to the project, and a QA detector keeps the class out                                                           |
| N21 | nothing points a journal append at the tool that stamps the time               | the owner's question, after a session of hand-stamped entries       | ✅ Remedied by Plan 00461 — a hand-written Edit/Write/Bash journal entry is now DENIED with the `mkplan.bash --journal` command (merged `e3f03f3e`, CI green at `ce31d6d8`)                                                                                            |
| N22 | the local "full QA" never runs shellcheck                                      | verifying Plan 00456's final QA before merge                        | ✅ Remedied by "Ledger 00422 N22: wire shellcheck into llm_qa.py so full QA covers it" — `shell_check` is now a `TOOL_REGISTRY` entry wrapping `run_shell_check.sh`; a wiring test pins every `run_all.sh` script against the registry so the next gap fails a test    |
| N23 | a worktree commit is judged against the main checkout's staged tree            | Plan 00462's agent, denied over a path only main had staged         | 🔄 Graduated to Plan 00464 — a teammate's payload `cwd` is the main checkout, and the commit gates pick their repo from it, so worktree commits are wrongly denied AND their own staged content is never checked                                                       |
| N24 | orchestrator simulate reports denials its blocking mode would never make       | a Plan 00463 review corrected the coordinator                       | ⬜ Open — simulate judges "not a coordination tool" (so every `Bash` is "would have been denied") while blocking denies only `Write`/`Edit`/`NotebookEdit`; the record meant to preview enforcement overstates it                                                      |
| N25 | `pipe_blocker` names the loop keyword `do` as a pipe's producer                | a coordinator `for … do grep … \| head`                             | ✅ Remedied — shared `strip_reserved_word_prefix` primitive, 12 other sites fixed with it; `319cdd35`, merged `fb76d640`                                                                                                                                               |
| N26 | commit gates never see content staged earlier in the same command              | Plan 00464's agent, with a probe                                    | 🔄 Graduated to Plan 00465 — `git add f && git commit` passes every staged-content gate unexamined (the secret-term scan included), and a same-command `git mv` makes plan QA falsely deny                                                                             |
| N27 | a worktree daemon idles out in the middle of a full QA run                     | Plan 00461's agent                                                  | ✅ Remedied (B1) — `llm_qa` now starts an idled-out daemon before a live consumer such as `smoke_test`, so no keep-alive is needed                                                                                                                                     |
| N28 | `plan_number_helper` resolves a relative `mkdir` against the workspace root    | Plan 00461's agent                                                  | ⬜ Open — `mkdir mkj/CLAUDE/Plan/00007-probe` run from `untracked/scratch/` was denied as a plan-folder creation; same class as N23, so the fix is 00464's command-directory resolver                                                                                  |
| N29 | `write_clobber_guard` blocks a Write to a file this session created with Write | the coordinator rewriting its own gate script                       | ✅ Remedied — `matches()` fires on every Read/Edit/Write, so every allowed call is recorded; `d2ed30a4`, merged `fb76d640`                                                                                                                                             |

## Questions waiting on the owner

**All six are decided, and all six are now built.** An unattended session took
the recommended option for each and stated the assumption beside it, so the
owner can reverse any one with a single message. The original questions, the
decisions and the delivering commits are all in
[DECISIONS.md](DECISIONS.md).

## Tasks

### Phase 1: the four inherited entries

- [x] ✅ **Task 1.1**: N1 — the question is stated as question 1 under
  "Questions waiting on the owner" above, with what each answer costs. The
  divergence itself is established and needs no further investigation.

- [x] ✅ **Task 1.2**: N2 — remedy (1) shipped as three depth-scoped globs on
  `lint_on_edit.options.exclude_paths` (`/untracked/scratch/*`,
  `/untracked/qa/**`, `/untracked/worktrees/**`), so a scratch probe stops being
  linted while every file that can reach history — and every acceptance fixture
  one level down — still is.

- [x] ✅ **Task 1.3**: N3 — chosen, and the choice is neither candidate.
  Remedy (1) cannot be implemented at sweep stage (nothing in a file is a
  machine-readable future-dated flag), and remedy (2) edits the entry grammar in
  a template shipped to every client, so it is owner-gated after all. What was
  buildable and un-gated: the check's remediation opened by telling the reader
  to MOVE the entry, which `journal-append-only` forbids once it is committed.
  It now leads with the append. The cited advisory is also gone — measured, and
  by archiving rather than by any remedy.

- [x] ✅ **Task 1.4**: N4 — stated as question 2 under "Questions waiting on
  the owner" above. Until it is answered, cancelling a declared cron for one
  session has no legal spelling.

- [x] ✅ **Task 1.5**: The class, named once rather than three times, as
  "Right about the state, wrong about the moment" in
  `CLAUDE/HANDLER_DEVELOPMENT.md`: the three sightings, the separating test (is
  there ANY legal sequence of moves that reaches an allowed state?), and the
  remedy direction — move WHEN the check runs, never weaken WHAT it checks,
  because 00419 N3's stage move is the only one of the three that is fixed. A
  fourth sighting is filed against the class.

### Phase 2: the release-review carry-over

- [x] ✅ **Task 2.1**: N5 — work the twelve-row table in
  [NIGGLES.md](NIGGLES.md). Rows (a) and (d) are done by Plan 00435, which also
  found a third disagreement in the same table and left a test behind so it
  cannot drift silently again. Row (f) is corrected rather than built: the class
  it names is already guarded by the integration test that reads the real
  config. All three rows the reviewers flagged as having teeth are done: (g) by Plan
  00436, (c) by 00437 and (i) by 00438. The other rows are done too: (b) by
  Plan 00440, (e) by 00442, (h) by 00439, and (j), (k) and (l) by 00441. Every
  row is terminal, each checked against the code by the owner-a agent
  ([report](subagent-reports/260924-n422-owner-a-opus-5-5.md)).

- [x] ✅ **Task 2.2**: N5 remedy (2) — Decided (unattended, 2026-09-24) and
  built. `dispatch_declaration` and `get_claude_md` now name the dispatching
  plan's `subagent-reports/` as the DEFAULT, tracked destination; the
  gitignored `fallback_report_dir` is only for when no plan applies. Commit
  `f013ac65` (owner-a), merged `d28b25fa`.

### Phase 3: the owner-reported entry

- [x] ✅ **Task 3.1**: N7 — stated as question 3 under "Questions waiting on the
  owner" above, including the asymmetry that makes it a decision rather than an
  oversight: the downgrade logic deliberately answers the mirror-image question
  NO. The mechanism is confirmed and needs no further investigation.

### Phase 4: the entries filed after this ledger opened

N8, N9 and N10 were each remedied by their own numbered plan (00431, 00433,
00432\) and carry no task here. N12 was corrected rather than remedied: the gate
it reported as red is green, and the revised verdict is that nothing needs
changing.

- [ ] ⬜ **Task 4.1**: N11 — remedy (1) only, and it is owner-gated: may the
  acceptance fixtures move out of the human scratch directory into a dedicated
  `untracked/acceptance/` root? Remedy (2) already exists as
  `test_acceptance_contract.py`, so there is nothing to build for it.

- [x] ✅ **Task 4.2**: N13 — remedied by Plan 00434. `mkplan.bash` states the
  root plan-folder count for the dispatch to carry, the guidance says to
  re-dispatch when the report's `Checked N live plans.` disagrees, and step 3b
  is written in Grep-tool terms behind a general guard: a shell fence in any
  shipped agent that does not declare `Bash` now fails.

- [x] ❌ **Task 4.3**: N16 — **CANCELLED, nothing to do here.** The work already
  lives in [Plan 00388](../00388-failsafe-marker-wiped-by-other-crons-in-multi-cron-sessions/PLAN.md)
  Task 2.4, graduated there from Plan 00392 N1 before this entry was written.
  Leaving a duplicate task open would split one owner ruling across two plans,
  which is the failure the ledger's own dedupe convention exists to stop.

## Success Criteria

- [x] ✅ Each of the four inherited entries reaches a terminal state IN THIS
  LEDGER — fixed with a RED-first test, determined from the record, or graduated
  to its own numbered plan. Re-filing any of them into ledger sixteen is a
  failure of this criterion, not a way of satisfying it. All four (N1, N3, N4,
  N7) are Decided (unattended, 2026-09-24) and built — see DECISIONS.md and
  NIGGLES.md.

- [ ] ⬜ **Assessed when this ledger closes, not before**: every entry is
  terminal by the same test. Open while this is the current ledger, because a
  rolling ledger exists to keep collecting.

- [ ] ⬜ Every release-bound consequence is in the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/`) before the status flips, or this criterion
  says explicitly that the plan has none.

## Delivery & Milestones

- Opened because ledger fourteen closed with four entries that were not
  terminal. The house precedent is 00413, which graduated its unresolved entries
  to numbered plans rather than counting them; these four are a ledger's worth of
  work on their own, so they get a ledger.
