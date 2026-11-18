# Plan 00623: build report (in progress)

Branch `agent-a13d7c8504105d4c9-aeae03b4`, built on the Plan 00614 round-6 tip `2ae46b106` merged with main (`894e2cd9d`). Not merged to main.

## Design (fixed before any code)

### 1. One "did it finish" result type

`utils/bounded_walk.py` holds `Bounded[T]`: `value`, `complete` and `reason`. Every bounded walk returns one:

- the link scan (`scan_project_links` returns `Bounded[LinkScan]`);
- the directory glob walk (`expand_directory_glob`; it no longer returns `None`);
- placement (the stat behind `_realpath_if_resolvable`);
- nesting depth (the `bash -c` / `$( )` body walkers in both `secret_file_matching` and `recursive_search`).

`Bounded.required()` raises `IncompleteScanError` when the walk did not finish. No bare `None`, `[]` or silent `return` may mean "stopped early". These silent stops are converted:

- the `[:LINK_DIRECTORY_CAP + 1]` slices in `_DirectoryWalk._expand`, `change` and `to_toplevel`: past the slice the move is computed;
- both depth limits: a deeper body that could move or read raises;
- the `OSError -> []` returns in `_wildcard_links` and `_matching_symlinked_directories`;
- `lexists` in `_realpath_if_resolvable` (N663).

### 2. One fail-closed handler

`resolution_failure.fail_closed_finding(...)` maps a `ResolutionFailedError` (and so an `IncompleteScanError`) to a finding. Every guard that calls the walkers uses it: the secret guard, the quarantine guard and the flaggable channel guard if it reaches them. The A1 routes (`TimeoutError`, `TooManyToEnumerateError`, internal errors) are left as they are: N662 records that as an owner decision.

### 3. Link index, off the hot path

- **In daemon memory only.** Nothing is written to disk, so no project file can forge it. A failed build, a build past its bound, or a directory that cannot be stat-ed during verification makes the result incomplete, and an incomplete result denies.
- **Built once, in the background**, like the protected-file index, and prewarmed by the guards' `prewarm_index`. Until it is built, a call falls back to the bounded per-call scan (512 directories); an incomplete scan still denies.
- **Verified at decision time, once per tool call** (inside `link_scan_scope`). The verifier walks the stored tree top down:
  - each directory is `lstat`-ed and compared on `(st_dev, st_ino, st_ctime_ns)`, never mtime (`touch -d` can reset mtime; ctime cannot be set);
  - a changed directory, or a "racy" one whose ctime was within a slack of when it was listed, is re-listed in place;
  - a directory that cannot be stat-ed is treated as changed.
- **Link kinds are never cached.** Each stored link is classified again at verification, because its target can change with no change to the directory holding it.
- **Bounds.** Verification has a directory cap, a re-list cap and a deadline. Past any of them the result is incomplete, which denies, and a background rebuild starts. Incremental re-lists are made under a lock.

### 4. Placing `~`, `$HOME`, `$TMPDIR`, `mktemp -d`

A move is placed only when the daemon's value is absolute, its realpath is outside the project, and the command does not reassign the variable. The place the shell already was is kept as well (an unset value leaves `cd` where it was). `$(mktemp -d ...)` creates a new empty directory and is placed as no new directory. Residual: the shell's value can differ from the daemon's (for example, set by a profile). That is the same class as D-C, and it is ledgered.

### 5. N667, N668, N663, N664

- **N667.** With a complete index, the top-level idiom no longer needs the `fail_closed=False` exemption; it is dropped, and a persisted `core.worktree` fixture pins the deny.
- **N668.** A word whose placed components contain `proc/self`, `proc/thread-self` or `dev/fd` (raw components, with `//` and `.` collapsed but no `..` collapsed) cannot be placed, so it fails closed.
- **N663.** An `lstat` `OSError` other than `ENOENT`/`ENOTDIR`/`ELOOP` is unresolvable when the word alone fits `PATH_MAX` and each of its components fits `NAME_MAX`.
- **N664.** Covered by item 1, nesting depth.

## Results

(filled in as phases land)
