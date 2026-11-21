# Plan 00627: handoff after Tasks 2.1 and 2.2

Branch `agent-acff915e4bf3b86e6-0a26f829`, pushed, not merged. The work is in commits `2a66d96ea` and `0ab0a037f`. `origin/main` was merged in afterwards (`6290ac524`) with no conflict, and `config-changes/v3.77.0.yaml` is untouched. The earlier handoff is [261120-r7-overturn-and-untracked-ttl-handoff.md](261120-r7-overturn-and-untracked-ttl-handoff.md). Journal: `JOURNAL/2026-11-20/155251Z-action-b79bc6.md`.

## Done (2a66d96ea)

- **`core/scratch_repos.py`** (new). It covers Task 2.1 and Task 2.2, plus the dirty-file half of P3.
  - `build_project_git` runs once per sweep in the project. It reads the worktree list, the remote-tracking refs confirmed by one `ls-remote` (live-verified), and the blob set of the verified default tip.
  - `classify_entry` gives each `.git` marker and each bare repository a kind: `REGISTERED_WORKTREE`, `OUTSIDE_POINTING`, `RELATED`, `STANDALONE` or `BROKEN`.
- **`scratch_verdict.judge`**:
  - `Verdict.REPOSITORY` is gone. `PROTECTED` and `Proof.P4` are live.
  - New inputs `repos` and `tracked`. A marker with no classification is STUCK, and so is an unknown tracked listing.
- **`scratch_sweep.run_sweep`** has a new required parameter, `project_git` (None means STUCK for every due entry).
  - It runs one `git ls-files -z -- <root>`. An entry holding a tracked file is PROTECTED.
  - It classifies only due, non-live, fully walked entries with no outside hard links.
- **`untracked_roots`** refuses two kinds of root:
  - any root outside this project's `untracked/`;
  - any path, literal or resolved, that passes through `untracked/repos` or `untracked/scratch-archive` of any checkout.
- **CLI.** `scratch-sweep` builds the `ProjectGit` from `branches.remote` and `resolve_remote_default_branch`. Its help text is updated.
- **`tests/support/scratch_tree.py`** gains `build_git_project` (real repositories, a local bare `origin`), `git`, `commit_file` and `quiet_project_git`.

## Done (0ab0a037f, after an advisor review)

- `resolve_sweep_root` refuses a root at or inside a repository below `untracked/`: a `.git` of any type, or the bare shape, at the root or any directory between it and `untracked/`. Without this, `--root untracked/scratch/<clone>` judged the clone's files as loose entries.
- P4 covers a tracked file only by exact path. Only a git directory (`RepoFindings.p4_git_dirs`) covers its subtree.
- `ls-files -v`: an `assume-unchanged` or `skip-worktree` entry protects a related clone, because `status` cannot see its edits.
- A failed project `ls-files` makes the report incomplete, not just a note.
- Release note 017 says PROTECTED, not REPOSITORY, and states the `--root` limit.

Targeted QA after the merge: 272 tests pass (the sets below, plus `tests/unit/config/test_scratch_config.py`). Before that: 200 tests pass across the scratch, roots, CLI and support tests. ruff, black and `mypy --strict` are clean on every touched file.

## Remaining

- **Task 2.3, P3 for ordinary files.** Hash the uncovered regular files of an otherwise-UNCERTAIN entry with `hash-object --no-filters` in the project, against `ProjectGit.remote_blobs`. Bound it by count and bytes. P4 is done.
- **Task 2.4.** The reference set and the REFERENCED verdict. `git grep -o -E '<root-rel>/[A-Za-z0-9._/-]+'` over HEAD and the unmerged local branches, built once per sweep, in the project. REFERENCED is still in `NOT_EVALUATED`.
- **Task 2.5.** The filing proposal table (DESIGN.md section 6) in the dry-run output.
- **Release note.** Update `017-...md` and the `--root` wording in `config-changes/v3.77.0.yaml` if it mentions roots outside `untracked/`. Not checked.

## Choices for the coordinator

- **The standalone verdict is the ordinary ladder, per DESIGN.md 3.3.** A standalone repository's `.git/objects` files pass no proof, so in practice it lands UNCERTAIN (packed, held, removed), not DISPOSABLE. Only an empty `.git` passes P5. If the owner's "a standalone repo in scratch is disposable" means the DISPOSABLE verdict (short hold), that needs a ruling and one line in `judge`.
- **A fake or broken `.git`** (no `HEAD`, an empty dir, a `.git` link) is STUCK indefinitely. It never becomes ordinary content.
- **The nested config allowlist** is deliberately narrow (`_ALLOWED_CONFIG`). An LFS clone (`filter.lfs.*`) or a partial clone is STUCK.
- **Bare repositories** are detected by shape (`HEAD`, `objects/` and `refs/`) and classified like markers. This was not asked for: it closes an R6 gap.

## Deletion surfaces for the security review

1. **`classify_entry` fails closed.** Any `_Broken` is STUCK. "No remote" is read from an allowlisted, include-free config. Relatedness needs a successful, sha-validated `rev-list`.
   - **Residual risk:** git itself is trusted to tell the truth. An `ls-files` answer covers only paths the walk saw, so a lying git could still cover a real untracked file. Proved by test: a listed path the walk never saw covers nothing.
2. **The P4 tip proof.** Every ref tip, plus HEAD, needs `for-each-ref --contains` in the PROJECT, with a matching ref whose sha equals the live `ls-remote` sha.
   - An object the project lacks means "not held".
   - The clone's own refs are never used as proof: a forged `refs/remotes/origin/main` inside the clone is tested.
   - More than `MAX_TIPS` (200) tips means PROTECTED.
3. **Dirty files.**
   - A staged change, a rename, a typechange or an unmerged path means PROTECTED.
   - A worktree-modified file passes only when its `--no-filters` blob is in the verified default tree.
   - A worktree deletion is accepted, because the content is in a pushed commit.
4. **Root reach** is lexical plus `realpath`; see `untracked_roots.py`. The tracked-file check runs per sweep, not per entry. Between that check and a later `--apply`, a file could become tracked. Phase 3's re-classification must repeat it.
5. **The index-rewrite test** (`test_a_stat_dirty_tracked_file_does_not_rewrite_the_nested_index` and the CLI inode test over a real stat-dirty clone) passes. It was not shown failing with a plain runner, because `run_git` forces `GIT_OPTIONAL_LOCKS=0` for every caller.
6. **Reflog-only commits are not checked.** A clone with a local commit that was then reset away (reachable only from the reflog or `ORIG_HEAD`) reads as clean and pushed, and is P4. The design covers "every ref tip and HEAD" only. Not built: it is listed for the review.
7. **`hash-object` follows a link.** It runs on regular files checked with `lstat` first. A link swapped in between would hash, never print, the target. Dry run only.
