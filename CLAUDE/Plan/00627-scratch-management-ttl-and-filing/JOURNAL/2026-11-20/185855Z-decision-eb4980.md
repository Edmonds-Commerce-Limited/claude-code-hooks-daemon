## 18:58 · decision · — — Task 3.4 hardening after review

This hardens Task 3.4 after review and corrects the previous Task 3.4 entry.

Three changes to verification and resume:

- **Restricted compares are batched.** `pack.verify_remaining` now runs its restricted `tar --compare` in argv batches of at most `COMPARE_ARGV_BUDGET` (64 KiB) of member names. It seeks the archive back to 0 before each batch. Without this, a large partly removed tree would hit E2BIG, and the resume would treat that as a failed check. A test forces one name per batch and puts the change in the later batch.
- **"Did not run" is no longer the same as "differs".** `_compare` now raises `TarDidNotRun`, a `VerifyFailed` subclass, when tar cannot be run at all: missing, timed out, or E2BIG. `_prove` maps it to `ProofUnavailable`. When any candidate record hit `ProofUnavailable`, `resume_claimed` returns `stuck` and does not rename back.
  - Correction to the previous entry: before this change, a tar failure on a partly removed tree did lead to a rename-back. That entry's claim, "only content no archive holds can be renamed back", was not true as built. It is true now.
- **Raw OS errors now refuse instead of escaping.** Failures of `fchmod`, `readlink`, the parent `fsync`, and a non-ENOENT `lstat` in resume used to escape as raw `OSError`. They now raise `RemoveRefused`.

Test changes:

- The deletion-surface scan now covers the whole module. Module-level and class-level references are listed under `<module>`. `rename` and `renames` were added to the scanned names. A unit test shows that a module-level `shutil.rmtree` alias is caught. The pinned list is unchanged.
- Correction to the previous entry: the unreadable-directory test had no injected twin. The EACCES test covers an unwritable directory, not an unreadable one. A twin now patches `walk_tree` to refuse and asserts that the tree is untouched.
