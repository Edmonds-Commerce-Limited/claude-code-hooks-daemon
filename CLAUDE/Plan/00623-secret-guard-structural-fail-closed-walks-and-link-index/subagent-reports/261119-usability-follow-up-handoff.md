# Plan 00623 usability follow-up: handoff (wind-down, nothing implemented)

Stopped at analysis, on the coordinator's WIND-DOWN. **No code, test, release-note, ledger or PLAN.md change was made.** The branch tip is still `65d8a3792`, plus this file.

## Measurements in `/workspace`

| Subtree                             | Directories |
| ----------------------------------- | ----------- |
| `untracked/scratch/`                | 229,905     |
| `.claude/worktrees/agent-a13d7c85…` | 69,486      |
| `.claude/worktrees/rc-3.75.0`       | 3,424       |
| each other worktree                 | 4 to 1,814  |

- **Scratch alone is over the 200,000-directory build cap.** Excluding the other checkouts would not stop `/workspace` overflowing.
- This worktree holds 318 links in scratch fixtures (`p623` 198, `614-r6` 120). Several of them lead to dummy protected files. So in this repository a computed move followed by a word that names one of those links is a **genuine** danger, and the deny for it is correct.

## Designs ruled out (advisor concurred)

- **Excluding subtrees** by `git worktree list`, gitignore or name. Bash can `cd` into an excluded tree, and the list it relies on is state the command can write (the F3 class). Proving that no link in the tree reaches a protected path means stat-ing every link in it, which is the same enumeration the exclusion was meant to avoid.
- **Any placement waiver of a stopped scan**, however gated (for example by an allowlist of commands that change nothing). The review removed this twice (F1, F3), and the brief forbids it.
- **Raising the cap**, or skipping enumeration silently.

## Next steps

Three separate stops block usability here. Measure each one first, with a script under the worktree's `untracked/scratch/` that lifts the cap in-process only:

- the total directory count, build time and verify time;
- the number of link-holding directories, directory links, distinct link names, and directory-link targets outside the root.

### 1. The 512 link-holding-directory stop in `_scan_from_index`

This looks like a cost bound only. Past 16 directories, `CwdSet.could_be_link` is already a test by link NAME, and the verified index already holds each directory's link entries (`_Listing.links`).

- **Change:** judge a word by link name against the index's verified listings, instead of stopping on the directory count.
- **Keep every existing deny:** `..`, globs, unlistable directories and `bases_above_scanned`.
- **Directory links** stay hard-bounded, and the scan denies past the bound: each one is a place a `cd` can land.
- **`recursive_search`** consumes the same scan (`computed_links`, `SEARCH_DIRECTORY_CAP`), so it needs the matching change.

### 2. The build cap of 200,000 directories

No sound fix exists without either admitting more directories or pruning scratch. Pruning scratch is not this agent's to do. **Decision needed from `main` or the owner.**

Before deciding, read `utils/protected_file_index.py`: it indexes the same tree and is the precedent.

### 3. Verify cost

Verification takes about 0.3 s per 69,000 directories. The whole of `/workspace` therefore needs 1.3 s or more against a 2 s deadline, even with the cap lifted.

### Tests

- **Usability test:** model the cap with a monkeypatched small cap. It must be RED at `65d8a3792`.
- **Negative twins:**
  - a word that names a link in a sibling tree still denies;
  - a build cut short still denies.
- The F1 to F4 tests must stay green **unedited**.

### Comparison baseline

Compare against tip `65d8a3792`, not `main`. `main` allows the F1 to F4 commands, so a comparison against it cannot see a regression. Run it cold, built, and under the review's `failclosed.py`, and put every DENY-to-ALLOW through `oracle.py`.

## Left untouched

- **Release note** `004-…`: not checked. Its cold-index wording is still to be verified against the review's "Left" section.
- **Ledger N670** and the **PLAN.md task boxes**: not updated.
- **Commit trailer:** the brief said Sonnet 5.5, but the harness reminder says Opus 5.5. This commit uses Opus 5.5, the model that actually ran.
