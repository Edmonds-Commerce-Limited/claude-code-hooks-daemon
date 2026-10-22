# Release Process

**ALWAYS use `/release` skill. NEVER manually tag, edit CHANGELOG.md, or edit RELEASES/\*.md.**

## 🚨 A RELEASE IS HUMAN-GATED (ABSOLUTE, READ BEFORE ANYTHING ELSE)

**A release may ONLY begin when a human invokes `/release` in the CURRENT session.
An agent must never start, resume, or complete a release on its own initiative.**

### Why — this is not ceremony

**A release is a decision about SCOPE, and scope is not visible from inside the
repository.** The human decides which work belongs in a bundle. An agent can see
that the tree is clean, that QA is fully green, and that a version is bumped — and from
that it can see nothing at all about whether the intended bundle is complete.
There may be work not started, work in another session, work not yet described to
you. Cutting a release early does not just publish sooner: it strands the rest of
the bundle behind a version boundary and forces an unplanned follow-up release.

"The gates all passed" is therefore NOT authorisation. The gates check that a
release *would be sound*, never that it is *wanted now*.

### The rule

**`/release` is the one and only authorisation.** There is no secondary
human confirmation before tagging or publishing (owner ruling, v3.57.0
release — an earlier revision of this document invented one and it was
wrong). The release process is gated ONLY by the factors that confirm the
release is ready: the pipeline's blocking gates (Steps 6, 8–13). It
ultimately passes — and publishes — or it fails and is aborted.

| Situation                                                              | Allowed to tag/publish?             |
| ---------------------------------------------------------------------- | ----------------------------------- |
| Human invoked `/release` and every blocking gate has passed            | YES — proceed, do not ask           |
| Release state file exists (a `/release` run in flight, see below)      | YES — resume and finish             |
| A cron tick, failsafe-recovery wake-up, or `/loop` iteration fires     | **NO** — no state file ⇒ no release |
| The working tree looks "ready" and a version bump is already committed | **NO**                              |
| A plan or TODO says "finish the release"                               | **NO**                              |

### A release MAY span a compaction — and then it MUST be finished

Releases are long. A compaction part-way through one is normal, not an anomaly,
and **abandoning a half-finished release is its own broken state**: the version
is bumped, `UNRELEASED/` task and manifest directories have been moved, the
changelog and release notes are written, and nothing is tagged. Leaving that
sitting in the tree is worse than either finishing or reverting it.

So the two failure modes are symmetric, and both are real:

- **Fabricating authorisation** — an agent decides a release is wanted because
  the tree looks ready. This publishes work the human never agreed to bundle.
- **Losing authorisation** — an agent drops a genuinely authorised release
  because a compaction ate the instruction. This strands the tree mid-release.

**Neither is solved by remembering harder.** Authorisation and progress must be
recorded WHERE A COMPACTION CANNOT REACH — on disk, not in context.

### The release state file

`/release` MUST write `untracked/release-state.json` as its first action, and
update it as each numbered step completes:

```json
{
  "version": "3.52.0",
  "authorised_by_human_at": "<ISO timestamp of the /release invocation>",
  "last_completed_step": 8,
  "notes": "human confirmed scope: plans 00197-00202 + 00206"
}
```

Once Step 8 opens the release pull request, the file also carries a `ci`
record of that pull request's CI run:

```json
"ci": {"pr_number": 12, "run_id": 987654, "head_sha": "<40-hex sha>", "conclusion": "success"}
```

All four fields are required and no others are allowed; while the run is still
going, `conclusion` is `pending`. The record is written as soon as the pull
request and its run exist (Step 8), and rewritten whenever a new commit on the
release branch starts a new run. Two things read it:

- `release_merge_freeze` (rule R-RELEASE-MERGE-FREEZE) takes `pr_number` as the
  open release pull request and freezes every other merge and push to `main`
  ([The merge freeze](#the-release-pull-request-and-the-merge-freeze)).
- `scripts/release/check_release_ci.py` (Step 13) exits non-zero with one named
  reason unless the conclusion is `success`, `head_sha` equals the commit at
  HEAD, and `gh run view <run_id>` still reports the same conclusion and head
  commit.

Rules for reading it:

- **No state file ⇒ no release is in progress.** A dirty tree, a bumped
  version, or a plan saying "finish the release" is NOT a substitute. Ask.
- **State file present ⇒ a release IS authorised.** Resume from
  `last_completed_step`; do not restart it and do not re-litigate whether it
  should happen. That authorisation covers the WHOLE pipeline, tagging and
  publishing included — once the blocking gates pass, proceed through the
  merge (Step 13) and Steps 14–15 without asking again. (A
  `publish_authorised` field in an old state file is legacy; ignore it.)
- **Resuming past Step 8** means the release branch and pull request already
  exist: `git switch release/<version>` (it is on `origin` if the checkout was
  lost), read `ci.pr_number`, and carry on from `last_completed_step`. A run
  recorded `pending` is waited for again (Step 8); never re-open a second pull
  request for the same version.
- **Delete the file** once Step 15 verification succeeds, so a later session
  cannot mistake a finished release for an in-flight one. Deleting it also
  lifts the merge freeze.

**Step 1a runs BEFORE the state file, and that is not a contradiction of
"first".** The state file is the first thing `/release` writes; the slate-clean
gate is the first thing it *runs*, and it precedes the write. A release that
never cleared the slate gate never started — nothing bumped, nothing moved, no
agent spawned — so there is no authorisation to preserve across a compaction.

Writing it first instead manufactures a deadlock, which is not hypothetical
(Plan 00407 N1): Step 1a's exit `2` tells you to stop with
`[awaiting-human] the release slate is not clean`, and `release_blocker` then
DENIES that stop because a state file exists at `last_completed_step: 0`. Its
only route out is deleting the file, which it correctly calls the ABORT action
— so the gate's documented outcome, "a human decides and re-invokes with
`accept-wip`", can only be reported as an abort, with the recorded
authorisation destroyed on the way. Those two outcomes read differently to
whoever finds the transcript, and only one of them is what happened.

So: run `release-slate-check` first, and write the state file once it returns
`0` — including the `0` that `accept-wip` produces.

The scope question — "is the bundle complete?" — is the one thing an agent
cannot answer from the repository, which is why `notes` records the human's
answer rather than the agent's inference.

**The blocking gates are the only gates.** Tagging and publishing are
outward-facing and effectively irreversible — which is exactly why the
pipeline's blocking gates exist. Once they pass inside an authorised
`/release` run, tag and publish without a further confirmation; there is no
"ask before those steps" rule. The doubt case is about STARTING a release
(no `/release`, no state file ⇒ ask), never about finishing one whose gates
are green.

### Recovering from an unauthorised release

Do NOT silently unpublish — that is a second unilateral outward-facing act. Tell
the human what was published and let them choose between leaving it (the next
bundle simply becomes the following version) and withdrawing it:

```bash
# ONLY on explicit human instruction:
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
gh release delete vX.Y.Z --yes
```

## Prerequisites

- Clean git state on `main`, whose HEAD passed CI (Step 1a checks it)
- `gh auth status` authenticated
- Write access to GitHub repository (push a branch, open and merge a pull
  request, push a tag, create a release)

## Quick Release

```claude-code
/release          # auto-detect bump
/release 2.2.0   # explicit version
/release patch    # bump type
```

## Pipeline Overview

```
PREPARE (in session, on branch release/<version>)
1.  Pre-Release Validation             1a slate gate, 1b release branch + agent validation, 1H Housekeeping phase, 1c Claude Code review
2.  Version Detection
3.  Version Update (Agent)
4.  Changelog Generation (Agent)
5.  Release Notes Creation (Agent)
6.  Move UNRELEASED Post-Upgrade Tasks   <- BLOCKING
7.  Opus Documentation Review          7.1 commit on the release branch
WAIT (CI on the pull request)
8.  Release Pull Request + CI Gate      <- BLOCKING   8a push + open PR, 8b Start-up Budget Gate <- BLOCKING, 8c wait for `Release gate`
9.  Breaking Changes Check               <- BLOCKING
10. Code Review Gate                     <- BLOCKING
11. CLAUDE.md Guidance Audit             <- BLOCKING
12. Acceptance Testing Gate              <- BLOCKING
RELEASE (in session, local daemon)
13. Verify CI & Merge the Pull Request   <- BLOCKING
14. Tag the Merge Commit & GitHub Release
15. Post-Release Verification         15.1 Housekeeping phase, post-release items
```

There is **no local full QA run** anywhere in this pipeline. The whole gate
(`llm_qa.py`'s every check, every supported Python, the performance sweeps)
runs in CI on the release pull request (workflow `release-gate.yml`, summary
check `Release gate`), and that run is the release's recorded QA result (the
state file's `ci` record). Targeted checks the session can run cheaply
(`llm_qa.py changed`, a single test file) are still fine at any step.

Steps 9–12 do not need the CI run to have finished: run them while Step 8c
waits. Any commit they add goes onto the release branch and is pushed, which
starts a new CI run; Step 8c then waits for THAT run and rewrites the `ci`
record. Step 13 refuses to merge anything CI did not pass on the exact head.

The **Housekeeping phase** ([below](#housekeeping-phase-every-release)) hooks into every release: chores that are not
about what is being released but need doing regularly, with the release as the checkpoint.

**ANY blocking gate failure = ABORT release immediately. No exceptions.**
Aborting after Step 8a also means closing the pull request (see
[Rollback](#rollback)).

Agents cannot spawn nested agents. Main Claude orchestrates by invoking agents sequentially.

## The Release Pull Request and the Merge Freeze

**Why a pull request.** The tag must land on a commit the whole gate passed.
Running the gate locally held the host lock for the entire suite, and no check
tied the gated tree to the tagged one: v3.67.0's tag carried a stale
UNRELEASED index (Plan 00474 ledger N263). The release pull request's CI tests
the exact commit that is then merged, and Step 13 proves it before merging
(Plan 00476).

**Why the tagged merge commit is the gated tree.** Step 14 tags the merge
commit `gh pr merge --merge` creates on `main`, not the pull request's head.
A merge commit's tree is the combination of its two parents. When the release
branch already contains every commit on `main` (it is up to date), the
combination adds nothing from `main`, so the merge commit's tree is
byte-for-byte the head's tree, the tree CI passed. Step 13 therefore requires
the branch to be up to date before merging, and Step 14 compares the two trees
before tagging.

**The freeze.** While the state file's `ci` record names a pull request,
project handler `release_merge_freeze` (rule **R-RELEASE-MERGE-FREEZE**) denies
every command in this project that would move `main` other than the release
itself: `git merge` on `main`, `git push` to `main` (including `HEAD:main`,
`--all` and `--mirror`), and `gh pr merge` of any pull request other than
`ci.pr_number` (or of none named). An unreadable or malformed state file denies
those same commands too (fail closed). Pushing the release branch, pushing the
tag, and `git pull` on `main` are not frozen.

**If `main` moves anyway** (another clone, the GitHub UI, a merge queued before
the freeze), the release branch is no longer up to date and the merge commit
would carry trees CI never saw. Update the branch, never `main`:

```bash
git -C /workspace fetch origin
git -C /workspace switch release/X.Y.Z
git -C /workspace merge --no-edit origin/main      # on the release branch: not frozen
git -C /workspace push origin release/X.Y.Z
```

The push starts a new `Release gate` run (the workflow cancels the superseded
one). Go back to Step 8c: wait for it, rewrite the `ci` record with the new
run id and head, and re-enter Step 13. If the merged-in commits change `src/`,
the Step 10 review and the Step 12 acceptance run cover them as well.

**Finishing or aborting lifts the freeze.** Finishing: Step 15 deletes the
state file. Aborting: close the pull request, then delete the state file
([Rollback](#rollback)). Never edit `ci.pr_number` to let another merge through.

## 🚨 Review Early, Never Drop Findings (Plan 00157)

The Code Review Gate (Step 10) and CLAUDE.md Guidance Audit (Step 11) run
**after** the pull request is opened (Step 8) and just **before** the
Acceptance gate (Step 12). That ordering has a cost: any fix applied to a
review finding is a new commit on the release branch, so CI runs the whole gate
again and the acceptance run restarts (code changes can regress earlier
tests). So **blocking** findings are expensive to fix in place, and there is
pressure to defer **non-blocking** findings — which risks losing review value as
silent tech debt.

Two non-negotiable rules close that gap:

1. **Prefer reviewing early.** When practical, run the code review + guidance
   audit against the diff *before* Step 8a opens the pull request, so findings
   can be fixed and committed before CI's one run rather than triggering a
   second run and a FAIL-FAST restart.

2. **A release carries no known defect.** Every review finding that describes
   a DEFECT — wrong behaviour, a fail-open gap, a leak, a contract the code
   does not keep — is fixed before the release ships, whether or not the
   reviewer called it blocking. "Non-blocking" is the reviewer's estimate of
   urgency; it is not permission to ship the defect. A review whose findings
   evaporate into scrollback is wasted work, and a review whose findings are
   parked is a release that knowingly ships broken.

   **Fix it in the release session, before the tag.** With rule 1 the review
   runs before the CI and acceptance gates, so fixing in place costs one pass,
   not a FAIL-FAST restart. Fix the defect on the release branch, run targeted
   QA, continue the pipeline.

   **Deferral is the human's call, never the agent's.** A defect may ship
   only if the human, asked in the release session, explicitly accepts it
   (say what it is and what it costs). An accepted defect is then the FIRST
   unit of work after Step 15, started in the same session — not a plan
   filed for someone to schedule. Three ledger plans (00295, 00311, 00319)
   sat untouched for a week under the previous wording, which is exactly the
   silent tech debt this section exists to prevent.

   **What may be filed instead of fixed**: a finding that is not a defect — a
   refactoring suggestion, a design question, a judgement call the reviewer
   flagged as such. File it as a plan (`CLAUDE/Plan/NNNNN-*`) with file:line
   and the reviewer's reasoning. Filing is automatic and needs no approval;
   "shall I file it?" is not a question to ask.

   **Preserve the evidence with it.** Review reports and probe harnesses
   normally land in `untracked/`, which is gitignored and does not survive a
   container restart — so the corpus proving a finding real is the first thing
   lost. Copy the report and any probes into the plan's own folder (which IS
   tracked) as part of filing it.

   This rule is not release-specific — it governs ANY review. The general
   statement, and the Definition of Done item that carries it, is
   [CLAUDE/CodeLifecycle/General.md](../CodeLifecycle/General.md) ("Review
   Findings Are Filed, Never Surfaced"); what this section adds is the
   release-specific sequencing above.

## 🚨 Absolute Paths Only (NON-NEGOTIABLE)

**Every command in the release flow MUST use absolute paths. NEVER `cd` into a subdirectory.**

The Bash tool's working directory **persists between calls**. A single `cd` (e.g. into `untracked/release-artifacts/` for a checksum loop) silently breaks every later relative-path command — `git tag -F RELEASES/vX.Y.Z.md`, `git push origin vX.Y.Z`, and `gh release create ... untracked/release-artifacts/*.sh` all resolve against the wrong cwd and fail with `could not open ...`, `src refspec does not match any`, or `no matches found`. This shipped a half-broken release attempt in v3.17.0 (main pushed, tag + GitHub release silently skipped) before it was caught.

Rules:

- Use `/workspace/...` absolute paths for ALL file arguments: `git tag -a vX.Y.Z -F /workspace/RELEASES/vX.Y.Z.md`, `gh release create ... /workspace/untracked/release-artifacts/upgrade.sh`, etc.
- If a step needs a different directory, prefer `git -C /workspace ...` or absolute paths over `cd`. If you must `cd`, immediately `cd /workspace` afterwards in the SAME command, and verify `pwd` before the next git/gh step.
- After tag + release creation, VERIFY with ground-truth checks (`git tag -l vX.Y.Z`, `git ls-remote --tags origin vX.Y.Z`, `gh release view vX.Y.Z`) — non-zero exit or empty result = the step failed; do not trust scrollback.

---

## Steps 1-5: Agent-Automated

### 1. Pre-Release Validation

**1a. Slate-clean gate (Plan 00359) — runs FIRST, before any agent is spawned.**

Every other gate in this pipeline looks at the CODE. This one looks at the
state of the WORK around it, because a release can otherwise begin on a HEAD
that CI never passed, over plans mid-work, with unlanded branches and live
worktrees — and every code gate would pass.

```bash
bin/hooks-daemon release-slate-check
```

| Exit | Meaning                                                                                                    | Pipeline                                         |
| ---- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `0`  | Clean: HEAD's exact sha has a completed, successful CI run; no plan mid-work; no branch ahead; no worktree | Proceeds exactly as before — no prompt, no pause |
| `2`  | Something is in flight. The report names every item                                                        | **STOP.** A human decides                        |
| `1`  | The check could not be made (no `gh`, not a repo, a lookup or a git listing failed)                        | **ABORT.** Never treated as clean                |

What the report shows, and how each is read:

- **HEAD CI** — the run for the EXACT HEAD sha, not "a recent green run".
  `in_progress`, `cancelled` and *absent* are all not green. CI runs a tier
  (docs, code or full) per change, and a docs or code tier passes without
  running the three-Python matrix, so a release needs a `qa.yml` run on that
  exact sha whose matrix jobs (`QA (Python3.x)`) all succeeded; a tier-only
  green is reported as such and is not green. The check reads the jobs with
  `gh run view`, and a `gh` failure or unreadable output is exit `1`, never
  green. Trigger the matrix with `gh workflow run qa.yml --ref main` (a manual
  dispatch has no base to diff, so it classifies as the full tier) and wait
  ([../QA.md](../QA.md), "CI tiers"). The full gate itself never runs on this
  host: it runs in CI on the release pull request (Step 8).
- **In flight** — plans with `**Status**: In Progress`. These block.
- **Waiting for this release** — In Progress plans whose status line names
  `/release` as what they are waiting on. Shown, never blocking: they are the
  opposite of a blocker.
- **High priority, not started** — surfaced for attention, never blocking.
  Whether a filed-but-unfixed finding should hold a release is a question of
  SCOPE, and scope is the human's call.
- **Branches ahead of main / live worktrees** — listed, never touched.

**Proceeding over in-flight work is an explicit act**: re-invoke as
`/release <version> accept-wip`, which passes `--accept`. The report still
prints and the exit becomes `0`, so the decision is in the invocation record.
`--accept` does NOT rescue exit `1` — acknowledging WIP is not acknowledging
blindness.

Once 1a returns `0`, write the state file (see "The release state file").

**1b. Cut the release branch, then agent validation.** Main Claude creates the
release branch from the clean, CI-green `main` HEAD that 1a just checked. The
name is exactly `release/<version>` (no `v`): `release-gate.yml` gates only a
pull request whose head branch starts with `release/`.

```bash
git -C /workspace switch -c release/X.Y.Z main
```

Every commit of Steps 1H to 12 goes on this branch; `main` does not move until
Step 13 merges the pull request. Then the release agent verifies: clean git
state, on `release/<version>`, version consistency across the files listed in
Step 3 "Version Update", no existing tag, gh CLI authenticated. It runs no
full QA (CI does, Step 8); a targeted check it can run cheaply is fine.
(`CLAUDE.md` carries no version string — it is a daemon-regenerated doc, not a
version-bump target.)

**ANY failure = IMMEDIATE ABORT. NO auto-fixing.**

**1H. Housekeeping phase — runs after 1b, before 1c.** See
[Housekeeping Phase](#housekeeping-phase-every-release). Its commits land on
the release branch, so CI and every later gate cover them.

**1c. Claude Code version record and changelog review (Plan 00486).** The daemon is
built on Claude Code, and nothing else notices what Claude Code added between two daemon
releases. This sub-step records the version this release was tested against and reviews
what changed since the previous one.

1. Run `claude --version`. That is the TO version.
2. The vendored changelog was refreshed by the Housekeeping phase (1H). Use that copy; refresh it again only if
   the refresh failed there.
3. FROM is the newest `claude_code_version` that is not `unknown` in
   `CLAUDE/development/claude-code-versions.yaml`. Dispatch the
   `claude-code-changelog-reviewer` agent with FROM, TO and the report path
   `untracked/release-artifacts/claude-code-review-vX.Y.Z.md`.
4. Add `vX.Y.Z` to `claude-code-versions.yaml`: `claude_code_version` (TO), `evidence`,
   `review_date`, `reviewed_through` (TO again; the `contract_staleness` SessionStart
   advisory compares the running Claude Code against the newest of these) and
   `review_report` (the path above). Every adopt, redundant or conflict
   row in the report becomes a plan or ledger entry before Step 8a; the report is copied
   into that plan's folder, because `untracked/` does not survive a container restart.
5. The same review flags instruction-loading changes against the contract in
   `contracts/claude-code-instructions/` (the agent brief names the topics). When it does,
   refresh the contract by the instruction-loading section of
   [HOOK-CONTRACT-REFRESH.md](../../docs/guides/HOOK-CONTRACT-REFRESH.md), so the page hash in its
   `META.json` records the evidence; when it does not, bump only that `META.json`'s
   `last_audited_claude_code_version`. The version-record test requires it to stay at or above the
   hooks contract's.

A release with no entry for its own version, or whose entry names a report that does not
exist, is an ABORT at Step 7.

### 2. Version Detection

Auto-detects from commits since last tag:

- **PATCH**: fix/bug/docs/refactor keywords
- **MINOR**: feat/Add/Implement keywords
- **MAJOR**: BREAKING/incompatible keywords

Agent proposes bump with justification. Manual override accepted.

### 3. Version Update

**The version-carrying files have one home: `VERSION_DECLARATIONS` in
`tests/unit/qa/test_version_bump_completeness.py` (other documents point there).** That test FAILS
when a registered file declares a version other than `version.py`'s, and when any other tracked file
(outside `CHANGELOG.md`, `RELEASES/`, `CLAUDE/UPGRADES/`, `CLAUDE/Plan/`, `tests/`) starts containing the
current version without being registered. Run it right after the bump
(`pytest tests/unit/qa/test_version_bump_completeness.py`) instead of waiting for a later gate. Two of the
files are regenerated rather than edited: `.claude/HOOKS-DAEMON.md` (regenerated, below) and `uv.lock`
(re-locked, below).

Also check README.md's stats still hold. Both the badge and the body state a
deliberately ROUNDED test figure ("12,000+"), which stays true across many
releases — update it only when the real count crosses the next round number,
not every release. README carries no handler count and no event-type count, so
there is nothing to sync from `.claude/HOOKS-DAEMON.md`; an earlier version of
this step named both, sending the reader hunting for figures that are not
there.

**Regenerate `.claude/HOOKS-DAEMON.md` after the version bump**: run `./bin/hooks-daemon generate-docs`. This tracked, generated doc embeds the daemon version in its header (`> Generated on YYYY-MM-DD (vX.Y.Z) …`), so without regenerating it the header ships stale one version behind (v3.43.1 shipped with a v3.43.0 header before this step existed). Stage `.claude/HOOKS-DAEMON.md` with the release commit (Step 7.1).

**Re-lock `uv.lock` after the `pyproject.toml` version bump** (self-install mode tracks `uv.lock`): run `uv lock`. The dependency QA check runs `uv lock --check` and will FAIL the Step 8 CI gate with a lockfile-out-of-date error until the lock is regenerated. Stage `uv.lock` with the release commit (Step 7.1).

### 4. Changelog Generation

[Keep a Changelog](https://keepachangelog.com/) format with Added/Changed/Fixed/Removed sections. Parses commits since last tag, groups by prefix, highlights BREAKING and SECURITY.

### 5. Release Notes

Creates `RELEASES/vX.Y.Z.md` with: summary, changelog, upgrade instructions (if breaking), install/upgrade commands, test stats, contributor list, comparison link.

**Fold in the pending callouts first.** `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
holds one short callout per plan that closed since the last release, written
by the plan in the voice of the release notes (Plan 00360; schema in that
directory's README). Read every `NNN-*.md` there and place each under the
Highlights section, grouped by its `Audience` header where that helps the
reader. These are the sentences the commit log cannot supply, so a callout is
never dropped and never paraphrased down to a changelog line. Step 6 then
moves the files out; a callout still in the directory after that is an ABORT.

---

## Step 6: Move UNRELEASED Post-Upgrade Tasks (BLOCKING)

**Context**: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/` accumulates task files written during the release cycle (audits of prior-version bugs, config-migration guidance, workflow-change notifications, etc.). At release time these MUST be moved into the versioned upgrade guide so upgrading users see them.

**See**: `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md` for the convention and schema.

### What to check

```bash
ls CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/
```

| State                           | Action                                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Only `README.md` present        | Nothing to move. Delete `post-upgrade-tasks/` from the versioned upgrade guide if one was scaffolded. |
| `NN-*.md` task files present    | Move them (steps below). Do NOT leave them in `UNRELEASED/`.                                          |
| Versioned upgrade guide missing | **ABORT** — create it from `CLAUDE/UPGRADES/upgrade-template/` first (see Step 9).                    |

### How to move

Target: `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/`.

Each command names the target path in full (substitute the versions), so
each one can run as its own Bash call: `project_containment` denies a write
target held in a variable nothing in the same call assigns.

```bash
mkdir -p "CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks"

# Copy the per-release index README (if not already present)
cp CLAUDE/UPGRADES/upgrade-template/post-upgrade-tasks/README.md "CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/README.md"

# Move each task file — use git mv so history follows
git mv CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/NN-*.md "CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/"
```

### Populate the per-release task index

Edit `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/README.md`:

1. Update the heading: `# Post-Upgrade Tasks — vPREV → vNEW`
2. Replace the placeholder task-index table with one row per moved task, ordered by filename. Each row: `| file | type | severity | applies-to | one-line summary |`.
3. Delete the `00-EXAMPLE-task.md` reference — that file only belongs in the template.

### Empty the UNRELEASED task index

The rows in `UNRELEASED/post-upgrade-tasks/README.md` name the files just moved
out. Replace that table, between the `BEGIN TASK INDEX` / `END TASK INDEX`
markers, with the `_No tasks are queued for the next release._` placeholder.
A row naming a missing file fails `tests/integration/test_repo_hygiene_check.py`
(rule `post-upgrade-index-drift`).

### Verify

```bash
# UNRELEASED should contain only README.md, and its index no rows
ls CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/
# Expected: README.md  (nothing else)
.venv/bin/python -m pytest tests/integration/test_repo_hygiene_check.py -q
# Expected: passes

# Versioned guide should list every moved task
cat CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/README.md
# Expected: task index populated, no placeholder rows, no 00-EXAMPLE reference
```

### Reference from release notes

If any moved tasks have `Severity: critical` or `recommended`, `RELEASES/vX.Y.Z.md` MUST reference the post-upgrade-tasks directory so upgrading users know to read it:

```markdown
## Post-Upgrade Tasks

After upgrading, review `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/post-upgrade-tasks/` — it contains [N] task(s) that may require action in your project (e.g. auditing files damaged by prior-version bugs, adapting to changed defaults).
```

**ABORT condition**: any `NN-*.md` file remains in `UNRELEASED/post-upgrade-tasks/` when moving to the next step.

### Move UNRELEASED pre-upgrade-tasks

`UNRELEASED/pre-upgrade-tasks/` holds changes a project must hear about BEFORE the release is deployed into it (Plan 00376). The upgrade gate reads them from the versioned guide, runs each task's `**Detect**` pattern over the project, and stops the upgrade on a hit. They move exactly like the post-upgrade tasks, into a sibling directory:

```bash
mkdir -p CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/pre-upgrade-tasks
cp CLAUDE/UPGRADES/upgrade-template/pre-upgrade-tasks/README.md CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/pre-upgrade-tasks/README.md
git mv CLAUDE/UPGRADES/UNRELEASED/pre-upgrade-tasks/[0-9][0-9]-*.md CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/pre-upgrade-tasks/
ls CLAUDE/UPGRADES/UNRELEASED/pre-upgrade-tasks/
# Expected: README.md  (nothing else)
```

Populate `$TARGET/README.md`'s heading and task index (one row per task, with its `Detect` pattern). If only `README.md` was present, there is nothing to move and no `pre-upgrade-tasks/` directory goes into the guide.

**A `critical` pre-upgrade task makes the release breaking for every project it detects**: the gate lists it first, under `READ THIS FIRST`, on those projects. Say so in `RELEASES/vX.Y.Z.md`, in the same section as the breaking changes.

**`breaking: true` in a config-changes manifest halts the fleet.** The gate lists it under `READ THIS FIRST` on EVERY upgrade that crosses that release, whether or not the project uses the changed keys; the reading confirmation (exit `3`) is the only stop. Set it only when the release renames, removes or changes a config key in a way that breaks an existing config (so `renamed`, `removed` or `changed` is non-empty); a release that only adds keys is not breaking. Say which upgrades it lists it for in `RELEASES/vX.Y.Z.md`.

**ABORT condition**: any `NN-*.md` file remains in `UNRELEASED/pre-upgrade-tasks/` when moving to the next step.

### Move UNRELEASED release-notes

Every callout in `UNRELEASED/release-notes/` was folded into `RELEASES/vX.Y.Z.md`
in Step 5. Move the files beside the post-upgrade tasks in the versioned
upgrade guide so the provenance of each sentence survives:

```bash
mkdir -p "CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/release-notes"
git mv CLAUDE/UPGRADES/UNRELEASED/release-notes/[0-9][0-9][0-9]-*.md "CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/release-notes/"
ls CLAUDE/UPGRADES/UNRELEASED/release-notes/
# Expected: README.md  (nothing else)
```

If only `README.md` is present there is nothing to move and no `release-notes/`
directory is created in the guide.

**ABORT condition**: any `NNN-*.md` file remains in `UNRELEASED/release-notes/`
when moving to the next step, or a moved callout's sentence is absent from
`RELEASES/vX.Y.Z.md`.

### Move UNRELEASED truth-changes

Truth-changes (Plan 00118) record statements that **were true** about working in a project but became false this release (a `was → now` doc-reconciliation list consumed by `upgrade.md` and `check-truth-changes`). Any staged in `UNRELEASED/truth-changes/` belong to **this** release and must move into the flat live directory, keeping their version-named filenames:

```bash
# Move each staged truth-changes manifest into the live directory
for f in CLAUDE/UPGRADES/UNRELEASED/truth-changes/v*.yaml; do
    [ -e "$f" ] || continue          # nothing staged this cycle
    git mv "$f" CLAUDE/UPGRADES/truth-changes/
done
```

Verify only `README.md` remains under `UNRELEASED/truth-changes/`:

```bash
ls CLAUDE/UPGRADES/UNRELEASED/truth-changes/
# Expected: README.md  (nothing else)
```

**ABORT condition**: any `v*.yaml` file remains in `UNRELEASED/truth-changes/` when moving to the next step.

### Move UNRELEASED config-changes

Config-changes (Plan 00133) is the per-version manifest of `added` / `renamed` / `removed` / `changed` config keys, consumed by `upgrade.md` and `check-config-migrations` to surface new + recommended options on upgrade. Any staged in `UNRELEASED/config-changes/` belong to **this** release and must move into the flat live directory, keeping their version-named filenames:

```bash
# Move each staged config-changes manifest into the live directory
for f in CLAUDE/UPGRADES/UNRELEASED/config-changes/v*.yaml; do
    [ -e "$f" ] || continue          # nothing staged this cycle
    git mv "$f" CLAUDE/UPGRADES/config-changes/
done
```

**Then set `date:` in each moved manifest** to today's release date in ISO 8601
form (`YYYY-MM-DD`). A staged manifest is drafted with `date: "UNRELEASED"`
because the release date does not exist yet; the move is the moment it becomes
knowable. Nothing reads this field at runtime — `ConfigMigrationManifest` parses
it into an attribute that is never rendered or compared — so a forgotten
placeholder is completely silent, and four shipped manifests carried one before
`check_repo_hygiene`'s `unreleased-manifest-date` rule was added to catch it.

Verify only `README.md` remains under `UNRELEASED/config-changes/`, and that no
live manifest still carries the placeholder:

```bash
ls CLAUDE/UPGRADES/UNRELEASED/config-changes/
# Expected: README.md  (nothing else)

grep -l 'UNRELEASED' CLAUDE/UPGRADES/config-changes/v*.yaml
# Expected: no output (the Step 8 CI gate enforces this too)
```

**ABORT condition**: any `v*.yaml` file remains in `UNRELEASED/config-changes/` when moving to the next step.

---

## Step 7: Opus Documentation Review

Opus reviews **documentation only** (not code/QA):

- Version numbers consistent across files
- README.md stats updated
- Changelog accurate and categorized
- Release notes comprehensive
- Security/breaking changes marked
- Upgrade instructions clear
- `UNRELEASED/post-upgrade-tasks/` contains only `README.md` (all tasks moved in Step 6)
- Moved tasks have populated the versioned guide's `post-upgrade-tasks/README.md` task index
- `UNRELEASED/pre-upgrade-tasks/` contains only `README.md`, and any moved pre-upgrade tasks are indexed in the guide's `pre-upgrade-tasks/README.md`
- `CLAUDE/development/claude-code-versions.yaml` has an entry for this release (Step 1c) whose `review_report` file exists
- Release notes reference post-upgrade tasks if any are `critical` or `recommended`
- Every callout moved out of `UNRELEASED/release-notes/` in Step 6 appears in the release notes, and that directory contains only `README.md`
- **Did this release change a documented truth?** (a workflow, command, or convention a project's own docs are likely to assert) — if so, a `truth-changes/v{X.Y.Z}.yaml` entry exists (`was → now`, or `now: ~` to retire it) and `UNRELEASED/truth-changes/` contains only `README.md`
- **Did this release add an opt-in feature or flip a default?** (a feature that would otherwise ship dormant in client projects) — if so, a `config-changes/v{X.Y.Z}.yaml` entry exists with `recommended: true` (and `recommended_value:` for a default flip) so the upgrade advisory actively promotes enabling it, and `UNRELEASED/config-changes/` contains only `README.md`

Approved -> proceed. Issues found -> agent fixes docs, re-submit until approved.

### Step 7.1: Commit on the release branch

Every release-preparation change is committed on `release/<version>`; nothing
is pushed to `main`.

**🚨 Stage source changes too — the file list below is NOT sufficient.** Any
step can modify `src/`, `scripts/` or `tests/` (a review fix in Step 10, a
`get_claude_md()` fix in Step 11, a FAIL-FAST fix in Step 12). The `git add`
list below names only version/doc artifacts, so such a fix is silently left
uncommitted unless you stage it explicitly. The daemon's own auto-commit hook
commits the *regenerated* `CLAUDE.md` on restart, so the GENERATED artifact
lands in git while its SOURCE handler does not, and the tagged tree ships
guidance no handler in it produces (caught by the Opus gate during v3.49.1).

**Always run this before staging** and add anything it reports:

```bash
git status --porcelain -- src/ scripts/ tests/
```

```bash
git add pyproject.toml version.py README.md CLAUDE.md CHANGELOG.md RELEASES/vX.Y.Z.md \
  .claude/HOOKS-DAEMON.md uv.lock .claude/ccy/claude-supervise.py \
  CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/ \
  CLAUDE/UPGRADES/UNRELEASED/
# Plus EVERY src/, scripts/ and tests/ path reported above.
git commit -m "Release vX.Y.Z: [Title]

- Updated version to X.Y.Z across all files
- Added comprehensive changelog entry
- Generated release notes

Full changelog: RELEASES/vX.Y.Z.md"
```

A later fix (Steps 9–12) is its own commit on the same branch, staged the same
way. Before Step 8a and again before Step 13 the check below must be empty:

```bash
git status --porcelain -- src/ scripts/ tests/
# Expected: empty.
```

---

## Step 8: Release Pull Request + CI Gate (BLOCKING)

The whole QA gate runs in CI on the release pull request, not on this host.
Workflow `.github/workflows/release-gate.yml` runs every `llm_qa.py` check
(one job per supported Python, sharded where long, the performance sweeps
alone on a runner) and ends in one summary check, **`Release gate`**, which is
green only if every other job succeeded. That summary is this gate. The
workflow is the single source of truth for which checks exist, and its own
`layout` job fails if they drift from `llm_qa.py`'s list — do not restate them
here.

The `hooks-daemon` skill's coherence with the shipped daemon is part of this
gate, not a separate step: `tests/integration/test_skill_surface_coherence.py`
(Plan 00330) runs inside the `tests` check and fails the release when a
registered handler is invisible to `optimise`, when the skill documents a CLI
verb that does not exist, names a retired handler, or references a config key
the schema does not define.

### Step 8a: Push the branch and open the pull request

```bash
git -C /workspace push -u origin release/X.Y.Z
gh pr create --base main --head release/X.Y.Z \
  --title "Release vX.Y.Z" \
  --body-file /workspace/untracked/release-artifacts/pr-body.md
```

Write the body file first (a short pointer to `RELEASES/vX.Y.Z.md`; never
pipe a body on stdin, which the sensitive-content guard cannot read). Then
find the run the push started and write the `ci` record into the state file
at once, because that record is what arms the merge freeze:

```bash
gh pr view <N> --json number,headRefOid --jq '{number, head: .headRefOid}'
gh run list --workflow release-gate.yml --branch release/X.Y.Z \
  --json databaseId,headSha,status,conclusion --limit 5
```

Take the run whose `headSha` equals the pull request's head, and record
`{"pr_number": <N>, "run_id": <id>, "head_sha": "<head>", "conclusion": "pending"}`
under `ci`. If no run for that head is listed yet, wait a minute and list again;
a run that never appears is an ABORT (the workflow did not trigger).

### Step 8b: Start-up Budget Gate (BLOCKING, Plan 00495)

Main Claude runs, on the release branch:

```bash
source scripts/lib/resolve_venv.sh
PY="$(resolve_venv_python /workspace)"
"$PY" scripts/release/check_startup_budget.py
```

It measures the CPU a daemon start spends before it binds its socket (fresh process, throwaway project, shipped example
config) and fails when the median is over the budget in `CLAUDE/Performance/startup-budget.json`. ANY non-zero exit =
ABORT: 1 means the start got slower than the budget (find the commit that added the cost; do not raise the budget to
pass), 2 means the measurement itself failed.

It is a release step, not part of `llm_qa.py all`, because a sample costs about a CPU-second and five are taken. It
measures CPU seconds, so other agents running tests on the host do not flake it. The budget and why it has that value
are in [../Performance/README.md](../Performance/README.md#start-up-budget).

### Step 8c: Wait for the `Release gate` check

The run takes the better part of an hour. Wait on it with a bound, in the
background so Steps 9–12 can proceed meanwhile — never an unbounded polling
loop:

```bash
# Bash tool with run_in_background; the timeout is the cap (2 hours).
timeout 7200 gh run watch <run_id> --interval 60 --exit-status
```

`gh pr checks <N> --watch --interval 60` under the same `timeout` works too.
When it ends, read the result rather than the exit code alone (`timeout`
exits 124 when the cap is hit, which is NOT a CI failure — look again):

```bash
gh run view <run_id> --json status,conclusion,headSha
gh pr checks <N>      # the `Release gate` row must read pass
```

Rewrite the state file's `ci` record with the run's real `conclusion` (and
its `headSha`, which must still equal `head_sha`), then set
`last_completed_step` to 8.

| Result                                         | Action                                                                                                                             |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `success` on the recorded head                 | Gate passed                                                                                                                        |
| `failure` / `cancelled` / `timed_out`          | **ABORT**, or fix on the release branch: commit, push, record the NEW run (`pending`), wait again. `gh run view <id> --log-failed` |
| `cancelled` because a newer push superseded it | Not a failure: record the newer run and wait for it                                                                                |
| Still running at the cap                       | Wait again (same command); the cap only bounds one wait                                                                            |

**Every push to the release branch starts a new run**, and the record must
always name the run for the branch's current head. A fix made in Steps 9–12
is therefore followed by: push, record the new run as `pending`, wait,
record its conclusion.

---

## Step 9: Breaking Changes Check (BLOCKING)

**Context**: v2.11 and v2.12 shipped breaking changes without upgrade docs.

### Detection

Scan the new CHANGELOG.md entry for:

1. Any entries in "Removed" section
2. "BREAKING" keyword in "Changed" section
3. Keywords: "BREAKING", "breaking change", "incompatible", "renamed"
4. New `@abstractmethod` on `Handler` base class in `core/handler.py`
   - If found: `_ABSTRACT_METHOD_VERSIONS` in `project_loader.py` must include it
   - Upgrade guide must document: method name, version, stub to add, detection via `validate-project-handlers`

### Decision

| Breaking Changes? | Upgrade Guide Exists? | Action                         |
| ----------------- | --------------------- | ------------------------------ |
| Yes               | Yes                   | Proceed                        |
| Yes               | No                    | **ABORT** - create guide first |
| No                | N/A                   | Proceed                        |

### Upgrade Guide Requirements

Location: `CLAUDE/UPGRADES/v{MAJOR}/v{PREV}-to-v{NEW}/`

Template: `CLAUDE/UPGRADES/upgrade-template/`

Must include: summary, version compatibility, pre-upgrade checklist, changes overview, step-by-step instructions, verification steps, rollback instructions.

Release notes MUST reference upgrade guide with BREAKING CHANGES section.

---

## Step 10: Code Review Gate (BLOCKING)

```bash
LAST_TAG=$(git describe --tags --abbrev=0)
git log --oneline "${LAST_TAG}..HEAD"
git diff "${LAST_TAG}..HEAD" -- src/
```

Review checklist:

- No bugs in `matches()`/`handle()` logic
- No security anti-patterns
- Priority ranges correct (see the [Priority Guide](../HANDLER_DEVELOPMENT.md#priority-guide))
- Tests exist for every handler change
- Named constants (no magic values), SOLID principles
- No debug code, workarounds, or leftover TODOs

Issues found = ABORT, fix, re-run `/release`. That applies to EVERY defect the
review finds, not only the ones the reviewer labelled blocking — see "Review
Early, Never Drop Findings" above: a release carries no known defect, and a
deferral needs the human's explicit acceptance in this session.

---

## Step 11: CLAUDE.md Guidance Audit (BLOCKING)

**This step is now a gate, not a sub-agent sweep** (Plan 00203). Coverage of
`get_claude_md()` is enforced continuously by
`tests/integration/test_claude_md_guidance_coverage.py`, which enumerates every
handler and fails unless each carries a recorded verdict — covered, or exempt
with a reason. Step 8's CI run already executes it, so if Step 8 passed, this
gate has passed.

Confirm explicitly:

```bash
source scripts/lib/resolve_venv.sh
PY="$(resolve_venv_python /workspace)"
"$PY" -m pytest tests/integration/test_claude_md_guidance_coverage.py -q
```

**Why the sweep was replaced.** The v3.52.0 release ran the sub-agent audit and
reported six PreToolUse *advisory* handlers returning `None`. Plan 00203 then
applied a written criterion to all 107 handlers and found **all six were
correct** — while two handlers the audit had not looked at were genuinely
missing guidance: `lint_on_edit` (PostToolUse, and it DENIES) and
`hedging_language_detector` (Stop, whose identical twin was covered). A sweep
scoped to one event type cannot find either, and re-derives the same verdicts
by hand every release. The table records them once.

**If the gate fails**, it names the handler and what to do. Apply the four
tests in `CLAUDE/HANDLER_DEVELOPMENT.md`, then either implement
`get_claude_md()` or record the exemption with its reason. If you change
`src/`: run targeted QA, restart the daemon, update the changelog, and commit
the source file on the release branch (Step 7.1), then push and wait for the
new CI run (Step 8c) — the daemon auto-commits the regenerated `CLAUDE.md`,
so a guidance fix can otherwise ship as a generated artifact with no source
behind it.

---

## Step 12: Acceptance Testing Gate (BLOCKING)

**The acceptance method lives in
[`CLAUDE/AcceptanceTests/GENERATING.md`](../AcceptanceTests/GENERATING.md)
("SUB-AGENT EXECUTION"), and `/acceptance-test` runs it; this step does not
restate it.** In one sentence: each
test's `Requires Main Thread` field in the generated playbook decides — `yes`
runs in the main thread and is never delegated, `no` may be delegated to
sub-agents batched by `Recommended Model`.

### Scope

```bash
LAST_TAG=$(git describe --tags --abbrev=0)
HANDLER_CHANGES=$(git diff "${LAST_TAG}..HEAD" --name-only -- src/claude_code_hooks_daemon/handlers/)
```

| Bump        | Handler Changes? | Action                              |
| ----------- | ---------------- | ----------------------------------- |
| MAJOR/MINOR | Any              | Full suite                          |
| PATCH       | Yes              | Targeted tests for changed handlers |
| PATCH       | No               | Skip — document in release notes    |

### Execution

**Step 12.0** (H-1 deterministic install/diagnostic gates — Plan 00104 Phase 9
Task 9.6 + Plan 00105 Phase 1): Run BOTH deterministic acceptance gates that
exercise the production install path and the production diagnostic scripts
end-to-end against a fresh fixture project. Together they catch:

- The v3.9.x regression class — `write-venv-metadata` writing the system
  interpreter as `python_path`, `daemon-cli.sh` / `health-check.sh` crashing
  with `ModuleNotFoundError`, skill `upgrade.sh` self-bootstrap silently
  falling back on network failure.
- The v3.10.0 SEV-1 class — `print_info` writing to stdout corrupting every
  `VAR=$(ensure_venv ...)` capture, breaking every upgrade in the field.
- Any future bug in `install_version.sh` → `ensure_venv` → `verify_venv` →
  `write-venv-metadata` → daemon-start that produces a non-running daemon.

```bash
# pytest needs the daemon's venv interpreter. Resolve it through the CANONICAL
# resolver — never hand-roll a venv path, and never assume the shell exports an
# interpreter variable (python-var-guidance-exempt: $PYTHON is named here as the
# banned pattern to warn against — no agent shell ever sets it; Plan 00192).
source scripts/lib/resolve_venv.sh
PY="$(resolve_venv_python /workspace)"
# HOOKS_DAEMON_RELEASE_GATE=1 is the explicit signal blocking_gate_guard.py
# (tests/acceptance/) requires before it escalates a skip of one of these
# files to a failure — this IS that release-gate invocation, so it must be
# set here (Plan 00466 N39 widened). An ad hoc run of these files with no
# daemon running, and no signal set, gets the ordinary skip instead.
HOOKS_DAEMON_RELEASE_GATE=1 "$PY" -m pytest tests/acceptance/test_diagnostic_scripts.py tests/acceptance/test_install_sh_end_to_end.py tests/acceptance/test_tool_use_error_recovery.py tests/acceptance/test_stop_hook_hard_block.py tests/acceptance/test_skill_install_python_discovery.py tests/acceptance/test_playbook_harness.py -v
# Expected: 0 failed, 0 skipped. The pass COUNT is deliberately not stated —
# see below.
```

**Why no expected counts** (Plan 00250 Task 1.2). This block used to carry a
per-file pass tally and a combined total. Every one of them had gone stale:
it claimed `test_diagnostic_scripts.py — 12 passed` (it has 15) and
`combined: 27 passed, 1 skipped` (it is 31 passed, 0 skipped, measured against
a running daemon). Nothing was wrong with the gate — the suite had simply grown,
which it will keep doing.

A count is a second copy of a fact the test run already reports, so it drifts
silently and then reads as a failure to whoever follows this procedure. **0
failed and 0 skipped** are the properties that actually matter and they do not
drift. The FILE LIST above is the contract; the numbers were never it.

The `1 skipped` in particular was load-bearing in the wrong direction: it
documented as normal exactly the condition this gate exists to catch. A skip
here means no daemon was running — which under H-1 is itself an abort condition,
as the note below says.

`test_playbook_harness.py` (Plan 00243) dispatches every playbook test that
declares a `tool_payload`, through the production hook wrappers, and asserts
both the decision AND the deny reason. It is what makes most of Step 12.4
automatic — see there for the split between what it owns and what a human
still runs. A skip here means no daemon was running, which under H-1 is itself
an abort condition.

**There is no expected skip.** `test_tool_use_error_recovery_branch_skipped_on_success`
used to skip while a release was in flight — this repository's own terminal
`release_blocker` project handler sits at priority 8, ahead of
`auto_continue_stop` at 10, so during a release it answers first and the
default branch's wording cannot be observed over the socket. Because this file
is a blocking gate that turns a skip into a failure, and the release guard
answers precisely while the gate runs, that skip could only ever fail. The
test now PASSES in that case: its real assertion — Branch 2.5 must not fire on
a clean turn — executes either way, and when the release guard answered it
additionally checks the guard named the state file. Any skip in this block is
an abort condition (see below).

ANY failure in any file = ABORT release. The 2026-05-01 field report
(Issues #1, #4, #6) escaped because the v3.9.0 acceptance suite never invoked
the diagnostic scripts — only hook dispatch. The v3.10.0 SEV-1 escaped
because the v3.10.0 H-1 gate synthesised state via `write-venv-metadata`
directly instead of running the production `ensure_venv` capture chain. Both
gaps are closed by adding `test_install_sh_end_to_end.py` here. The Plan
00101 silent-stop recurrence (Edit-on-unread-file → tool_use_error → no
recovery) is closed by adding `test_tool_use_error_recovery.py` — exercises
the `auto_continue_stop` Branch 2.5 directly against the live daemon socket.
The Plan 00101 Phase 9 suggestion-level-downgrade regression class
(v2.1.114 silently demoting JSON-stdout `decision=block` to
`level: suggestion, preventedContinuation: false`) is closed by adding
`test_stop_hook_hard_block.py` — invokes the production bash wrappers
`.claude/hooks/stop` and `.claude/hooks/subagent-stop` as subprocesses
and asserts the exit-2 + stderr contract that v2.1.114 honours for hard
re-entry. The test skips cleanly when no daemon is running locally; under
H-1 the daemon is always started before this step, so a skip for THAT
reason is itself an abort condition — distinct from the release-in-flight
skip described above, which is expected. Always read the skip message
rather than counting skips. The Plan 00110 host-a field-report regression
class (host has `python3` → 3.9 alongside `python3.13` / `python3.14`, but
pre-Plan-00110 install.sh aborted with a hardcoded `python3.11` suggestion
that the host did not have) is closed by adding
`test_skill_install_python_discovery.py` — invokes the production
`src/.../skills/hooks-daemon/scripts/install.sh` against synthesised PATH
layouts and asserts (a) the host-a scenario auto-selects `python3.14`
without operator help, and (b) the failure diagnostic NAMES the observed
`python3.9 (3.9.21)` interpreter instead of a hardcoded suggestion that
may not exist on the host.

**Step 12.1**: Restart daemon, verify RUNNING.

**Step 12.2**: Verify OBSERVABLE handlers in system-reminders (SessionStart, UserPromptSubmit, PostToolUse).

**Step 12.3**: Generate playbook: `./bin/hooks-daemon generate-playbook > /tmp/playbook.md`

**Step 12.4**: Execute what the harness does NOT own.

Step 12.0 already ran `test_playbook_harness.py`, which dispatched every
playbook block that declares a `tool_payload` on a dispatchable event
(`PreToolUse`/`PostToolUse`) and asserted its decision and deny reason. **Do
not re-run those by hand** — they passed deterministically or Step 12.0 aborted
the release.

What remains manual is exactly what the harness reports as SKIPPED, and it
prints a reason for every one. Ask it rather than working from a list here:

```bash
"$PY" -c "
import json, subprocess, sys
from pathlib import Path
from collections import Counter
from claude_code_hooks_daemon.daemon.playbook_harness import split_playbook
blocks = json.loads(subprocess.run(['./bin/hooks-daemon','generate-playbook','--format','json'],
                                   capture_output=True, text=True).stdout)
executable, skipped = split_playbook(blocks, Path.cwd())
print(f'harness ran {len(executable)}; {len(skipped)} need a human:')
for reason, n in Counter(s.reason for s in skipped).most_common():
    print(f'  {n:4d}  {reason}')
"
```

Route each remaining test by its `Requires Main Thread` field (see the Step 12
intro). They fall into four kinds, and the difference matters because only the
first is unfinished work rather than a permanent boundary:

- **Prose with no payload** — a human performs the tool call the sentence
  describes. Converting one to a payload moves it into the harness.
- **Non-tool events** (`SessionStart`, `Status`, `UserPromptSubmit`, `Stop`,
  …) — no tool call exists for a payload to carry, so these are OBSERVABLE in
  session or VERIFIED_BY_LOAD. Permanent.
- **Missing toolchain** — a language linter this machine does not have.
  Installing it moves the test into the harness on the next run.
- **`harness_cannot_produce`** — Claude Code rewrites the input before the
  daemon sees it. Permanently unreachable by any harness; the behaviour stays
  covered by unit and socket-level tests.

The generated playbook is the single source of truth for which tests exist and
how many — do not restate counts here or above. This section previously
hardcoded "~65 blocking / ~24 advisory" while `generate-playbook` was emitting
over 200 tests.

**Nothing is narrowed by this.** Every block is in exactly one of the two
buckets — `split_playbook` is a total partition, asserted by
`test_the_partition_loses_nothing` — so a test cannot fall between the
automated route and the manual one. A test that stops being executable moves
into the skip list with its reason attached; it never disappears.

**Step 12.5**: All tests must pass. Failed = 0.

### FAIL-FAST Cycle

1. STOP testing immediately
2. Fix bug with TDD, on the release branch
3. Run targeted QA (`./scripts/qa/llm_qa.py changed`), commit (Step 7.1), push
4. Record the new CI run and wait for it (Step 8c); the whole gate re-runs there
5. Restart daemon
6. **RESTART ALL tests from Step 12.1** (code changes can regress earlier tests)
7. Repeat until zero failures and the new run is green

---

## Step 13: Verify CI & Merge the Pull Request (BLOCKING)

Run in the main thread, on `release/X.Y.Z`, after Steps 8–12 have all passed.

**13.1 Nothing left behind.** `git status --porcelain -- src/ scripts/ tests/`
is empty and the local branch equals `origin/release/X.Y.Z`
(`git -C /workspace status -sb` shows no `ahead`). A non-empty result is a fix
that never reached CI: commit, push, and go back to Step 8c.

**13.2 CI passed this exact head.** Non-zero exit = ABORT (or fix and go back
to Step 8c); it prints one line naming the reason:

```bash
scripts/release/check_release_ci.py
```

**13.3 The branch is up to date with `main`**, so the merge commit's tree is
the gated tree ([why](#the-release-pull-request-and-the-merge-freeze)):

```bash
git -C /workspace fetch origin
git -C /workspace merge-base --is-ancestor origin/main HEAD
# Exit 0 = up to date. Non-zero = main moved: update the branch as described
# in "The Release Pull Request and the Merge Freeze", then back to Step 8c.
```

**13.4 Merge**, with a merge commit — never squash or rebase (both are denied,
and either would tag a commit whose ancestry and tree CI never saw):

```bash
gh pr merge <N> --merge --match-head-commit <head_sha>
```

`--match-head-commit` makes GitHub refuse the merge if the branch head is not
the commit CI passed. Then bring the merge commit into the local `main`
(`git pull` is not frozen):

```bash
git -C /workspace switch main
git -C /workspace pull --ff-only origin main
```

Set `last_completed_step` to 13.

## Step 14: Tag the Merge Commit & GitHub Release

**14.0 The merge commit is the gated tree.** `main`'s HEAD must be the merge
commit of the release pull request, its second parent the CI-passed head, and
its tree identical to that head's. Any mismatch = STOP and tell the human;
do not tag:

```bash
git -C /workspace rev-parse HEAD^2                 # must equal ci.head_sha
git -C /workspace rev-parse 'HEAD^{tree}'          # these two must be equal
git -C /workspace rev-parse '<head_sha>^{tree}'
```

The release bundle MUST include `bootstrap-checksums.txt` alongside ALL FOUR
self-bootstrapping skill scripts: `upgrade.sh`, `daemon-cli.sh`,
`health-check.sh`, and `init-handlers.sh`. Each script's self-bootstrap stanza
(Plan 00104 Task 5.1 Decision 3.C + Plan 00105 Phase 4 Decision 3.B)
downloads the manifest, looks up its own basename, sha256-verifies its own
body, and aborts the run if either is missing or inconsistent. Skipping any
of these four artifacts ships a release that every existing installation
refuses to run for that script — every diagnostic invocation aborts loudly
with `Error: bootstrap-checksums.txt has no entry for <basename>`.

**Note on `upgrade.sh` (Plan 00109)**: As of v3.15.0 the skill-pushed
`upgrade.sh` is a thin shim that fetches `scripts/upgrade.sh` from
`main` HEAD and execs it — it no longer carries a self-bootstrap stanza
and clients never run the published `upgrade.sh` artifact. The artifact
is still bundled here for cross-symmetry with the three sibling scripts
that DO still self-bootstrap against the manifest. Plan 00109 Decision 4
captures the rationale: removing `upgrade.sh` from the manifest would
require touching this loop and the manifest builder, with no upside
until the sibling-script thinning plan lands. Once the siblings are
thinned too, all four artifacts can be dropped together.

GitHub rejects a release body over 125,000 characters (HTTP 422), and only
when `gh release create` runs, after the tag is pushed. Step 5 folds every
holding-area callout into `RELEASES/vX.Y.Z.md` verbatim, so a large release
can exceed it (v3.67.0 was 126,003). `build_github_release_body.py` writes
the body GitHub receives: the notes unchanged when they fit, otherwise the
notes with the verbatim `## Highlights` replaced by a link to that section
at the tag, every other section intact. It exits non-zero if even that is
over the cap, so it runs BEFORE the tag: a failure there publishes nothing.
The committed `RELEASES/vX.Y.Z.md` is never modified.

```bash
scripts/release/build_github_release_body.py vX.Y.Z

# On main, HEAD = the merge commit checked in 14.0. The tag push is not frozen.
git tag -a vX.Y.Z -m "[Full release notes from RELEASES/vX.Y.Z.md]"
git push origin vX.Y.Z

gh release create vX.Y.Z \
  --title "vX.Y.Z - [Release Title]" \
  --notes-file untracked/release-artifacts/github-release-body.md \
  --latest

# Stage the four skill scripts, build bootstrap-checksums.txt, upload all
# five assets to the release just created, and read the release back to
# prove every asset landed. Non-zero exit = the release is NOT done.
scripts/release/publish_bootstrap_assets.sh vX.Y.Z
```

`publish_bootstrap_assets.sh` is the ONLY supported way to attach the
bundle: it scans the skill tree for every script carrying the stanza and
refuses to build a manifest that misses one, and
`tests/integration/test_publish_bootstrap_assets.py` pins that this file,
`.claude/skills/release/invoke.sh` and `.claude/agents/release-agent.md`
all invoke it after `gh release create`. v3.62.1 shipped with no assets
because the followed procedure ran `gh release create` bare; a release
whose procedure omits this step cannot pass QA now. To inspect the bundle
without a release: `scripts/release/publish_bootstrap_assets.sh vX.Y.Z --build-only`.

To repair an ALREADY published release that is missing its assets, bundle
the bytes of that tag rather than of `main` HEAD:

```bash
git worktree add untracked/worktrees/tag-vX.Y.Z vX.Y.Z
HOOKS_DAEMON_SKILL_SCRIPTS_DIR=untracked/worktrees/tag-vX.Y.Z/src/claude_code_hooks_daemon/skills/hooks-daemon/scripts \
  scripts/release/publish_bootstrap_assets.sh vX.Y.Z
git worktree remove untracked/worktrees/tag-vX.Y.Z
```

### Relay binary (Plan 00290 Phase 5 — the `daemon.transport.relay_source: download` convenience asset)

**Only if a musl-capable `rustc` is available on this machine** (`rustc --print target-list | grep x86_64-unknown-linux-musl`). Build-from-source stays the
FIRST-CLASS route for clients regardless (`relay/hooks_relay.rs` +
`relay/build.sh` ship in every release, no cargo/crates needed) — this step
only produces the CONVENIENCE download asset for clients who choose
`relay_source: download` over `relay_source: build`. Skip this block entirely
if no toolchain is available here; a release missing the relay asset is still
valid — the download route just has nothing to fetch until a later release
adds it, and `install/relay_deploy.py` reports that as an advisory, never a
hard failure.

```bash
scripts/release/build_relay_release_assets.sh untracked/release-artifacts

gh release upload vX.Y.Z \
  untracked/release-artifacts/hooks-relay-x86_64-unknown-linux-musl \
  untracked/release-artifacts/SHA256SUMS
```

**Verification before continuing**:

```bash
# Every artifact must be reachable from the latest-release URL each
# self-bootstrap stanza uses, and every script's published sha must match
# its manifest entry. ABORT release if any curl fails or any sha mismatches.
BASE="https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases/latest/download"
mkdir -p untracked/scratch
curl -fsSL -o untracked/scratch/_check.txt "$BASE/bootstrap-checksums.txt"
for script in upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh; do
    PUBLISHED_SHA="$(curl -fsSL "$BASE/$script" | sha256sum | awk '{print $1}')"
    MANIFEST_SHA="$(awk -v name="$script" '$2 == name {print $1; exit}' untracked/scratch/_check.txt)"
    if [ -z "$MANIFEST_SHA" ]; then
        echo "ABORT: manifest has no entry for $script"; exit 1
    fi
    if [ "$PUBLISHED_SHA" != "$MANIFEST_SHA" ]; then
        echo "ABORT: published $script sha ($PUBLISHED_SHA) != manifest ($MANIFEST_SHA)"; exit 1
    fi
done
# All four matched: release is internally consistent.
```

## Step 15: Post-Release Verification

```bash
git tag -l vX.Y.Z
gh release view vX.Y.Z --json tagName,isDraft,isPrerelease,url \
  --jq '{tag: .tagName, draft: .isDraft, prerelease: .isPrerelease, url: .url}'
# Expected: draft=false, prerelease=false
git -C /workspace push origin --delete release/X.Y.Z   # merged, so allowed
git -C /workspace branch -d release/X.Y.Z
```

Then delete `untracked/release-state.json`: the release is finished, and the
merge freeze lifts with it.

### Step 15.1: Housekeeping phase, post-release items

Run the post-release list in [Housekeeping Phase](#housekeeping-phase-every-release).

## Housekeeping Phase (every release)

Owner rulings 2026-10-05 (D3) and 2026-10-06. Every release is also a checkpoint for chores that are not about what is
being released but need doing regularly. They are listed here and run each time, in two halves. Add a chore here when
it is agreed; a chore that would change what the release contains goes in the pre-gate half, so the gates cover it.

### Pre-gate items (Step 1H: after 1b cuts the release branch, before 1c)

Each item that changes tracked files is committed on the release branch, so the pull request's CI run and every later
gate judge the result.

- [ ] **Refetch and resave every vendored remote doc.** Run `bin/hooks-daemon remote-docs refresh --all`, then
  `bin/hooks-daemon remote-docs check`. Commit the refreshed files under `remote-docs/` and `.claude/REMOTE-DOCS.md`;
  their provenance frontmatter is rewritten by the tool, and the commit gate rejects any file without it. A page that
  fails to refresh keeps its old copy: record the URL and the error in the release's working notes, and do not hand-edit
  the file. This also provides the fresh Claude Code changelog that Step 1c reviews.

### Post-release items (Step 15.1)

- [ ] **Clean stale files under `untracked/`**: scratch, old probe copies, dead worktree venvs. Keep anything a live
  worktree (`git worktree list`) or an open report points at.

---

## Rollback

An abort is reported to the human with the gate that failed; the actions below
only undo what was done.

| State                            | Action                                                                                                                                           |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Before Step 8a (branch is local) | `git switch main`; delete the state file; the local `release/X.Y.Z` branch may stay for inspection (`git branch -d` needs the human if unmerged) |
| Pull request open, not merged    | `gh pr close <N> --comment "Release vX.Y.Z aborted: <gate>"`, then delete the state file (this lifts the merge freeze). `main` never moved       |
| Merged, not tagged               | Do not tag. Tell the human: `main` now carries the release commit; the next release supersedes it, or they revert the merge                      |
| Tag created                      | `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z && gh release delete vX.Y.Z --yes` (ONLY on explicit human instruction)                  |
| Published                        | Create an immediate patch release (NEVER force-push tags)                                                                                        |

## Manual Release (Bypass Skill)

```bash
# 1. git switch -c release/X.Y.Z main   (after release-slate-check exits 0)
# 2. Edit versions: pyproject.toml, version.py, README.md
# 3. Update CHANGELOG.md (Keep a Changelog format) and create RELEASES/vX.Y.Z.md
# 4. Move UNRELEASED/post-upgrade-tasks/NN-*.md and UNRELEASED/pre-upgrade-tasks/NN-*.md
#    into the versioned upgrade guide and populate each directory's README.md
#    task index; fold every
#    UNRELEASED/release-notes/NNN-*.md callout into RELEASES/vX.Y.Z.md and move
#    the files into the guide's release-notes/
# 5. Commit on the branch; scripts/release/check_startup_budget.py (Step 8b; non-zero = do not release)
# 6. git push -u origin release/X.Y.Z && gh pr create --base main --head release/X.Y.Z
#    and record the ci block in untracked/release-state.json (Step 8a)
# 7. Wait for the `Release gate` check (Step 8c); acceptance tests (Step 12)
# 8. scripts/release/check_release_ci.py, branch up to date with origin/main,
#    gh pr merge <N> --merge --match-head-commit <head_sha>, then pull main (Step 13)
# 9. Body: scripts/release/build_github_release_body.py vX.Y.Z   (BEFORE the tag; non-zero = do not tag)
# 10. Tag the merge commit: git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z
# 11. gh release create vX.Y.Z --title "vX.Y.Z - [Title]" --notes-file untracked/release-artifacts/github-release-body.md --latest
# 12. scripts/release/publish_bootstrap_assets.sh vX.Y.Z   (the release is NOT done until this exits 0)
```

## Semver Guidelines

| Level | When                                                                |
| ----- | ------------------------------------------------------------------- |
| PATCH | Bug fixes, security patches, docs                                   |
| MINOR | New handlers/features, config options, backwards-compatible         |
| MAJOR | Breaking API/config changes, removed features, Python version bumps |

No fixed schedule. Critical bugs = immediate patch. Features = minor when stable. Breaking = plan ahead.

## Related

- Skill spec: `.claude/skills/release/SKILL.md` (and its `invoke.sh`)
- Release agent: `.claude/agents/release-agent.md`
- Release gate workflow: `.github/workflows/release-gate.yml`
- CI record check: `scripts/release/check_release_ci.py`
- Merge freeze: `.claude/project-handlers/pre_tool_use/release_merge_freeze.py`
- QA pipeline: `CLAUDE/QA.md`
- Acceptance tests: `CLAUDE/AcceptanceTests/GENERATING.md`
