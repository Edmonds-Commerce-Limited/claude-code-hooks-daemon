# N588: upgrade `modified_files` lists only what the upgrade changed

**Branch**: `agent-ac4f3ae9be87cf434-a6fe075d` (fix commit `5ea599e80`, merged with origin/main).

## Defect

`scripts/upgrade.sh` filled `UPGRADE_METADATA`'s `modified_files` from `git status --porcelain` over the whole
project, so uncommitted work left by another agent was listed. That output also split names on spaces, because
`awk '{print $NF}'` printed only the last word of each line. A client gate that exempts listed paths as daemon-owned
would therefore exempt unrelated files.

## Fix

- New **Step 1b** in `upgrade.sh`, taken before Step 3. Step 3 is the first step that can write into the project,
  because it may clone the daemon there. It records every dirty path with its state, using
  `git status --porcelain -z --untracked-files=all`. The state is the blob hash from `git hash-object --no-filters`
  for a file, `link:` plus the hash of the target for a symlink, `absent` for a deleted path, and `other` for a directory such as a nested
  repository.
- Four inline functions: `_dirty_paths`, `_dirty_path_record`, `_dirty_path_states` and `_upgrade_changed_paths`.
  - They are inline because the script is fetched standalone and cannot source a library.
  - They use no associative arrays, so they run on the bash 3.2 that macOS ships.
  - Renames and copies list both sides.
  - Records are `%q`-quoted, one per line, so any file name compares exactly.
- At metadata emission, `modified_files` holds paths that are dirty now whose record is not in the snapshot. Those are
  paths new to the dirty set, or a path that was already dirty and has different content.
- If the snapshot or the comparison fails, the script warns and leaves `modified_files` empty. It never falls back to
  listing the whole tree.
- The new contract is stated in the comment at the emission spot and in the skill's `upgrade.md` step 2. Both copies of
  that file were updated.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/008-upgrade-modified-files-lists-only-its-own-changes.md`.
- N588 is marked fixed in `NIGGLES.md`.

## Test

`tests/integration/test_upgrade_sh_modified_files_scope.py` lifts the real functions out of `upgrade.sh` and runs them
against a temporary git repository. The fixture has these pre-existing changes, none of which may be listed:

- an unrelated modified file;
- an unrelated deleted file;
- an unrelated staged rename;
- an untracked file whose name contains a space;
- an untracked symlink.

It then makes these changes as the upgrade, all of which must be listed:

- a modification;
- a new file;
- a deletion;
- a staged rename, with both sides listed;
- a new symlink;
- a further edit to a file that was already dirty.

There are also two wiring tests. One checks that the snapshot is taken before Step 3. The other checks that the
emission no longer uses `git status --porcelain`.

The test failed before the change (6 tests) and passes after it. `shellcheck -x scripts/upgrade.sh` is clean.

## Caveat

`modified_files` stays comma-joined, so a path that itself contains a comma is still ambiguous to whoever parses the
list. This is not new.
