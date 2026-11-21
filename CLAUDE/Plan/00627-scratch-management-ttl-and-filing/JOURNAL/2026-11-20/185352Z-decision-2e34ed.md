## 18:53 · decision · 8cc27a3f1 — Task 3.4: descriptor-based removal and resume

Task 3.4 built (commit 8cc27a3f1): `core/scratch_archive_remove.py` with `remove_claimed` and `resume_claimed`, plus `verify_remaining` in `core/scratch_archive_pack.py`. Still not reachable from any CLI flag.

Decisions:

- **Proof lives in the function.** `remove_claimed` re-reads the index and requires the handed record to be one of its records (by value) and to name the entry (`PurePosixPath(original_path).name == name`, equality, not `endswith`). It then walks, runs `verify(..., expected_sha256=record.sha256)`, and walks again; both listings must be identical. The skipped special files and the counts must equal the record's, because `verify` compares only packed names, so a FIFO added after packing would otherwise pass.
- **Removal is driven by the post-verify listing, never a fresh scan.** Each name is `lstat`-ed through its parent's descriptor and must still be the listed inode. Files are compared on everything (ino, dev, nlink, ctime, mtime, size). Directories are compared on identity only, because their times change as they are emptied. `unlink` is used only for listed non-directories and `rmdir` only for listed directories. A name that is not listed makes `rmdir` fail with ENOTEMPTY, which stops the removal.
- **Mount id, not just `st_dev`.** A bind mount on the same filesystem keeps `st_dev`, and `walk_tree` and tar's `--one-file-system` would both pass it. Every opened directory's mount id (procfs fdinfo `mnt_id`) must equal the parent's. An unreadable mount id refuses. For Task 3.9: `walk_tree`/pack have the same `st_dev`-only gap. Packing does not delete, but it could archive a bind source's content.
- **EACCES** inside the tree gets one retry, after `fchmod` u+wx on that directory's own descriptor. EPERM (immutable) is never retried. The scratch root itself is never chmodded.
- **Partly removed tree.** A crash mid-removal leaves a strict subset of the archive. A full `verify` fails on that, and renaming it back would put a half-deleted tree under its live name. The new `pack.verify_remaining` requires three things: the SHA matches the record, every remaining name is an archive member, and `tar --compare` restricted to the remaining non-directories is clean. We checked empirically that member-restricted compare ignores missing siblings and catches a changed file. `resume_claimed` tries full and then partial for each candidate record. Any proof that passes removes. When none passes, the tree is renamed back (and only content no archive holds can be renamed back), or reported stuck if the name is retaken.
- **Record matching** uses checkout plus basename, newest first. Content verification resolves ambiguity between same-named records, so the record schema is unchanged.
- **Torn index tail** is not a refusal. `read_index` returns only complete newline-terminated records, so a record found there was fsynced whole.

Tests (`tests/unit/core/test_scratch_archive_remove.py`) cover:

- refusals with the tree unchanged;
- escapes: a symlink swapped in after verify, and between lstat and open mid-removal; a file swapped for a link; a name added mid-removal; a monkeypatched mount id; a hard link to outside; a FIFO; EPERM followed by a resume;
- a crash sequencer: claim, pack, append, the 1st or 3rd unlink, the 1st or 3rd rmdir, and after removal, each both raised and as a hard stop. Recovery is then run twice. Each case asserts that the original or a recorded archive holding all of it exists, and that the second run reports `absent`.

Three tests skip here: a real bind mount (the container lacks the privilege), a real `chattr +i` (no chattr), and an unreadable directory (running as root). Each has an injected-fault twin that runs.

Deletion surfaces for Task 3.9, pinned by `test_deletion_surfaces_are_only_the_listed_ones`:

- `scratch_archive.py` `append` (`ftruncate` of a torn index tail);
- `scratch_archive.py` `discard_unrecorded` (`unlink` of an unrecorded archive);
- `scratch_archive_remove.py` `_delete` (`unlink`, `rmdir`).
