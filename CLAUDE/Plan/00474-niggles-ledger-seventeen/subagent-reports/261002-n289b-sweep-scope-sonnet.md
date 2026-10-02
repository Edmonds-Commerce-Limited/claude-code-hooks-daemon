# N289b: SessionStart path sweeps on the real main checkout (sonnet)

## What the two sweeps walk

`gitignore_safety_checker` and `secret_file_hygiene_checker` both call
`scan_git_file_states`, which runs four `git ls-files` variants and returns
tracked, untracked-visible and untracked-IGNORED paths. They then judge every
path with `path_is_protected` (glob match on the spelling and on the realpath).
Measured on /workspace: 532,394 paths, of which 527,748 are ignored files.
Breakdown of the ignored ones: about 456,000 under `untracked/scratch` (copies
of repository trees), about 70,000 in virtualenvs and interpreter trees. The
coordinator's hypothesis about nested worktrees is not what happens: git
reports a nested checkout as ONE directory entry and never lists its files
(`untracked/worktrees/` contributed a single line). The cost is the sheer count
of ignored files plus a per-path price of about 66 microseconds (two `realpath`
walks and up to six glob sweeps).

What they need: gitignore_safety needs "is this protected file ignored and is
it ciphertext"; hygiene needs the same plus permissions. Both legitimately look
at ignored files (a protected file in an ignored directory is exactly the
case), so descending is kept; foreign trees are pruned and the per-path price is
cut.

## Changes

1. `utils/git_file_states.py`: ignored UNTRACKED files under a directory holding
   `pyvenv.cfg`, or under any `node_modules`, are dropped from the scan (by
   structure, not name). Tracked files there stay. An ignored directory with
   neither marker (the scratch copies) is still judged in full.
2. `utils/secret_file_matching.py`: `protected_among(paths, patterns)` equals
   `path_is_protected` per path, but resolves each directory once (and each
   directory through its parent's listing), reads symlink status from one
   `scandir` per directory instead of an `lstat` per file, and skips the glob
   matcher for a path that carries none of the patterns' literal runs. Symlinks,
   missing files, relative paths and NUL bytes fall back to the per-path call.
3. `utils/path_exclusion.py`: `literal_screen(patterns)`, a sound one-regex
   pre-test (disabled when any pattern has no literal run or is the vendor
   token); a property test checks that a screened-out text never matches.
4. `utils/git_file_states.py`: `scan_git_file_states_for_event` shares one scan
   between the two handlers of the same event (keyed by the identity of the
   event dict and the root; the next event rescans), and
   `GitFileStates.protected_relpaths` keeps the protection verdict per pattern
   set, so the second sweep costs about 0.01 s.
5. Both handlers use these. Release note 211.

## Timings on /workspace (read only; src from this worktree)

| step                                            | before (main) | after           |
| ----------------------------------------------- | ------------- | --------------- |
| gitignore sweep (scan + judge)                  | 35.3 s        | 8.2 s           |
| hygiene sweep (judge only; scan 2.2 s separate) | 33.5 s        | 0.01 s (shared) |
| both sweeps together                            | about 71 s    | 8.2 s           |
| paths judged                                    | 532,394       | 446,917         |

Findings reported on main are identical before and after (none either way); the
detection tests are synthetic trees because main has no protected file to find.
The rest of the chain on main (coordinator's figures: git-upstream 2.1 s,
docs-qa 1.2 s, plan-qa 0.7 s, others about 2 s) puts the whole chain at about
14 to 15 s, an estimate not a measurement: I did not run the full controller
against /workspace because building it there rewrites the CLAUDE.md block.

## Remaining cost and recommendation

About 3.2 s is the four serial `git ls-files` calls (git itself) and about 5 s is
the per-path judgement of the 447,000 scratch-copy paths. Running the four git
calls concurrently would save about 1 s. The bulk is `untracked/scratch` copies
of whole repositories; a project can stop paying for them by not keeping such
copies inside the working tree, which is outside this change's reach.

## Tests

Tests written first (ImportError on the new names, then green). touched files:
test_git_file_states, test_path_exclusion, test_secret_file_matching and the two
session_start handler suites: all pass. Differential coverage: `protected_among`
vs `path_is_protected` over plain, symlinked-file, symlinked-directory, nested,
dangling, looping, missing and NUL-byte paths; foreign-tree pruning with real git
repositories.
