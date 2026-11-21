# Plan 00627: scratch management ttl and filing

**Status**: In Progress
**Created**: 2026-11-19
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet for the build tasks, Opus for the Phase 3 review
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`untracked/scratch/` grew to 229,905 directories and about 2.4 GiB (3,628 top-level entries, 1,001 nested repositories or worktrees, 623 of them dirty). That pushed the secret guard's link index past its 200,000-directory cap and caused real false denials (Plan 00623). Nothing removes scratch, in the main checkout or in any worktree.

The owner asked for a full scratch management system: "scratch files should have TTL, old files MUST be filed properly or deleted. I suggest 24 hours. has value - keep (plan folder, main project script etc), no value - delete".

This plan builds it. Every scratch entry gets a 24-hour TTL. Past it, a machine check decides the entry's fate: stay (live or protected work), be filed (the sweep proposes a tracked home), or be packed into one verified archive, held, and removed. An agent's own statement that something has no value is never an input. The design, the rulings and the threat analysis are in [DESIGN.md](DESIGN.md). The rulings are settled by a fable sub-agent under the owner's delegation, 2026-11-19, and the owner may overturn any of them.

This plan is design only until the owner or coordinator starts Phase 1. No existing scratch content was deleted in writing it.

## Relationship to Plan 00560

[Plan 00560](../00560-scratch-directory-unrecorded-assets/PLAN.md) covers what should not be written to scratch (GitHub #155). This plan covers what happens to what is there. DESIGN.md section 1 has the full table. In short:

- 00560's final owner rulings stand: no fallback report store, no consumption ledger or stop gate, consume-then-remove.
- 00560's Goal 7, Phase 6 Tasks 6.1 and 6.3 (the SessionStart sweep and the `find ... -delete` rewrite) move here.
- 00560's non-goal "never delete or move automatically" and its provisional baseline exemption are overturned by the owner's words above.
- Both plans use one `scratch:` config block.

## Goals

- Every scratch entry past its TTL (24 hours by default, configurable) is filed, archived or removed, unless a machine test shows it is live or holds work that exists nowhere else.
- Removal is only ever by machine proof or after a verified archive has been held and announced. A repository or worktree that has somewhere to push (a remote, or shared history with the project) and holds unpushed commits or dirty tracked content is never packed or removed (DESIGN.md R6). A standalone repository has no special rule: the owner, 2026-11-20, "no special rules for repos ... scratch repo - i dont know what this is for but its presumably for testing stuff etc - no value". It is DISPOSABLE by proof P7, the coordinator's application of those words (DESIGN.md R7a); files beside it are judged on their own.
- Each directory directly under `untracked/` has a configurable TTL, as the owner asked on 2026-11-20: "default/configurable TTL for untracked paths: untracked-ttl: repos: * (means unlimited, never clear); scratch: 7d; other-dir: 36h". `untracked/repos` and the reference-repository roots are never swept (DESIGN.md section 4.1, R16).
- `hooks-daemon scratch-sweep` reports by default and acts with `--apply`. It runs from the housekeeping pass, a must-do item and a routine.
- A SessionStart report, and caps on directories, bytes and entries that warn and then block before the link index is affected. The link index excludes nothing.
- Scratch is written inside a per-session directory the daemon creates and marks, so each entry has an owner and a birth time.
- A worktree's scratch is evacuated safely when the worktree is reaped.
- The instructions that tell agents where to write scratch describe the session directory and the TTL.

## Non-Goals

- Deleting or moving any existing scratch content while this plan is design only.
- Moving files into tracked homes automatically. The sweep proposes; an agent or a human files (DESIGN.md R4).
- A per-file consumption ledger or a Stop gate (Plan 00560, owner ruling).
- Excluding scratch from the link index, or raising its cap.
- Branch and worktree hygiene outside scratch (Plan 00558, complete, and Plan 00594).
- The daemon's own registered stores (venvs, sockets, logs, caches). They are counted in the caps, not swept.

## Tasks

Every build task is test-first: the failing test is written and seen to fail before the code. Fake trees come from the Task 1.1 builder. No task acts on this repository's real scratch until Phase 8.

### Phase 0: Design

- [x] ✅ **Task 0.1**: Write [DESIGN.md](DESIGN.md): taxonomy, value test, TTL, archive store, caps, tooling, threats, test plan, contradictions.
- [ ] ⬜ **Task 0.2**: Fact-check DESIGN.md against the repository with `hooks-daemon-plan-fact-checker` and fold in the findings.
- [ ] ⬜ **Task 0.3**: The owner reads the rulings table (DESIGN.md section 0). Building may start before this; a ruling the owner overturns changes one section.

### Phase 1: Read-only core (no mutation anywhere)

- [x] ✅ **Task 1.1**: Add the fake-tree builder `tests/support/scratch_tree.py` (the project's helper directory) with its own tests (entries, set mtimes, links to dummy files outside the root, hard links, FIFOs, unreadable directories).
- [x] ✅ **Task 1.2**: Add the `scratch:` keys of DESIGN.md section 10 to the config model, with validation tests (bounds, `extra="forbid"`).
- [x] ✅ **Task 1.3**: Add the entry walker: per entry, directories, files, bytes, newest mtime, special files, link counts, nested `.git` markers. `lstat` only, one device, a `ScanDeadline` budget, and an explicit incomplete result.
- [x] ✅ **Task 1.4**: Add the TTL clock (DESIGN.md section 4): newest mtime, root ctime, birth time, future mtimes, maximum lifetime.
- [x] ✅ **Task 1.5**: Add liveness: process working directories (reusing `default_process_cwds`), background-process records, minimum age.
- [x] ✅ **Task 1.6**: Add the verdict type and the ordering, with proofs P1, P2 and P5 (the ones that need no git).
- [x] ✅ **Task 1.7**: Add `hooks-daemon scratch-sweep` as a dry run only: the table and `--json`. Test that a run changes no inode (snapshot before and after).
- [x] ✅ **Task 1.8**: Drop the R7 wording from the verdict code (owner, 2026-11-20). A `.git` marker stays "repository, not judged" until Task 2.1 classifies it.
- [x] ✅ **Task 1.9**: Add `scratch.untracked_ttl` and `untracked_default_ttl` (DESIGN.md section 4.1) in place of `ttl_hours` and `sweep.extra_roots`, and one root resolver (`core/untracked_roots.py`) that refuses `untracked/repos`, the reference roots and the archive store. Release note `017-scratch-sweep-dry-run-and-untracked-ttls.md` and `config-changes/v3.77.0.yaml` are in `CLAUDE/UPGRADES/UNRELEASED/`.

### Phase 2: Git proofs and references

- [x] ✅ **Task 2.1**: Classify each nested repository: registered worktree, outside-pointing `.git` file, related, standalone, linked inside (DESIGN.md section 3.3). A standalone repository is DISPOSABLE by P7 (R7a); git runs in a nested repository take no locks and run no hooks or fsmonitor.
- [x] ✅ **Task 2.2**: Add the related-repository tests: dirty tracked content, stash, ref tips proved against the main repository's objects and remote-held refs. A git failure or timeout is STUCK.
- [x] ✅ **Task 2.3**: Add proof P3 (identical copy by blob hash, hashed in-process with `O_NOFOLLOW`, bounded per sweep by files and bytes) and P4 (clean pushed clone).
- [x] ✅ **Task 2.4**: Add the reference set (exact path, HEAD and unmerged branch tips) and the REFERENCED verdict.
- [x] ✅ **Task 2.5**: Add the filing proposal table (DESIGN.md section 6) to the dry-run output.

### Phase 3: The archive store and `--apply`

- [x] ✅ **Task 3.0**: Prerequisite for Tasks 3.8 and 3.9. Close DESIGN.md section 13 rows N1 (alternates lender PROTECTED), N2 (`--separate-git-dir`), N3 (venv layout and `_is_venv`), N4 (`./` and `//` sub-root spelling) and the reflog/`ORIG_HEAD` row, test-first (a failing test per row, then the fix). From the 261120 re-review: Phases 1-2 are safe to merge as a dry run only; DISPOSABLE is not yet safe to act on.
- [x] ✅ **Task 3.1**: Add the store: flat layout, mode 0700, `index.jsonl`, `flock`.
- [x] ✅ **Task 3.2**: Add claim-by-rename through a directory descriptor, with the fingerprint re-check and rename-back.
- [x] ✅ **Task 3.3**: Add pack and bidirectional verify (GNU tar by argv, `tar --compare`, member count, SHA-256, `fsync`), including the special-file skip list and the link-count refusal.
- [x] ✅ **Task 3.4**: Add descriptor-based removal of a claimed tree, and resumption of a leftover `.sweeping-` tree.
- [x] ✅ **Task 3.5**: Add batch packing of loose files by run and verdict.
- [x] ✅ **Task 3.6**: Add expiry by verdict retention, `restore <id>` and `keep` (bounded, reasoned, no repeated reason).
- [x] ✅ **Task 3.7**: Add proof P6 (adopt a tarball beside its original).
- [x] ✅ **Task 3.8** (depends on Task 3.0): Wire `--apply`, rebuilding every per-sweep git fact for the run (DESIGN.md section 5.2 step 1: tracked files, worktrees, verified tips and blobs, references). Add the crash-safety tests (a failure after each step), the escape tests and the property test of DESIGN.md section 14.
- [ ] ⬜ **Task 3.9** (depends on Task 3.0): Independent adversarial review of Phases 1 to 3 (data loss, link escapes, TOCTOU) before any later phase runs `--apply` outside tests. It must review the Task 3.0 fixes for the N1-N4 and reflog/`ORIG_HEAD` rows of DESIGN.md section 13. Review fixes landed (DESIGN.md section 13, Task 3.9 rows): D-EXEC 1-3, D-PATH F1 and F2, and a malformed TTL refusing its root (section 4.1) are closed; F-BYPS F1 is closed at first-level roots and OPEN for a borrower in another first-level root or `untracked/repos`; F-BYPS F2 is held by the interim TTY-confirm gate on `--apply`, whose removal is an owner decision after Tasks 4.4 and 5.2.
- Fixes after Task 3.9 (DESIGN.md section 13, fix A and fix B rows): fix A identifies a claim by device, inode and birth time (no birth time: no claim, fail closed); fix B refuses any entry holding an inode whose uid or gid is not the effective user's. Both await the independent security review.
- [x] ✅ **Task 3.10**: Add `scratch-sweep status`: list the live archives (id, original path, verdict, effective expiry with keeps applied, reusing the expiry module's computation). Read-only: it never creates the store and takes no lock it does not need.

### Phase 4: The session directory convention

- [x] ✅ **Task 4.1**: Create and announce the per-session directory and its manifest at SessionStart. First step: confirm on a live payload what SessionStart can export to the shell. Built as `core/scratch_session.py` and the SessionStart handler `scratch_sweep`; no export (DESIGN.md section 7).
- [x] ✅ **Task 4.2**: Add `hooks-daemon scratch new` (entry, birth, purpose, plan, bounded TTL). Built as `cmd_scratch_new` in `daemon/cli.py`; a never-cleared scratch root bounds the TTL by `scratch.max_ttl_hours`.
- [x] ✅ **Task 4.3**: Make the session directory the TTL container: its children are the entries, and it is removed when empty and old. Done: never packed whole (step 1), children judged per session sub-root with container holds carried down (step 2), `--apply` archives and restores each due child individually with the directory identity checked fail-closed (step 3), an empty old session directory is removed under the `new_entry` flock (step 4); DESIGN.md section 13.
- Fixes after the Phase 4 reviews (DESIGN.md section 13, Phase 4 review rows): an entry that is itself a mount point is refused by `walk_tree` (D-PATH); a session `.scratch-keep` added after classification, or a session name no longer a directory at the hold, holds its children (F-BYPS); the deletion-surface inventory now covers every scratch-removal importer and `scratch_session.py`, matching `os.`/`shutil.` calls only.
- [x] ✅ **Task 4.4**: Add `R-SCRATCH-KEEP-MARKER` (an agent may not create `.scratch-keep`) and the KEPT verdict for it.
- [x] ✅ **Task 4.5**: Add the unowned-entry advisory for a new entry made directly in a scratch root. Built as the PreToolUse handler `scratch_unowned_entry` (`scratch.sweep.unowned_entry` injected as `_scratch`; `block` denies under R-SCRATCH-UNOWNED-ENTRY). Known gap: the Bash write scan does not report `mkdir` or `touch`, so those make an entry unseen.

### Phase 5: Reporting and enforcement

- [x] ✅ **Task 5.1**: Add the cached inventory file and its background refresh (SessionStart, after a directory-creating command, after a sweep). `core/scratch_inventory.py` (atomic write, read-as-problem, refresh lock, last `CapLevel` fed forward as `previous`); refreshed at SessionStart (`cli.start_scratch_inventory_refresh`), after `scratch-sweep --apply`, and after a Bash command that creates a directory under the scratch root (PostToolUse `scratch_inventory_refresher`, detector `utils/scratch_dir_creation.py`, shared with Task 5.4). A dry run does NOT write it: `TestReadOnly` contracts the dry run as changing no inode.
- [x] ✅ **Task 5.2**: Add the SessionStart handler `scratch_sweep`, printed directly after `branch_sweep`: counts by verdict, overdue-to-file list, expiring archives, caps. Silent when clean; never silent when incomplete. `render_inventory_report` in the existing handler (same priority 56 as `branch_sweep`; the chain's name tie-break orders it directly after, and `git_upstream_checker` at 56 is a slow sweep sorted last: `test_scratch_sweep_order.py`).
- [x] ✅ **Task 5.3**: Add the cap evaluation (warn, block, incomplete can only raise). `core/scratch_caps.py` `evaluate_caps`; pure, not yet wired to an inventory (5.1) or a report (5.2).
- [x] ✅ **Task 5.4**: Add `R-SCRATCH-CAP`: deny directory-creating commands into scratch at block; never a file write; the never-stranded downgrade. PreToolUse `scratch_cap_guard` (priority 19) reads the cached inventory only; advises in `caps.mode: advise` (this repository, until Task 8.3) and when only LIVE/KEPT/PROTECTED entries keep scratch over the block cap. `utils/scratch_dir_creation.scratch_roots` adds the configured sweep root, which the refresher now watches too.
- [x] ✅ **Task 5.5**: Add pressure mode to `--apply`. `scratch_archive_apply.Pressure`/`pressure_for`: only when the cached inventory's caps are at block and the root has a TTL; packs not-yet-due DISPOSABLE/UNCERTAIN entries idle for `pressure_idle_minutes`, due entries first then largest directory count; the archive's expiry adds the TTL's remainder. Every other rule (complete classification, fresh liveness/references, the claim, the TTY gate) is unchanged.
- [x] ✅ **Task 5.6**: Add the must-do item through `session_actions_directive`. `ScratchSweepHandler` is now `SessionStartVerifiable` (declared INFO); its read-only `verify_still_needed` (`sweep_action_required`) is true while an entry is due or a cap is at warn, which puts it on the must-do list. A missing inventory adds no item.
- [x] ✅ **Task 5.7**: Add the housekeeping steps `scratch-sweep` and `scratch-sweep-apply` (unconfirmed, DESIGN.md R13) and update the Decision 6 text. Interim (coordinator ruling): while `--apply` refuses without a terminal, `scratch-sweep-apply` is a report-only advisory step (the dry run, and the apply command for a human); it becomes the unconfirmed mutating step only when the owner removes the TTY gate.
- [x] ✅ **Task 5.8**: Declare the sweep as a routine in this repository so a sweep that stops running is reported. `CLAUDE/Routine/00004-scratch-sweep/` (schedule, 7 days, grace 3 days; cadence chosen by the implementing agent, owner to confirm); `hooks-daemon routine-qa` reports it as never run until the first run is recorded.

### Phase 6: Worktrees and the link index

- [x] ✅ **Task 6.1**: Sweep every registered worktree's scratch root; limit a sub-agent's `--apply` to its own checkout. (Dry run from the main checkout reports every other registered worktree's root; `--apply` from a registered linked worktree acts on that checkout's own root only and packs into the main store; `restore`/`keep` stay main-only; TTY gate unchanged. The CLI cannot tell a sub-agent apart, so the limit is structural: every `--apply` is held to the checkout it runs in.)
- [ ] ⬜ **Task 6.2**: Add evacuate mode and call it from `worktree-reap --reap` and `cleanup_after_merge` before the removal is judged (DESIGN.md section 11).
- [ ] ⬜ **Task 6.3**: After Plan 00623 merges, read the link index's listed-directory count and cap for `caps.project_directories`. Blocked on 00623 (still unmerged at Phase 6 handoff 7).

### Phase 7: Instructions and retirement of the old report

- [ ] ⬜ **Task 7.1**: Rewrite the scratch guidance at every place DESIGN.md section 12 lists, at the `src/` originals, coordinated with Plan 00560 Task 2.1 and 2.3.
- [x] ✅ **Task 7.2**: Replace `stale_litter.collect_scratch_report` and retire `stale_scratch_days` with a config-changes entry. The idle advisory's `scratch_sweep_report` reads the cached inventory only (due entries by verdict, the `scratch-sweep` dry run; never a walk, never a delete); the age walk is gone from `stale_litter`; `removed` entry in the v3.77.0 manifest; the example config drops the key.
- [x] ✅ **Task 7.3**: Add the docs/plan QA check that flags a tracked line citing an `untracked/` path as evidence (advisory). Docs QA check `untracked-evidence-citation` (EDIT, ADVISE, never blocks): a markdown line new in the edit, outside a fence, naming an `untracked/` file plus an evidence word; table row in `DocumentationStrategy.core.md` (both copies).
- [ ] ⬜ **Task 7.4**: Write the handler guidance, the docs and the entries in `CLAUDE/UPGRADES/UNRELEASED/` (release notes, config-changes).

### Phase 8: Dogfood on this repository

- [ ] ⬜ **Task 8.1**: Run the dry run on the real backlog and journal the table's totals by verdict. The owner sees it before anything is applied.
- [ ] ⬜ **Task 8.2**: File what the report marks overdue to file for live plans; list the PROTECTED clones for the owner.
- [ ] ⬜ **Task 8.3**: Run `--apply`, journal the before and after directory counts, and confirm the link index builds under its cap.
- [ ] ⬜ **Task 8.4**: Close the contradictions of DESIGN.md section 15 and the niggle that points at them.

## Success Criteria

- [ ] On a fake tree, every row of DESIGN.md sections 3.1 to 3.3 has a test, and the property test passes: `--apply` never changes a path that a fresh classification calls LIVE, KEPT or PROTECTED.
- [ ] A failure injected after each step of the removal order leaves the original or a verified archive, and a second run converges.
- [ ] No link is followed: the escape tests leave every outside dummy file untouched.
- [ ] A dry run changes no inode.
- [ ] A related repository (a remote, or shared history) with unpushed commits or dirty tracked content is never packed or removed, including when its own remote refs claim otherwise and when the remote cannot be reached. A standalone repository is DISPOSABLE by P7 (R7a) and covers nothing beside its own root, and one marker of another kind in the same entry decides the entry.
- [ ] No sweep root is, or lies inside, `untracked/repos`, a reference-repository root or the archive store, whatever `scratch.untracked_ttl` says; a malformed TTL falls back to the key's default with a warning and is never read as `"*"`.
- [ ] The cap guard denies a directory-creating command at the block cap and never denies a commit or journal body file.
- [ ] No code path and no printed suggestion deletes on age alone.
- [ ] After the dogfood run this repository's scratch is under the warn caps, or the report names each protected entry that keeps it above.
- [ ] Release notes and config-changes entries are recorded in the pending-release holding area `CLAUDE/UPGRADES/UNRELEASED/`.
- [ ] An independent adversarial review of the removal path passes.

## Delivery & Milestones

- Design written: [DESIGN.md](DESIGN.md), rulings R1 to R16 (R7 overturned by the owner).
