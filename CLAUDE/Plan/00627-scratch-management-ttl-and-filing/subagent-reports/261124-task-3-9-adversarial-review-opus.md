STOPPING BECAUSE: the Task 3.9 adversarial review is done. Nothing in the repo was modified; all fixtures are throwaway.

**Probe directory:** `/workspace/untracked/scratch/s-20261121T111743Z-0a12d28f/rev627/`. It holds `harness.py`, the scripts `p0`–`p9`, and `pytest.txt`, the capture of the targeted test run. That run covered 5 files (adversarial, remove, claim, apply, repos): 371 passed, 3 skipped.

**Verdict:** Phases 1-3 are **safe for a human-gated `--apply`**. They are **not yet safe for Task 6B's unattended path** until finding 1 is fixed.

**Counts:** 0 critical, 1 important, 3 suggestions. Five of the six findings were reproduced (CONFIRMED) and one is PLAUSIBLE; finding 1 is an existing OPEN row shown to be wider than recorded.

## Task 3.0 fixes and fix A / fix B: all hold (CONFIRMED)
- **N1:** `git clone --shared` between two entries, and a hand-written relative alternates line, both make the lender PROTECTED (`scratch_sweep.py:448-494`) (p9).
- **N2:** I tried `[CORE]`, a valueless key, `yes`, a quoted value, a comment, a later override, `include.path` and a `core "x"` subsection. Each verdict matches git's own reading or is more conservative. `--separate-git-dir` with the git directory in entry A and the work tree in entry B, or outside the project, or with the git directory named `.git`, is PROTECTED in every case (p2).
- **N3:** user files under a venv's `bin/` and `share/` stay UNCERTAIN (p1).
- **N4:** the `./`, `//` and `../scratch/` spellings are REFERENCED, and so is a sub-root spelled `.//subroot/./e`. A `subway` sibling is not (p9).
- **Reflog / pseudo-refs:** a reflog-only commit, `ORIG_HEAD` after the reflog was expired, a multi-line `FETCH_HEAD`, a linked worktree's own reflog, a custom ref and a tag-only commit are all PROTECTED (p2).
- **Fix A:** the statx struct matches `stat %W` on btrfs and tmpfs (p5). With no birth time the claim is refused: no event and no rename. A leftover claim made by hand is reported `foreign` and left alone (p4).
- **Fix B:** a foreign uid deep in the tree, a foreign gid only, and a foreign uid on the root are each refused before any claim event (p4).
- **Escapes:** a symlinked `untracked/` is refused by `resolve_sweep_root` (p6).
- **Round trip** (pack, then restore, compared): non-UTF-8 names, names with a newline or a leading dash, mode 000 and 0555, setuid, absolute and dangling links, a 3.4k-character path and an empty directory all came back identical (p7).

## Important
**1. An alternates borrower outside the swept root loses its history once the lender's 12-hour hold ends (CONFIRMED, p8).** This extends OPEN row F-BYPS F1 (DESIGN.md:415) beyond what the row states: the borrower can be anywhere on disk, not just in another first-level root.
- **Reproduction:** a standalone repo `scratch/lender2` gets DISPOSABLE P7. A clone made with `git clone --shared` outside the project borrows from it. `--apply` archives and removes the lender. Afterwards, `git log` in the borrower fails with `unable to normalize alternate`, and fsck exits with rc 2.
- **Code:** `scratch_sweep.py:448-494` reads borrowers only inside the root.
- **Fix:** borrowers outside the root cannot be enumerated, so the fix belongs on the proof side. Never give a repository's `objects/` the short P7 or P4 hold: pack such entries as UNCERTAIN (168 hours) and print the restore command. As a minimum, also scan every first-level root and `untracked/repos`.
- **Blocks 6B:** yes. This is the one data-loss route on the 12-hour path that runs with no human.

## Suggestions
**2. A leftover claim on a restored entry is removed on the strength of the old archive record (CONFIRMED, p3).**
- **Sequence:** restore, then a crash after the claim step, then a rerun. `resume_claimed` (`scratch_archive_remove.py:550-603`) removes the tree using the earlier record, even when part of the restored tree has since been deleted (the `partial` path). The data stays only for that record's remaining retention, not a fresh one.
- **Correction to my own first reading:** with the real clock, a restored entry is *not* due again straight away, because the extract's fresh ctime makes it LIVE at age 0 (p9).
- **Fix:** in resume, accept only records whose `packed_at` is later than the claim event's `at`.

**3. User xattrs are dropped silently, and sparse files come back dense (CONFIRMED, p7).** `user.note` was missing after the round trip. The create and extract flags (`scratch_archive_pack.py:588-590`, `scratch_archive_restore.py:111-117`) carry no `--xattrs`/`--sparse`, and `tar --compare` cannot see the loss.
- **Fix:** refuse an entry holding `user.*` xattrs, or pack with `--xattrs --sparse` and compare them.

**4. A race between the worktree blockers check and the removal (PLAUSIBLE).** Plain `git worktree remove` deletes ignored files. A file written into the worktree's `untracked/` after the check (`cli.py:11194`) but before the removal (`worktree_reaping.py:500`) is deleted without being archived.
- **Fix:** re-run `worktree_blockers` immediately before line 500, or rename the worktree aside before removing it.
- I read this path but did not run it.

## By design (not findings)
- `node_modules/`, `*.egg-info/` and `__pycache__/` holding a `findings.md` are DISPOSABLE under P2, per section 3.2.
- A commit dangling with no reference at all is P4; git gc would drop it too.
- Directories with message-like names such as `ci-repro/` and `qa-x/` stay UNCERTAIN.

## OPEN rows and 6B
- **Open file descriptor not detected (DESIGN.md:410):** blocks 6B, unchanged.
- **Linked-worktree expiry using the shared original-path prefix (DESIGN.md:438):** must be closed before 6B runs in a linked worktree.
- **TTY gate (F-BYPS F2):** removing it is exactly what 6B does, so findings 1 and the open-descriptor row must close first.

## What these probes did not test
- Every apply probe stubbed liveness and references to False.
- The session-directory path (`apply_sessions`) was not run.
- Everything ran as uid 0, so the permission-failure paths (the EACCES retry, unreadable files) are untested.
- The no-birth-time case was simulated by patching only `scratch_archive_remove.birth_stamp`.
- The 3 skipped tests are listed in `pytest.txt`; I did not check why they skip.

## Cleanup
The fixture trees `p0`–`p9` contain nested repos that the real sweep will hold as PROTECTED. The scripts rebuild them, so deleting those trees loses nothing.