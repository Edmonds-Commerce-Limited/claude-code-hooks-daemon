# Plan 00627: design of the scratch management system

Paths are under `src/claude_code_hooks_daemon/` unless stated. Code claims were read on main at `201a17fae`; the link index is cited from the unmerged branch `agent-a13d7c8504105d4c9-aeae03b4` (Plan 00623), where `utils/link_index.py` lives.

## 0. Authority and rulings

**The owner's words (verbatim, in session, 19 November 2026):** "use fable - we need a full scratch management system. scratch files should have TTL, old files MUST be filed properly or deleted. I suggest 24 hours. has value - keep (plan folder, main project script etc), no value - delete".

Every ruling below marked **R** is **settled by a fable sub-agent under the owner's delegation, 2026-11-19**. The owner may overturn any of them; each is written so that overturning it changes one section.

| Id  | Ruling                                                                                                                                                                                                                                                             | Section |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| R1  | An entry past its TTL has exactly four possible fates: stay (it is live or protected), be filed (a tracked home), be archived (one verified tarball, held, then removed), or be removed after a hold. Nothing past TTL stays as a directory tree unless protected. | 3, 5    |
| R2  | TTL is 24 hours by default, configurable, and the clock is the newest mtime inside the entry, with three backstops (birth marker, a maximum lifetime, a live-process check).                                                                                       | 4       |
| R3  | Deletion needs a machine proof. An agent's statement that something has no value is never an input. What cannot be proved valueless is UNCERTAIN, and UNCERTAIN is packed, verified, held for longer, announced, and only then removed.                            | 3       |
| R4  | The sweep proposes filing and never performs it. Filing is authorship (a name, a destination, a commit) and must pass the content guards, which see only `Write` and `Edit`.                                                                                       | 6       |
| R5  | Nothing is removed directly. Every removal goes through the archive store, and the store is flat (no directory trees), so it never adds to the link index.                                                                                                         | 5       |
| R6  | A repository or worktree holding unpushed commits or dirty tracked content is never packed and never removed by the sweep. "Unpushed" is defined only for a repository that has somewhere to push (a remote, or shared history with the project).                  | 3.3     |
| R7  | A standalone repository (no remote, history unrelated to the project) is UNCERTAIN, never DISPOSABLE: packed whole, held for the long retention.                                                                                                                   | 3.3     |
| R8  | A reference from a tracked file protects an entry from removal, not from packing. A referenced entry past TTL becomes one archive with no expiry until it is filed or the reference goes.                                                                          | 3.4     |
| R9  | Scratch is written inside a per-session directory the daemon creates and marks. The TTL unit is a child of that directory.                                                                                                                                         | 7       |
| R10 | Caps are judged on directories, bytes and entries. Above the warn cap the session is told; above the block cap, directory-creating commands into scratch are denied and the sweep may pack idle entries before their TTL. Message files are never denied.          | 8       |
| R11 | The link index never excludes scratch. The fix is fewer directories.                                                                                                                                                                                               | 9       |
| R12 | Plan 00560's baseline exemption (its provisional Q4) and its non-goal "never delete or move automatically" are overturned by the owner's words above. Its final owner rulings stand.                                                                               | 1       |
| R13 | The housekeeping step that applies the sweep acts without confirmation. This amends Plan 00330 Decision 6 for this one step, because every removal trails a hold window.                                                                                           | 10      |
| R14 | A worktree's scratch is evacuated into the main checkout's archive store before the worktree is reaped; a protected entry still refuses the reap.                                                                                                                  | 11      |
| R15 | Only a human may pin an entry for ever (`.scratch-keep`); an agent may only pause it, for a bounded time, with a reason.                                                                                                                                           | 3.5     |

## 1. Relationship to Plan 00560

`find-plan scratch` returns Plan 00560 (scratch directory unrecorded assets, GitHub #155). That plan is about work that should never have been in scratch; this one is about what happens to what is there. They share one `scratch:` config block.

| 00560 item                                                                           | Standing here                                                                                                                                       |
| ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1: no fallback report store (owner, final)                                          | **Stands.** A report with no plan folder has no tracked home; the sweep can only say so (section 6).                                                |
| No consumption ledger, no stop gate (owner, final)                                   | **Stands.** This design adds no per-file ledger and no Stop gate.                                                                                   |
| Consume-then-remove (owner, final)                                                   | **Stands** and helps: a consumed body file never reaches the sweep.                                                                                 |
| Scratch-shape whitelist (stand-in, provisional)                                      | **Stands**, judged on the basename at any depth, so it works inside a session directory unchanged. The shapes are reused as proof P1 (section 3.2). |
| Goal 7, Phase 6, Task 6.3: the SessionStart sweep and the `find ... -delete` rewrite | **Moves to this plan** (Phases 5 and 7 here). 00560 keeps Task 6.2 (refused replies).                                                               |
| Q4: a baseline cutoff, older files counted and never listed (stand-in, provisional)  | **Overturned (R12).** The backlog goes through the same ladder as new entries.                                                                      |
| Q6: 24 hours (stand-in, provisional)                                                 | **Confirmed by the owner's words.**                                                                                                                 |
| Non-goal: "Deleting or moving any file automatically"                                | **Overturned (R12)** for deletion after proof or hold. Moving into tracked homes stays manual (R4).                                                 |
| Registered stores are left alone by the sweep                                        | **Narrowed.** They are not swept, but their directories are counted in the caps (section 8), because the link index counts them.                    |

## 2. Facts this design rests on

- **Measured before the first pack** (`untracked/scratch-measure-report.md`, `untracked/scratch-measure-sorted.tsv`, `untracked/scratch-measure-gitstat.tsv`; all three are untracked and are cited here as the source, with the figures copied): 229,905 directories, 190,046 files, about 2.40 GiB, 3,628 top-level entries (101 directories, 3,527 loose files), 1,001 nested `.git` markers, 623 with a dirty tree, 542 with commits on no remote ref, 392 with a remote.
- **One entry held 73% of the directories**: `rv614c`, 168,449 directories in 1.0 MB. It was packed to `untracked/scratch/rv614c.tar.gz` and the tree removed (Plan 00623 journal, 12:38 entry), leaving 61,456 directories. The same journal records the verification used: entry count equal, `tar --compare` silent with exit 0.
- **Age does not find the problem alone.** 2,886 entries older than 7 days hold about 575 MB; 742 newer entries hold about 1.84 GiB. Most directories are days old, not months.
- **Most nested repositories are synthetic fixtures with no remote.** The few with real lineage (`w609-*`, `r614c*`) are clones of this project with dirty or local-only content. `w609-mainwt` is a registered worktree of this repository (`git worktree list`).
- **The link index** (`utils/link_index.py` on the 00623 branch): `build_link_index` lists every directory under the project root, `.git` included, and returns an overflowed index at `BUILD_DIRECTORY_CAP` = 200,000 or after `BUILD_DEADLINE_SECONDS` = 60. An overflowed index is an unfinished walk, and an unfinished walk fails closed: that is the false-denial route.
- **Scratch exists in every checkout.** Four of the six agent worktrees under `.claude/worktrees/` have their own `untracked/scratch/`. Nothing reads them.
- **The mechanisms to reuse** exist: `utils/stale_checkouts.py` `ScanDeadline` (budgeted scans), `core/worktree_reaping.py` `default_process_cwds` (`/proc/<pid>/cwd`, never a `pgrep -f` pattern) and the minimum-age rule, `daemon/housekeeping.py` `HOUSEKEEPING_STEPS`, `handlers/session_start/branch_sweep.py` (cached inventory inside a budget), `handlers/session_start/routine_qa_sweep.py` (the dead-man's switch), `handlers/session_start/session_actions_directive.py` (the must-do list), `core/branch_park.py` (a bounded pause with a reason) and `utils/regenerable_paths.py` (the pattern dialect).

## 3. Taxonomy and the value test

### 3.1 The unit, and the verdicts

A **scratch root** is `untracked/scratch/` in the main checkout and in every registered worktree. An **entry** is a direct child of a session directory (section 7), or, for legacy content, a direct child of a scratch root. An entry is judged whole: one verdict, one action.

Verdicts are computed in this order. The first that applies wins.

| Verdict        | Meaning                                                                              | Action past TTL                                                             |
| -------------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| **LIVE**       | Within TTL, or something is using it now (section 4)                                 | None                                                                        |
| **KEPT**       | A human pinned it, or an agent paused it and the pause has not run out (section 3.5) | None; reported                                                              |
| **PROTECTED**  | It holds work that exists nowhere else by a machine test (section 3.3)               | Never packed, never removed; reported every session with the filing command |
| **REFERENCED** | A tracked file names it by exact path (section 3.4)                                  | Packed to one archive with no expiry; reported as "overdue to file"         |
| **DISPOSABLE** | A proof in section 3.2 holds                                                         | Packed, held for the short retention, removed                               |
| **UNCERTAIN**  | None of the above                                                                    | Packed, held for the long retention, announced, removed                     |
| **STUCK**      | The sweep could not read, pack or verify it                                          | Left in place; reported with the reason                                     |

UNCERTAIN is the default, and it is safe by construction: its only route to removal is a verified archive that sits for the long retention with its restore command printed at every session start.

### 3.2 Proofs of NO VALUE (DISPOSABLE)

An entry is DISPOSABLE when it is past TTL, not LIVE, not KEPT, not PROTECTED, not REFERENCED, and **every** file in it is covered by one of these proofs. A mixed entry is UNCERTAIN.

| Id  | Proof                                                                                                                                                                                                                                                      | Covers                                            |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| P1  | **Consumed shape.** The basename matches a message or log shape: Plan 00560's message, body and journal globs, plus `*.log`, `*.out`, `ci-*`, `qa-*`, `push-*`. Generic `*.txt`, `*.json`, `*.tsv`, `*.md` are deliberately not in this proof.             | Commit, merge, PR, issue and journal bodies; logs |
| P2  | **Regenerable by name.** A subtree matching the `regenerable_paths` dialect: `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `node_modules/`, `*.egg-info/`, and a directory holding `pyvenv.cfg`.                                       | Caches, venvs                                     |
| P3  | **Identical copy.** The file's git blob hash exists in the main repository's object database and is in the **remote-held blob set** (section 3.3.1). Existence in the object database alone proves nothing: a stash or an unpushed branch has objects too. | Copies of the tree, exported files                |
| P4  | **Clean pushed clone.** A nested repository that passes every test in section 3.3, whose untracked files are each covered by P1, P2, P3 or P5.                                                                                                             | Clones made for a repro, with nothing local       |
| P5  | **Empty.** A zero-byte file or an empty directory.                                                                                                                                                                                                         | Leftovers                                         |
| P6  | **Already archived.** A tarball beside its original, where the bidirectional comparison of section 5.2 passes. The tarball is adopted into the store and the original is treated as packed. Its retention still comes from the original's verdict.         | The by-hand packing already done                  |

P1 is the only proof that trusts a name, and it trusts it only in the direction 00560 already enforces at creation: those shapes are the files a command consumes. A report saved as `commit-notes.txt` would be lost after the short hold. That limit is accepted and stated in the guidance.

### 3.3 Proofs of HAS VALUE for repositories (PROTECTED)

Every `.git` directory or file found at any depth in an entry is a repository to judge. The walk finds them; it does not run git inside a path it has not classified.

| Kind                                                                       | Test                                                                                                                                                                                                                                                                                                                                       | Verdict for the entry                                                                     |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| Registered worktree of the project                                         | Its path is in the main repository's `git worktree list --porcelain`                                                                                                                                                                                                                                                                       | PROTECTED. Removal goes through `git worktree remove` and its guard, never a tree delete. |
| `.git` file pointing outside the entry, not registered                     | The `gitdir:` target is not inside the entry                                                                                                                                                                                                                                                                                               | PROTECTED. It is part of some other repository; a human decides.                          |
| Related repository: has a remote, or shares a root commit with the project | (a) `git status --porcelain --untracked-files=no` is empty, or every dirty file's blob passes P3; (b) no stash; (c) every ref tip and HEAD is an ancestor of a **live-verified remote tip** (section 3.3.1)                                                                                                                                | All three hold: P4 applies. Any fails: PROTECTED.                                         |
| Standalone repository: no remote, no shared root commit                    | None. It has nowhere to push, so "unpushed" does not apply (R6). **Its local commits and any dirty tracked content are packed with it and removed when the hold ends**: this is the one place the design narrows "never delete a repository with unpushed commits or dirty tracked content", and the ruling the owner should look at first | UNCERTAIN (R7). Packed whole with its `.git`. Never DISPOSABLE.                           |
| Linked worktree of a nested repository, inside the same entry              | The `gitdir:` target is inside the entry                                                                                                                                                                                                                                                                                                   | Judged with its parent.                                                                   |

The clone's own refs are never the proof. The measurement found a clone with 47 commits "on no remote-tracking ref" that were probably stale refs; the clone's refs prove nothing either way.

#### 3.3.1 What "a remote holds it" means

The main repository's remote-tracking refs are a cache too, and a cached positive is what Plan 00626 moved the branch proofs away from. So this design reuses the rule of `core/remote_branch_proof.py` rather than writing a second one:

- **Live-verified remote tips.** One batched `git ls-remote` of the project's remote (`live_remote_tips`, the listing in `utils/remote_refs.py`). A remote-tracking ref in the main repository counts only when its sha equals the live tip of the same name. With no network answer there are no verified tips, and P3 and P4 prove nothing: entries fall to UNCERTAIN or PROTECTED, never to DISPOSABLE.
- **Test (c).** A commit is held when `git merge-base --is-ancestor <commit> <verified tip>` holds in the main repository for some verified tip. A commit object the main repository does not have is not held.
- **Remote-held blob set (P3).** Built once per sweep as the blobs in the tree of the verified default-branch tip (`git ls-tree -r`), keyed by blob hash. A scratch file passes when `git hash-object` of its content is in that set. Historical blobs are deliberately left out: the set stays small, and a copy of the current tree is the case that occurs.
- Every failure and timeout is a reason, never a pass (the module's own rule).

A standalone repository's dirty or committed content is not proved by any of this; that is why it is UNCERTAIN and never DISPOSABLE.

A git command that times out, fails or is refused makes the entry STUCK, never DISPOSABLE.

### 3.4 Referenced by a tracked file (REFERENCED)

The reference set is built once per sweep, not once per entry: `git grep -h -o -E 'untracked/scratch/[A-Za-z0-9._/-]+'` over the main checkout's HEAD tree and over the tip of every local branch not merged into the default branch. An entry is referenced when a match equals its path or lies inside it. A bare word (the measurement's "word-only match") is not a reference.

A reference means a tracked file is leaning on evidence git does not carry. So a referenced entry must be filed (section 6). Until it is, it is protected from removal (R8), and past TTL it is packed to one archive with no expiry, which is what already happened by hand to `rv614c`. The sweep report names the referencing file and line.

To stop new references, a docs/plan QA check flags a tracked line that cites an `untracked/` path as evidence (advisory first; Phase 7).

### 3.5 Human work and pauses (KEPT)

"Anything the owner or a human wrote" cannot be recognised from file content, and there is no ledger of who wrote what (00560, owner ruling). Two mechanisms stand in:

- **`.scratch-keep`**: a file at the top of an entry, holding one line of reason. An entry with it is KEPT for ever. A guard denies an agent creating it (`Write`, `Edit`, or a Bash-authored path), so it is a human's mark (R15).
- **`scratch-sweep keep <entry> --reason "..." [--hours N]`**: an agent's pause, recorded in the store index, bounded by `scratch.keep.max_hours`, refused when the reason repeats the last one for that entry (the `branch-park` rule).

Legacy content has neither mark. For it, the long retention of UNCERTAIN is the protection, and that limit is stated plainly in the first dogfood report (Phase 8).

### 3.6 What lives in scratch today, by class

| Class                               | Examples                                                               | Verdict past TTL                          | Filed where, if valuable                                                          |
| ----------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------------- |
| Message and body files              | `commit-*`, `journal-*`, `issue-*`, pingbus message files              | DISPOSABLE (P1)                           | Already consumed: the commit, journal or issue is the record                      |
| Logs and captures with a log shape  | `ci-*.txt`, `qa-*`, `*.log`, `*.out`                                   | DISPOSABLE (P1)                           | A figure worth keeping goes into a journal entry                                  |
| Generic captures and notes          | `*.txt`, `*.json`, `*.tsv`, ad-hoc `*.md`                              | UNCERTAIN                                 | Report or findings: `<plan>/subagent-reports/`. Decision: a journal entry         |
| Briefs and handoffs                 | `brief-*.md`, sub-agent handoff files                                  | UNCERTAIN                                 | `<plan>/subagent-reports/` (a handoff for plan work belongs there from the start) |
| Review output                       | `00622-review3/` (findings text plus generated fixtures)               | REFERENCED if cited, else UNCERTAIN       | Findings and case lists: `<plan>/subagent-reports/`. Fixtures: not filed          |
| Probe harnesses and scripts         | `*.py`, `*.sh`, `*.bash`                                               | UNCERTAIN                                 | `scripts/` (tooling) or `tests/` (a harness, with its test first)                 |
| Generated fixture trees             | `rv614c/`, `probe-run/`, `tmpXXXX/`                                    | UNCERTAIN (or P3/P5 where they hold)      | Not filed. The generator, if worth keeping, is a script (row above)               |
| Throwaway repositories              | `proj-*`, `gitprobe`, repositories with links to dummy protected files | UNCERTAIN (standalone, R7)                | Not filed                                                                         |
| Clones and worktrees of the project | `w609-*`, `r614c*`                                                     | P4 if clean and pushed, else PROTECTED    | Push the commits (`git push origin HEAD:refs/heads/<name>`), then it is P4        |
| Caches and venvs                    | `__pycache__/`, a venv                                                 | DISPOSABLE (P2)                           | Not filed                                                                         |
| Release-bound notes                 | a draft release note or upgrade task                                   | UNCERTAIN                                 | `CLAUDE/UPGRADES/UNRELEASED/`                                                     |
| Durable knowledge                   | a how-to, an investigation write-up with no plan                       | UNCERTAIN                                 | `CLAUDE/` docs or `docs/`; with no home, a plan folder is requested (00560 Q1)    |
| Tarballs                            | `rv614c.tar.gz`                                                        | Adopted into the store (P6), or UNCERTAIN | Not filed                                                                         |

## 4. TTL and liveness

- **TTL** = `scratch.ttl_hours`, default 24. An entry may carry a longer one in the session manifest (section 7), bounded by `scratch.max_ttl_hours` (default 72).
- **Clock** = now minus the newest of: the mtime of every file and directory in the entry (`lstat`, links never followed), the entry root's ctime, and the session manifest's birth time for that entry. An mtime in the future is ignored for that inode and its ctime is used.
- **Why three inputs.** `cp -a` and `tar -x` restore old mtimes, so a fresh copy can look expired: the root's ctime and the birth time cover that. `touch` keeps an entry young for ever: `scratch.max_lifetime_hours` (default 168) is measured from birth, or from the first time the inventory saw an unmarked entry, and past it the mtime is no longer consulted.
- **LIVE regardless of age** when: a process has its working directory inside the entry (`default_process_cwds`); or a tracked background process's command names the entry's path (`background_process_tracker` records); or the entry is younger than `scratch.min_age_minutes` (default 30) by birth or ctime.
- **Past TTL means due.** A due entry must leave by one of the four fates in R1. The sweep makes that true for every verdict except PROTECTED and KEPT, which it reports until a human or an agent acts.

## 5. Removal: the archive store

### 5.1 Layout

`untracked/scratch-archive/` in the **main** checkout only, mode 0700, flat: archive files, one `index.jsonl`, one lock file. No directory trees, so the store adds one directory to the link index however much it holds.

Each index record: id, original path, checkout, verdict, proof ids, packed-at, expires-at (null for REFERENCED and for a kept record), entry counts by type, archive size and SHA-256, skipped special files, and the restore command. Loose files of one run and one verdict are packed together into one archive, so 3,500 loose files become a handful of files.

### 5.2 The order of operations (never both gone)

For each due entry that is DISPOSABLE, UNCERTAIN or REFERENCED, under the store's `flock`:

1. **Re-classify** from a full, unbudgeted walk of that entry. A cached verdict never authorises an action.
2. **Claim**: `renameat` the entry to `.sweeping-<name>` in the same directory, through a directory descriptor opened with `O_NOFOLLOW`. From here a late writer using the old path fails loudly instead of writing into a tree that is about to go.
3. **Re-check** liveness and the fingerprint (entry count, newest ctime) against step 1. Any change: rename back, verdict LIVE.
4. **Pack** with GNU tar by argv (no shell), from inside the claimed directory, with `--one-file-system`, never `-h` or `--dereference`. Links are stored as links. Sockets, FIFOs and device nodes are skipped and listed in the record.
5. **Verify, both ways**: `tar --compare` exits 0 with no output (archive against tree), and the archive's member count equals the walk's count less the listed skips (tree against archive, which `--compare` alone does not check). Then record the SHA-256 and `fsync` the archive and the index.
6. **Remove** the claimed tree with descriptor-based removal (`shutil.rmtree` where `avoids_symlink_attacks` is true; otherwise refuse), staying on one device.
7. **Expire**: a later sweep removes an archive whose `expires-at` has passed, after re-checking that no keep record or new reference covers it. Retention: `scratch.archive.disposable_hours` (default 12) and `scratch.archive.uncertain_hours` (default 168).

The claim rename is expected to change the entry root's own ctime (the builder confirms this in Task 3.2). So the fingerprint leaves the root inode out, and an entry renamed back carries a recorded "claimed at" time that the section 4 clock subtracts, so a STUCK entry does not look newly born. Both have a test.

A failure at steps 2 to 5 renames the entry back and marks it STUCK. A failure at step 6 leaves a `.sweeping-` tree and a complete archive; the next sweep finishes the removal after re-verifying the archive against it. At every point the original, a verified archive, or both exist.

### 5.3 What is never done

- No `find ... -delete`, no bulk `rm -rf` of a path string, in code or in any printed suggestion.
- No action on an entry whose walk hit a budget, an unreadable directory or a second device. Incomplete is STUCK.
- No following of a link, at the entry root or inside it. An entry that is itself a link has only the link removed, with its target recorded.
- No packing of a file whose link count exceeds the names seen inside the entry: its other name is outside, and the archive would copy content the entry does not own.
- No removal of a registered worktree's tree, and none of a PROTECTED or KEPT entry.
- No printing of file content. The sweep reports names, counts, sizes and proof ids only.

## 6. Filing: who does it and where

**The sweep proposes; an agent or a human files (R4).** For each UNCERTAIN, REFERENCED or PROTECTED entry the report prints a destination and the command that would move it. Nothing is moved by the sweep, because a filed file needs a name, a commit and the content guards (`sensitive_content`, `qa_suppression`, `markdown_organization`), which do not see a `mv`.

The destination is chosen by rule, and the rule is only a suggestion (as in 00560 D4, content picks the hint and never the verdict):

| Signal                                                                 | Proposed home                                                                               |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| The manifest names a plan, or the entry name starts with a plan number | `CLAUDE/Plan/<plan>/subagent-reports/` for prose; a journal entry for a decision            |
| A script                                                               | `scripts/` or `tests/`, test first (`tdd_enforcement` applies)                              |
| Release wording                                                        | `CLAUDE/UPGRADES/UNRELEASED/`                                                               |
| Commits or dirty tracked files in a related repository                 | Commit, then push to a branch on the remote; the entry then passes P4                       |
| Prose with no plan                                                     | "No tracked home: ask the coordinator for a plan folder" (00560 Q1), and it stays UNCERTAIN |
| A file above `scratch.filing.max_bytes` (default 262,144)              | "Too large to track: file a summary and let the rest expire"                                |

An entry that is filed is then deleted by its filer, or simply expires. An entry nobody files expires through its verdict. That is the owner's rule: filed, or deleted.

## 7. The convention: one directory per session

- **Name**: `untracked/scratch/s-<UTC date and time>-<first 8 of the session id>/`, created by the daemon at SessionStart in the checkout the session starts in, and announced in the SessionStart context as "your scratch directory". A sub-agent uses its parent session's directory name inside its own checkout's scratch root.
- **Manifest**: `.scratch-session.json` in that directory, written by the daemon: schema version, session id, birth time, checkout, branch, and an `entries` map. `hooks-daemon scratch new <name> [--purpose ...] [--plan NNNNN] [--ttl-hours N]` creates an entry, records its birth, purpose, plan and TTL, and prints the path. The purpose and plan feed only the filing proposal.
- **Owner and birth** therefore come from the daemon, not from the agent and not from mtime.
- **A session directory** is itself removed when it is empty apart from its manifest and older than the TTL.
- **Unowned entries** (a new file or directory made directly in a scratch root) draw an advisory naming the session directory, through the same accessor 00560 uses for Bash-authored writes. It starts as an advisory; the mode key allows a deny later.
- Whether SessionStart can also export the path to the shell (Claude Code's environment file for hooks) is to be confirmed on a live payload as the first step of Task 4.1; the design does not depend on it.

## 8. Caps

Counted from a cached inventory (`untracked/scratch-inventory.json`, one file): per entry, directories, files, bytes, newest mtime and verdict hint. The inventory is refreshed in a background thread at SessionStart, after a Bash command that creates directories under a scratch root, and by every `scratch-sweep` run. A hook only ever reads the file.

| Key                                | Warn                      | Block                     |
| ---------------------------------- | ------------------------- | ------------------------- |
| `scratch.caps.directories`         | 10,000                    | 25,000                    |
| `scratch.caps.bytes`               | 1 GiB                     | 4 GiB                     |
| `scratch.caps.entries`             | 500                       | 2,000                     |
| `scratch.caps.project_directories` | 50% of the link index cap | 75% of the link index cap |

Counts cover every scratch root, the archive store and the registered stores under `untracked/`, because the link index counts all of them.

- **At warn**: a SessionStart line and a must-do item naming `scratch-sweep --apply`.
- **At block**: rule `R-SCRATCH-CAP` denies a Bash command that creates a directory tree under a scratch root (`mkdir`, `git clone`, `git init`, `git worktree add`, `cp -r`, `tar -x`, `mktemp -d`), naming the largest entries and the sweep command. A `Write` of a file, and a redirect into a file, are never denied: commit and journal bodies must always be writable.
- **Pressure mode**: at block, `scratch-sweep --apply` also packs entries that are not yet due, largest directory count first, provided they are not LIVE, KEPT or PROTECTED and have been idle for `scratch.caps.pressure_idle_minutes` (default 30). Packing is not removal: such an archive expires no sooner than its entry's TTL plus its verdict's retention.
- **Never stranded**: if a sweep has run and the count is still over the block cap only because of PROTECTED, KEPT or LIVE entries, the deny becomes an advisory listing them.
- **An incomplete inventory** can raise a cap verdict and never lower one, and the report says it is incomplete.

**Rollout.** The cap guard is built in Phase 5 and the backlog is cleared in Phase 8, and this repository's scratch alone is at about 61,000 directories, over the proposed block cap; the registered stores have not been measured at all. So this repository runs `caps.mode: advise` until Task 8.3 has run, and the default figures in the table are provisional until Task 1.7's dry run has measured scratch and the stores.

A single command can still make 168,000 directories before any hook runs. The cap cannot prevent that; pressure mode is what bounds how long it lasts.

## 9. The link index

- No exclusion of any path, in config or code (R11). The index's promise is that it has seen every directory.
- The sweep reduces what it sees: a packed entry is one file, and the store is one directory.
- When Plan 00623 merges, the index exposes the number of directories it listed and its cap; `scratch.caps.project_directories` reads those instead of counting again. Until then the inventory's own count is used for scratch and the stores only.
- The sweep's reporting names the largest entries by directory count first, because directory count, not bytes, is what overflows the index.

## 10. Tooling and enforcement surfaces

| Surface                              | Behaviour                                                                                                                                                                                                                                                   | Reuses                                            |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| `hooks-daemon scratch-sweep`         | Dry run by default: a table of entry, verdict, proof, action, directories, bytes. `--apply` acts. `--json`, `--root`, `--entry`. Sub-commands `keep`, `restore <id>`, `status`. A sub-agent's `--apply` is limited to its own checkout's root.              | `branch-sweep` CLI shape; `ScanDeadline`          |
| `hooks-daemon scratch new`           | Creates an entry in the session directory and records it                                                                                                                                                                                                    | `mkplan.bash` lock pattern                        |
| SessionStart handler `scratch_sweep` | Creates the session directory; prints, from the cached inventory only, the counts by verdict, the overdue-to-file list, archives about to expire with restore commands, and the caps. Silent when clean. Says so when the inventory is incomplete or stale. | `branch_sweep`, printed directly after it         |
| Must-do item                         | When anything is due or a cap is at warn: "run `scratch-sweep --apply`"                                                                                                                                                                                     | `session_actions_directive`                       |
| Housekeeping                         | A report step `scratch-sweep` and a mutating step `scratch-sweep-apply` that acts without confirmation (R13)                                                                                                                                                | `HOUSEKEEPING_STEPS`, `UNCONFIRMED_STEP_NAMES`    |
| Idle pass                            | `idle_housekeeping_advisory` names the sweep instead of printing `find ... -delete`; `stale_scratch_days` is retired with a config-changes entry                                                                                                            | `stale_litter.collect_scratch_report` is replaced |
| Routine                              | This repository declares a routine for the sweep, so a sweep that stopped running is reported                                                                                                                                                               | `CLAUDE/Routine/`, `routine_qa_sweep`             |
| `R-SCRATCH-CAP`                      | Section 8                                                                                                                                                                                                                                                   | Bash command parsing helpers                      |
| `R-SCRATCH-KEEP-MARKER`              | Denies an agent creating `.scratch-keep`                                                                                                                                                                                                                    | `get_written_file_paths`                          |
| Unowned-entry advisory               | Section 7                                                                                                                                                                                                                                                   | 00560's shared predicate                          |

Config, added to 00560's single top-level block:

```yaml
scratch:
  ttl_hours: 24
  max_ttl_hours: 72
  max_lifetime_hours: 168
  min_age_minutes: 30
  sweep:
    extra_roots: []              # other agent-written ignored directories to judge the same way
    max_listed: 50
    unowned_entry: advise        # advise | block | off
  archive:
    disposable_hours: 12
    uncertain_hours: 168
  keep:
    max_hours: 168
  filing:
    max_bytes: 262144
  caps:
    directories: {warn: 10000, block: 25000}
    bytes: {warn: 1073741824, block: 4294967296}
    entries: {warn: 500, block: 2000}
    project_directories: {warn_percent: 50, block_percent: 75}
    pressure_idle_minutes: 30
    mode: block                  # block | advise | off
```

This repository sets `sweep.extra_roots` to the loose files directly under `untracked/`, `untracked/briefs/`, `untracked/reports/` and `untracked/agent-reports/` (not its `auto/` store, which has its own pruning).

## 11. Worktrees

- Each registered worktree's `untracked/scratch/` is a scratch root, swept from the main checkout or from inside that worktree.
- **On reap** (`worktree-reap --reap`, `cleanup_after_merge`): before the removal is judged, the reaper runs the sweep on that worktree's scratch root in **evacuate** mode. Every entry is classified whatever its age. A PROTECTED, KEPT or STUCK entry refuses the reap, as scratch does today. Everything else is packed into the main checkout's store with its normal retention. An empty scratch root (its `.gitignore` only) is then not a blocker.
- `NEVER_REGENERABLE` stays: scratch is never declared rebuildable. What changes is that there is a sanctioned way to empty it.
- A registered worktree that lives inside a scratch root (`w609-mainwt`) is reported with the `git worktree remove` command; the sweep never touches its tree.

## 12. Changes to the instructions agents read

Every place that tells an agent where to write scratch says three things: write inside your session directory; it is gone after 24 hours; anything worth keeping is filed where git carries it. The places, to be edited at their `src/` originals:

- `project_containment`: the source comment, rule `fix` and `verbose`, deny suffix and guidance ("Write it inside the repository"). This merges with 00560 Task 2.1; whichever lands first carries the wording.
- `pipe_blocker` guidance ("`pytest tests/ > untracked/scratch/out.txt`"), `plan_journal_guard` rule fix, `subagent_context_budget` handoff text and `DEFAULT_HANDOFF_GLOBS`, `curl_pipe_shell` example, `issue_report/reproduction.py`, `utils/scratch_dir.py`.
- `CLAUDE/PlanJournalling.md`, `mkplan.bash` usage, agent and skill definitions, shipped templates (00560 F10 counted them).
- Probe and review harness guidance: generated fixture trees go in an entry made by `scratch new`, and a harness removes its own tree when it finishes.

## 13. Threat and failure analysis

| Risk                                                                               | Defence                                                                                                                                                                        |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Valuable work removed because a rule misjudged it                                  | DISPOSABLE needs a positive proof for every file; everything else is held 168 hours as a verified archive and announced each session; PROTECTED and KEPT are never touched     |
| An agent declares its own work valueless                                           | No verdict input comes from an agent. `keep` can only delay; `.scratch-keep` is denied to agents                                                                               |
| Unpushed commits or dirty files in a clone                                         | Section 3.3, tested against the main repository's objects, with every git failure read as STUCK                                                                                |
| Stale or forged remote-tracking refs inside a clone make it look pushed            | The clone's own refs are never the proof                                                                                                                                       |
| A running agent's entry is swept under it                                          | TTL on newest mtime; process working-directory check; background-process records; minimum age; claim-by-rename so a late write fails loudly; the restore command in the report |
| The tree changes between verification and removal (TOCTOU)                         | Claim first, then re-check the fingerprint, then pack and verify the claimed tree, which no path any agent holds still names                                                   |
| A link inside scratch points outside (including at a dummy or real protected file) | `lstat` everywhere; tar stores links; removal is descriptor-based; the entry root as a link has only the link removed; one device only                                         |
| A hard link shares content with a file outside the entry                           | Link-count check; such an entry is STUCK                                                                                                                                       |
| A path swapped for a link between check and use                                    | Operations go through directory descriptors opened `O_NOFOLLOW`, not through path strings resolved earlier                                                                     |
| A partial archive is trusted                                                       | Bidirectional verification, SHA-256, `fsync` before removal; an archive with no index record is ignored and reported                                                           |
| Crash or kill mid-sweep                                                            | Section 5.2: at every step the original or a verified archive exists; `.sweeping-` trees are resumed or renamed back                                                           |
| Two sweeps at once (two sessions, a worktree and main)                             | One `flock` on the store; the claim rename is atomic                                                                                                                           |
| Unreadable, read-only or foreign-owned files                                       | Pack fails, entry renamed back, STUCK with the reason. Write permission is added only on directories inside a claimed tree, without following links                            |
| File names starting with `-`, or holding newlines                                  | argv with `--` and `./` prefixes; NUL-separated lists; no shell                                                                                                                |
| The scan is cut short and reads as clean                                           | An incomplete scan is reported as incomplete, authorises nothing, and can only raise a cap verdict                                                                             |
| The archive store itself grows without bound                                       | Every record but REFERENCED and kept ones expires; store bytes count toward the caps; the report lists never-expiring records                                                  |
| The archive copies protected content                                               | Packing moves bytes within the ignored tree and prints none of them; the link-count rule stops content the entry does not own; nothing is read into a session                  |
| The cap guard wedges a session                                                     | Files are never denied; the deny downgrades when only protected entries remain                                                                                                 |
| The sweep is disabled or stops running, and scratch grows again                    | The routine's dead-man's switch; the caps, which need no sweep to fire                                                                                                         |
| Clock changes                                                                      | Future mtimes ignored; expiry compares stored UTC instants; a backwards jump only delays removal                                                                               |

## 14. Test plan

All test-first, with fake trees under pytest's `tmp_path`, an injected clock, injected process list and injected git runner where a real repository is not the point.

- **A tree builder** (`tests/helpers/scratch_tree.py`): entries with set mtimes and ctimes, session manifests, links to dummy files outside the fake root, hard links, FIFOs, unreadable directories, real `git init` repositories with and without a bare "remote", a clone of a fake project with dirty, stashed and unpushed states.
- **Clock**: newest mtime wins; a `cp -a` copy is not due; `touch` cannot outlive the maximum lifetime; a future mtime is ignored.
- **Verdicts**: one test per row of sections 3.1 to 3.3, plus the ordering (LIVE over everything, PROTECTED over REFERENCED, and so on) and "a mixed entry is UNCERTAIN".
- **Proofs**: P3 with a blob that exists only on an unpushed branch (not proved); P4 with stale remote refs inside the clone (not proved); P1 not matching `notes.txt`.
- **References**: exact path counts, bare word does not, a reference on an unmerged branch counts.
- **Archive**: round trip (pack, verify, restore, compare with the original); the archive is flat; mismatch injected at each verification refuses the removal.
- **Crash safety**: a failure injected after each of steps 2 to 6; assert the original or a verified archive exists, and that a second run converges.
- **Escapes**: a link at the entry root, a link deep inside, a link swapped in between classify and claim; assert the outside dummy file's content and mtime are untouched.
- **Races**: a write between classify and claim makes the entry LIVE; a process working directory inside refuses.
- **Dry run**: an apply-free run leaves every inode's mtime, ctime and name unchanged (a snapshot comparison).
- **Caps**: warn, block, pressure order, the never-stranded downgrade, an incomplete inventory.
- **Handlers**: unit tests per handler, plus acceptance tests for `R-SCRATCH-CAP`, `R-SCRATCH-KEEP-MARKER` and the SessionStart report, with fixtures under `untracked/acceptance/`.
- **A property test**: for random trees, after `--apply`, no path that a fresh classification calls LIVE, KEPT or PROTECTED has changed.

## 15. Existing code and plans that contradict this design

| Id  | Where                                                                                                   | Contradiction                                                                                                                                                                   | Resolution                                                              |
| --- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| X1  | `utils/stale_litter.py:38,41,44,193`                                                                    | 14-day default, per-file mtime, a 100,000-entry and 3-second scan, and a printed `find ... -type f -mmin +N -delete`: removal on age alone, files only, directories left behind | Replaced (Task 7.2)                                                     |
| X2  | `handlers/user_prompt_submit/idle_housekeeping_advisor.py:159`                                          | The only scratch report rides a handler that is off by default and fires on idle ticks                                                                                          | SessionStart handler and must-do item (Phase 5)                         |
| X3  | `handlers/pre_tool_use/project_containment.py:117` and its rule and guidance text (00560 CODE-FACTS F1) | Calls scratch the place for durable work                                                                                                                                        | Section 12                                                              |
| X4  | `utils/regenerable_paths.py:59`, `config/models.py:2462`                                                | `NEVER_REGENERABLE` makes any worktree with scratch content refuse removal, with no way to empty it                                                                             | Section 11                                                              |
| X5  | `handlers/pre_tool_use/subagent_context_budget.py:87`                                                   | `DEFAULT_HANDOFF_GLOBS` accepts `untracked/scratch/**` as a handoff home; a handoff there now expires                                                                           | Guidance: plan work hands off into `subagent-reports/`                  |
| X6  | `issue_report/reproduction.py:51-55`                                                                    | Tells agents a fixture under scratch "survives"; it survives a restart and then the TTL                                                                                         | Wording (Task 7.1)                                                      |
| X7  | `daemon/housekeeping.py:30`                                                                             | Housekeeping step reports default to `untracked/reports`, an ignored directory that nothing prunes                                                                              | Listed in `extra_roots` for this repository; ledgered                   |
| X8  | `daemon/housekeeping.py` module docstring, Decision 6                                                   | Only the two formatters act without confirmation                                                                                                                                | Amended by R13                                                          |
| X9  | `utils/link_index.py` (00623 branch) `BUILD_DIRECTORY_CAP`                                              | The index fails whole at the cap with no warning below it                                                                                                                       | Section 8 and 9                                                         |
| X10 | Plan 00560 non-goal, Q4 baseline, DESIGN.md section 6                                                   | No automatic removal; backlog exempt                                                                                                                                            | R12                                                                     |
| X11 | `handlers/subagent_stop/subagent_report_persistence.py` (00560 CODE-FACTS F4)                           | Prunes saved replies by count and age with no value test                                                                                                                        | Left as it is (a crash net with its own retention); counted in the caps |
| X12 | Every agent worktree's own `untracked/scratch/`                                                         | Read by nothing                                                                                                                                                                 | Section 11                                                              |
| X13 | `pipe_blocker` guidance and `plan_journal_guard.py:202`                                                 | Point at the bare scratch root                                                                                                                                                  | Section 12                                                              |
| X14 | `core/worktree_paths.py:89`                                                                             | Treats `untracked/scratch/wt` as a place worktrees may sit                                                                                                                      | Kept working; such a worktree is PROTECTED and reported                 |
