## 18:36 · decision · — — Task 3.2: claim by no-replace rename

Task 3.2 built: `core/scratch_archive_claim.py`, tests in `tests/unit/core/test_scratch_archive_claim.py`.

Decisions:

- The claim rename is `renameat2(RENAME_NOREPLACE)` through the parent's descriptor (ctypes, libc). A plain `rename` silently replaces an existing file or empty directory at `.sweeping-<name>`; tests pin that neither is replaced. Where `renameat2` is unavailable nothing is claimed (`ClaimRefused`), never a fallback to plain rename.
- Confirmed empirically (as DESIGN 5.2 asks): the claim rename changes the entry root's ctime. The fingerprint is (inode count, newest ctime below the root, root kind, inode, device, mtime and size), so the root's own ctime is left out.
- A changed fingerprint, a failed walk of the claimed tree, a false liveness check or one that raises all rename back and return `RenamedBack` with the reason and the claim time (`claimed_at_ns`) for the section 4 clock to subtract.
- A rename-back whose original name was retaken meanwhile raises `ClaimStuck` and leaves the entry whole under `.sweeping-<name>`; the next sweep resolves it (Task 3.4).
- The shared walk (`walk_tree`) is lstat-only, opens directories `O_NOFOLLOW` relative to the parent descriptor and checks each opened inode against the lstat it came from, stays on one device, and is bounded in inodes, names per directory and depth (so open descriptors are bounded too). Any gap raises `WalkRefused`, which authorises nothing.
- An entry that is itself a symlink is claimed as the link; its target is untouched. A directory swapped for a symlink between classification and claim changes the fingerprint and is renamed back.
- The unreadable-directory test skips under root (this container runs as root); the walk's refusal path is still covered by the missing-entry and swap tests.
