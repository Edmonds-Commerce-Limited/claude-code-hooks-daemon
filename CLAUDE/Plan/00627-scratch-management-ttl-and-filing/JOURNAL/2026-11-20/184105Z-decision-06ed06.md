## 18:41 · decision · — — Task 3.3: pack and two-way verify

Task 3.3 built: `core/scratch_archive_pack.py` (`pack`, `verify`, `find_gnu_tar`), tests in `tests/unit/core/test_scratch_archive_pack.py`; plus `tests/unit/core/test_scratch_archive_unreachable.py` (no module outside `core/scratch_archive*` imports or names them; `scratch-sweep` has only its dry-run flags).

Decisions:

- GNU tar is checked by `--version` and run by absolute path and argv, with the environment replaced by `LC_ALL=C` and a fixed `PATH` (a hostile `TAR_OPTIONS` is pinned by a test as having no effect).
- tar's working directory is the procfs magic link of a descriptor of the claimed inode (checked against the walk's inode), passed with `pass_fds`, so a path swapped after the claim cannot redirect it.
- The member list is our own walk, NUL-separated, `./`-prefixed, on stdin with `--verbatim-files-from --no-recursion`; names such as `--checkpoint-action=exec=...`, `-rf` and a newline are stored as names and never run (pinned).
- Hard links: any non-directory with a link count above 1 refuses the entry. This is the owner brief's rule and is stricter than DESIGN 5.3 (which allows an internal pair); both shapes are tested and both refuse.
- Sockets, FIFOs and device nodes are never opened: skipped and listed; an entry that is itself one is refused.
- Verify, both ways: headers read first (`tarfile` stream, no extraction) and every member must be `.` or under `./` with no `..` and of type dir, file or symlink, before any compare runs (a spy tar proves it is not run on an escaping archive); `tar --compare` must exit 0 with no output; the member set must equal a fresh walk's (catches an added file); the SHA-256 must match the record when one is given.
- Every refusal discards the unrecorded archive (`ArchiveStore.discard_unrecorded`); the claim stays the caller's to release.
