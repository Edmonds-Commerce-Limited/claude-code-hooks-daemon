## 18:34 · decision · — — Task 3.1: the archive store

Task 3.1 built: `core/scratch_archive.py` (`ArchiveStore`, `ArchiveRecord`), tests in `tests/unit/core/test_scratch_archive.py`.

Decisions:

- The store path is injected; it is opened `O_DIRECTORY|O_NOFOLLOW` and refused (never repaired) when it is a link, a non-directory, foreign-owned or any mode but 0700. A store the call creates is `fchmod`ed to 0700 so a permissive umask cannot widen it.
- Every store file is reached through the store descriptor with `O_NOFOLLOW`; a symlinked `index.jsonl` is refused, its target untouched.
- The `flock` is non-blocking: a second sweep gets `StoreBusy` rather than waiting. Append, archive creation and discard need the lock.
- A torn final index line (no newline) is the expected crash artefact: reported as `torn_tail`, its archive counts as unrecorded, and the next append truncates it under the lock so a new record never glues onto it. Any interior malformed line refuses the store.
- Archive ids are `YYYYmmddTHHMMSSZ-<12 hex>`, checked on every use, so an id can never carry a path component.
- `os.scandir` on a descriptor shares its stream offset, so a second listing through the same descriptor came back empty (found by the audit test). `list_names` lists through a fresh descriptor of `.`.
- The store's one deletion is `discard_unrecorded`: an archive file no record names, under the lock.
