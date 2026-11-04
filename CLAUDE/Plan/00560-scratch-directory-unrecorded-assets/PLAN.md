# Plan 00560: scratch directory unrecorded assets

**Status**: In Progress
**Created**: 2026-11-03
**Owner**: dev
**Priority**: High
**GitHub Issue**: #155 (related: #152)
**Recommended Executor**: Opus for Phase 1 design, Sonnet for the build tasks
**Execution Strategy**: Sub-Agent Orchestration

## Overview

**The class: an unrecorded asset.** Valuable work (research, a review, a design, a decision pending with the owner, a sub-agent report, a diagnostic change) kept only where git does not carry it to the remote. #155 found about 237 such files among about 272,000 scratch files in one project, and three near-losses in one week.

**The rule: the scratch directory holds only short-lived files consumed in the same session.** That means commit and PR message bodies, journal body files, issue bodies, agent briefs and captures that are read back. Anything worth keeping goes where git carries it: a plan folder, a journal entry, a commit on a pushed branch, an issue or a PR comment.

Today the daemon itself steers the other way ([CODE-FACTS.md](CODE-FACTS.md), with citations):

- `project_containment` calls `untracked/scratch/` durable (F1).
- `markdown_organization` allows markdown anywhere under `untracked/` (F2).
- `dispatch_declaration` accepts any path, ignored or not, as a non-plan destination (F3).
- `subagent_report_persistence` keeps every reply only in an ignored, pruned store (F4).
- The only scratch report suggests `find ... -delete` on age alone (F6).
- Nothing judges scratch at a stop (F7).

**Why content cannot decide.** You cannot tell scratch from an asset by reading the file: headings, length and words like "report" are trivially gamed, and journal and PR bodies have them too. The robust signals are **consumption** (did a later command use the file as input?), **shape** (is it a known short-lived kind?) and **age**.

**This repository is the first test case.** The coordinator writes briefs, issue bodies, commit and journal bodies and QA captures under `untracked/scratch/`, and `untracked/worktrees/` holds its worktrees. Measured at plan time (F10): 90,346 files, 1.4 GB, with sub-agent reports in `untracked/briefs/` and `untracked/agent-reports/`. The design must keep the legitimate traffic friction-free and still catch the reports.

## Mapping the issue's requested items

| #155 item                                                         | Owner          | Where                                                  |
| ----------------------------------------------------------------- | -------------- | ------------------------------------------------------ |
| 1. Consumption ledger and Stop/SubagentStop gate                  | **dropped**    | Owner ruling; replaced by Goal 8 (consume-then-remove) |
| 2. Scratch-shape allowlist, registered stores, PreToolUse deny    | this plan      | Goal 6; Phase 5                                        |
| 3. Stop steering (`project_containment`, `markdown_organization`) | this plan      | Goal 1; Phase 2                                        |
| 4. `dispatch_declaration`: an ignored path is not a declaration   | this plan      | Goal 2; Phase 3                                        |
| 5. `subagent_report_persistence` is a crash net, never the record | this plan      | Goal 3; Phases 3 and 6                                 |
| 6. `git worktree remove --force` of a worktree holding work       | **Plan 00558** | 00558 Goal 10 (Task 4.1); patch-then-remove is Goal 12 |
| 7a. SessionStart: scratch survivors, earlier sessions' unconsumed | this plan      | Goal 7; Phase 6                                        |
| 7b. SessionStart: unpushed local branches, dirty worktrees        | **Plan 00558** | 00558 Goals 2 (sweep report) and 6 (Stop guard)        |

This plan does not duplicate items 6 and 7b. Where the two plans meet, they share one design: see the dependency below.

## Dependency on Plan 00558

**Reduced:** the owner dropped this plan's stop gate, and 00558 is Complete with its guards built, so what remains shared is the sweep placement and principle text (DESIGN.md section 9). The original text follows for the record.

Two new gates will judge a stop: 00558's branch guard (its Goal 6, DESIGN.md section 6) and this plan's scratch gate (Goal 5). They must share one design for:

- **registration**: two handlers, or one Stop handler with two checks;
- **priority**: 00558 places its guard after the priority-9 recorders and before `auto_continue_stop` (10 in this project), and after `subagent_handoff_gate` (11) on SubagentStop;
- **message shape**: one deny listing every finding with the same three choices, and the shared principle text (00558 DESIGN.md section 12, `BRANCH_LIMIT_PRINCIPLE`), extended to say that a file in scratch is not a record;
- **the never-strand rule**: the `MAX_STOP_BLOCKS` pattern, the usage-pause and release-state exemptions, and the handoff path.

The two SessionStart sweeps (00558 Goal 2, this plan's Goal 7) should also print as one housekeeping block. Whichever plan builds its gate first writes the shared piece; the other reuses it. Task 1.3 settles this with 00558's owner before either gate is built.

## Goals

1. **The guidance says scratch is consumed-only.** `project_containment` (source, deny text, guidance) and `markdown_organization` stop presenting the ignored root as a home for durable work. `markdown_organization` allows only scratch shapes there. Every doc that mentions `untracked/scratch` agrees.
2. **An ignored path is not a dispatch declaration.** `dispatch_declaration` stops counting a destination under an ignored path (or outside the repository) as declared. There is no non-plan fallback store (owner, Q1): an agent with a durable report and no plan folder stops and asks for one.
3. **Persisted replies are a crash net, never the record.** At SubagentStop, a concrete plan-folder file the dispatch named must exist. At SessionStart, replies refused for that and then let go are reported before retention prunes them (reduced, DESIGN.md D6).
4. ~~A consumption ledger.~~ **Dropped** by owner ruling (JOURNAL/2026-11-04/094151Z-decision-b2519a.md).
5. ~~A Stop and SubagentStop gate.~~ **Dropped** by the same ruling.
6. **A scratch-shape whitelist.** A new file under the ignored root that is not a configured scratch shape inside the scratch directory is denied at PreToolUse, through `Write` and Bash-authored writes. The deny names the tracked home for the file's kind; content signals choose only that suggestion, never the verdict (DESIGN.md D4).
7. **A SessionStart sweep.** It reports scratch survivors older than a configured age (24 hours by default) with three choices: use it now, move it to a tracked home, or delete it. It replaces the delete-everything suggestion of the Plan 00470 stale-scratch report and prints beside 00558's branch sweep.
8. **Consume, then remove (owner).** A listed command that consumes a scratch file (`git commit -F`, `gh ... --body-file`, `mkplan.bash --journal`, ...) must chain `&& rm <file>`; the unchained form is denied (DESIGN.md section 7).

## Non-Goals

- Anything about branches and worktrees: forced worktree removal, unpushed branches, dirty worktrees and evacuate-then-destroy are Plan 00558's.
- Judging a file by its content. Content picks the suggested home; it never decides the verdict.
- Deleting or moving any file automatically. Every gate and sweep names the choices; the agent or a human acts.
- Triaging this repository's existing backlog by hand inside this plan. The plan provides the tools; Q4 decides how the backlog is handled.
- Changing what the daemon writes to its own runtime files under `untracked/` (sockets, logs, caches). Those are registered stores.

## Design

The questions are in [DESIGN-QUESTIONS.md](DESIGN-QUESTIONS.md); the decisions are in [DESIGN.md](DESIGN.md). D1 and D2 are dropped and D3 reduced by owner ruling; D4, D5 and the sweep rest on the stand-in's provisional rulings; D6 is reduced by Q1; the config surface is one top-level `scratch:` block.

## Tasks

### Phase 1: Design

- [x] ✅ **Task 1.1**: Settle D1 to D3 in [DESIGN.md](DESIGN.md). D1 and D2 dropped, D3 reduced to age-only, by owner ruling.
- [x] ✅ **Task 1.2**: Settle D4 to D6 and the config surface in [DESIGN.md](DESIGN.md): name-pattern whitelist, `untracked/` root, reduced D6, one `scratch:` block, consume-then-remove rule.
- [ ] ⬜ **Task 1.3**: Agree the shared Stop/SubagentStop design with Plan 00558. Open: the stop gate is dropped and 00558 is Complete, so the coordinator decides whether this closes as reduced (DESIGN.md section 9).
- [ ] 🚫 **Task 1.4**: Decide the modes and rollout (Q5) and the backlog (Q4). Blocked on the owner: Q5 is open; Q4 has a provisional stand-in answer (DESIGN.md section 6).
- [x] ✅ **Task 1.5**: Fact-check CODE-FACTS.md and DESIGN.md against the repository and fold in the findings (done inline, not by a dispatched checker; see the journal).

### Phase 2: Guidance stops steering into scratch (TDD; items 3 and 5's wording)

Cheap changes that stop the steering before any gate exists.

- [ ] ⬜ **Task 2.1**: `project_containment`: the source comment, rule `fix`/`verbose`, deny suffix and guidance (F1) say the scratch directory is for consumed, short-lived files, and that durable work goes to a plan folder, a journal, a pushed commit or an issue.
- [ ] ⬜ **Task 2.2**: `markdown_organization`: `untracked/` is no longer a general markdown home. Only the scratch shapes are allowed, through the shared predicate (DESIGN.md D4), behind a migration-safe option (F2).
- [ ] ⬜ **Task 2.3**: Sweep every doc, agent or skill definition and shipped template that mentions `untracked/scratch` (F10: 32 under `CLAUDE/`, `.claude/` and `CLAUDE.md`, plus 11 under `src/`, `README.md` and two `docs/guides/` files) so none calls it a place to keep work. Edit the `src/` originals of deployed skills, not only the `.claude/skills/` copies.

### Phase 3: Dispatch declarations and persisted replies (TDD; items 4 and 5)

- [ ] ⬜ **Task 3.1**: `dispatch_declaration`: a destination under a configured ignored root or outside the repository is not a declaration, in advisory and strict mode alike. The contract text drops the gitignored fallback and says a plan-less durable report stops and asks (Q1, F3).
- [ ] ⬜ **Task 3.2**: Extend `subagent_report_path_verifier` to refuse a SubagentStop whose dispatch prompt (read from the agent transcript, D6) named a plan-folder file that does not exist (F5).
- [ ] ⬜ **Task 3.3**: `subagent_report_persistence` guidance and docstring say it is a crash net, never the record (F4).

### Phase 4: Consume, then remove (TDD; item 1 as reduced by the owner)

- [x] ❌ **Task 4.1**: PostToolUse consumption ledger. Cancelled by owner ruling (094151Z entry).
- [x] ❌ **Task 4.2**: Stop and SubagentStop gate for unconsumed files. Cancelled by the same ruling.
- [ ] ⬜ **Task 4.3**: Add `scratch_consume_chain`: deny a listed consumer of a scratch file not followed by `&& rm <file>` (DESIGN.md section 7).

### Phase 5: Scratch-shape whitelist deny (TDD; item 2)

- [ ] ⬜ **Task 5.0**: Add the `scratch:` config block and the shared `utils/scratch_shapes.py` predicate (DESIGN.md D4, section 8).
- [ ] ⬜ **Task 5.1**: Add the PreToolUse deny for a `Write` that creates a non-shape file under the ignored root. The suggested tracked home is chosen from the file's kind.
- [ ] ⬜ **Task 5.2**: Extend the deny to Bash-authored writes (redirect, `tee`, heredoc) through `get_written_file_paths`.

### Phase 6: SessionStart sweep (TDD; items 5 and 7a)

- [ ] ⬜ **Task 6.1**: Add the SessionStart sweep: survivors older than the configured age, each with the three choices, files before the baseline counted only. It must be time-bounded, entry-capped and silent when clean, reusing `stale_litter`'s scan budget.
- [ ] ⬜ **Task 6.2**: Report saved replies that Task 3.2 refused and then let go, before retention prunes them (Goal 3, reduced D6).
- [ ] ⬜ **Task 6.3**: Replace the `find ... -delete` suggestion in `stale_litter.collect_scratch_report` (F6) with the three choices, and print the sweep beside 00558's branch sweep.

### Phase 7: Ship

- [ ] ⬜ **Task 7.1**: Write the handler guidance and docs, and add the sweep to the `/hooks-daemon housekeeping` step.
- [ ] ⬜ **Task 7.2**: Add release notes and config-changes manifest entries in the pending-release holding area `CLAUDE/UPGRADES/UNRELEASED/`.
- [ ] ⬜ **Task 7.3**: Dogfood on this repository: run the sweep, act on what it finds per Q4, and confirm the gate and deny fire on a live session.
- [ ] ⬜ **Task 7.4**: Comment on #155 with what shipped, and point items 6 and 7b at Plan 00558.

## Open questions for the owner

A plain-language version of these questions, for the owner to answer, is in [OWNER-DECISIONS.md](OWNER-DECISIONS.md).

**Status (DESIGN.md section 0):** Q1 decided by the owner (no fallback store). Q2 and Q7 moot (ledger dropped). Q3, Q4, Q6 and the name whitelist: provisional stand-in answers (223017Z entry), overturnable by the owner. **Q5 open, owner only.**

- **Q1. The non-plan fallback for a dispatch.** Options: a configured tracked directory (for example `CLAUDE/AgentReports/`), a GitHub issue or PR comment, or none (plan-less dispatches must name an issue). **Recommended:** a configured tracked directory, unset by default. While it is unset, a plan-less dispatch must name a plan folder or an issue, and the contract text says so.
- **Q2. Does a `Read` of a file count as consumption?** **Recommended:** yes, because a capture is meant to be read back. It is safe only because Goal 6 stops a non-scratch shape being created in the first place (D1).
- **Q3. Scope of the ignored root.** Options: `untracked/` only, or every gitignored path (`git check-ignore`). **Recommended:** configured roots, default `untracked/`; widen later if field reports show assets elsewhere.
- **Q4. This repository's backlog (90,346 files, 1.4 GB).** **Recommended:** the first sweep writes a baseline listing (tracked, in this plan's folder). Later sweeps report only files outside the baseline plus the baseline's count. The owner triages the `*-report.md` files in `untracked/briefs/` and `untracked/agent-reports/` once, by hand, into plan folders or issues.
- **Q5. Rollout mode.** **Recommended:** the gate and the deny ship as `advise` in the model default for one release, then `block`. This repository runs `block` from the start to dogfood it, matching 00558's rollout (DESIGN.md section 9).
- **Q6. The age threshold.** The existing report uses 14 days; #155 asks for 24 hours. **Recommended:** 24 hours for the new sweep. The 14-day option is retired and its config key mapped onto the new one with a config-changes manifest entry.
- **Q7. Whose files does a main-thread Stop judge?** **Recommended:** the files created by the session's main thread plus its sub-agents' files that are still unconsumed. A SubagentStop judges only that agent's own files. This matches 00558's split (DESIGN.md section 6).

## Success Criteria

- [ ] `project_containment` and `markdown_organization` no longer call the scratch directory durable or a general markdown home. Tests in `tests/unit/handlers/pre_tool_use/test_project_containment.py` and `test_markdown_organization.py` assert the new wording, and assert that a non-shape `.md` under `untracked/` is denied while `untracked/scratch/journal-1.md` is allowed.
- [ ] A "not plan work" dispatch whose only destination is under `untracked/` or `/tmp` is undeclared in advisory and strict mode. Tested in `tests/unit/handlers/pre_tool_use/test_dispatch_declaration.py`.
- [ ] A SubagentStop whose dispatch named a plan-folder file that does not exist is refused. Tested in `tests/unit/handlers/subagent_stop/test_subagent_report_path_verifier.py`.
- [ ] Each listed consumer of a scratch file (`git commit -F`, `git merge -F`, `git tag -F`, `gh ... --body-file`, `gh release --notes-file`, `mkplan.bash --journal`) is denied without a `&&`-chained `rm` of that file and allowed with one; a tracked `-F` file is never judged. Tested per consumer.
- [ ] A non-shape file created under the ignored root is denied via `Write`, a redirect, `tee` and a heredoc; each whitelisted shape and an existing file are allowed. Tested per route.
- [ ] The SessionStart sweep reports old survivors with the three choices, counts files before the baseline without listing them, and stays silent on a clean tree. No suggested command deletes in bulk. Tested, including the scan budget.
- [ ] Saved replies refused by Task 3.2 and then let go are reported before pruning. Tested.
- [ ] The shared Stop design with Plan 00558 is recorded in both plans' DESIGN.md.
- [ ] Release notes and config-changes entries are recorded in `CLAUDE/UPGRADES/UNRELEASED/` (the pending-release holding area).
- [ ] GitHub #155 is commented on with what shipped and closed.

## Delivery & Milestones

- Plan written: issue #155 mapped, code facts in [CODE-FACTS.md](CODE-FACTS.md).
- Phase 1 design written ([DESIGN.md](DESIGN.md)); Task 1.3 and Q5 open.
