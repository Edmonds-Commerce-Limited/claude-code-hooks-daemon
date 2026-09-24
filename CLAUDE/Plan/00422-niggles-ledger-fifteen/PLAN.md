# Plan 00422: niggles ledger fifteen

**Status**: Blocked
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

**Blocked, not in progress.** Eleven of the fifteen rows are terminal. Every
one of the remaining four ⏸ rows is an owner question that has been stated and
is waiting for an answer (N1 scope, N4 A/B/C, N7, N11), and both 🔄 rows have
had their buildable half delivered — what is left in each is an open design
question, not work. There is no row an executor could advance without an answer
first, so the status says so: `In Progress` claimed work was moving and
misreported this ledger as mid-work to the release slate check, which is the
one reader that acts on the difference.

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

| #   | Verdict                                                                  | Origin                                                              | Status                                                                                                                                                                                                                                                                 |
| --- | ------------------------------------------------------------------------ | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N1  | the `Priority` constants are not the numbers a fresh install ships       | [00419 N8](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)   | ⏸ Owner question 1 — stated, waiting                                                                                                                                                                                                                                   |
| N2  | the linter runs on gitignored scratch output                             | [00419 N11](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)  | ✅ Resolved — depth-scoped exclusions shipped                                                                                                                                                                                                                          |
| N3  | a committed future-dated entry makes the journal uncorrectable           | [00419 N12](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)  | 🔄 Remediation fixed; (2) owner-gated, advisory expired                                                                                                                                                                                                                |
| N4  | a cron cannot be both cancelled for a session and declared in config     | [00419 N13](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)  | ⏸ Owner question 2 — stated, waiting                                                                                                                                                                                                                                   |
| N5  | the v3.65.0 release reviews' NON-defects had no durable home             | the v3.65.0 release reviews                                         | ✅ CLOSED — all twelve rows resolved; (f) corrected, not built                                                                                                                                                                                                         |
| N6  | a worktree cannot run the acceptance gates, and says the wrong reason    | Plan 00424                                                          | ✅ CLOSED — fault 1 by Plans 00431/00443; fault 2 by Plan 00445, and it was never a worktree fault: the autouse env-isolation fixture stripped the documented `CLAUDE_HOOKS_SOCKET_PATH` workaround from every wrapper subprocess. 14.75s against a run killed at 480s |
| N7  | the supervisor's effort floor cannot see an effort set from the selector | owner report, in session                                            | ⏸ Owner question 3 — stated, waiting                                                                                                                                                                                                                                   |
| N8  | the socket-path guard fails open exactly where it is needed              | in session, hours after N6 fault 1 shipped                          | ✅ Remedied by Plan 00431                                                                                                                                                                                                                                              |
| N9  | worktree isolation plus an explicit worktree instruction nests them      | in session, by causing it                                           | ✅ Remedied by Plan 00433                                                                                                                                                                                                                                              |
| N10 | a QA checker's own tests overwrite that checker's real QA artefact       | a full `llm_qa all` run's intermediate artefacts                    | ✅ Remedied by Plan 00432                                                                                                                                                                                                                                              |
| N11 | acceptance probe fixtures live in the sanctioned human scratch directory | surfaced by N2's second failure                                     | ⏸ Owner question 4 — (2) already exists                                                                                                                                                                                                                                |
| N12 | the supervisor asset has been red under its own lint gate since v3.65.0  | in session, after v3.65.0 shipped                                   | ✅ Corrected — the gate is green; no code change due                                                                                                                                                                                                                   |
| N13 | the plan-dedupe scout cleared a plan tree it never read                  | a dispatch before filing Plan 00430                                 | ✅ Remedied by Plan 00434                                                                                                                                                                                                                                              |
| N14 | four more `utils`/`docs_qa` → `plan_qa` edges, found by N5 row (h)'s fix | the guard written for Plan 00439                                    | 🔄 Both `gitfacts` edges cleared by Plan 00444 (a split, not the move this entry assumed — `plan_counter()` IS plan-specific); two design questions remain open                                                                                                        |
| N15 | the dedupe scout reported a file path for a report it never wrote        | the dispatch before filing Plan 00441                               | ✅ CLOSED by Plan 00446 — a SubagentStop handler blocks a stop claiming a path that is not on disk; neither listed remedy as written (both were costed against the wrong surface)                                                                                      |
| N16 | the failsafe cron has two zero-token defences; `issue-sdlc` has neither  | in session, on the receiving end of three consecutive no-op ticks   | ❌ SUPERSEDED — already held by Plan 00388 as graduated 00392 N1 (its Task 2.4). Filed without a dedupe check; 00388 also shows the two halves are ONE mechanism, not two gaps                                                                                         |
| N17 | a stale `paths.py` docstring produced a confident wrong verdict          | triaging issue #53, by checking a sub-agent's finding before acting | ✅ Remedy (1) SHIPPED — both resolver docstrings now name the slug filter and which steps apply it; the sibling had the same gap and said "fully usable", which was worse. Remedies (2)/(3) not taken: a test pinning prose shape is not truth                         |
| N18 | LSP.md relies on an `untracked/venv` symlink nothing creates             | chasing a Pyright diagnostic during issue #53                       | ✅ Remedied by "Ledger 00422 N18: create and maintain untracked/lsp-venv so LSP.md's claims are true" — a new name avoids the `LEGACY_VENV` collision; ProjectContext creates/repoints it from `sys.prefix` on self-install daemon start                               |
| N19 | the Python nested-install check can never fire in a real client          | reviewing Plan 00455, whose agent copied it into `init.sh`          | ✅ Remedied by "Ledger 00422 N19: delete the pyproject.toml exemption so the nested-install cleanup fires for real clients" — cleanup is now unconditional; the destructive branch also handles a symlinked nested path and symlinks inside it                         |
| N20 | the acceptance probes cannot pass in a worktree whose daemon is running  | Plan 00456's final QA in its worktree                               | ✅ Remedied by Plan 00458. It was not a worktree fault: six guards matched skip lists as a bare substring. They now match whole path segments relative to the project, and a QA detector keeps the class out                                                           |
| N21 | nothing points a journal append at the tool that stamps the time         | the owner's question, after a session of hand-stamped entries       | ⬜ Open — `mkplan.bash --journal` shipped in v3.66.0, yet an Edit/Write/heredoc append to a `JOURNAL/` file draws no advisory naming it                                                                                                                                |
| N22 | the local "full QA" never runs shellcheck                                | verifying Plan 00456's final QA before merge                        | ✅ Remedied by "Ledger 00422 N22: wire shellcheck into llm_qa.py so full QA covers it" — `shell_check` is now a `TOOL_REGISTRY` entry wrapping `run_shell_check.sh`; a wiring test pins every `run_all.sh` script against the registry so the next gap fails a test    |
| N23 | a worktree commit is judged against the main checkout's staged tree      | Plan 00462's agent, denied over a path only main had staged         | 🔄 Graduated to Plan 00464 — a teammate's payload `cwd` is the main checkout, and the commit gates pick their repo from it, so worktree commits are wrongly denied AND their own staged content is never checked                                                       |
| N24 | orchestrator simulate reports denials its blocking mode would never make | a Plan 00463 review corrected the coordinator                       | ⬜ Open — simulate judges "not a coordination tool" (so every `Bash` is "would have been denied") while blocking denies only `Write`/`Edit`/`NotebookEdit`; the record meant to preview enforcement overstates it                                                      |
| N25 | `pipe_blocker` names the loop keyword `do` as a pipe's producer          | a coordinator `for … do grep … \| head`                             | ⬜ Open — `do grep x f \| head` is blocked as producer `do`, and the fix it prints whitelists `^do\b`, which would exempt every loop body                                                                                                                              |

## Questions waiting on the owner

Six entries are blocked on a decision rather than on work. They are collected
here so the whole set can be read in one sitting: each is ONE question, with
what each answer costs and what happens while it goes unanswered. Nothing here
needs investigation first — every one has been measured.

1. **N1 — how loud may a template-versus-constants test be?** `priority.py` and
   the `init_config.py` template disagree across the whole `status_line` block
   and have for longer than the handler that surfaced it has existed; relative
   order is preserved, so nothing misbehaves and no check can see it. A
   consistency test would fix that permanently. **Does it get to fail across the
   WHOLE template, or only across the `status_line` block?** Whole-template may
   surface more than the divergence found, which is a scope call, not a bug fix.
   Unanswered: the constants keep documenting a relationship a fresh install
   cannot have.

2. **N4 — may a session suppress a cron the project declared?** Obeying an
   instruction to cancel `issue-sdlc` makes the next Stop block, because the
   enforcer refuses a session missing a declared job — correctly. The only
   existing knob (edit `persistent_crons`) stops the job for every session on
   every branch. **Is there to be a session-scoped pause, recorded through an
   expiring marker like the "blocked only on human input" one, or does
   "cancelled for now" remain unspellable?** A pause hands a session the ability
   to switch off a guard the project declared. Unanswered: the two moves stay
   mutually exclusive and whoever hits it re-derives that from two failures.

3. **N7 — is an unattributed effort drop a human choice?** A bare `/effort`
   opens Claude Code's own selector, which names nothing the supervisor can
   read, so the manual-effort latch never sets and the floor puts it back.
   **Should an effort drop the supervisor did not itself inject be trusted as
   manual and latched?** The downgrade logic deliberately answers the
   mirror-image question NO — an unattributed model change gets no restore — so
   answering YES here is a real asymmetry to accept, not an oversight to
   correct. Unanswered: setting effort from the selector keeps getting undone.

4. **N11 — may the acceptance fixtures leave the human scratch directory?** The
   lint strategies write their probe fixtures under `untracked/scratch/`, the
   same directory agents are told to use for working notes, which is what forced
   the depth-scoped exclusion N2 shipped. A dedicated `untracked/acceptance/`
   root separates them properly. **Is that move worth making?** It renames a
   path ten strategies, the playbook harness and client-facing docs all name.
   Unanswered: the coupling stays, and the next exclusion has to rediscover it.

5. **N3 — may a `correction` category be added to the journal grammar?** It is
   the only implementable remedy for the three-rule contradiction, and the
   grammar lives in `_JOURNAL_TEMPLATE_.md`, which ships to every client. **Is
   that a template change worth making?** Unanswered: nothing breaks — the
   contradiction is self-limiting, since the ordering sweep only reads live
   plans — but a correction stays illegible as a correction.

6. **N5 — should a review dispatch default to a TRACKED report destination?**
   `dispatch_declaration` currently recommends `untracked/agent-reports/`, which
   is gitignored; that is how twenty release-review non-defects came within one
   container restart of being lost. **Should the default move somewhere git can
   see?** It changes what every client project is told, not just this one.
   Unanswered: the next reviewer's evidence lands somewhere nothing durable
   reads.

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

- [ ] 🔄 **Task 2.1**: N5 — work the twelve-row table in
  [NIGGLES.md](NIGGLES.md). Rows (a) and (d) are done by Plan 00435, which also
  found a third disagreement in the same table and left a test behind so it
  cannot drift silently again. Row (f) is corrected rather than built: the class
  it names is already guarded by the integration test that reads the real
  config. All three rows the reviewers flagged as having teeth are done: (g) by Plan
  00436, (c) by 00437 and (i) by 00438. Six rows remain, and every one of them
  is a correctness-of-documentation or tidiness item rather than a defect.

- [ ] ⬜ **Task 2.2**: N5 remedy (2), owner-gated — decide whether a review
  dispatch should default to a TRACKED report destination, so a reviewer's
  evidence lands where git can see it without the coordinator remembering.
  `dispatch_declaration` currently recommends the gitignored path.

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

- [ ] ⬜ Each of the four inherited entries reaches a terminal state IN THIS
  LEDGER — fixed with a RED-first test, determined from the record, or graduated
  to its own numbered plan. Re-filing any of them into ledger sixteen is a
  failure of this criterion, not a way of satisfying it.

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
