# CI failures in three Plan 00627 tests (ext4, non-root runner)

GitHub CI on main (run 44854305236 and later) failed three unit-core tests that pass on the local gate (btrfs, root). Test fix: commit 8fd24f5c1 on branch `ci-main-red-fix`.

## Root causes

- `test_scratch_archive_restore.py::TestRoundTrip::test_one_entry_of_a_batch_comes_back`: the hand-built `TarInfo` defaulted to uid/gid 0. Restore extracts with `--no-same-owner`, so the staged files carry the restoring user's ids, and `tar --compare` reports `Uid differs` / `Gid differs` for any non-root runner. Reproduced with `setpriv --reuid=65534`. The fixture now records `os.geteuid()` / `os.getegid()`, as a real pack does.
- `test_scratch_archive_remove.py::TestResume::test_a_claim_record_for_another_inode_does_not_cover_the_name` and `test_scratch_archive_apply.py::TestResumeReclaimExpireOrder::test_an_archive_whose_claim_is_still_present_never_expires`: not ownership. The CI runner's filesystem is ext4, which hands a just-freed inode number straight back, so the "new" directory made at the claim name carried the recorded `ClaimEvent` inode and was treated as the sweep's own claim (`renamed-back` / `stuck`, not `foreign`). Proven by recording the replacement directory's inode: the outcome is `renamed-back`, as in CI. The remove test now makes the replacement while the old inode is still allocated; the apply test makes it on an inode no claim event records (the retry branch was exercised by forcing a collision). Both assert the inode differs.

Verified: `test_scratch_archive_{apply,remove,restore,pack}.py` pass as root and as uid 65534 (btrfs only; no ext4 available locally, so the CI run on main after merge is the ext4 confirmation).

## Design questions for the owner (not changed)

1. Restore ownership (inferred from the mechanism, not run end to end with a real pack): `tar --compare` checks uid/gid, but extraction uses `--no-same-owner`. An archive whose members are owned by a uid/gid other than the restorer's (a foreign-owned file in scratch, a file in a setgid directory) would therefore fail restore verification every time. Either pack refuses such members up front, or restore handles ownership.
2. Claim identity is `(dev, ino)` only. On ext4 a stale `ClaimEvent` can cover a new directory at the claim name after inode reuse. Observed outcomes keep the content (`renamed-back` moves it to the original name, `stuck` leaves it), but the identity is weaker than the tests assumed. Whether to add a further identity check is a design call.
