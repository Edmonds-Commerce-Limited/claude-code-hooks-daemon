# PR 251 independent security review (deletion code) - Plan 00627

Scope: `git diff origin/main...HEAD` in /workspace/untracked/worktrees/plan-00635-host-seat-lane-guard
(13 src files, 11 test files, DESIGN.md, NIGGLES N732-N735, release note 106).
Probes: /workspace/untracked/scratch/s-20261121T111743Z-0a12d28f/rev251/probes/ (outputs: p_resume.out, p_xsf.out beside them).
Nothing was run with --apply against real scratch or worktrees.

## Verdict

REQUEST CHANGES (small). One PR-introduced weakening of fail-closed (F2): the new packed_at filter can
drop the only valid record, and a PARTLY removed tree is then renamed back under its original name.
On main the same sequence finishes the removal against the verifying archive (probe p2 rerun with the
filter neutralised: `removed`, partial=True). It needs a wall-clock step back between claim and pack plus a
crash mid-removal, and the removed files stay restorable from the archive until its hold ends, so the risk
is low; but the fix is a few lines. Not safe to merge as-is if "nothing weakens fail-closed" is the bar;
safe to merge if F2 is fixed or explicitly accepted and filed. Everything else in the diff only adds holds
or refusals; no other path deletes earlier than main or removes what main kept.

Counts: 0 critical, 0 high, 1 medium (F2, CONFIRMED, PR-introduced), 1 low (F1, mechanism CONFIRMED,
pipeline reachability PLAUSIBLE), 1 low (F3, PLAUSIBLE), 3 info/suggestions.

Evidence basis: findings 2, 3 and 5 were tested with real-filesystem probes (probes/). Items 1, 4 and 6 were
verified by reading the code plus the PR's own tests (525 passed), not by a separate experiment. The claims
"forged/unparseable times refuse" and "evacuation's later pack refuses" are from code reading / the handoff,
not probed.

Checks: black, ruff, mypy clean on all changed files (mypy: 13 src files, no issues).
Targeted tests: 525 passed, 3 skipped (bind mount, chattr, xz unavailable) across the 11 changed test files.
Release note 106: numbering correct (main ends at 105; open PRs are #251 and dependabot #220). Accuracy: its
"accepts only an archive packed after that claim was recorded" is slightly overstated (F1: after the EARLIEST
covering claim), and it does not say a partly removed tree can be renamed back (F2).
DESIGN.md rows: honest; residuals stated (narrowed-not-closed for finding 4; owner question for N735).

## Question-by-question

1. objects/ UNCERTAIN + unreadable pointer STUCK. `in_object_store` runs before every proof in
   `_coverage`, so it can only turn a covered node uncovered (DISPOSABLE -> UNCERTAIN, 12 h -> 168 h).
   `uncovered_nodes` returning None makes `_with_p3` return the judgement unchanged (no P3). `_with_dependencies`
   now STUCKs UNCERTAIN as well as DISPOSABLE; `_carried_down` still early-returns for non-actionable rows,
   so PROTECTED/KEPT/LIVE are never rewritten. Node paths are root-relative with the entry first, so a bare
   entry (`e/HEAD`) and an `objects` symlink are both caught. Nothing deletes earlier; nothing kept is now removed.
2. Resume filter. Inode reuse and forged-time attacks fail (birth required; unparseable/naive times refuse).
   Two weaknesses remain: F1 and F2 below.
3. xattrs/sparse (real files on this host's btrfs, compress=zstd): file, dir and entry-root `user.*` xattrs,
   tail-sparse, middle-sparse and mode-000 sparse files all REFUSED; dense, empty and compressed dense files
   PACKABLE (btrfs reports logical st_blocks; SEEK_HOLE decides). Refusal paths: pack -> PackRefused -> release
   (rename back); apply pre-claim -> outcome refused; remove `_prove` -> RemoveRefused -> left claimed; resume ->
   tries next record then rename back; batch `_loose_node` -> BatchRefused. None deletes. Evacuation still uses
   only `refuse_foreign_owner`, but the pack after it refuses. ACLs/`security.capability` remain (N732, filed).
4. `reap_worktree`: `blockers_fn` is required and is the last call before `git worktree remove`
   (worktree_reaping.py:515-524); a blocker returns `blocked=True` and cmd_worktree_reap prints KEEP and
   continues (cli.py:11255-11258); an exception from it propagates before the remove. `worktree_blockers` fails
   closed on git errors. Correctly described as narrowing only.
5. Open descriptors (real /proc): fd open, deleted-but-open, mmap-only and a bare directory fd inside the entry
   all read as in use; idle entry not. The check runs AFTER the claim rename (scratch_archive_claim.py:415), so a
   new open by path cannot follow; an fd opened later through a pre-held directory fd is the stated residual.
   Mount-namespace case could not be tested (unshare: EPERM) - see F3.
6. `_scratch_apply` sets expire only when store checkout == this checkout (cli.py:7373); store_checkout is
   always set before apply (cli.py:6834). If git cannot resolve the main worktree, both store path and expiry
   fall back to the worktree's own store, which is consistent.

## Findings

### F1 - LOW - mechanism CONFIRMED, pipeline reachability PLAUSIBLE: resume takes the EARLIEST covering claim, so a renamed-back tree reclaimed later is removed on an archive from the first claim

- Where: src/claude_code_hooks_daemon/core/scratch_archive_remove.py:339 (`min(times)`), used at :562 and :570-576.
- Why: a rename-back (`release`, or resume's rename-back) keeps the inode AND birth, so the first claim event still
  "covers" the tree after a later claim. `packed_at >= earliest claim` then admits a record packed for the first claim.
- Repro: probes/p_resume.py `p1_rename_back_then_reclaim`: claim at T-7d, pack + record (UNCERTAIN, expires T+1h),
  release, claim again at T, crash before pack, resume -> `removed` on the old archive with one hour of retention
  left. Output: `p1 outcome: removed ... archive expires 2026-11-20T13:00:00+00:00 | NOW 2026-11-20T12:00:00+00:00`.
- Note: the probe calls `release()` right after a recorded pack, which the apply pipeline never does directly;
  in the pipeline the route is remove refused -> left-claimed -> resume finds no verifying record -> rename back.
- Preconditions: a recorded pack whose removal was refused, a later rename back, the tree returning to the
  archived content exactly, then a crash between claim and pack. Rare; same impact class as finding 2.
- Fix: bind the record to the claim, not to the clock: accept only records whose `archive_id` equals the
  `archive_id` of the LATEST claim event covering this inode (`_apply_row` already writes the pack's archive_id
  into the ClaimEvent, scratch_archive_apply.py:689-701; confirm the batch path does the same). Minimum fix:
  `max(times)` instead of `min(times)`. Test: the p1 sequence must end `renamed-back`.

### F2 - MEDIUM - CONFIRMED, PR-INTRODUCED (clock step simulated): a wall-clock step back between claim and pack renames a PARTLY removed tree back

- Where: scratch_archive_remove.py:570-576 and :632-638.
- Why: claim `at` and `packed_at` both come from `sources.now` (wall clock, cli.py:7166). If the clock steps back
  between them, the only valid record is filtered out; a tree already partly removed then has no candidate and is
  renamed back to its original name, reason "no record names the entry" (false: one does). The archive holding the
  removed files keeps its normal expiry, so after retention those files are gone with no STUCK report.
- Repro: probes/p_resume.py `p2_clock_steps_back_mid_removal` (packed_at = claim - 1 s, a.txt removed):
  `p2 outcome: renamed-back ... reason='no record names the entry' ... a.txt back: False | partial tree at original name: True`.
- Regression check: the same probe with the filter neutralised (main's behaviour) ends `removed`, partial=True:
  main finished the removal against the verifying archive; this PR renames the partial tree back.
- Latent: `adopt`/`finish_adoption` stamp `packed_at` with the adopt event time (scratch_archive_adopt.py:190, :281),
  which precedes any later claim of the original; `pack_batch`/adopt have no production caller yet (grep), but once
  wired, every resume of an adopted original would hit this without any clock step.
- Fix: the archive_id binding from F1 removes the clock from the decision. Independently, when any record naming
  the entry was excluded by the time filter, return `stuck` (never rename back), and word the reason accordingly.

### F3 - LOW - PLAUSIBLE: descriptors held from another mount namespace are not matched

- Where: scratch_liveness.py:432-494 (`_descriptor_paths`, `_mapped_paths`), scratch_archive_facts.py:50-52.
- Why: `/proc/<pid>/fd` link text is the path in the holder's namespace (e.g. a `docker run -v "$PWD":/app` test
  holding `/app/untracked/scratch/x/f`), which never matches the resolved root. The DESIGN row names PID namespaces
  only. Not testable here (unshare EPERM). Pre-existing for cwd too, so not a regression.
- Fix: compare identities instead of text: `os.stat(f"/proc/{pid}/fd/{n}")` follows the magic link to the real
  inode in any namespace; match `(st_dev, st_ino)` against the entry's walked inodes. At minimum add "another mount
  namespace" to the DESIGN.md residual.

### F4 - INFO: N733 can be closed

probes/p_resume.py `p3_n733_old_behaviour` neutralises the filter (earliest claim forced to 1970) and reruns
`test_a_record_packed_before_the_claim_does_not_prove_the_tree`'s sequence: outcome `removed` where the test asserts
`renamed-back`, so the test is RED on the old behaviour.

### F5 - SUGGESTION: per-entry re-read of every process's fd table and maps

`entry_in_use` (cli.py:7329-7336) calls `sources.cwds()` per entry, and that now reads every pid's fd links and
maps. With thousands of entries this costs entries x processes x fds. Fresh reads are deliberate for safety;
consider caching for one claim only if the cost shows.

### F6 - SUGGESTION: N735 has a mechanical partial answer

A main-checkout expiry could hold any record whose `checkout` names a worktree still in `git worktree list`,
and let a removed worktree's records expire. That closes the live-worktree half without the never-expires
problem the DESIGN row cites; the removed-worktree half stays the owner's call.
