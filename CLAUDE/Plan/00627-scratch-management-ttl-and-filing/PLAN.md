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
- [ ] ⬜ **Task 2.5**: Add the filing proposal table (DESIGN.md section 6) to the dry-run output.

### Phase 3: The archive store and `--apply`

- [ ] ⬜ **Task 3.1**: Add the store: flat layout, mode 0700, `index.jsonl`, `flock`.
- [ ] ⬜ **Task 3.2**: Add claim-by-rename through a directory descriptor, with the fingerprint re-check and rename-back.
- [ ] ⬜ **Task 3.3**: Add pack and bidirectional verify (GNU tar by argv, `tar --compare`, member count, SHA-256, `fsync`), including the special-file skip list and the link-count refusal.
- [ ] ⬜ **Task 3.4**: Add descriptor-based removal of a claimed tree, and resumption of a leftover `.sweeping-` tree.
- [ ] ⬜ **Task 3.5**: Add batch packing of loose files by run and verdict.
- [ ] ⬜ **Task 3.6**: Add expiry by verdict retention, `restore <id>` and `keep` (bounded, reasoned, no repeated reason).
- [ ] ⬜ **Task 3.7**: Add proof P6 (adopt a tarball beside its original).
- [ ] ⬜ **Task 3.8**: Wire `--apply`, rebuilding every per-sweep git fact for the run (DESIGN.md section 5.2 step 1: tracked files, worktrees, verified tips and blobs, references). Add the crash-safety tests (a failure after each step), the escape tests and the property test of DESIGN.md section 14.
- [ ] ⬜ **Task 3.9**: Independent adversarial review of Phases 1 to 3 (data loss, link escapes, TOCTOU) before any later phase runs `--apply` outside tests. It must rule on the open reflog/`ORIG_HEAD` row of DESIGN.md section 13.

### Phase 4: The session directory convention

- [ ] ⬜ **Task 4.1**: Create and announce the per-session directory and its manifest at SessionStart. First step: confirm on a live payload what SessionStart can export to the shell.
- [ ] ⬜ **Task 4.2**: Add `hooks-daemon scratch new` (entry, birth, purpose, plan, bounded TTL).
- [ ] ⬜ **Task 4.3**: Make the session directory the TTL container: its children are the entries, and it is removed when empty and old.
- [ ] ⬜ **Task 4.4**: Add `R-SCRATCH-KEEP-MARKER` (an agent may not create `.scratch-keep`) and the KEPT verdict for it.
- [ ] ⬜ **Task 4.5**: Add the unowned-entry advisory for a new entry made directly in a scratch root.

### Phase 5: Reporting and enforcement

- [ ] ⬜ **Task 5.1**: Add the cached inventory file and its background refresh (SessionStart, after a directory-creating command, after a sweep).
- [ ] ⬜ **Task 5.2**: Add the SessionStart handler `scratch_sweep`, printed directly after `branch_sweep`: counts by verdict, overdue-to-file list, expiring archives, caps. Silent when clean; never silent when incomplete.
- [ ] ⬜ **Task 5.3**: Add the cap evaluation (warn, block, incomplete can only raise).
- [ ] ⬜ **Task 5.4**: Add `R-SCRATCH-CAP`: deny directory-creating commands into scratch at block; never a file write; the never-stranded downgrade.
- [ ] ⬜ **Task 5.5**: Add pressure mode to `--apply`.
- [ ] ⬜ **Task 5.6**: Add the must-do item through `session_actions_directive`.
- [ ] ⬜ **Task 5.7**: Add the housekeeping steps `scratch-sweep` and `scratch-sweep-apply` (unconfirmed, DESIGN.md R13) and update the Decision 6 text.
- [ ] ⬜ **Task 5.8**: Declare the sweep as a routine in this repository so a sweep that stops running is reported.

### Phase 6: Worktrees and the link index

- [ ] ⬜ **Task 6.1**: Sweep every registered worktree's scratch root; limit a sub-agent's `--apply` to its own checkout.
- [ ] ⬜ **Task 6.2**: Add evacuate mode and call it from `worktree-reap --reap` and `cleanup_after_merge` before the removal is judged (DESIGN.md section 11).
- [ ] ⬜ **Task 6.3**: After Plan 00623 merges, read the link index's listed-directory count and cap for `caps.project_directories`. Blocked on 00623.

### Phase 7: Instructions and retirement of the old report

- [ ] ⬜ **Task 7.1**: Rewrite the scratch guidance at every place DESIGN.md section 12 lists, at the `src/` originals, coordinated with Plan 00560 Task 2.1 and 2.3.
- [ ] ⬜ **Task 7.2**: Replace `stale_litter.collect_scratch_report` and retire `stale_scratch_days` with a config-changes entry.
- [ ] ⬜ **Task 7.3**: Add the docs/plan QA check that flags a tracked line citing an `untracked/` path as evidence (advisory).
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
